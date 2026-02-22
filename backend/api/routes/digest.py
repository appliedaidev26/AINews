"""Digest routes: today's and historical daily digests."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from backend.db import get_db
from backend.db.models import Article

router = APIRouter(prefix="/digest", tags=["digest"])


async def _get_digest(digest_date: date, category: Optional[str], db: AsyncSession) -> dict:
    stmt = select(Article).where(
        Article.digest_date == digest_date,
        Article.is_enriched >= 0,
    )
    if category:
        stmt = stmt.where(Article.category == category)

    stmt = stmt.order_by(desc(Article.engagement_signal))

    result = await db.execute(stmt)
    articles = result.scalars().all()

    # Category breakdown counts
    cat_stmt = select(Article.category, func.count(Article.id)).where(
        Article.digest_date == digest_date,
        Article.is_enriched >= 0,
    ).group_by(Article.category)
    cat_result = await db.execute(cat_stmt)
    categories = {row[0]: row[1] for row in cat_result.all() if row[0]}

    return {
        "date": str(digest_date),
        "total": len(articles),
        "categories": categories,
        "articles": [a.to_dict() for a in articles],
    }


@router.get("/today")
async def get_today_digest(
    category: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await _get_digest(date.today(), category, db)


@router.get("/{digest_date}")
async def get_digest_by_date(
    digest_date: date,
    category: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await _get_digest(digest_date, category, db)
