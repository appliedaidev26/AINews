"""Semantic deduplication via Vertex AI Vector Search.

Falls back to hash-only dedup when Vertex AI is not configured.
"""
import logging
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)


def _get_embedding(text: str) -> Optional[list[float]]:
    """Embed text using Vertex AI text-embedding-005. Returns None on failure."""
    if not settings.gcp_project_id or not settings.vertex_ai_index_endpoint_id:
        return None
    try:
        from google.cloud import aiplatform
        from vertexai.language_models import TextEmbeddingModel

        aiplatform.init(project=settings.gcp_project_id, location=settings.vertex_ai_location)
        model = TextEmbeddingModel.from_pretrained("text-embedding-005")
        result = model.get_embeddings([text])
        return result[0].values
    except Exception as exc:
        logger.warning(f"Vertex AI embedding failed: {exc}")
        return None


def _find_neighbors(embedding: list[float], k: int = 5) -> list[tuple[str, float]]:
    """Query Vertex AI Vector Search for nearest neighbors.

    Returns list of (datapoint_id, cosine_distance) pairs.
    Cosine distance ∈ [0, 2]; similarity = 1 - distance/2  (approx for unit vectors).
    """
    if not settings.gcp_project_id or not settings.vertex_ai_index_endpoint_id:
        return []
    try:
        from google.cloud import aiplatform_v1

        client = aiplatform_v1.MatchServiceClient(
            client_options={"api_endpoint": f"{settings.vertex_ai_location}-aiplatform.googleapis.com"}
        )
        endpoint = (
            f"projects/{settings.gcp_project_id}/locations/{settings.vertex_ai_location}"
            f"/indexEndpoints/{settings.vertex_ai_index_endpoint_id}"
        )
        query = aiplatform_v1.FindNeighborsRequest.Query(
            datapoint=aiplatform_v1.IndexDatapoint(feature_vector=embedding),
            neighbor_count=k,
        )
        request = aiplatform_v1.FindNeighborsRequest(
            index_endpoint=endpoint,
            deployed_index_id=settings.vertex_ai_deployed_index_id or settings.vertex_ai_index_id,
            queries=[query],
        )
        response = client.find_neighbors(request=request)
        neighbors = response.nearest_neighbors[0].neighbors if response.nearest_neighbors else []
        return [(n.datapoint.datapoint_id, n.distance) for n in neighbors]
    except Exception as exc:
        logger.warning(f"Vertex AI find_neighbors failed: {exc}")
        return []


def _cosine_similarity_from_distance(distance: float) -> float:
    """Convert Vertex AI cosine distance to similarity.

    Vertex AI returns cosine distance = 1 - cosine_similarity (for unit vectors).
    """
    return 1.0 - distance


def deduplicate_articles(articles: list[dict]) -> list[dict]:
    """Remove semantically duplicate articles using Vertex AI Vector Search.

    For each article, embeds the title and queries the shared index for
    near-duplicates. If any neighbor exceeds the similarity threshold, the
    article is considered a duplicate and skipped.

    Falls back to no semantic dedup (all articles pass) when Vertex AI is
    not configured — hash dedup in the pipeline still catches exact duplicates.
    """
    if not articles:
        return []

    threshold = settings.dedup_similarity_threshold
    vertex_configured = bool(settings.gcp_project_id and settings.vertex_ai_index_endpoint_id)

    if not vertex_configured:
        logger.info("Vertex AI not configured — skipping semantic dedup (hash dedup still active)")
        return articles

    kept = []
    for article in articles:
        title = article.get("title", "")
        embedding = _get_embedding(title)

        if embedding is None:
            # Embedding failed — keep the article (conservative choice)
            kept.append(article)
            continue

        neighbors = _find_neighbors(embedding, k=5)
        is_dup = False
        for neighbor_id, distance in neighbors:
            sim = _cosine_similarity_from_distance(distance)
            if sim >= threshold:
                logger.debug(
                    f"Semantic dedup: '{title[:60]}' matches neighbor {neighbor_id} "
                    f"(sim={sim:.3f} >= {threshold})"
                )
                is_dup = True
                break

        if not is_dup:
            kept.append(article)

    removed = len(articles) - len(kept)
    logger.info(f"Semantic dedup: {len(articles)} → {len(kept)} (removed {removed} duplicates)")
    return kept
