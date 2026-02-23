"""Hacker News ingestion via Algolia Search API."""
import hashlib
import logging
from datetime import datetime, timezone, timedelta, date
from typing import Optional

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"

AI_ML_KEYWORDS = [
    "llm", "large language model", "gpt", "claude", "gemini", "mistral",
    "machine learning", "deep learning", "neural network", "ai ", "artificial intelligence",
    "reinforcement learning", "transformer", "diffusion", "stable diffusion",
    "openai", "anthropic", "google deepmind", "meta ai", "hugging face",
    "fine-tuning", "rag", "retrieval augmented", "computer vision", "nlp",
    "natural language", "chatbot", "inference", "training", "dataset",
    "benchmark", "robotics", "autonomous", "foundation model",
]


def _is_ai_ml(title: str, url: str = "") -> bool:
    text = (title + " " + url).lower()
    return any(kw in text for kw in AI_ML_KEYWORDS)


def _make_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:64]


async def fetch_hackernews(target_date: Optional[date] = None) -> list[dict]:
    """Fetch AI/ML stories from HN Algolia API published on target_date."""
    target_date = target_date or date.today()

    # Compute Unix timestamp range for the full day (UTC)
    day_start = int(datetime(target_date.year, target_date.month, target_date.day,
                             0, 0, 0, tzinfo=timezone.utc).timestamp())
    day_end   = day_start + 86400  # exclusive: start of next day

    articles = []

    params = {
        "query": "AI machine learning LLM",
        "tags": "story",
        "numericFilters": f"points>={settings.hn_min_score},created_at_i>={day_start},created_at_i<{day_end}",
        "hitsPerPage": 100,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(ALGOLIA_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"HN fetch failed: {e}")
            return []

    for hit in data.get("hits", []):
        title = hit.get("title", "")
        url   = hit.get("url", "")
        object_id = hit.get("objectID", "")

        if not title or not _is_ai_ml(title, url):
            continue

        if not url:
            url = f"https://news.ycombinator.com/item?id={object_id}"

        created_at = hit.get("created_at")
        published_at = None
        if created_at:
            try:
                published_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except Exception:
                pass

        articles.append({
            "title": title,
            "original_url": url,
            "source_name": "HackerNews",
            "source_type": "hn",
            "author": hit.get("author"),
            "published_at": published_at,
            "digest_date": target_date,
            "engagement_signal": hit.get("points", 0),
            "dedup_hash": _make_hash(url),
        })

    logger.info(f"HN: fetched {len(articles)} AI/ML articles for {target_date}")
    return articles
