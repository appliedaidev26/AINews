"""Main ingestion pipeline: fetches, deduplicates, and enriches articles."""
import asyncio
import logging
from datetime import date
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


def _get_existing_hashes(session: Session, target_date: date) -> set[str]:
    """Retrieve dedup hashes already in DB for the given date."""
    rows = session.execute(
        select(Article.dedup_hash).where(Article.digest_date == target_date)
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


async def run_pipeline(target_date: Optional[date] = None) -> dict:
    target_date = target_date or date.today()
    logger.info(f"Starting ingestion pipeline for {target_date}")

    # --- Step 1: Fetch from all sources ---
    hn_articles, reddit_articles, arxiv_articles, rss_articles = await asyncio.gather(
        fetch_hackernews(target_date),
        asyncio.to_thread(fetch_reddit, target_date),
        asyncio.to_thread(fetch_arxiv, target_date),
        asyncio.to_thread(fetch_rss, target_date),
    )

    raw_articles = hn_articles + reddit_articles + arxiv_articles + rss_articles
    logger.info(f"Fetched {len(raw_articles)} total raw articles")

    # --- Step 2: Filter already-ingested ---
    with Session(sync_engine) as session:
        existing_hashes = _get_existing_hashes(session, target_date)
        new_articles = [a for a in raw_articles if a["dedup_hash"] not in existing_hashes]
        logger.info(f"{len(new_articles)} new articles after hash filter (skipped {len(raw_articles) - len(new_articles)})")

        if not new_articles:
            logger.info("No new articles to process")
            return {"fetched": len(raw_articles), "new": 0, "enriched": 0}

        # --- Step 3: Semantic deduplication ---
        deduped = await asyncio.to_thread(deduplicate_articles, new_articles)
        logger.info(f"{len(deduped)} articles after semantic dedup")

        # --- Step 4: Save to DB ---
        saved = _save_articles(session, deduped)
        logger.info(f"Saved {len(saved)} articles to database")

    # --- Step 5: Enrich with Gemini ---
    enriched_count = await enrich_articles(saved_ids=[a.id for a in saved])
    logger.info(f"Enriched {enriched_count} articles")

    return {
        "fetched": len(raw_articles),
        "new": len(deduped),
        "saved": len(saved),
        "enriched": enriched_count,
        "date": str(target_date),
    }


if __name__ == "__main__":
    import sys
    target = None
    if len(sys.argv) > 1 and sys.argv[1] != "today":
        from datetime import date as dt
        target = dt.fromisoformat(sys.argv[1])

    result = asyncio.run(run_pipeline(target))
    print(result)
