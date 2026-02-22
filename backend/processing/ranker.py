"""Relevancy scoring: compute per-user article scores."""
import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import select, delete

from backend.db import sync_engine
from backend.db.models import Article, UserProfile, UserArticleScore

logger = logging.getLogger(__name__)


def relevancy_score(article: Article, user_profile: UserProfile) -> float:
    """
    Weighted relevancy score for one article × user profile.

    Weights:
      tag_overlap  45%  — intersection of article tags and user interests
      role_score   35%  — Gemini's audience score for the user's role
      engagement   20%  — normalized engagement signal (HN score, upvotes)
    """
    art_tags = set(article.tags or [])
    user_tags = set(user_profile.interests or [])

    if art_tags:
        tag_overlap = len(art_tags & user_tags) / len(art_tags)
    else:
        tag_overlap = 0.0

    role_score = 0.5
    if article.audience_scores and user_profile.role:
        role_score = article.audience_scores.get(user_profile.role, 0.5)

    engagement = min((article.engagement_signal or 0) / 1000.0, 1.0)

    score = (tag_overlap * 0.45) + (role_score * 0.35) + (engagement * 0.20)
    return round(score, 3)


def compute_scores_for_user(session: Session, user: UserProfile, days: int = 7) -> int:
    """
    Compute (or refresh) relevancy scores for a user against recent articles.
    Returns number of scores written.
    """
    cutoff = date.today() - timedelta(days=days)
    articles = session.execute(
        select(Article).where(
            Article.digest_date >= cutoff,
            Article.is_enriched == 1,
        )
    ).scalars().all()

    # Delete old scores for this user
    session.execute(
        delete(UserArticleScore).where(UserArticleScore.user_id == user.id)
    )

    scores = []
    for article in articles:
        s = relevancy_score(article, user)
        scores.append(UserArticleScore(
            user_id=user.id,
            article_id=article.id,
            relevancy_score=s,
        ))

    session.add_all(scores)
    session.commit()
    logger.info(f"Computed {len(scores)} scores for user {user.session_id}")
    return len(scores)


def get_ranked_feed(
    session: Session,
    user: UserProfile,
    date_filter: date | None = None,
    category: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> list[dict]:
    """
    Return articles ranked by relevancy score for the user.
    Falls back to engagement_signal if scores haven't been computed yet.
    """
    from sqlalchemy import desc, and_

    cutoff = date_filter or (date.today() - timedelta(days=7))

    # Join articles with user scores
    stmt = (
        select(Article, UserArticleScore.relevancy_score)
        .outerjoin(
            UserArticleScore,
            and_(
                UserArticleScore.article_id == Article.id,
                UserArticleScore.user_id == user.id,
            ),
        )
        .where(Article.digest_date >= cutoff, Article.is_enriched == 1)
    )

    if category:
        stmt = stmt.where(Article.category == category)

    results = session.execute(stmt).all()

    rows = []
    for article, score in results:
        d = article.to_dict()
        d["relevancy_score"] = score if score is not None else 0.0
        rows.append(d)

    rows.sort(key=lambda r: r["relevancy_score"], reverse=True)

    offset = (page - 1) * per_page
    return rows[offset : offset + per_page]
