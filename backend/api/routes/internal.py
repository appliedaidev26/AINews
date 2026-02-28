"""Internal routes — called by Cloud Tasks and Pub/Sub push subscriptions.

These endpoints are protected by OIDC tokens issued by Google (Cloud Tasks,
Pub/Sub, and Cloud Scheduler all attach a service-account Bearer token).
In local dev (no GCP_PROJECT_ID set) authentication is skipped automatically.
"""
import asyncio
import base64
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db import sync_engine
from backend.db.models import Article, PipelineRun, PipelineTaskRun
from backend.ingestion.pubsub import publish_articles_saved
from backend.processing.dedup import deduplicate_articles

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"])


# ---------------------------------------------------------------------------
# OIDC auth dependency
# ---------------------------------------------------------------------------

def require_internal(authorization: Optional[str] = Header(None)) -> None:
    """Verify Google OIDC Bearer token on internal endpoints.

    In production GCP_PROJECT_ID is set → token is verified.
    In local dev GCP_PROJECT_ID is empty → auth is skipped.
    """
    if not settings.gcp_project_id:
        return  # local dev — Cloud Tasks / Pub/Sub not used, skip

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing OIDC Bearer token")

    token = authorization[len("Bearer "):]
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
        # Audience must match the Cloud Run service URL
        id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            settings.cloud_run_url,
        )
    except Exception as exc:
        logger.warning("OIDC token verification failed: %s", exc)
        raise HTTPException(status_code=403, detail="Invalid OIDC token")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upsert_task_run(run_id: int, source: str, target_date: date, status: str,
                     articles_saved: Optional[int] = None, error_message: Optional[str] = None):
    """UPSERT a pipeline_task_runs row for one (run_id, source, date)."""
    with Session(sync_engine) as session:
        row = session.execute(
            select(PipelineTaskRun).where(
                PipelineTaskRun.run_id == run_id,
                PipelineTaskRun.source == source,
                PipelineTaskRun.date == target_date,
            )
        ).scalar_one_or_none()

        if row is None:
            row = PipelineTaskRun(
                run_id=run_id,
                source=source,
                date=target_date,
                status=status,
                articles_saved=articles_saved,
                error_message=error_message,
            )
            session.add(row)
        else:
            row.status = status
            if articles_saved is not None:
                row.articles_saved = articles_saved
            if error_message is not None:
                row.error_message = error_message
            row.updated_at = datetime.now(timezone.utc)

        session.commit()


def _get_existing_hashes(candidate_hashes: set[str]) -> set[str]:
    with Session(sync_engine) as session:
        rows = session.execute(
            select(Article.dedup_hash).where(Article.dedup_hash.in_(candidate_hashes))
        ).scalars().all()
    return set(rows)


def _save_articles(articles: list[dict]) -> list[int]:
    """Insert articles; returns list of new article IDs.

    Uses ON CONFLICT DO NOTHING to handle race conditions where the same
    dedup_hash is inserted by concurrent requests.
    """
    if not articles:
        return []
    values = []
    for art in articles:
        art.pop("_abstract", None)
        values.append(art)
    with Session(sync_engine) as session:
        stmt = (
            pg_insert(Article)
            .values(values)
            .on_conflict_do_nothing(index_elements=["dedup_hash"])
            .returning(Article.id)
        )
        saved_ids = list(session.execute(stmt).scalars().all())
        session.commit()
    return saved_ids


def _decode_pubsub_payload(body: dict) -> dict:
    """Decode a Pub/Sub push subscription message body."""
    message = body.get("message", {})
    data_b64 = message.get("data", "")
    if not data_b64:
        raise ValueError("No data in Pub/Sub message")
    return json.loads(base64.b64decode(data_b64).decode())


# ---------------------------------------------------------------------------
# POST /internal/fetch-source
# ---------------------------------------------------------------------------

class FetchSourceRequest(BaseModel):
    run_id: int
    source: str   # "hn" | "reddit" | "arxiv" | "rss"
    date: str     # ISO date string


