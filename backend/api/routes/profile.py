"""Profile routes: onboarding save and personalized feed."""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from backend.db import get_db
from backend.db.models import Article, UserProfile, UserArticleScore
from backend.api.auth import get_current_uid

router = APIRouter(prefix="/profile", tags=["profile"])


class ProfileCreate(BaseModel):
    role: str
    interests: list[str]
    focus: str


@router.post("")
async def save_profile(
    payload: ProfileCreate,
    uid: str = Depends(get_current_uid),
    db: AsyncSession = Depends(get_db),
):
    """Create or update a user profile from onboarding."""
    result = await db.execute(
        select(UserProfile).where(UserProfile.session_id == uid)
    )
    profile = result.scalar_one_or_none()

    if profile:
        profile.role = payload.role
        profile.interests = payload.interests
        profile.focus = payload.focus
    else:
        profile = UserProfile(
            session_id=uid,
            role=payload.role,
            interests=payload.interests,
            focus=payload.focus,
        )
        db.add(profile)

    await db.commit()
    await db.refresh(profile)

    # Trigger background score computation (fire-and-forget via asyncio task)
    import asyncio
    asyncio.create_task(_compute_scores_async(profile.id))

    return profile.to_dict()


@router.get("/feed")
async def get_personalized_feed(
    uid: str = Depends(get_current_uid),
    category: Optional[str] = Query(None),
    tags: Optional[str] = Query(None, description="Comma-separated tags to filter by (any match)"),
    source_type: Optional[str] = Query(None, description="Comma-separated source types: hn,reddit,arxiv,rss"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Return articles sorted by relevancy score for the authenticated user."""
    result = await db.execute(
        select(UserProfile).where(UserProfile.session_id == uid)
    )
    profile = result.scalar_one_or_none()

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found — complete onboarding first")

    cutoff = date.today() - timedelta(days=7)

    # Build query joining articles with user scores
    stmt = (
        select(Article, UserArticleScore.relevancy_score)
        .outerjoin(
            UserArticleScore,
            and_(
                UserArticleScore.article_id == Article.id,
                UserArticleScore.user_id == profile.id,
            ),
        )
        .where(Article.digest_date >= cutoff, Article.is_enriched >= 0)
    )

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

    results = await db.execute(stmt)
    rows = results.all()

    feed = []
    for article, score in rows:
        d = article.to_dict()
        d["relevancy_score"] = round(score, 3) if score is not None else 0.0
        feed.append(d)

    feed.sort(key=lambda r: r["relevancy_score"], reverse=True)

    offset = (page - 1) * per_page
    paginated = feed[offset : offset + per_page]

    return {
        "session_id": uid,
        "page": page,
        "per_page": per_page,
        "total": len(feed),
        "articles": paginated,
    }


async def _compute_scores_async(user_id: int) -> None:
    """Compute relevancy scores in the background after profile save."""
    import asyncio
    from backend.db import AsyncSessionLocal
    from backend.processing.ranker import relevancy_score
    from backend.db.models import UserArticleScore
    from sqlalchemy import delete

    try:
        async with AsyncSessionLocal() as session:
            cutoff = date.today() - timedelta(days=7)
            user_result = await session.execute(select(UserProfile).where(UserProfile.id == user_id))
            user = user_result.scalar_one_or_none()
            if not user:
                return

            articles_result = await session.execute(
                select(Article).where(Article.digest_date >= cutoff, Article.is_enriched == 1)
            )
            articles = articles_result.scalars().all()

            await session.execute(delete(UserArticleScore).where(UserArticleScore.user_id == user_id))

            scores = [
                UserArticleScore(
                    user_id=user_id,
                    article_id=a.id,
                    relevancy_score=relevancy_score(a, user),
                )
                for a in articles
            ]
            session.add_all(scores)
            await session.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Background score compute failed: {e}")
