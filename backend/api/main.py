"""FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.db import create_tables
from backend.api.routes import articles, digest, profile

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — creating tables if needed")
    await create_tables()
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
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(articles.router)
app.include_router(digest.router)
app.include_router(profile.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
