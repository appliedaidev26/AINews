"""Main ingestion pipeline: fetches, deduplicates, and enriches articles."""
import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.config import settings
from backend.db import sync_engine
from backend.db.models import Article
from backend.ingestion.sources.hackernews import fetch_hackernews
from backend.ingestion.sources.reddit import fetch_reddit
from backend.ingestion.sources.arxiv_source import fetch_arxiv
from backend.ingestion.sources.rss_feeds import fetch_rss
from backend.processing.dedup import deduplicate_articles
from backend.processing.enricher import enrich_articles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def _update_progress(run_id, progress: dict):
    if run_id is None:
        return
    from sqlalchemy.orm import Session as _Session
    from backend.db import sync_engine
    from backend.db.models import PipelineRun
    with _Session(sync_engine) as session:
        # Read-merge-write: merge new stage fields into the existing JSONB so that
        # metadata written at run creation (sources_used, rss_feed_ids_used,
        # rss_feed_names_used) is preserved across every stage-update call.
        row = session.get(PipelineRun, run_id)
        if row is not None:
            row.progress = {**(row.progress or {}), **progress}
            session.commit()


def _update_run(run_id, status, result=None, error_message=None, duration_seconds=None):
    if run_id is None:
        return
    from sqlalchemy.orm import Session as _Session
    from sqlalchemy import update as sa_update
    from backend.db import sync_engine
    from backend.db.models import PipelineRun
    with _Session(sync_engine) as session:
        session.execute(
            sa_update(PipelineRun).where(PipelineRun.id == run_id).values(
                status=status,
                completed_at=datetime.now(timezone.utc),
                result=result,
                error_message=error_message,
                duration_seconds=duration_seconds,
            )
        )
        session.commit()


def _get_existing_hashes(session: Session, candidate_hashes: set[str]) -> set[str]:
    """Return which of the candidate hashes are already in the DB (globally, not per-date)."""
    if not candidate_hashes:
        return set()
    rows = session.execute(
        select(Article.dedup_hash).where(Article.dedup_hash.in_(candidate_hashes))
    ).scalars().all()
    return set(rows)


def _save_articles(session: Session, articles: list[dict]) -> list[Article]:
    """Persist new article records, skip duplicates."""
    saved = []
    for art in articles:
        extra = art.pop("_abstract", None)  # don't store raw abstract
        obj = Article(**art)
        session.add(obj)
        saved.append(obj)
    session.commit()
    # Refresh to get IDs
    for obj in saved:
        session.refresh(obj)
    return saved


async def _run_one_date(
    target_date: date,
    run_id: Optional[int],
    date_idx: int,
    dates_total: int,
    running_totals: dict,
    effective_from: date,
    effective_to: date,
    enabled_sources: set[str],
    rss_feed_ids: Optional[set[int]],
) -> dict:
    """Run the full pipeline for a single date. Returns per-date counts."""
    logger.info(f"Processing date {date_idx + 1}/{dates_total}: {target_date}")

    # --- Step 1: Fetch from all sources ---
    _update_progress(run_id, {
        "date_from": str(effective_from),
        "date_to":   str(effective_to),
        "stage": "fetching",
        "current_date": str(target_date),
        "dates_completed": date_idx,
        "dates_total": dates_total,
        **running_totals,
    })
    fetch_coros = []
    if "hn"     in enabled_sources: fetch_coros.append(fetch_hackernews(target_date))
    if "reddit" in enabled_sources: fetch_coros.append(asyncio.to_thread(fetch_reddit, target_date))
    if "arxiv"  in enabled_sources: fetch_coros.append(asyncio.to_thread(fetch_arxiv, target_date))
    if "rss"    in enabled_sources: fetch_coros.append(asyncio.to_thread(fetch_rss, target_date, rss_feed_ids))

    results = await asyncio.gather(*fetch_coros)
    raw_articles = [art for sublist in results for art in sublist]
    logger.info(f"[{target_date}] Fetched {len(raw_articles)} total raw articles")

    # --- Step 2: Filter already-ingested ---
    _update_progress(run_id, {
        "date_from": str(effective_from),
        "date_to":   str(effective_to),
        "stage": "filtering",
        "current_date": str(target_date),
        "dates_completed": date_idx,
        "dates_total": dates_total,
        "fetched": running_totals["fetched"] + len(raw_articles),
        **{k: v for k, v in running_totals.items() if k != "fetched"},
    })
    with Session(sync_engine) as session:
        candidate_hashes = {a["dedup_hash"] for a in raw_articles}
        existing_hashes = _get_existing_hashes(session, candidate_hashes)
        new_articles = [a for a in raw_articles if a["dedup_hash"] not in existing_hashes]
        logger.info(f"[{target_date}] {len(new_articles)} new after hash filter (skipped {len(raw_articles) - len(new_articles)})")

        if not new_articles:
            logger.info(f"[{target_date}] No new articles to process")
            return {"fetched": len(raw_articles), "new": 0, "saved": 0, "enriched": 0}

        # --- Step 3: Semantic deduplication ---
        _update_progress(run_id, {
            "date_from": str(effective_from),
            "date_to":   str(effective_to),
            "stage": "deduping",
            "current_date": str(target_date),
            "dates_completed": date_idx,
            "dates_total": dates_total,
            "fetched": running_totals["fetched"] + len(raw_articles),
            "new": running_totals["new"] + len(new_articles),
            "saved": running_totals["saved"],
            "enriched": running_totals["enriched"],
        })
        deduped = await asyncio.to_thread(deduplicate_articles, new_articles)
        logger.info(f"[{target_date}] {len(deduped)} articles after semantic dedup")

        # --- Step 4: Save to DB ---
        _update_progress(run_id, {
            "date_from": str(effective_from),
            "date_to":   str(effective_to),
            "stage": "saving",
            "current_date": str(target_date),
            "dates_completed": date_idx,
            "dates_total": dates_total,
            "fetched": running_totals["fetched"] + len(raw_articles),
            "new": running_totals["new"] + len(new_articles),
            "deduped": len(deduped),
            "saved": running_totals["saved"],
            "enriched": running_totals["enriched"],
        })
        saved = _save_articles(session, deduped)
        logger.info(f"[{target_date}] Saved {len(saved)} articles to database")

    # --- Step 5: Enrich with Gemini (concurrent) ---
    # Build totals that include this date's contributions so enrichment progress is accurate
    current_totals = {
        "fetched":  running_totals["fetched"]  + len(raw_articles),
        "new":      running_totals["new"]      + len(new_articles),
        "saved":    running_totals["saved"]    + len(saved),
        "enriched": running_totals["enriched"],
    }
    _update_progress(run_id, {
        "date_from": str(effective_from),
        "date_to":   str(effective_to),
        "stage": "enriching",
        "current_date": str(target_date),
        "dates_completed": date_idx,
        "dates_total": dates_total,
        **current_totals,
        "total_to_enrich": len(saved),
    })
    enriched_count = await enrich_articles(
        saved_ids=[a.id for a in saved],
        run_id=run_id,
        target_date=target_date,
        date_idx=date_idx,
        dates_total=dates_total,
        running_totals=current_totals,
    )
    logger.info(f"[{target_date}] Enriched {enriched_count} articles")

    return {
        "fetched":  len(raw_articles),
        "new":      len(new_articles),   # articles that passed the hash-exists check
        "saved":    len(saved),          # articles after semantic dedup, written to DB
        "enriched": enriched_count,
    }


