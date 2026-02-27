import logging

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import create_engine, select, func
from backend.config import settings
from backend.db.models import Base, RssFeed

logger = logging.getLogger(__name__)

# Async engine for FastAPI
# db-f1-micro has 25 max_connections; keep pool tiny so multiple Cloud Run instances fit.
# connect_args timeout prevents hangs when DB is unreachable during startup.
# db-f1-micro has 25 max_connections.
# With maxScale=4 Cloud Run instances, budget ~6 connections per instance (4×6=24).
# Local dev: larger pools since only one process runs.
_is_local_env = not settings.gcp_project_id
async_engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=3 if _is_local_env else 2,
    max_overflow=2 if _is_local_env else 1,
    pool_timeout=10 if _is_local_env else 10,
    connect_args={"timeout": 10},  # asyncpg connection-level timeout (seconds)
)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

# Sync engine for ingestion pipeline (used in background tasks AND internal handlers).
# Production: concurrent /internal/fetch-source, /internal/enrich, /internal/vectorize
# plus /internal/finalize-runs all need sync connections simultaneously.
# Budget: pool_size=5 + max_overflow=3 = 8 per instance. With maxScale=4: 4×8=32.
# This exceeds 25-conn limit of db-f1-micro but max_overflow connections are short-lived
# and Cloud Run rarely runs 4 instances at full concurrency simultaneously.
sync_engine = create_engine(
    settings.database_url_sync,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=3,
    pool_timeout=30,
    connect_args={"connect_timeout": 10},  # psycopg2 connection-level timeout (seconds)
)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def create_tables():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Additive column migrations — safe to re-run (IF NOT EXISTS)
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS progress JSONB"
            )
        )
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS practical_takeaway TEXT"
            )
        )
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS date_to VARCHAR(20)"
            )
        )
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS is_vectorized INTEGER DEFAULT 0"
            )
        )
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS total_tasks INTEGER"
            )
        )
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS enrich_retries INTEGER DEFAULT 0"
            )
        )
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS summary TEXT"
            )
        )
    await _seed_rss_feeds()


async def _seed_rss_feeds():
    """Insert default RSS feeds if the table is empty."""
    from backend.ingestion.sources.rss_feeds import DEFAULT_RSS_FEEDS

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(func.count()).select_from(RssFeed))
        count = result.scalar()
        if count and count > 0:
            return
        for feed in DEFAULT_RSS_FEEDS:
            session.add(RssFeed(name=feed["name"], url=feed["url"]))
        await session.commit()
        logger.info(f"Seeded {len(DEFAULT_RSS_FEEDS)} default RSS feeds")
