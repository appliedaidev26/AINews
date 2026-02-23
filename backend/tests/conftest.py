"""
Shared fixtures for E2E tests.

os.environ.setdefault() calls must appear BEFORE any backend import because
`settings = get_settings()` runs at module import time via @lru_cache.
"""
import os

os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("GEMINI_API_KEY", "test")

import pytest
from sqlalchemy import text
from httpx import AsyncClient, ASGITransport

TEST_ADMIN_KEY = os.environ["ADMIN_API_KEY"]


@pytest.fixture(scope="session", autouse=True)
async def init_db():
    """Create all tables once for the test session."""
    from backend.db import async_engine
    from backend.db.models import Base

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in [
            "ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS progress JSONB",
            "ALTER TABLE articles ADD COLUMN IF NOT EXISTS practical_takeaway TEXT",
            "ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS date_to VARCHAR(20)",
        ]:
            await conn.execute(text(stmt))


@pytest.fixture(autouse=True)
async def clean_db():
    """Truncate all data before each test so each test starts with a clean slate."""
    from backend.db import async_engine

    async with async_engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE TABLE articles, pipeline_runs, user_article_scores, user_profiles "
            "RESTART IDENTITY CASCADE"
        ))
    yield


@pytest.fixture
async def client():
    """HTTP client wired directly to the FastAPI app (no network, real DB)."""
    from backend.api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
async def db():
    """Raw AsyncSession for direct seeding of test data."""
    from backend.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session
