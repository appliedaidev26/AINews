"""FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.db import create_tables
from backend.api.routes import articles, digest, profile, admin, internal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def _init_firebase() -> None:
    """Initialize Firebase Admin SDK if credentials are configured."""
    if not settings.firebase_project_id and not settings.google_application_credentials:
        logger.warning(
            "Firebase not configured — profile routes will reject all requests. "
            "Set FIREBASE_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS in .env"
        )
        return
    try:
        import firebase_admin
        from firebase_admin import credentials

        if firebase_admin._apps:
            return  # already initialized

        if settings.google_application_credentials:
            cred = credentials.Certificate(settings.google_application_credentials)
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app(options={"projectId": settings.firebase_project_id})

        logger.info(f"Firebase Admin SDK initialized (project: {settings.firebase_project_id})")
    except ImportError:
        logger.error("firebase-admin not installed — run: pip install firebase-admin")
    except Exception as exc:
        logger.error(f"Firebase Admin init failed: {exc}")


async def _cleanup_orphaned_runs() -> None:
    """Mark any runs stuck in 'running' from a previous server crash as 'failed'."""
    from sqlalchemy import update as sa_update
    from backend.db import async_engine
    from backend.db.models import PipelineRun
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(async_engine) as session:
        # Only mark legacy "running" runs as failed on restart (not Cloud Tasks "queued" runs
        # which are managed externally and don't depend on server process continuity).
        result = await session.execute(
            sa_update(PipelineRun)
            .where(
                PipelineRun.status == "running",
                PipelineRun.total_tasks.is_(None),  # legacy asyncio mode only
            )
            .values(
                status="failed",
                completed_at=datetime.now(timezone.utc),
                error_message="Server restarted while run was active",
            )
            .returning(PipelineRun.id)
        )
        orphaned = result.scalars().all()
        await session.commit()
    if orphaned:
        logger.warning(f"Marked {len(orphaned)} orphaned run(s) as failed on startup: {orphaned}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — creating tables if needed")
    try:
        await create_tables()
        await _cleanup_orphaned_runs()
    except Exception as exc:
        # Don't crash on startup if DB is temporarily unavailable.
        # The app will still serve /health; DB-backed routes will fail until DB recovers.
        logger.error(f"Startup DB init failed (non-fatal): {exc}")
    _init_firebase()
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="AI News API",
    description="Curated AI/ML news aggregator for engineering leaders and practitioners",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins + [o.strip() for o in settings.cors_extra_origins.split() if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Admin-Key"],
)

app.include_router(articles.router)
app.include_router(digest.router)
app.include_router(profile.router)
app.include_router(admin.router)
app.include_router(internal.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
