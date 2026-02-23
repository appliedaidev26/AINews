"""
End-to-end API tests: real HTTP → FastAPI handler → real PostgreSQL → validated JSON.

No mocking of DB or routes. Each test starts with a truncated DB (via clean_db fixture
in conftest.py) and seeds exactly the data it needs.
"""
from datetime import date, datetime, timezone, timedelta

import pytest

from backend.db.models import Article
from backend.tests.conftest import TEST_ADMIN_KEY


# ---------------------------------------------------------------------------
# Article factory helper — avoids repetition across tests
# ---------------------------------------------------------------------------

def _article(**kwargs) -> Article:
    defaults = dict(
        title="Test Article",
        original_url="https://example.com/test",
        source_name="TestSource",
        source_type="rss",
        digest_date=date.today(),
        published_at=datetime.now(timezone.utc),
        dedup_hash="hash-default",
        is_enriched=1,
        engagement_signal=10,
        category="Research",
        tags=["llms"],
        summary_bullets=["b1", "b2", "b3", "b4", "b5"],
        annotations=[],
        why_it_matters="matters",
        practical_takeaway="do something",
        audience_scores={"ml_engineer": 0.9},
        related_article_ids=[],
    )
    defaults.update(kwargs)
    return Article(**defaults)


# ---------------------------------------------------------------------------
# Test 1: health endpoint
# ---------------------------------------------------------------------------

