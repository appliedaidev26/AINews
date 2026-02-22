from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, Float,
    ForeignKey, UniqueConstraint, Index, func
)
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(1000), nullable=False)
    original_url = Column(String(2000), nullable=False)
    source_name = Column(String(100), nullable=False)   # e.g. "HackerNews", "Reddit/MachineLearning"
    source_type = Column(String(50), nullable=False)    # "hn", "reddit", "arxiv", "rss"
    author = Column(String(200))
    published_at = Column(DateTime(timezone=True))
    ingested_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    digest_date = Column(Date, nullable=False, index=True)

    # AI-enriched fields
    summary_bullets = Column(JSONB)           # list of strings
    annotations = Column(JSONB)              # list of verbatim quotes
    why_it_matters = Column(Text)
    category = Column(String(100), index=True)
    tags = Column(ARRAY(Text))
    audience_scores = Column(JSONB)          # {role: float}
    related_article_ids = Column(ARRAY(Integer))

    # Signals
    engagement_signal = Column(Integer, default=0)
    dedup_hash = Column(String(64), unique=True, index=True)
    # Enrichment state
    is_enriched = Column(Integer, default=0)  # 0=pending, 1=done, -1=failed

    __table_args__ = (
        Index("ix_articles_digest_category", "digest_date", "category"),
        Index("ix_articles_tags", "tags", postgresql_using="gin"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "original_url": self.original_url,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "author": self.author,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "ingested_at": self.ingested_at.isoformat() if self.ingested_at else None,
            "digest_date": self.digest_date.isoformat() if self.digest_date else None,
            "summary_bullets": self.summary_bullets or [],
            "annotations": self.annotations or [],
            "why_it_matters": self.why_it_matters,
            "category": self.category,
            "tags": self.tags or [],
            "audience_scores": self.audience_scores or {},
            "related_article_ids": self.related_article_ids or [],
            "engagement_signal": self.engagement_signal or 0,
            "is_enriched": self.is_enriched,
        }


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), unique=True, nullable=False, index=True)
    role = Column(String(50))                # engineering_leader, ml_engineer, data_scientist, software_engineer, researcher
    interests = Column(ARRAY(Text))          # selected interest tags
    focus = Column(String(100))             # keeping_up, practitioner, team_leader
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    scores = relationship("UserArticleScore", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "interests": self.interests or [],
            "focus": self.focus,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class UserArticleScore(Base):
    __tablename__ = "user_article_scores"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False)
    relevancy_score = Column(Float, nullable=False)
    computed_at = Column(DateTime(timezone=True), default=func.now())

    user = relationship("UserProfile", back_populates="scores")
    article = relationship("Article")

    __table_args__ = (
        UniqueConstraint("user_id", "article_id", name="uq_user_article"),
        Index("ix_user_article_scores_user_date", "user_id", "computed_at"),
    )