@router.post("/fetch-source")
async def fetch_source(req: FetchSourceRequest, _: None = Depends(require_internal)):
    """Fetch one source for one date, dedup, save, and publish to Pub/Sub.

    Called by Cloud Tasks (one task per source × date combination).
    """
    try:
        target_date = date.fromisoformat(req.date)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date: {req.date}")

    _upsert_task_run(req.run_id, req.source, target_date, "running")
    logger.info("fetch-source start: run=%s source=%s date=%s", req.run_id, req.source, target_date)

    try:
        # 1. Fetch
        raw_articles = await _fetch_one_source(req.source, target_date)
        logger.info("fetch-source fetched %d raw articles", len(raw_articles))

        # 2. Hash dedup
        candidate_hashes = {a["dedup_hash"] for a in raw_articles}
        existing_hashes = await asyncio.to_thread(_get_existing_hashes, candidate_hashes)
        new_articles = [a for a in raw_articles if a["dedup_hash"] not in existing_hashes]
        logger.info("fetch-source hash dedup: %d → %d", len(raw_articles), len(new_articles))

        # 3. Semantic dedup (Vertex AI)
        if new_articles:
            deduped = await asyncio.to_thread(deduplicate_articles, new_articles)
        else:
            deduped = []
        logger.info("fetch-source semantic dedup: %d → %d", len(new_articles), len(deduped))

        # 4. Save
        saved_ids: list[int] = []
        if deduped:
            saved_ids = await asyncio.to_thread(_save_articles, deduped)
        logger.info("fetch-source saved %d articles", len(saved_ids))

        # 5. Publish to Pub/Sub
        publish_articles_saved(
            article_ids=saved_ids,
            run_id=req.run_id,
            source=req.source,
            target_date=req.date,
        )

        # 6. Update task status
        _upsert_task_run(req.run_id, req.source, target_date, "success", articles_saved=len(saved_ids))

        return {
            "status": "success",
            "fetched": len(raw_articles),
            "new": len(new_articles),
            "deduped": len(deduped),
            "saved": len(saved_ids),
        }

    except Exception as exc:
        logger.exception("fetch-source failed: run=%s source=%s date=%s", req.run_id, req.source, target_date)
        _upsert_task_run(req.run_id, req.source, target_date, "failed", error_message=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


async def _fetch_one_source(source: str, target_date: date) -> list[dict]:
    """Dispatch to the correct fetcher."""
    if source == "hn":
        from backend.ingestion.sources.hackernews import fetch_hackernews
        return await fetch_hackernews(target_date)
    elif source == "reddit":
        from backend.ingestion.sources.reddit import fetch_reddit
        return await asyncio.to_thread(fetch_reddit, target_date)
    elif source == "arxiv":
        from backend.ingestion.sources.arxiv_source import fetch_arxiv
        return await asyncio.to_thread(fetch_arxiv, target_date)
    elif source == "rss":
        from backend.ingestion.sources.rss_feeds import fetch_rss
        return await asyncio.to_thread(fetch_rss, target_date, None)
    else:
        raise ValueError(f"Unknown source: {source}")


# ---------------------------------------------------------------------------
# POST /internal/enrich  (Pub/Sub push subscription)
# ---------------------------------------------------------------------------

@router.post("/enrich")
async def enrich_handler(request: Request, _: None = Depends(require_internal)):
    """Pub/Sub push subscription handler: enrich articles with Gemini.

    Pub/Sub delivers messages as:
      { "message": { "data": "<base64 JSON>" }, "subscription": "..." }
    """
    body = await request.json()

    try:
        payload = _decode_pubsub_payload(body)
    except Exception as exc:
        logger.error("enrich: bad Pub/Sub payload: %s", exc)
        # Return 200 to ack — malformed messages should not be retried
        return {"status": "acked_bad_payload"}

    article_ids: list[int] = payload.get("article_ids", [])
    run_id: Optional[int] = payload.get("run_id")

    if not article_ids:
        logger.info("enrich: no article_ids in payload — nothing to do")
        return {"status": "noop"}

    logger.info("enrich: enriching %d articles (run=%s)", len(article_ids), run_id)

    from backend.processing.enricher import enrich_articles
    enriched = await enrich_articles(saved_ids=article_ids, run_id=run_id)
    logger.info("enrich: done, enriched %d/%d", enriched, len(article_ids))

    return {"status": "ok", "enriched": enriched, "total": len(article_ids)}


# ---------------------------------------------------------------------------
# POST /internal/vectorize  (Pub/Sub push subscription)
# ---------------------------------------------------------------------------

@router.post("/vectorize")
async def vectorize_handler(request: Request, _: None = Depends(require_internal)):
    """Pub/Sub push subscription handler: embed and upsert articles to Vertex AI."""
    body = await request.json()

    try:
        payload = _decode_pubsub_payload(body)
    except Exception as exc:
        logger.error("vectorize: bad Pub/Sub payload: %s", exc)
        return {"status": "acked_bad_payload"}

    article_ids: list[int] = payload.get("article_ids", [])
    if not article_ids:
        return {"status": "noop"}

    logger.info("vectorize: vectorizing %d articles", len(article_ids))

    from backend.processing.vectorizer import upsert_article_vector

    # Read article data then release connection — don't hold it during Vertex AI calls
    with Session(sync_engine) as session:
        rows = session.execute(
            select(Article.id, Article.title).where(Article.id.in_(article_ids))
        ).all()
    article_data = [(r.id, r.title) for r in rows]

    # Vectorize without holding a DB connection
    results: dict[int, bool] = {}
    for aid, title in article_data:
        ok = await asyncio.to_thread(upsert_article_vector, aid, title, "")
        results[aid] = ok

    # Write statuses in a short-lived session
    success = 0
    with Session(sync_engine) as session:
        for aid, ok in results.items():
            session.execute(
                __import__("sqlalchemy").text(
                    "UPDATE articles SET is_vectorized = :status WHERE id = :id"
                ),
                {"status": 1 if ok else -1, "id": aid},
            )
            if ok:
                success += 1
        session.commit()

    logger.info("vectorize: done, %d/%d succeeded", success, len(article_ids))
    return {"status": "ok", "vectorized": success, "total": len(article_ids)}


# ---------------------------------------------------------------------------
# GET /internal/finalize-runs  (Cloud Scheduler, every 60s)
# ---------------------------------------------------------------------------

@router.get("/finalize-runs")
async def finalize_runs(_: None = Depends(require_internal)):
    """Check Cloud Tasks-based pipeline runs and flip PipelineRun status when all tasks complete.

    Called by Cloud Scheduler every 60 seconds.
    """
    terminal_statuses = ("success", "failed", "cancelled")

    with Session(sync_engine) as session:
        # Find runs that are in queued/running state and have total_tasks set (Cloud Tasks mode)
        active_runs = session.execute(
            select(PipelineRun).where(
                PipelineRun.status.in_(["queued", "running"]),
                PipelineRun.total_tasks.isnot(None),
            )
        ).scalars().all()

        finalized = []
        stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)

        for run in active_runs:
            # Expire tasks stuck in "running" for >10 minutes (worker died)
            stale_tasks = session.execute(
                select(PipelineTaskRun).where(
                    PipelineTaskRun.run_id == run.id,
                    PipelineTaskRun.status == "running",
                    PipelineTaskRun.updated_at < stale_cutoff,
                )
            ).scalars().all()
            for t in stale_tasks:
                t.status = "failed"
                t.error_message = "Timed out — worker did not report back within 10 minutes"
                logger.warning("Marked stale task %s (run=%s, %s/%s) as failed", t.id, run.id, t.source, t.date)

            # Count completed tasks
            counts = session.execute(
                select(
                    func.count(PipelineTaskRun.id).label("total"),
                    func.count(PipelineTaskRun.id).filter(
                        PipelineTaskRun.status == "success"
                    ).label("succeeded"),
                    func.count(PipelineTaskRun.id).filter(
                        PipelineTaskRun.status == "failed"
                    ).label("failed"),
                ).where(PipelineTaskRun.run_id == run.id)
            ).one()

            completed = counts.succeeded + counts.failed
            # Also account for tasks that were never created (enqueue failed or worker never started)
            run_age_minutes = (datetime.now(timezone.utc) - run.started_at).total_seconds() / 60
            tasks_missing = run.total_tasks - counts.total
            stale_run = run_age_minutes > 15 and tasks_missing > 0

            if completed < run.total_tasks and not stale_run:
                # Set to running if still queued
                if run.status == "queued" and counts.total > 0:
                    run.status = "running"
                continue

            # All tasks have completed (or run is stale with missing tasks)
            if counts.failed > 0 or tasks_missing > 0:
                run.status = "partial"
            else:
                run.status = "success"

            run.completed_at = datetime.now(timezone.utc)
            if run.started_at:
                delta = run.completed_at - run.started_at
                run.duration_seconds = delta.total_seconds()

            # Summarize result
            saved_total = session.execute(
                select(func.sum(PipelineTaskRun.articles_saved)).where(
                    PipelineTaskRun.run_id == run.id,
                    PipelineTaskRun.status == "success",
                )
            ).scalar() or 0
            run.result = {
                "saved": int(saved_total),
                "tasks_succeeded": counts.succeeded,
                "tasks_failed": counts.failed,
                "date_from": run.target_date,
                "date_to": run.date_to or run.target_date,
            }
            finalized.append(run.id)
            logger.info(
                "Finalized run %s → %s (%d succeeded, %d failed tasks)",
                run.id, run.status, counts.succeeded, counts.failed,
            )

        session.commit()

    return {"finalized": finalized, "checked": len(active_runs)}


