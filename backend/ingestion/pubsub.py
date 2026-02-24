"""Pub/Sub publisher helper."""
import json
import logging

from backend.config import settings

logger = logging.getLogger(__name__)


def publish_articles_saved(
    article_ids: list[int],
    run_id: int,
    source: str,
    target_date: str,
) -> bool:
    """Publish a message to ainews.articles.saved Pub/Sub topic.

    Subscribers:
      - /internal/enrich   (enrichment push subscription)
      - /internal/vectorize (vectorization push subscription)

    Returns True on success, False on failure.
    """
    if not settings.gcp_project_id:
        logger.debug("Pub/Sub not configured — skipping publish")
        return False

    try:
        from google.cloud import pubsub_v1

        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(settings.gcp_project_id, settings.pubsub_topic)

        data = json.dumps({
            "article_ids": article_ids,
            "run_id": run_id,
            "source": source,
            "date": target_date,
        }).encode()

        future = publisher.publish(topic_path, data)
        future.result()  # wait for delivery confirmation
        logger.debug(
            "Published %d article IDs to Pub/Sub (run=%s source=%s date=%s)",
            len(article_ids), run_id, source, target_date,
        )
        return True

    except Exception as exc:
        logger.error("Pub/Sub publish failed: %s", exc)
        return False