async def test_health(client):
    """App starts without error and /health returns the expected shape."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


# ---------------------------------------------------------------------------
# Test 2: article list filtering and pagination
# ---------------------------------------------------------------------------

async def test_article_list_and_date_filter(client, db):
    """
    Validates:
    - date_from/date_to filter uses COALESCE(published_at::date, digest_date)
    - is_enriched=-1 articles are excluded from listings
    - category filter works
    - pagination response shape is correct
    """
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)

    # Article A: published 30 days ago but digest_date=today (backfill scenario)
    a = _article(
        title="Article A",
        dedup_hash="hash-filter-a",
        published_at=datetime(
            thirty_days_ago.year, thirty_days_ago.month, thirty_days_ago.day,
            12, 0, tzinfo=timezone.utc,
        ),
        digest_date=today,
        is_enriched=1,
        category="Research",
    )
    # Article B: published today, normal case
    b = _article(
        title="Article B",
        dedup_hash="hash-filter-b",
        published_at=datetime.now(timezone.utc),
        digest_date=today,
        is_enriched=1,
        category="Research",
    )
    # Article C: failed enrichment — must be excluded from all listings
    c = _article(
        title="Article C",
        dedup_hash="hash-filter-c",
        published_at=datetime.now(timezone.utc),
        digest_date=today,
        is_enriched=-1,
        category="Tools",
    )
    db.add_all([a, b, c])
    await db.commit()
    await db.refresh(a)
    await db.refresh(b)

    d30 = str(thirty_days_ago)
    d_today = str(today)

    # 1. Filter by 30 days ago: only A matches (pub_date = 30d ago), B & C are today
    resp = await client.get(f"/articles?date_from={d30}&date_to={d30}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["articles"]) == 1
    assert data["articles"][0]["title"] == "Article A"

    # 2. Filter by today: only B matches (C excluded by is_enriched=-1, A pub_date=30d ago)
    resp = await client.get(f"/articles?date_from={d_today}&date_to={d_today}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["articles"]) == 1
    assert data["articles"][0]["title"] == "Article B"

    # 3. Category filter: Research → A and B, not C
    resp = await client.get("/articles?category=Research")
    assert resp.status_code == 200
    data = resp.json()
    titles = {art["title"] for art in data["articles"]}
    assert "Article A" in titles
    assert "Article B" in titles
    assert "Article C" not in titles

    # 4. Pagination shape
    resp = await client.get("/articles?page=1&per_page=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 1
    assert data["per_page"] == 1
    assert len(data["articles"]) == 1
    assert "articles" in data


# ---------------------------------------------------------------------------
# Test 3: article detail and related articles
# ---------------------------------------------------------------------------

async def test_article_detail_and_related(client, db):
    """
    Validates:
    - GET /articles/{id} returns a 'related_articles' list with correct shape
    - GET /articles/99999 returns 404
    """
    a = _article(title="Article A", dedup_hash="hash-detail-a", tags=["llms"])
    b = _article(title="Article B", dedup_hash="hash-detail-b", tags=["llms"])
    db.add_all([a, b])
    await db.commit()
    await db.refresh(a)
    await db.refresh(b)

    # Link A → B as a related article
    a.related_article_ids = [b.id]
    await db.commit()

    resp = await client.get(f"/articles/{a.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "related_articles" in data
    assert len(data["related_articles"]) == 1
    rel = data["related_articles"][0]
    assert rel["id"] == b.id
    assert "title" in rel
    assert "category" in rel
    assert "source_name" in rel
    assert "digest_date" in rel

    # Non-existent article → 404
    resp = await client.get("/articles/99999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test 4: admin auth enforcement and coverage endpoint
# ---------------------------------------------------------------------------

async def test_admin_auth_and_coverage(client, db):
    """
    Validates:
    - Missing X-Admin-Key header → 422 (FastAPI request validation)
    - Wrong key → 403
    - Correct key returns coverage data with accurate per-date counts
    """
    today = date.today()
    yesterday = today - timedelta(days=1)

    db.add_all([
        _article(dedup_hash="hash-cov-1", digest_date=today, is_enriched=1),
        _article(dedup_hash="hash-cov-2", digest_date=today, is_enriched=1),
        _article(dedup_hash="hash-cov-3", digest_date=today, is_enriched=-1),
        _article(dedup_hash="hash-cov-4", digest_date=yesterday, is_enriched=1),
    ])
    await db.commit()

    # No header → 422 (required Header parameter missing)
    resp = await client.get("/admin/coverage")
    assert resp.status_code == 422

    # Wrong key → 403
    resp = await client.get("/admin/coverage", headers={"X-Admin-Key": "wrong-key"})
    assert resp.status_code == 403

    # Correct key → 200 with coverage list
    resp = await client.get("/admin/coverage?days=7", headers={"X-Admin-Key": TEST_ADMIN_KEY})
    assert resp.status_code == 200
    data = resp.json()
    assert "coverage" in data

    coverage_by_date = {row["date"]: row for row in data["coverage"]}

    today_str = str(today)
    assert today_str in coverage_by_date
    row = coverage_by_date[today_str]
    assert row["total"] == 3
    assert row["enriched"] == 2
    assert row["failed"] == 1
    assert row["pending"] == 0

    yesterday_str = str(yesterday)
    assert yesterday_str in coverage_by_date
    row = coverage_by_date[yesterday_str]
    assert row["total"] == 1
    assert row["enriched"] == 1


# ---------------------------------------------------------------------------
# Test 5: digest today and historical date
# ---------------------------------------------------------------------------

async def test_digest_today_and_historical(client, db):
    """
    Validates:
    - /digest/today returns correct totals and category breakdown
    - /digest/{past_date} with no data returns 200 with total=0 (not 404/500)
    """
    today = date.today()
    yesterday = today - timedelta(days=1)

    db.add_all([
        _article(dedup_hash="hash-dig-1", digest_date=today, category="Research"),
        _article(dedup_hash="hash-dig-2", digest_date=today, category="Research"),
        _article(dedup_hash="hash-dig-3", digest_date=today, category="Tools"),
    ])
    await db.commit()

    resp = await client.get("/digest/today")
    assert resp.status_code == 200
    data = resp.json()
    assert data["date"] == str(today)
    assert data["total"] == 3
    assert data["categories"]["Research"] == 2
    assert data["categories"]["Tools"] == 1
    assert len(data["articles"]) == 3

    # Historical date with no data → 200, empty result (not 404 or 500)
    resp = await client.get(f"/digest/{yesterday}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
