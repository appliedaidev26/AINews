"""Admin routes — pipeline trigger, run history, cancellation, coverage, and sources."""
import asyncio
import hmac
import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, text, delete, func, or_

from backend.config import settings
from backend.db import get_db, sync_engine
from backend.db.models import Article, PipelineRun, PipelineTaskRun, RssFeed
from backend.ingestion.pipeline import run_pipeline
from backend.ingestion.cloud_tasks import enqueue_fetch_task
from backend.processing.enricher import enrich_failed_articles, enrich_pending_articles
from backend.ingestion.pubsub import publish_articles_saved

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

# Module-level registry of live asyncio tasks keyed by run_id.
# Works reliably on single-instance Cloud Run (min-instances=1).
_active_tasks: dict[int, asyncio.Task] = {}


async def _run_enrichment_task(coro, run_id: int, total_articles: int):
    """Wrap an enrichment coroutine so it updates the PipelineRun when done."""
    import time
    t0 = time.monotonic()
    try:
        enriched = await coro
        duration = time.monotonic() - t0
        ratio = enriched / total_articles if total_articles > 0 else 1.0
        if total_articles > 0 and ratio < 0.5:
            status = "partial"
            error_msg = f"Enrichment mostly failed: {enriched}/{total_articles} ({ratio:.0%})"
        else:
            status = "success"
            error_msg = None
        from sqlalchemy.orm import Session as _Session
        with _Session(sync_engine) as session:
            run = session.get(PipelineRun, run_id)
            if run:
                run.status = status
                run.completed_at = datetime.now(timezone.utc)
                run.duration_seconds = duration
                run.error_message = error_msg
                run.result = {"enriched": enriched, "total": total_articles}
                session.commit()
    except asyncio.CancelledError:
        from sqlalchemy.orm import Session as _Session
        with _Session(sync_engine) as session:
            run = session.get(PipelineRun, run_id)
            if run:
                run.status = "cancelled"
                run.completed_at = datetime.now(timezone.utc)
                run.duration_seconds = time.monotonic() - t0
                run.error_message = "Cancelled by admin"
                session.commit()
        raise
    except Exception as exc:
        from sqlalchemy.orm import Session as _Session
        with _Session(sync_engine) as session:
            run = session.get(PipelineRun, run_id)
            if run:
                run.status = "failed"
                run.completed_at = datetime.now(timezone.utc)
                run.duration_seconds = time.monotonic() - t0
                run.error_message = str(exc)
                session.commit()
        logger.exception("Enrichment task failed for run %s", run_id)


def _check_concurrent_limit():
    """Raise HTTP 429 if too many pipeline runs are already active."""
    active = sum(1 for t in _active_tasks.values() if not t.done())
    if active >= settings.max_concurrent_runs:
        raise HTTPException(
            status_code=429,
            detail=f"Too many concurrent runs ({active}/{settings.max_concurrent_runs}). "
                   f"Wait for an active run to finish or cancel one first.",
        )


def require_admin(x_admin_key: str = Header(...)) -> str:
    if not settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Admin disabled")
    if not hmac.compare_digest(x_admin_key, settings.admin_api_key):
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return x_admin_key


