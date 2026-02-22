"""Admin routes — pipeline trigger and ops endpoints."""
import asyncio
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from backend.config import settings
from backend.ingestion.pipeline import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


def _check_key(x_admin_key: str) -> None:
    if not settings.admin_api_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")


@router.post("/ingest")
async def trigger_ingest(
    target_date: Optional[date] = Query(None, description="ISO date e.g. 2026-02-21; defaults to today"),
    x_admin_key: str = Header(...),
):
    _check_key(x_admin_key)
    asyncio.create_task(run_pipeline(target_date))
    return {"status": "started", "date": str(target_date or date.today())}
