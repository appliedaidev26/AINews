"""Semantic deduplication using TF-IDF + cosine similarity (sklearn)."""
import logging

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from backend.config import settings

logger = logging.getLogger(__name__)


def deduplicate_articles(articles: list[dict]) -> list[dict]:
    """
    Remove semantically duplicate articles using TF-IDF cosine similarity on titles.
    Threshold from settings (default 0.85).
    """
    if not articles:
        return []

    titles = [a["title"] for a in articles]
    threshold = settings.dedup_similarity_threshold

    vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
    try:
        tfidf_matrix = vectorizer.fit_transform(titles)
    except Exception as e:
        logger.warning(f"TF-IDF failed ({e}) — skipping dedup")
        return articles

    keep_indices = []
    for i in range(len(articles)):
        is_dup = False
        for j in keep_indices:
            sim = cosine_similarity(tfidf_matrix[i], tfidf_matrix[j])[0][0]
            if sim >= threshold:
                is_dup = True
                logger.debug(f"Dedup: '{titles[i][:60]}' ~ '{titles[j][:60]}' ({sim:.3f})")
                break
        if not is_dup:
            keep_indices.append(i)

    kept = [articles[i] for i in keep_indices]
    logger.info(f"Dedup: {len(articles)} → {len(kept)} (removed {len(articles) - len(kept)} duplicates)")
    return kept
