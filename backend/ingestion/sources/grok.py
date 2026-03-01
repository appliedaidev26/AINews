"""Grok (xAI) ingestion — trending AI news via real-time web + X/Twitter search."""
import hashlib
import json
import logging
from datetime import date, datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from backend.config import settings

logger = logging.getLogger(__name__)

QUERIES = [
    {
        "id": "viral_ai",
        "prompt": (
            "Find the AI and machine learning stories with the MOST likes, retweets, "
            "and views on X/Twitter in the last 24 hours. Only include stories with "
            "1,000+ total engagement (likes + retweets + comments + views combined). "
            "Focus on genuinely viral content that is being widely shared right now."
        ),
    },
    {
        "id": "hot_discussions",
        "prompt": (
            "Find AI and machine learning threads and discussions with the MOST comments "
            "and replies on X/Twitter, Reddit, and Hacker News in the last 24 hours. "
            "Only include stories with 1,000+ total engagement (likes + retweets + "
            "comments + views combined). Focus on topics generating heated debate or "
            "widespread discussion."
        ),
    },
    {
        "id": "major_announcements",
        "prompt": (
            "Find major AI company announcements (product launches, model releases, "
            "partnerships, funding rounds) from the last 24 hours that are generating "
            "massive engagement. Only include stories with 1,000+ total engagement "
            "(likes + retweets + comments + views combined). Include press coverage "
            "and social media reactions."
        ),
    },
    {
        "id": "community_buzz",
        "prompt": (
            "Find open-source AI releases, research papers, tools, and libraries from "
            "the last 24 hours with strong community engagement — 1,000+ GitHub stars, "
            "HuggingFace downloads, or X/Twitter engagement (likes + retweets + comments "
            "+ views combined must be 1,000+). Focus on practical tools and repos people "
            "are actually excited about."
        ),
    },
    {
        "id": "breaking",
        "prompt": (
            "Find BREAKING AI news stories going viral RIGHT NOW with rapidly growing "
            "engagement. Only include stories with 1,000+ total engagement (likes + "
            "retweets + comments + views combined). Focus on stories published in the "
            "last few hours that are spreading fast."
        ),
    },
]

_SYSTEM_PROMPT = (
    "You are a news research assistant. Return ONLY a JSON object with an "
    '"articles" array. Each article must have: title (string), url (full https URL '
    "to the original source — NOT an X/Twitter link unless the news originated there), "
    "author (string or null), engagement (object with likes, retweets, comments, views "
    "as integers — use 0 if unknown), buzz_rank (integer 1-10, 10 = most viral), "
    "source_hint (string — where you found it, e.g. 'X/Twitter', 'Reddit', 'HN', "
    "'TechCrunch'). Return up to {max_articles} articles, sorted by engagement "
    "(highest first). If you cannot find enough qualifying articles, return fewer. "
    "Do NOT invent or hallucinate articles or URLs."
)


def _make_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:64]


def _validate_url(url: str) -> bool:
    """Check that a URL has a valid scheme and netloc."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _map_engagement(engagement: dict, buzz_rank: int) -> int:
    """Compute engagement_signal for DB storage.

    If real metrics available: likes + 3*retweets + 5*comments, capped at 500.
    Fallback: buzz_rank scaled linearly from xai_base_engagement.
    """
    likes = engagement.get("likes", 0) or 0
    retweets = engagement.get("retweets", 0) or 0
    comments = engagement.get("comments", 0) or 0

    has_real_metrics = (likes + retweets + comments) > 0
    if has_real_metrics:
        raw = likes + 3 * retweets + 5 * comments
        return min(raw, 500)

    # Fallback: scale buzz_rank around xai_base_engagement
    # rank 1 → base*0.5, rank 5 → base, rank 10 → base*2
    base = settings.xai_base_engagement
    return int(base * (0.5 + 0.15 * buzz_rank))


def _passes_engagement_gate(engagement: dict, buzz_rank: int) -> bool:
    """Check if article meets the minimum engagement threshold.

    Total engagement = likes + retweets + comments (views excluded — inflated).
    If no metrics available, accept only if buzz_rank >= 8.
    """
    likes = engagement.get("likes", 0) or 0
    retweets = engagement.get("retweets", 0) or 0
    comments = engagement.get("comments", 0) or 0
    total = likes + retweets + comments

    has_real_metrics = total > 0
    if has_real_metrics:
        return total >= settings.xai_min_engagement

    # No real metrics — rely on Grok's assessment
    return buzz_rank >= 8


def _query_grok(client, query: dict, target_date: date, seen_urls: set[str]) -> list[dict]:
    """Run a single Grok query and return parsed articles."""
    max_articles = settings.xai_articles_per_query
    system_prompt = _SYSTEM_PROMPT.format(max_articles=max_articles)

    try:
        response = client.chat.completions.create(
            model=settings.xai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query["prompt"]},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        content = response.choices[0].message.content
        data = json.loads(content)
        raw_articles = data.get("articles", [])
    except json.JSONDecodeError as e:
        logger.error("Grok [%s]: JSON parse error: %s", query["id"], e)
        return []
    except Exception as e:
        logger.error("Grok [%s]: API error: %s", query["id"], e)
        return []

    articles = []
    for item in raw_articles:
        url = (item.get("url") or "").strip()
        if not url or not _validate_url(url):
            logger.debug("Grok [%s]: skipping invalid URL: %s", query["id"], url)
            continue

        if url in seen_urls:
            continue
        seen_urls.add(url)

        engagement = item.get("engagement", {}) or {}
        buzz_rank = min(max(int(item.get("buzz_rank", 5)), 1), 10)

        if not _passes_engagement_gate(engagement, buzz_rank):
            logger.debug(
                "Grok [%s]: dropping below engagement gate: %s", query["id"], item.get("title", "")[:60]
            )
            continue

        articles.append({
            "title": (item.get("title") or "Untitled").strip()[:300],
            "original_url": url,
            "source_name": f"Grok/{item.get('source_hint', query['id'])}",
            "source_type": "grok",
            "author": (item.get("author") or None),
            "published_at": datetime.now(timezone.utc),
            "digest_date": target_date,
            "engagement_signal": _map_engagement(engagement, buzz_rank),
            "dedup_hash": _make_hash(url),
        })

    logger.info("Grok [%s]: returned %d articles (from %d raw)", query["id"], len(articles), len(raw_articles))
    return articles


def fetch_grok(target_date: Optional[date] = None) -> list[dict]:
    """Fetch trending AI news from Grok. Sync function (wrapped with to_thread in pipeline)."""
    target_date = target_date or date.today()

    if not settings.xai_api_key:
        logger.info("Grok: XAI_API_KEY not set — skipping Grok ingestion")
        return []

    try:
        from openai import OpenAI
    except ImportError:
        logger.error("Grok: openai package not installed")
        return []

    client = OpenAI(
        api_key=settings.xai_api_key,
        base_url="https://api.x.ai/v1",
    )

    seen_urls: set[str] = set()
    all_articles: list[dict] = []

    queries = QUERIES[: settings.xai_queries_per_run]
    for query in queries:
        articles = _query_grok(client, query, target_date, seen_urls)
        all_articles.extend(articles)

    logger.info("Grok: total %d articles for %s", len(all_articles), target_date)
    return all_articles
