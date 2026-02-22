"""Cloud Run Job entry point — triggered by Cloud Scheduler."""
import asyncio
import logging
import sys
from datetime import date

from backend.ingestion.pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


async def main():
    target_date = None
    if len(sys.argv) > 1:
        try:
            target_date = date.fromisoformat(sys.argv[1])
        except ValueError:
            logger.warning(f"Invalid date argument '{sys.argv[1]}' — defaulting to today")

    result = await run_pipeline(target_date)
    logger.info(f"Pipeline complete: {result}")
    return result


if __name__ == "__main__":
    asyncio.run(main())
