"""Cloud Tasks queue helpers for fan-out ingestion."""
import json
import logging
from datetime import date

from backend.config import settings

logger = logging.getLogger(__name__)

# Queue name per source (must match queues created in GCP)
QUEUE_FOR_SOURCE = {
    "hn":     "hn-ingestion",
    "rss":    "rss-ingestion",
    "arxiv":  "arxiv-ingestion",
    "reddit": "reddit-ingestion",
}


def enqueue_fetch_task(run_id: int, source: str, target_date: date) -> bool:
    """Create a Cloud Task to call POST /internal/fetch-source.

    Task name includes run_id+source+date for global uniqueness within queue.
    Creating a task with an existing name is a no-op (built-in idempotency).

    Returns True on success (or task already exists), False on failure.
    """
    if not settings.gcp_project_id or not settings.cloud_run_url:
        logger.warning(
            "Cloud Tasks not configured (GCP_PROJECT_ID or CLOUD_RUN_URL missing) "
            "— skipping task enqueue for %s %s", source, target_date
        )
        return False

    try:
        from google.cloud import tasks_v2
        from google.protobuf import duration_pb2

        client = tasks_v2.CloudTasksClient()
        queue = QUEUE_FOR_SOURCE.get(source, f"{source}-ingestion")
        parent = client.queue_path(
            settings.gcp_project_id,
            settings.cloud_tasks_region,
            queue,
        )

        task_name = client.task_path(
            settings.gcp_project_id,
            settings.cloud_tasks_region,
            queue,
            f"{source}-{run_id}-{target_date}",
        )

        payload = json.dumps({
            "run_id": run_id,
            "source": source,
            "date": str(target_date),
        }).encode()

        task = {
            "name": task_name,
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{settings.cloud_run_url}/internal/fetch-source",
                "headers": {"Content-Type": "application/json"},
                "body": payload,
            },
        }

        if settings.cloud_run_sa_email:
            task["http_request"]["oidc_token"] = {
                "service_account_email": settings.cloud_run_sa_email,
                "audience": settings.cloud_run_url,
            }

        client.create_task(request={"parent": parent, "task": task})
        logger.debug("Enqueued Cloud Task %s-%s-%s", source, run_id, target_date)
        return True

    except Exception as exc:
        # Already exists → idempotent success
        if "ALREADY_EXISTS" in str(exc) or "409" in str(exc):
            logger.debug("Cloud Task already exists for %s %s (run %s)", source, target_date, run_id)
            return True
        logger.error("Failed to enqueue Cloud Task for %s %s: %s", source, target_date, exc)
        return False
