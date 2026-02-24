"""Vertex AI Vector Search: embed article titles and upsert datapoints to the index."""
import logging
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)


def _get_embedding(text: str) -> Optional[list[float]]:
    """Embed text using Vertex AI text-embedding-005. Returns None on failure."""
    if not settings.gcp_project_id:
        return None
    try:
        from google.cloud import aiplatform
        from vertexai.language_models import TextEmbeddingModel

        aiplatform.init(project=settings.gcp_project_id, location=settings.vertex_ai_location)
        model = TextEmbeddingModel.from_pretrained("text-embedding-005")
        result = model.get_embeddings([text])
        return result[0].values
    except Exception as exc:
        logger.warning(f"Vertex AI embedding failed for text '{text[:60]}': {exc}")
        return None


def upsert_article_vector(article_id: int, title: str, abstract: str = "") -> bool:
    """Embed article and upsert its vector to Vertex AI Vector Search index.

    Uses title + first 500 chars of abstract as input text.
    Returns True on success, False on failure.
    """
    if not settings.gcp_project_id or not settings.vertex_ai_index_id:
        logger.debug("Vertex AI not configured — skipping vectorization")
        return False

    input_text = title
    if abstract:
        input_text = f"{title}\n\n{abstract[:500]}"

    embedding = _get_embedding(input_text)
    if embedding is None:
        return False

    try:
        from google.cloud import aiplatform_v1

        client = aiplatform_v1.IndexServiceClient(
            client_options={"api_endpoint": f"{settings.vertex_ai_location}-aiplatform.googleapis.com"}
        )
        index_name = (
            f"projects/{settings.gcp_project_id}/locations/{settings.vertex_ai_location}"
            f"/indexes/{settings.vertex_ai_index_id}"
        )
        datapoint = aiplatform_v1.IndexDatapoint(
            datapoint_id=str(article_id),
            feature_vector=embedding,
        )
        request = aiplatform_v1.UpsertDatapointsRequest(
            index=index_name,
            datapoints=[datapoint],
        )
        client.upsert_datapoints(request=request)
        logger.debug(f"Upserted vector for article {article_id}")
        return True
    except Exception as exc:
        logger.warning(f"Vertex AI upsert failed for article {article_id}: {exc}")
        return False
