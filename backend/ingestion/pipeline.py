"""Main ingestion pipeline: fetches, deduplicates, and enriches articles."""
import asyncio
import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.config import settings
from backend.db import sync_engine
from backend.db.models import Article, PipelineTaskRun
from backend.ingestion.sources.hackernews import fetch_hackernews
from backend.ingestion.sources.reddit import fetch_reddit
from backend.ingestion.sources.arxiv_source import fetch_arxiv
from backend.ingestion.sources.rss_feeds import fetch_rss
from backend.processing.dedup import deduplicate_articles
from backend.processing.enricher import enrich_articles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


_progress_lock = threading.Lock()

def _update_progress(run_id, progress: dict):
    if run_id is None:
        return
    from sqlalchemy.orm import Session as _Session
    from backend.db import sync_engine
    from backend.db.models import PipelineRun
    with _progress_lock:
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


def _upsert_task_run(run_id, source: str, target_date, status: str,
                     articles_saved=None, error_message=None):
    """UPSERT a pipeline_task_runs row for one (run_id, source, date)."""
    if run_id is None:
        return
    from sqlalchemy.orm import Session as _Session
    from backend.db import sync_engine as _engine
    with _Session(_engine) as session:
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


def _get_existing_hashes(session: Session, candidate_hashes: set[str]) -> set[str]:
    """Return which of the candidate hashes are already in the DB (globally, not per-date)."""
    if not candidate_hashes:
        return set()
    rows = session.execute(
        select(Article.dedup_hash).where(Article.dedup_hash.in_(candidate_hashes))
    ).scalars().all()
    return set(rows)


def _save_articles(session: Session, articles: list[dict]) -> list[Article]:
    """Persist new article records, skip duplicates via ON CONFLICT DO NOTHING."""
    if not articles:
        return []
    values = []
    for art in articles:
        art.pop("_abstract", None)  # don't store raw abstract
        values.append(art)
    stmt = pg_insert(Article).values(values).on_conflict_do_nothing(index_elements=["dedup_hash"])
    stmt = stmt.returning(Article)
    result = session.execute(stmt)
    saved = list(result.scalars().all())
    session.commit()
    return saved


_SOURCE_FETCHERS = {
    "hn":     lambda td, _fids: fetch_hackernews(td),
    "reddit": lambda td, _fids: asyncio.to_thread(fetch_reddit, td),
    "arxiv":  lambda td, _fids: asyncio.to_thread(fetch_arxiv, td),
    "rss":    lambda td, fids: asyncio.to_thread(fetch_rss, td, fids),
}


async def _fetch_source_safe(
    source: str,
    target_date: date,
    run_id: Optional[int],
    rss_feed_ids: Optional[set[int]],
) -> tuple[str, list[dict], Optional[str]]:
    """Fetch a single source with error isolation.

    Returns (source, articles, error_string_or_None).
    On failure other sources continue unaffected.
    """
    _upsert_task_run(run_id, source, target_date, "running")
    try:
        fetcher = _SOURCE_FETCHERS.get(source)
        if fetcher is None:
            raise ValueError(f"Unknown source: {source}")
        articles = await fetcher(target_date, rss_feed_ids)
        return (source, articles, None)
    except Exception as exc:
        logger.error("[%s][%s] Fetch failed: %s", target_date, source, exc, exc_info=True)
        _upsert_task_run(run_id, source, target_date, "failed", error_message=str(exc))
        return (source, [], str(exc))


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
    """Run the full pipeline for a single date. Returns per-date counts + source_errors."""
    logger.info(f"Processing date {date_idx + 1}/{dates_total}: {target_date}")

    # --- Step 1: Fetch from all sources (fault-isolated per source) ---
    _update_progress(run_id, {
        "date_from": str(effective_from),
        "date_to":   str(effective_to),
        "stage": "fetching",
        "current_date": str(target_date),
        "dates_completed": date_idx,
        "dates_total": dates_total,
        **running_totals,
    })
    source_list = [s for s in ("hn", "reddit", "arxiv", "rss") if s in enabled_sources]
    fetch_results = await asyncio.gather(*[
        _fetch_source_safe(src, target_date, run_id, rss_feed_ids)
        for src in source_list
    ])

    # Collect results and errors
    raw_articles: list[dict] = []
    source_errors: dict[str, str] = {}
    for src, articles, err in fetch_results:
        raw_articles.extend(articles)
        if err is not None:
            source_errors[src] = err

    logger.info(f"[{target_date}] Fetched {len(raw_articles)} total raw articles"
                + (f" ({len(source_errors)} source(s) failed)" if source_errors else ""))

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
            # Mark successful sources even when no new articles
            for src in source_list:
                if src not in source_errors:
                    _upsert_task_run(run_id, src, target_date, "success", articles_saved=0)
            return {"fetched": len(raw_articles), "new": 0, "saved": 0, "enriched": 0, "source_errors": source_errors}

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

        # Update per-source task run records with article counts
        from collections import Counter
        source_counts = Counter(a.source_type for a in saved)
        for src in source_list:
            if src not in source_errors:
                _upsert_task_run(run_id, src, target_date, "success",
                                 articles_saved=source_counts.get(src, 0))

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
        "source_errors": source_errors,
    }


