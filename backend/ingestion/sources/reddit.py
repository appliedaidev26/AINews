"""Reddit ingestion via PRAW."""
import hashlib
import logging
from datetime import datetime, timezone, date, timedelta
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


def _time_filter_for(target_date: date) -> str:
    """Pick the narrowest PRAW time_filter that covers target_date."""
    days_ago = (date.today() - target_date).days
    if days_ago <= 1:
        return "day"
    if days_ago <= 7:
        return "week"
    if days_ago <= 30:
        return "month"
    return "year"


def fetch_reddit(target_date: Optional[date] = None) -> list[dict]:
    """Fetch top posts from AI/ML subreddits published on target_date."""
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

    time_filter = _time_filter_for(target_date)
    logger.info(f"Reddit: using time_filter='{time_filter}' for {target_date}")

    articles = []
    for sub_name in SUBREDDITS:
        try:
            subreddit = reddit.subreddit(sub_name)
            # Fetch more posts than needed so filtering by date leaves enough
            for post in subreddit.top(time_filter=time_filter, limit=100):
                if post.score < MIN_UPVOTES:
                    continue
                if post.is_self and not post.selftext:
                    continue

                published_at = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)

                # Only keep posts whose publish date matches target_date (UTC)
                if published_at.date() != target_date:
                    continue

                url = post.url
                if post.is_self:
                    url = f"https://reddit.com{post.permalink}"

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

    logger.info(f"Reddit: fetched {len(articles)} articles for {target_date}")
    return articles
