"""Reddit ingestion via PRAW."""
import hashlib
import logging
from datetime import datetime, timezone, date
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)

SUBREDDITS = [
    "MachineLearning",
    "LocalLLaMA",
    "datascience",
    "artificial",
    "singularity",
]

MIN_UPVOTES = 50


def _make_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:64]


def fetch_reddit(target_date: Optional[date] = None) -> list[dict]:
    """Fetch top posts from AI/ML subreddits. Returns list of article dicts."""
    target_date = target_date or date.today()

    if not settings.reddit_client_id or not settings.reddit_client_secret:
        logger.warning("Reddit API credentials not set — skipping Reddit ingestion")
        return []

    try:
        import praw
    except ImportError:
        logger.error("praw not installed")
        return []

    reddit = praw.Reddit(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        user_agent=settings.reddit_user_agent,
    )

    articles = []
    for sub_name in SUBREDDITS:
        try:
            subreddit = reddit.subreddit(sub_name)
            for post in subreddit.top(time_filter="day", limit=25):
                if post.score < MIN_UPVOTES:
                    continue
                if post.is_self and not post.selftext:
                    continue

                url = post.url
                # For self-posts, use reddit permalink
                if post.is_self:
                    url = f"https://reddit.com{post.permalink}"

                published_at = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)

                articles.append({
                    "title": post.title,
                    "original_url": url,
                    "source_name": f"Reddit/r/{sub_name}",
                    "source_type": "reddit",
                    "author": str(post.author) if post.author else None,
                    "published_at": published_at,
                    "digest_date": target_date,
                    "engagement_signal": post.score,
                    "dedup_hash": _make_hash(url),
                })
        except Exception as e:
            logger.error(f"Reddit fetch failed for r/{sub_name}: {e}")

    logger.info(f"Reddit: fetched {len(articles)} articles")
    return articles