async def run_pipeline(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    # Legacy single-date param — kept for backward compat
    target_date: Optional[date] = None,
    run_id: Optional[int] = None,
    enabled_sources: Optional[set[str]] = None,
    rss_feed_ids: Optional[set[int]] = None,
    populate_trending: bool = False,
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

    # Compute trending dates that need an extra HN+Reddit pass
    trending_dates: list[date] = []
    if populate_trending:
        trending_candidates = [date.today() - timedelta(days=1), date.today()]
        # Skip dates already covered by the main range with HN+Reddit enabled
        main_has_hn_reddit = {"hn", "reddit"}.issubset(enabled_sources)
        main_date_set = set(all_dates)
        for td in trending_candidates:
            if not (main_has_hn_reddit and td in main_date_set):
                trending_dates.append(td)
        # Deduplicate (in case today-1 == yesterday produces duplicates)
        trending_dates = sorted(set(trending_dates))

    total_dates = len(all_dates) + len(trending_dates)

    # Compute and persist total_tasks so BackfillDetail can show the task grid
    total_tasks = len(all_dates) * len(enabled_sources) + len(trending_dates) * 2
    if run_id is not None:
        from sqlalchemy.orm import Session as _Session
        from backend.db import sync_engine as _engine
        from backend.db.models import PipelineRun as _PR
        with _Session(_engine) as session:
            row = session.get(_PR, run_id)
            if row is not None:
                row.total_tasks = total_tasks
                session.commit()

    t0 = time.monotonic()
    logger.info(f"Starting pipeline for {effective_from} → {effective_to} ({len(all_dates)} day(s))"
                + (f" + {len(trending_dates)} trending date(s)" if trending_dates else "")
                + f" · {total_tasks} total tasks")

    totals = {"fetched": 0, "new": 0, "saved": 0, "enriched": 0}
    all_source_errors: dict[str, str] = {}

    try:
        date_sem = asyncio.Semaphore(settings.pipeline_concurrency)

        async def _run_with_sem(idx, d):
            async with date_sem:
                return (idx, await _run_one_date(d, run_id, idx, total_dates, dict(totals), effective_from, effective_to, enabled_sources, rss_feed_ids))

        date_results = await asyncio.gather(*[_run_with_sem(i, d) for i, d in enumerate(all_dates)])
        for _idx, day_result in sorted(date_results):
            for k in totals:
                totals[k] += day_result.get(k, 0)
            all_source_errors.update(day_result.get("source_errors", {}))

        # Trending pass: fetch HN+Reddit for yesterday/today
        async def _run_trending_with_sem(t_idx, td):
            global_idx = len(all_dates) + t_idx
            logger.info(f"Trending pass: {td} (HN+Reddit only)")
            async with date_sem:
                return (t_idx, await _run_one_date(
                    td, run_id, global_idx, total_dates, dict(totals),
                    effective_from, effective_to,
                    enabled_sources={"hn", "reddit"}, rss_feed_ids=None,
                ))

        trending_results = await asyncio.gather(*[_run_trending_with_sem(i, td) for i, td in enumerate(trending_dates)])
        for _idx, day_result in sorted(trending_results):
            for k in totals:
                totals[k] += day_result.get(k, 0)
            all_source_errors.update(day_result.get("source_errors", {}))

        result = {
            **totals,
            "date_from": str(effective_from),
            "date_to":   str(effective_to),
            "sources_used": sorted(enabled_sources),
            "rss_feed_ids_used": sorted(rss_feed_ids) if rss_feed_ids is not None else None,
        }

        # Determine run status based on source failures and enrichment ratio
        enrichment_ratio = totals["enriched"] / totals["saved"] if totals["saved"] > 0 else 1.0
        error_parts: list[str] = []
        if all_source_errors:
            error_parts.append(f"{len(all_source_errors)} source fetch(es) failed: "
                               + "; ".join(f"{k}: {v[:120]}" for k, v in list(all_source_errors.items())[:5]))
        if totals["saved"] > 0 and enrichment_ratio < 0.5:
            error_parts.append(
                f"Enrichment mostly failed: {totals['enriched']}/{totals['saved']} articles enriched "
                f"({enrichment_ratio:.0%})"
            )

        if error_parts:
            error_msg = " | ".join(error_parts)
            logger.warning(error_msg)
            _update_run(run_id, "partial", result=result, error_message=error_msg, duration_seconds=time.monotonic() - t0)
        else:
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
