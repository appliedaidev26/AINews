"""Admin routes — pipeline trigger, run history, and cancellation."""
import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from backend.config import settings
from backend.db import get_db
from backend.db.models import PipelineRun
from backend.ingestion.pipeline import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

# Module-level registry of live asyncio tasks keyed by run_id.
# Works reliably on single-instance Cloud Run (min-instances=1).
_active_tasks: dict[int, asyncio.Task] = {}


def _check_key(x_admin_key: str) -> None:
    if not settings.admin_api_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")


@router.post("/ingest")
async def trigger_ingest(
    target_date: Optional[date] = Query(None, description="ISO date e.g. 2026-02-21; defaults to today"),
    triggered_by: str = Query("api"),
    x_admin_key: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    _check_key(x_admin_key)
    effective_date = target_date or date.today()

    # Create run record BEFORE fire-and-forget so run_id is available immediately
    run = PipelineRun(
        target_date=str(effective_date),
        triggered_by=triggered_by,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    task = asyncio.create_task(run_pipeline(target_date=target_date, run_id=run.id))
    _active_tasks[run.id] = task
    # Clean up registry when task finishes (success, failure, or cancel)
    task.add_done_callback(lambda _: _active_tasks.pop(run.id, None))

    return {"status": "started", "date": str(effective_date), "run_id": run.id}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: int,
    x_admin_key: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    _check_key(x_admin_key)

    task = _active_tasks.get(run_id)
    if task is None or task.done():
        raise HTTPException(status_code=404, detail="No active task found for this run_id")

    task.cancel()  # Raises CancelledError inside pipeline coroutine
    return {"status": "cancelling", "run_id": run_id}


@router.get("/runs")
async def list_runs(
    limit: int = Query(50, ge=1, le=200),
    x_admin_key: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    _check_key(x_admin_key)
    result = await db.execute(
        select(PipelineRun).order_by(desc(PipelineRun.started_at)).limit(limit)
    )
    runs = result.scalars().all()
    return {"runs": [r.to_dict() for r in runs], "total": len(runs)}
