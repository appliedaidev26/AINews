"""Arxiv ingestion via arxiv Python library."""
import hashlib
import logging
from datetime import date, timezone
from typing import Optional

logger = logging.getLogger(__name__)

ARXIV_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.CV", "stat.ML"]
MAX_RESULTS_PER_CAT = 50  # fetch more so date filtering still yields enough

AI_KEYWORDS = [
    "language model", "llm", "transformer", "diffusion", "neural", "deep learning",
    "reinforcement", "fine-tun", "generative", "attention", "rag", "retrieval",
    "benchmark", "multimodal", "instruction", "alignment", "reasoning",
]


def _is_relevant(title: str, abstract: str) -> bool:
    text = (title + " " + abstract).lower()
    return any(kw in text for kw in AI_KEYWORDS)


def _make_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:64]


def fetch_arxiv(target_date: Optional[date] = None) -> list[dict]:
    """Fetch AI/ML papers from Arxiv submitted on target_date."""
    target_date = target_date or date.today()

    try:
        import arxiv
    except ImportError:
        logger.error("arxiv not installed")
        return []

    # Arxiv date filter format: YYYYMMDDHHMMSS
    date_str = target_date.strftime("%Y%m%d")
    date_filter = f"submittedDate:[{date_str}0000 TO {date_str}2359]"

    articles = []
    seen_ids = set()

    for category in ARXIV_CATEGORIES:
        try:
            client = arxiv.Client()
            search = arxiv.Search(
                query=f"cat:{category} AND {date_filter}",
                max_results=MAX_RESULTS_PER_CAT,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending,
            )

            for result in client.results(search):
                arxiv_id = result.entry_id
                if arxiv_id in seen_ids:
                    continue
                seen_ids.add(arxiv_id)

                title    = result.title
                abstract = result.summary or ""

                if not _is_relevant(title, abstract):
                    continue

                # Double-check the submission date matches (Arxiv date filter is sometimes fuzzy)
                published_at = result.published
                if published_at:
                    if published_at.tzinfo is None:
                        published_at = published_at.replace(tzinfo=timezone.utc)
                    if published_at.date() != target_date:
                        continue

                url     = result.entry_id
                authors = ", ".join(a.name for a in result.authors[:3])
                if len(result.authors) > 3:
                    authors += " et al."

                articles.append({
                    "title": title,
                    "original_url": url,
                    "source_name": f"Arxiv/{category}",
                    "source_type": "arxiv",
                    "author": authors,
                    "published_at": published_at,
                    "digest_date": target_date,
                    "engagement_signal": 0,
                    "dedup_hash": _make_hash(url),
                    "_abstract": abstract,
                })

        except Exception as e:
            logger.error(f"Arxiv fetch failed for {category}: {e}")

    logger.info(f"Arxiv: fetched {len(articles)} papers for {target_date}")
    return articles
