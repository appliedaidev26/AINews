"""Admin routes — pipeline trigger, run history, cancellation, coverage, and sources."""
import asyncio
import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, text, delete, func

from backend.config import settings
from backend.db import get_db
from backend.db.models import PipelineRun, RssFeed
from backend.ingestion.pipeline import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

# Module-level registry of live asyncio tasks keyed by run_id.
# Works reliably on single-instance Cloud Run (min-instances=1).
_active_tasks: dict[int, asyncio.Task] = {}


def require_admin(x_admin_key: str = Header(...)) -> str:
    if not settings.admin_api_key or x_admin_key != settings.admin_api_key:
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
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
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
            "stage": "queued",
            "sources_used": sorted(enabled_sources),
            "rss_feed_ids_used": sorted(parsed_feed_ids) if parsed_feed_ids is not None else None,
            "rss_feed_names_used": rss_feed_names_used,
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    task = asyncio.create_task(
        run_pipeline(date_from=effective_from, date_to=effective_to, run_id=run.id,
                     enabled_sources=enabled_sources, rss_feed_ids=parsed_feed_ids)
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
    if not run or run.status != "running":
        raise HTTPException(status_code=404, detail="No active run found for this run_id")

    run.status = "cancelled"
    run.completed_at = datetime.now(timezone.utc)
    run.error_message = "Cancelled by admin (task lost — server had restarted)"
    await db.commit()
    return {"status": "cancelled", "run_id": run_id}


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


@router.post("/clear-db")
async def clear_db(
    key: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Truncate articles, pipeline_runs, and user_article_scores. Preserves rss_feeds and user_profiles."""
    article_count = (await db.execute(text("SELECT COUNT(*) FROM articles"))).scalar()
    run_count     = (await db.execute(text("SELECT COUNT(*) FROM pipeline_runs"))).scalar()

    await db.execute(text(
        "TRUNCATE TABLE articles, pipeline_runs, user_article_scores RESTART IDENTITY CASCADE"
    ))
    await db.commit()

    logger.warning(f"DB cleared by admin: {article_count} articles, {run_count} pipeline runs deleted")
    return {
        "status":    "cleared",
        "deleted":   {"articles": article_count, "pipeline_runs": run_count},
        "preserved": ["rss_feeds", "user_profiles"],
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
