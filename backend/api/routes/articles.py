"""Article routes: list and detail."""
from datetime import date, datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, and_, or_, func, cast, Float, Date as SADate

from backend.db import get_db
from backend.db.models import Article, RssFeed

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("")
async def list_articles(
    digest_date: Optional[date] = Query(None, description="Filter by exact date (YYYY-MM-DD)"),
    date_from: Optional[date] = Query(None, description="Range start date (inclusive)"),
    date_to: Optional[date] = Query(None, description="Range end date (inclusive)"),
    category: Optional[str] = Query(None),
    tags: Optional[str] = Query(None, description="Comma-separated tags to filter by (any match)"),
    source_type: Optional[str] = Query(None, description="Comma-separated source types: hn,reddit,arxiv,rss"),
    source_name: Optional[str] = Query(None, description="Comma-separated source names to filter by (e.g. 'OpenAI Blog,Anthropic Blog')"),
    sort_by: Optional[str] = Query("engagement", description="Sort order: engagement or date"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Article).where(
        or_(Article.is_enriched.is_(None), Article.is_enriched >= 0)  # exclude -1 failed; include NULL (pending, not yet marked)
    )

    if digest_date:
        stmt = stmt.where(Article.digest_date == digest_date)
    else:
        pub_date = func.coalesce(cast(Article.published_at, SADate), Article.digest_date)
        if date_from:
            stmt = stmt.where(pub_date >= date_from)
        if date_to:
            stmt = stmt.where(pub_date <= date_to)
    if category:
        stmt = stmt.where(Article.category == category)
    if tags:
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
        if tag_list:
            stmt = stmt.where(Article.tags.overlap(tag_list))
    if source_type or source_name:
        conditions = []
        if source_type:
            src_list = [s.strip().lower() for s in source_type.split(",") if s.strip()]
            if src_list:
                conditions.append(Article.source_type.in_(src_list))
        if source_name:
            name_list = [n.strip() for n in source_name.split(",") if n.strip()]
            if name_list:
                conditions.append(Article.source_name.in_(name_list))
        if conditions:
            stmt = stmt.where(or_(*conditions))

    # Total count (before pagination) for frontend pagination controls
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    if sort_by == "date":
        stmt = stmt.order_by(desc(Article.published_at))
    else:
        stmt = stmt.order_by(desc(Article.engagement_signal), desc(Article.published_at))
    stmt = stmt.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(stmt)
    articles = result.scalars().all()

    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "articles": [a.to_dict() for a in articles],
    }


@router.get("/trending")
async def get_trending_articles(
    hours: int = Query(48, ge=1, le=168, description="Time window in hours (max 7 days)"),
    limit: int = Query(5, ge=1, le=10, description="Max articles to return"),
    db: AsyncSession = Depends(get_db),
):
    """Return top articles ranked by HN-style time-decayed engagement signal."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    ref_time = func.coalesce(Article.published_at, Article.ingested_at)
    age_hours = cast(func.extract('epoch', func.now() - ref_time), Float) / 3600.0
    trending_score = (
        func.greatest(cast(Article.engagement_signal, Float), 1.0)
        / func.pow(age_hours + 2.0, 1.5)
    ).label('trending_score')

    stmt = (
        select(Article, trending_score)
        .where(
            and_(
                func.coalesce(Article.published_at, Article.ingested_at) >= cutoff,
                or_(Article.is_enriched.is_(None), Article.is_enriched >= 0),
            )
        )
        .order_by(desc(trending_score))
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    articles = []
    for article, score in rows:
        d = article.to_dict()
        d['trending_score'] = round(float(score), 4)
        articles.append(d)

    return {"hours": hours, "limit": limit, "articles": articles}


@router.get("/source-names")
async def get_source_names(db: AsyncSession = Depends(get_db)):
    """Return names of active RSS feeds for use in the feed filter sidebar."""
    result = await db.execute(
        select(RssFeed.name).where(RssFeed.is_active == True).order_by(RssFeed.name)
    )
    return {"feed_names": result.scalars().all()}


@router.get("/{article_id}")
async def get_article(article_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Article).where(Article.id == article_id))
    article = result.scalar_one_or_none()

    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    data = article.to_dict()

    # Populate related articles
    related = []
    if article.related_article_ids:
        rel_result = await db.execute(
            select(Article).where(Article.id.in_(article.related_article_ids))
        )
        rel_articles = rel_result.scalars().all()
        rel_by_id = {a.id: a for a in rel_articles}
        for rid in article.related_article_ids:
            if rid in rel_by_id:
                ra = rel_by_id[rid]
                related.append({
                    "id": ra.id,
                    "title": ra.title,
                    "category": ra.category,
                    "source_name": ra.source_name,
                    "digest_date": ra.digest_date.isoformat() if ra.digest_date else None,
                })
    data["related_articles"] = related

    return data
