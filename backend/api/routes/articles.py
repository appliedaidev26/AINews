"""Article routes: list and detail."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, and_

from backend.db import get_db
from backend.db.models import Article

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("")
async def list_articles(
    digest_date: Optional[date] = Query(None, description="Filter by date (YYYY-MM-DD)"),
    category: Optional[str] = Query(None),
    tags: Optional[str] = Query(None, description="Comma-separated tags to filter by (any match)"),
    source_type: Optional[str] = Query(None, description="Comma-separated source types: hn,reddit,arxiv,rss"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Article).where(Article.is_enriched >= 0)  # 0=pending, 1=enriched (exclude -1 failed)

    if digest_date:
        stmt = stmt.where(Article.digest_date == digest_date)
    if category:
        stmt = stmt.where(Article.category == category)
    if tags:
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
        if tag_list:
            stmt = stmt.where(Article.tags.overlap(tag_list))
    if source_type:
        src_list = [s.strip().lower() for s in source_type.split(",") if s.strip()]
        if src_list:
            stmt = stmt.where(Article.source_type.in_(src_list))

    stmt = stmt.order_by(desc(Article.engagement_signal), desc(Article.published_at))
    stmt = stmt.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(stmt)
    articles = result.scalars().all()

    return {
        "page": page,
        "per_page": per_page,
        "articles": [a.to_dict() for a in articles],
    }


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