async def run_pipeline(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    # Legacy single-date param — kept for backward compat
    target_date: Optional[date] = None,
    run_id: Optional[int] = None,
    enabled_sources: Optional[set[str]] = None,
    rss_feed_ids: Optional[set[int]] = None,
) -> dict:
    # Resolve effective range
    effective_from = date_from or target_date or date.today()
    effective_to   = date_to or effective_from
    if enabled_sources is None:
        enabled_sources = {"hn", "reddit", "arxiv", "rss"}

    all_dates = [
        effective_from + timedelta(days=i)
        for i in range((effective_to - effective_from).days + 1)
    ]

    t0 = time.monotonic()
    logger.info(f"Starting pipeline for {effective_from} → {effective_to} ({len(all_dates)} day(s))")

    totals = {"fetched": 0, "new": 0, "saved": 0, "enriched": 0}

    try:
        for idx, d in enumerate(all_dates):
            _update_progress(run_id, {
                "date_from": str(effective_from),
                "date_to":   str(effective_to),
                "stage": "fetching",
                "current_date": str(d),
                "dates_completed": idx,
                "dates_total": len(all_dates),
                **totals,
            })
            day_result = await _run_one_date(d, run_id, idx, len(all_dates), dict(totals), effective_from, effective_to, enabled_sources, rss_feed_ids)
            for k in totals:
                totals[k] += day_result.get(k, 0)

        result = {
            **totals,
            "date_from": str(effective_from),
            "date_to":   str(effective_to),
            "sources_used": sorted(enabled_sources),
            "rss_feed_ids_used": sorted(rss_feed_ids) if rss_feed_ids is not None else None,
        }
        _update_run(run_id, "success", result=result, duration_seconds=time.monotonic() - t0)
        return result

    except asyncio.CancelledError:
        _update_run(run_id, "cancelled", error_message="Cancelled by admin", duration_seconds=time.monotonic() - t0)
        raise
    except Exception as exc:
        _update_run(run_id, "failed", error_message=str(exc), duration_seconds=time.monotonic() - t0)
        raise


if __name__ == "__main__":
    import sys
    from datetime import date as dt

    date_from_arg = None
    date_to_arg   = None

    if len(sys.argv) > 1 and sys.argv[1] != "today":
        date_from_arg = dt.fromisoformat(sys.argv[1])
    if len(sys.argv) > 2:
        date_to_arg = dt.fromisoformat(sys.argv[2])

    result = asyncio.run(run_pipeline(date_from=date_from_arg, date_to=date_to_arg))
    print(result)
