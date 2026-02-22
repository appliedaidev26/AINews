"""RSS feed ingestion via feedparser."""
import hashlib
import logging
from datetime import datetime, timezone, date
from typing import Optional
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)

DEFAULT_RSS_FEEDS = [
    {"name": "OpenAI Blog",         "url": "https://openai.com/blog/rss.xml"},
    {"name": "Anthropic Blog",      "url": "https://www.anthropic.com/rss.xml"},
    {"name": "Google DeepMind",     "url": "https://deepmind.google/blog/rss.xml"},
    {"name": "HuggingFace Blog",    "url": "https://huggingface.co/blog/feed.xml"},
    {"name": "Google AI Blog",      "url": "https://blog.research.google/feeds/posts/default"},
    {"name": "Meta AI Blog",        "url": "https://ai.meta.com/blog/rss/"},
    {"name": "The Gradient",        "url": "https://thegradient.pub/rss/"},
    {"name": "Import AI",           "url": "https://importai.substack.com/feed"},
    {"name": "Simon Willison",      "url": "https://simonwillison.net/atom/everything/"},
    {"name": "Towards Data Science","url": "https://towardsdatascience.com/feed"},
]


def _parse_date(entry) -> Optional[datetime]:
    for field in ["published", "updated"]:
        val = entry.get(f"{field}_parsed")
        if val:
            import time
            ts = time.mktime(val)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
    return None


def _make_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:64]


def _get_active_feeds() -> list[dict]:
    """Query active RSS feeds from DB, falling back to defaults on error."""
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        from backend.db import sync_engine
        from backend.db.models import RssFeed

        with Session(sync_engine) as session:
            rows = session.execute(
                select(RssFeed).where(RssFeed.is_active == True)
            ).scalars().all()
            if rows:
                return [{"name": r.name, "url": r.url} for r in rows]
    except Exception as e:
        logger.warning(f"Failed to load feeds from DB, using defaults: {e}")
    return DEFAULT_RSS_FEEDS


def fetch_rss(target_date: Optional[date] = None) -> list[dict]:
    """Fetch articles from RSS feeds published on target_date."""
    target_date = target_date or date.today()

    try:
        import feedparser
    except ImportError:
        logger.error("feedparser not installed")
        return []

    feeds = _get_active_feeds()
    articles = []
    for feed_cfg in feeds:
        try:
            feed = feedparser.parse(feed_cfg["url"])
            entries = feed.get("entries", [])[:50]  # check more entries to find the right date

            for entry in entries:
                url   = entry.get("link", "")
                title = entry.get("title", "")
                if not url or not title:
                    continue

                published_at = _parse_date(entry)

                # Only include articles published on target_date (UTC)
                if published_at is None or published_at.date() != target_date:
                    continue

                author = entry.get("author") or entry.get("dc_creator")

                articles.append({
                    "title": title,
                    "original_url": url,
                    "source_name": feed_cfg["name"],
                    "source_type": "rss",
                    "author": author,
                    "published_at": published_at,
                    "digest_date": target_date,
                    "engagement_signal": 0,
                    "dedup_hash": _make_hash(url),
                })

        except Exception as e:
            logger.error(f"RSS fetch failed for {feed_cfg['name']}: {e}")

    logger.info(f"RSS: fetched {len(articles)} articles for {target_date}")
    return articles
