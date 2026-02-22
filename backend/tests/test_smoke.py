"""Smoke tests — verify app boots and core routes respond."""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock


@pytest.fixture(autouse=True)
def mock_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://x:x@localhost/x")
    monkeypatch.setenv("GEMINI_API_KEY", "test")


@pytest.mark.asyncio
async def test_health():
    """App imports and root route exists without crashing."""
    with patch("backend.db.get_db", return_value=AsyncMock()):
        from backend.api.main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # The app should start without errors (404 on / is fine — it means it started)
            resp = await ac.get("/")
            assert resp.status_code in (200, 404)


@pytest.mark.asyncio
async def test_articles_route_exists():
    """GET /articles responds (may return empty list, not 500)."""
    with patch("backend.db.get_db", return_value=AsyncMock()), \
         patch("backend.api.routes.articles.get_db", return_value=AsyncMock()):
        from backend.api.main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/articles")
            assert resp.status_code != 500