@router.post("/ingest")
async def trigger_ingest(
    date_from:    Optional[date] = Query(None, description="Range start (ISO date, e.g. 2026-01-01)"),
    date_to:      Optional[date] = Query(None, description="Range end (ISO date, e.g. 2026-01-31)"),
    target_date:  Optional[date] = Query(None, description="Legacy single-date param — kept for compat"),
    triggered_by: str            = Query("api"),
    sources:      str            = Query("hn,reddit,arxiv,rss", description="Comma-separated source types to include"),
    rss_feed_ids: str            = Query("", description="Comma-separated RSS feed IDs; empty means all active feeds"),
    populate_trending: bool      = Query(False, description="Also fetch last 2 days of HN+Reddit for trending strip"),
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _check_concurrent_limit()
    effective_from = date_from or target_date or date.today()
    effective_to   = date_to or effective_from

    enabled_sources = {s.strip().lower() for s in sources.split(",") if s.strip()}
    if not enabled_sources:
        enabled_sources = {"hn", "reddit", "arxiv", "rss"}

    parsed_feed_ids: Optional[set[int]] = None
    if rss_feed_ids.strip():
        parsed_feed_ids = {int(i) for i in rss_feed_ids.split(",") if i.strip().isdigit()}

    # Resolve feed names now (denormalized) so the detail panel can display them
    # even if feeds are later renamed or deleted.
    rss_feed_names_used: Optional[dict] = None
    if "rss" in enabled_sources:
        feed_q = select(RssFeed.id, RssFeed.name)
        if parsed_feed_ids is not None:
            feed_q = feed_q.where(RssFeed.id.in_(parsed_feed_ids))
        else:
            feed_q = feed_q.where(RssFeed.is_active == True)  # noqa: E712
        feed_rows = (await db.execute(feed_q)).all()
        rss_feed_names_used = {row.id: row.name for row in feed_rows}

    run = PipelineRun(
        started_at=datetime.now(timezone.utc),
        status="running",
        target_date=str(effective_from),
        date_to=str(effective_to),
        triggered_by=triggered_by,
        progress={
            "run_type": "ingestion",
            "stage": "queued",
            "sources_used": sorted(enabled_sources),
            "rss_feed_ids_used": sorted(parsed_feed_ids) if parsed_feed_ids is not None else None,
            "rss_feed_names_used": rss_feed_names_used,
            "populate_trending": populate_trending,
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    task = asyncio.create_task(
        run_pipeline(date_from=effective_from, date_to=effective_to, run_id=run.id,
                     enabled_sources=enabled_sources, rss_feed_ids=parsed_feed_ids,
                     populate_trending=populate_trending)
    )
    _active_tasks[run.id] = task
    task.add_done_callback(lambda _: _active_tasks.pop(run.id, None))

    return {
        "status":    "started",
        "date_from": str(effective_from),
        "date_to":   str(effective_to),
        "run_id":    run.id,
        "sources":   sorted(enabled_sources),
    }


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: int,
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    task = _active_tasks.get(run_id)
    if task is not None and not task.done():
        task.cancel()  # Raises CancelledError inside pipeline coroutine
        return {"status": "cancelling", "run_id": run_id}

    # Task not in memory — server may have restarted. Fall back to direct DB update.
    result = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run or run.status not in ("running", "queued"):
        raise HTTPException(status_code=404, detail="No active run found for this run_id")

    run.status = "cancelled"
    run.completed_at = datetime.now(timezone.utc)
    run.error_message = "Cancelled by admin (task lost — server had restarted)"
    await db.commit()
    return {"status": "cancelled", "run_id": run_id}


@router.post("/retry-failed")
async def retry_failed_enrichments(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _check_concurrent_limit()
    effective_from = date_from or (date.today() - timedelta(days=90))
    effective_to = date_to or date.today()

    count_result = await db.execute(
        select(func.count(Article.id)).where(
            Article.is_enriched == -1,
            Article.digest_date >= effective_from,
            Article.digest_date <= effective_to,
        )
    )
    article_count = count_result.scalar() or 0

    if article_count == 0:
        return {"status": "nothing_to_retry", "article_count": 0}

    run = PipelineRun(
        started_at=datetime.now(timezone.utc),
        status="running",
        target_date=str(effective_from),
        date_to=str(effective_to),
        triggered_by="retry_failed",
        progress={
            "run_type": "retry",
            "stage": "enriching",
            "fetched": 0, "new": 0, "saved": 0, "enriched": 0,
            "total_to_enrich": article_count,
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    task = asyncio.create_task(
        _run_enrichment_task(
            enrich_failed_articles(effective_from, effective_to, run.id),
            run.id, article_count,
        )
    )
    _active_tasks[run.id] = task
    task.add_done_callback(lambda _: _active_tasks.pop(run.id, None))

    return {
        "status": "started",
        "run_id": run.id,
        "article_count": article_count,
        "date_from": str(effective_from),
        "date_to": str(effective_to),
    }


@router.post("/republish-failed")
async def republish_failed(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reset is_enriched=-1 articles to 0 and republish to Pub/Sub for batch processing."""
    effective_from = date_from or (date.today() - timedelta(days=90))
    effective_to = date_to or date.today()

    result = await db.execute(
        select(Article.id).where(
            Article.is_enriched == -1,
            Article.digest_date >= effective_from,
            Article.digest_date <= effective_to,
        )
    )
    article_ids = list(result.scalars().all())

    if not article_ids:
        return {"status": "nothing_to_republish", "count": 0}

    # Reset to pending
    await db.execute(
        text("UPDATE articles SET is_enriched = 0 WHERE id = ANY(:ids)"),
        {"ids": article_ids},
    )
    await db.commit()

    # Republish to Pub/Sub in batches (enrich handler processes 15 at a time)
    ok = publish_articles_saved(
        article_ids=article_ids,
        run_id=0,
        source="republish",
        target_date="republish",
    )

    return {
        "status": "republished" if ok else "publish_failed",
        "count": len(article_ids),
        "date_from": str(effective_from),
        "date_to": str(effective_to),
    }


@router.post("/enrich-pending")
async def enrich_pending(
    date_from: Optional[date] = Query(None, description="Only enrich articles on or after this date"),
    date_to:   Optional[date] = Query(None, description="Only enrich articles on or before this date"),
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Enrich all pending articles (is_enriched IS NULL or 0) in the optional date range."""
    _check_concurrent_limit()
    stmt = select(func.count(Article.id)).where(
        or_(Article.is_enriched.is_(None), Article.is_enriched == 0)
    )
    if date_from:
        stmt = stmt.where(Article.digest_date >= date_from)
    if date_to:
        stmt = stmt.where(Article.digest_date <= date_to)
    article_count = (await db.execute(stmt)).scalar() or 0

    if article_count == 0:
        return {"status": "nothing_to_enrich", "article_count": 0}

    run = PipelineRun(
        started_at=datetime.now(timezone.utc),
        status="running",
        target_date=str(date_from or date.today()),
        date_to=str(date_to or date.today()),
        triggered_by="enrich_pending",
        progress={
            "run_type": "enrichment",
            "stage": "enriching",
            "fetched": 0, "new": 0, "saved": 0, "enriched": 0,
            "total_to_enrich": article_count,
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    task = asyncio.create_task(
        _run_enrichment_task(
            enrich_pending_articles(run_id=run.id, date_from=date_from, date_to=date_to),
            run.id, article_count,
        )
    )
    _active_tasks[run.id] = task
    task.add_done_callback(lambda _: _active_tasks.pop(run.id, None))

    return {
        "status": "started",
        "run_id": run.id,
        "article_count": article_count,
        "date_from": str(date_from) if date_from else None,
        "date_to": str(date_to) if date_to else None,
    }


@router.get("/runs/{run_id}")
async def get_run(
    run_id: int,
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.to_dict()


@router.get("/runs")
async def list_runs(
    limit: int = Query(50, ge=1, le=200),
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PipelineRun).order_by(desc(PipelineRun.started_at)).limit(limit)
    )
    runs = result.scalars().all()
    return {"runs": [r.to_dict() for r in runs], "total": len(runs)}


@router.get("/coverage")
async def get_coverage(
    days: int = Query(90, ge=1, le=365),
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return per-date article counts for the last N days."""
    cutoff = date.today() - timedelta(days=days)
    result = await db.execute(
        text("""
            SELECT
                digest_date,
                COUNT(*)                                        AS total,
                COUNT(*) FILTER (WHERE is_enriched =  1)      AS enriched,
                COUNT(*) FILTER (WHERE is_enriched =  0)      AS pending,
                COUNT(*) FILTER (WHERE is_enriched = -1)      AS failed
            FROM articles
            WHERE digest_date >= :cutoff
            GROUP BY digest_date
            ORDER BY digest_date DESC
        """),
        {"cutoff": cutoff},
    )
    rows = result.mappings().all()
    return {
        "coverage": [
            {
                "date":     str(r["digest_date"]),
                "total":    r["total"],
                "enriched": r["enriched"],
                "pending":  r["pending"],
                "failed":   r["failed"],
            }
            for r in rows
        ]
    }


# ── Sources management ──────────────────────────────────────────────


class RssFeedBody(BaseModel):
    name: str
    url: str
    is_active: bool = True


@router.get("/sources")
async def get_sources(
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all RSS feeds from DB + read-only HN/Reddit/Arxiv configs."""
    result = await db.execute(select(RssFeed).order_by(RssFeed.id))
    feeds = [f.to_dict() for f in result.scalars().all()]

    from backend.ingestion.sources.hackernews import AI_ML_KEYWORDS as HN_KEYWORDS
    from backend.ingestion.sources.reddit import SUBREDDITS, MIN_UPVOTES
    from backend.ingestion.sources.arxiv_source import ARXIV_CATEGORIES, AI_KEYWORDS as ARXIV_KEYWORDS

    return {
        "rss_feeds": feeds,
        "readonly": {
            "hackernews": {
                "min_score": settings.hn_min_score,
                "keyword_count": len(HN_KEYWORDS),
            },
            "reddit": {
                "subreddits": SUBREDDITS,
                "min_upvotes": MIN_UPVOTES,
                "configured": bool(settings.reddit_client_id and settings.reddit_client_secret),
            },
            "arxiv": {
                "categories": ARXIV_CATEGORIES,
                "keyword_count": len(ARXIV_KEYWORDS),
            },
        },
    }


@router.post("/sources/rss")
async def add_rss_feed(
    body: RssFeedBody,
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    name = body.name.strip()
    url = body.url.strip()

    if not name or len(name) > 100:
        raise HTTPException(status_code=422, detail="Name must be 1-100 characters")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=422, detail="URL must be a valid http(s) URL")

    # Check duplicate
    existing = await db.execute(select(RssFeed).where(RssFeed.url == url))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A feed with this URL already exists")

    # Validate feed is reachable and parseable
    import httpx
    import feedparser

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not fetch URL: {e}")

    parsed_feed = feedparser.parse(resp.text)
    if not parsed_feed.get("entries"):
        raise HTTPException(status_code=422, detail="URL does not appear to be a valid RSS/Atom feed (no entries found)")

    feed = RssFeed(name=name, url=url, is_active=body.is_active)
    db.add(feed)
    await db.commit()
    await db.refresh(feed)
    return feed.to_dict()


@router.put("/sources/rss/{feed_id}")
async def update_rss_feed(
    feed_id: int,
    body: RssFeedBody,
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(RssFeed).where(RssFeed.id == feed_id))
    feed = result.scalar_one_or_none()
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")

    name = body.name.strip()
    url = body.url.strip()

    if not name or len(name) > 100:
        raise HTTPException(status_code=422, detail="Name must be 1-100 characters")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=422, detail="URL must be a valid http(s) URL")

    # Check duplicate (excluding self)
    existing = await db.execute(
        select(RssFeed).where(RssFeed.url == url, RssFeed.id != feed_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A feed with this URL already exists")

    feed.name = name
    feed.url = url
    feed.is_active = body.is_active
    await db.commit()
    await db.refresh(feed)
    return feed.to_dict()


@router.post("/queue-run")
async def queue_run(
    date_from:    Optional[date] = Query(None, description="Range start (ISO date)"),
    date_to:      Optional[date] = Query(None, description="Range end (ISO date)"),
    triggered_by: str            = Query("api"),
    sources:      str            = Query("hn,reddit,arxiv,rss", description="Comma-separated source types"),
    rss_feed_ids: str            = Query("", description="Comma-separated RSS feed IDs; empty means all active feeds"),
    populate_trending: bool      = Query(False, description="Also fetch last 2 days of HN+Reddit for trending strip"),
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a PipelineRun and execute the in-process pipeline."""
    _check_concurrent_limit()
    effective_from = date_from or date.today()
    effective_to   = date_to or effective_from

    enabled_sources = {s.strip().lower() for s in sources.split(",") if s.strip()}
    if not enabled_sources:
        enabled_sources = {"hn", "reddit", "arxiv", "rss"}

    parsed_feed_ids: Optional[set[int]] = None
    if rss_feed_ids.strip():
        parsed_feed_ids = {int(i) for i in rss_feed_ids.split(",") if i.strip().isdigit()}

    # Resolve feed names for the detail panel
    rss_feed_names_used: Optional[dict] = None
    if "rss" in enabled_sources:
        feed_q = select(RssFeed.id, RssFeed.name)
        if parsed_feed_ids is not None:
            feed_q = feed_q.where(RssFeed.id.in_(parsed_feed_ids))
        else:
            feed_q = feed_q.where(RssFeed.is_active == True)  # noqa: E712
        feed_rows = (await db.execute(feed_q)).all()
        rss_feed_names_used = {row.id: row.name for row in feed_rows}

    run = PipelineRun(
        started_at=datetime.now(timezone.utc),
        status="running",
        target_date=str(effective_from),
        date_to=str(effective_to),
        triggered_by=triggered_by,
        progress={
            "run_type": "backfill",
            "stage": "fetching",
            "sources_used": sorted(enabled_sources),
            "rss_feed_ids_used": sorted(parsed_feed_ids) if parsed_feed_ids is not None else None,
            "rss_feed_names_used": rss_feed_names_used,
            "populate_trending": populate_trending,
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    task = asyncio.create_task(
        run_pipeline(
            date_from=effective_from,
            date_to=effective_to,
            run_id=run.id,
            enabled_sources=enabled_sources,
            rss_feed_ids=parsed_feed_ids,
            populate_trending=populate_trending,
        )
    )
    _active_tasks[run.id] = task
    task.add_done_callback(lambda _: _active_tasks.pop(run.id, None))

    return {
        "status":    "running",
        "run_id":    run.id,
        "date_from": str(effective_from),
        "date_to":   str(effective_to),
        "sources":   sorted(enabled_sources),
    }


@router.get("/runs/{run_id}/tasks")
async def get_run_tasks(
    run_id: int,
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all pipeline_task_runs rows for a run plus a run summary."""
    run_result = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
    run = run_result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    tasks_result = await db.execute(
        select(PipelineTaskRun)
        .where(PipelineTaskRun.run_id == run_id)
        .order_by(PipelineTaskRun.date, PipelineTaskRun.source)
    )
    tasks = tasks_result.scalars().all()

    return {
        "run": run.to_dict(),
        "tasks": [t.to_dict() for t in tasks],
    }


@router.get("/runs/{run_id}/enrich-status")
async def get_run_enrich_status(
    run_id: int,
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return enrichment and vectorization counts for articles saved in this run.

    We identify articles by joining pipeline_task_runs dates to articles.digest_date.
    """
    # Get date range for this run
    run_result = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
    run = run_result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    from datetime import date as _date
    date_from_obj = _date.fromisoformat(run.target_date)
    date_to_obj   = _date.fromisoformat(run.date_to or run.target_date)

    result = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total_saved,
                COUNT(*) FILTER (WHERE is_enriched  = 1) AS enriched,
                COUNT(*) FILTER (WHERE is_vectorized = 1) AS vectorized
            FROM articles
            WHERE digest_date BETWEEN :date_from AND :date_to
        """),
        {"date_from": date_from_obj, "date_to": date_to_obj},
    )
    row = result.mappings().one()
    return {
        "total_saved": row["total_saved"],
        "enriched":    row["enriched"],
        "vectorized":  row["vectorized"],
    }


@router.post("/runs/{run_id}/tasks/retry")
async def retry_run_tasks(
    run_id: int,
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Re-enqueue all failed tasks for a run."""
    run_result = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
    run = run_result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    failed_tasks_result = await db.execute(
        select(PipelineTaskRun).where(
            PipelineTaskRun.run_id == run_id,
            PipelineTaskRun.status == "failed",
        )
    )
    failed_tasks = failed_tasks_result.scalars().all()

    if not failed_tasks:
        return {"status": "nothing_to_retry", "retried": 0}

    enqueued = 0
    for task in failed_tasks:
        task.status = "pending"
        ok = enqueue_fetch_task(run_id, task.source, task.date)
        if ok:
            enqueued += 1

    await db.commit()
    return {"status": "ok", "retried": enqueued, "total_failed": len(failed_tasks)}


@router.post("/runs/{run_id}/tasks/{source}/{task_date}/retry")
async def retry_single_task(
    run_id: int,
    source: str,
    task_date: str,
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Re-enqueue a single failed task for a specific (source, date)."""
    try:
        parsed_date = date.fromisoformat(task_date)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date: {task_date}")

    task_result = await db.execute(
        select(PipelineTaskRun).where(
            PipelineTaskRun.run_id == run_id,
            PipelineTaskRun.source == source,
            PipelineTaskRun.date == parsed_date,
        )
    )
    task = task_result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = "pending"
    task.error_message = None
    await db.commit()

    ok = enqueue_fetch_task(run_id, source, parsed_date)
    return {
        "status": "enqueued" if ok else "enqueue_failed",
        "run_id": run_id,
        "source": source,
        "date": task_date,
    }


@router.get("/dlq")
async def get_dlq(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List dead-lettered articles: enrichment permanently failed (is_enriched=-1 AND retries>=3)
    or vectorization failed (is_vectorized=-1)."""
    from backend.api.routes.internal import ENRICH_RETRY_CAP

    # Count totals
    enrich_failed_count = (await db.execute(
        select(func.count(Article.id)).where(
            Article.is_enriched == -1,
            Article.enrich_retries >= ENRICH_RETRY_CAP,
        )
    )).scalar() or 0

    vectorize_failed_count = (await db.execute(
        select(func.count(Article.id)).where(
            Article.is_vectorized == -1,
        )
    )).scalar() or 0

    # Query articles matching DLQ criteria
    dlq_filter = or_(
        (Article.is_enriched == -1) & (Article.enrich_retries >= ENRICH_RETRY_CAP),
        Article.is_vectorized == -1,
    )
    total = (await db.execute(select(func.count(Article.id)).where(dlq_filter))).scalar() or 0

    result = await db.execute(
        select(Article)
        .where(dlq_filter)
        .order_by(desc(Article.ingested_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    articles = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "enrich_failed": enrich_failed_count,
        "vectorize_failed": vectorize_failed_count,
        "articles": [
            {
                "id": a.id,
                "title": a.title,
                "source_type": a.source_type,
                "source_name": a.source_name,
                "digest_date": str(a.digest_date) if a.digest_date else None,
                "ingested_at": a.ingested_at.isoformat() if a.ingested_at else None,
                "is_enriched": a.is_enriched,
                "is_vectorized": a.is_vectorized,
                "enrich_retries": a.enrich_retries,
                "original_url": a.original_url,
            }
            for a in articles
        ],
    }


@router.post("/dlq/retry")
async def retry_dlq(
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reset all DLQ articles and republish for reprocessing."""
    from backend.api.routes.internal import ENRICH_RETRY_CAP

    # Reset enrichment DLQ
    enrich_ids_result = await db.execute(
        select(Article.id).where(
            Article.is_enriched == -1,
            Article.enrich_retries >= ENRICH_RETRY_CAP,
        )
    )
    enrich_ids = list(enrich_ids_result.scalars().all())

    if enrich_ids:
        await db.execute(
            text("UPDATE articles SET is_enriched = 0, enrich_retries = 0 WHERE id = ANY(:ids)"),
            {"ids": enrich_ids},
        )

    # Reset vectorization DLQ
    vector_ids_result = await db.execute(
        select(Article.id).where(Article.is_vectorized == -1)
    )
    vector_ids = list(vector_ids_result.scalars().all())

    if vector_ids:
        await db.execute(
            text("UPDATE articles SET is_vectorized = 0 WHERE id = ANY(:ids)"),
            {"ids": vector_ids},
        )

    await db.commit()

    # Republish to Pub/Sub (or direct enrich in dev)
    all_ids = list(set(enrich_ids + vector_ids))
    published = False
    if all_ids:
        published = publish_articles_saved(
            article_ids=all_ids,
            run_id=0,
            source="dlq_retry",
            target_date="dlq_retry",
        )

    return {
        "status": "retried",
        "enrich_reset": len(enrich_ids),
        "vectorize_reset": len(vector_ids),
        "published": published,
    }


@router.post("/clear-db")
async def clear_db(
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Truncate articles, pipeline_runs, pipeline_task_runs, and user_article_scores. Preserves rss_feeds and user_profiles."""
    article_count = (await db.execute(text("SELECT COUNT(*) FROM articles"))).scalar()
    run_count     = (await db.execute(text("SELECT COUNT(*) FROM pipeline_runs"))).scalar()
    task_count    = (await db.execute(text("SELECT COUNT(*) FROM pipeline_task_runs"))).scalar()

    await db.execute(text(
        "TRUNCATE TABLE articles, pipeline_runs, pipeline_task_runs, user_article_scores RESTART IDENTITY CASCADE"
    ))
    await db.commit()

    logger.warning(f"DB cleared by admin: {article_count} articles, {run_count} pipeline runs, {task_count} task runs deleted")
    return {
        "status":    "cleared",
        "deleted":   {"articles": article_count, "pipeline_runs": run_count, "pipeline_task_runs": task_count},
        "preserved": ["rss_feeds", "user_profiles"],
    }


@router.get("/stats")
async def get_stats(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None),
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return article counts grouped by source_type, with optional month/year filters."""
    date_filter = []
    if year is not None:
        date_filter.append(func.extract("year", Article.digest_date) == year)
    if month is not None and year is not None:
        date_filter.append(func.extract("month", Article.digest_date) == month)

    # Source breakdown
    stmt = select(Article.source_type, func.count(Article.id).label("cnt")).group_by(Article.source_type)
    for f in date_filter:
        stmt = stmt.where(f)
    rows = (await db.execute(stmt)).all()
    by_source = {row.source_type: row.cnt for row in rows}
    total = sum(by_source.values())

    # Pipeline health breakdown
    pipeline_stmt = select(
        func.count(Article.id).label("total"),
        func.count(Article.id).filter(Article.is_enriched == 1).label("enriched"),
        func.count(Article.id).filter(Article.is_enriched == 0).label("enrich_pending"),
        func.count(Article.id).filter(Article.is_enriched == -1).label("enrich_failed"),
        func.count(Article.id).filter(Article.is_vectorized == 1).label("vectorized"),
        func.count(Article.id).filter(Article.is_vectorized == 0).label("vectorize_pending"),
        func.count(Article.id).filter(Article.is_vectorized == -1).label("vectorize_failed"),
    )
    for f in date_filter:
        pipeline_stmt = pipeline_stmt.where(f)
    p = (await db.execute(pipeline_stmt)).mappings().one()

    return {
        "total": total,
        "by_source": by_source,
        "pipeline": {
            "enriched": p["enriched"],
            "enrich_pending": p["enrich_pending"],
            "enrich_failed": p["enrich_failed"],
            "vectorized": p["vectorized"],
            "vectorize_pending": p["vectorize_pending"],
            "vectorize_failed": p["vectorize_failed"],
        },
        "filters": {"month": month, "year": year},
    }


@router.delete("/sources/rss/{feed_id}")
async def delete_rss_feed(
    feed_id: int,
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(RssFeed).where(RssFeed.id == feed_id))
    feed = result.scalar_one_or_none()
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    await db.delete(feed)
    await db.commit()
    return {"status": "deleted", "id": feed_id}