# ---------------------------------------------------------------------------
# GET /internal/scrub-orphans  (Cloud Scheduler, every 60m)
# ---------------------------------------------------------------------------

ENRICH_RETRY_CAP = 3  # max scrub-driven retries for is_enriched=-1 articles


@router.get("/scrub-orphans")
async def scrub_orphans(_: None = Depends(require_internal)):
    """Re-publish articles that are still pending enrichment/vectorization.

    Catches articles whose Pub/Sub publish failed during /internal/fetch-source
    or whose enrichment/vectorization workers crashed.

    Also retries articles stuck at is_enriched=-1 (enrichment hard-failed) up to
    ENRICH_RETRY_CAP times by resetting them to is_enriched=0 before republishing.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)

    with Session(sync_engine) as session:
        # Articles pending enrichment (normal path)
        pending_enrich_ids = session.execute(
            select(Article.id).where(
                Article.is_enriched == 0,
                Article.ingested_at < cutoff,
            )
        ).scalars().all()

        # Articles that failed enrichment but still have retries left — reset to pending
        failed_enrich = session.execute(
            select(Article).where(
                Article.is_enriched == -1,
                Article.enrich_retries < ENRICH_RETRY_CAP,
                Article.ingested_at < cutoff,
            )
        ).scalars().all()

        retried_ids: list[int] = []
        for article in failed_enrich:
            article.is_enriched = 0
            article.enrich_retries = (article.enrich_retries or 0) + 1
            retried_ids.append(article.id)
        if retried_ids:
            session.commit()
            logger.info(
                "scrub-orphans: reset %d failed-enrich articles to pending (retries incremented)",
                len(retried_ids),
            )

        # Articles pending vectorization
        pending_vector = session.execute(
            select(Article.id).where(
                Article.is_vectorized == 0,
                Article.ingested_at < cutoff,
            )
        ).scalars().all()

        # Articles that failed vectorization — reset to pending for retry
        # (vectorization is idempotent, failures are rare, no retry cap needed)
        failed_vector = session.execute(
            select(Article).where(
                Article.is_vectorized == -1,
                Article.ingested_at < cutoff,
            )
        ).scalars().all()

        failed_vector_ids: list[int] = []
        for article in failed_vector:
            article.is_vectorized = 0
            failed_vector_ids.append(article.id)
        if failed_vector_ids:
            session.commit()
            logger.info(
                "scrub-orphans: reset %d failed-vectorize articles to pending",
                len(failed_vector_ids),
            )

    all_enrich_ids = list(pending_enrich_ids) + retried_ids

    enrich_published = 0
    if all_enrich_ids:
        ok = publish_articles_saved(
            article_ids=all_enrich_ids,
            run_id=0,
            source="scrub",
            target_date="scrub",
        )
        if ok:
            enrich_published = len(all_enrich_ids)
        logger.info(
            "scrub-orphans: republished %d enrich articles (%d pending + %d retried)",
            enrich_published, len(pending_enrich_ids), len(retried_ids),
        )

    all_vector_ids = list(pending_vector) + failed_vector_ids
    vector_published = 0
    if all_vector_ids:
        ok = publish_articles_saved(
            article_ids=all_vector_ids,
            run_id=0,
            source="scrub",
            target_date="scrub",
        )
        if ok:
            vector_published = len(all_vector_ids)
        logger.info(
            "scrub-orphans: republished %d vectorize articles (%d pending + %d retried)",
            vector_published, len(pending_vector), len(failed_vector_ids),
        )

    return {
        "pending_enrich": len(pending_enrich_ids),
        "failed_enrich_retried": len(retried_ids),
        "pending_vector": len(pending_vector),
        "failed_vector_retried": len(failed_vector_ids),
        "enrich_published": enrich_published,
        "vector_published": vector_published,
    }
