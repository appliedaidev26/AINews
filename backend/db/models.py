from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, Float, Boolean,
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
    practical_takeaway = Column(Text)        # single actionable sentence
    category = Column(String(100), index=True)
    tags = Column(ARRAY(Text))
    audience_scores = Column(JSONB)          # {role: float}
    related_article_ids = Column(ARRAY(Integer))

    # Signals
    engagement_signal = Column(Integer, default=0)
    dedup_hash = Column(String(64), unique=True, index=True)
    # Enrichment state
    is_enriched = Column(Integer, default=0)    # 0=pending, 1=done, -1=failed
    is_vectorized = Column(Integer, default=0)  # 0=pending, 1=done, -1=failed
    enrich_retries = Column(Integer, default=0) # incremented by scrub-orphans each time -1 is reset to 0

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
            "practical_takeaway": self.practical_takeaway,
            "category": self.category,
            "tags": self.tags or [],
            "audience_scores": self.audience_scores or {},
            "related_article_ids": self.related_article_ids or [],
            "engagement_signal": self.engagement_signal or 0,
            "is_enriched": self.is_enriched,
            "is_vectorized": self.is_vectorized,
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


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id               = Column(Integer, primary_key=True, index=True)
    started_at       = Column(DateTime(timezone=True), nullable=False)
    completed_at     = Column(DateTime(timezone=True), nullable=True)
    status           = Column(String(20), nullable=False, default="running", index=True)  # queued|running|success|partial|failed|cancelled
    target_date      = Column(String(20), nullable=False)   # date_from (ISO string) — kept for compat
    date_to          = Column(String(20), nullable=True)    # null → single-date run; set → range run
    triggered_by     = Column(String(50), nullable=False, default="api")
    total_tasks      = Column(Integer, nullable=True)       # N_sources × N_dates (Cloud Tasks mode)
    result           = Column(JSONB, nullable=True)   # {"fetched","new","saved","enriched","date_from","date_to"}
    progress         = Column(JSONB, nullable=True)   # legacy: {"stage","fetched","new","saved","enriched",...}
    error_message    = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    task_runs = relationship("PipelineTaskRun", back_populates="pipeline_run", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id":               self.id,
            "started_at":       self.started_at.isoformat() if self.started_at else None,
            "completed_at":     self.completed_at.isoformat() if self.completed_at else None,
            "status":           self.status,
            "target_date":      self.target_date,
            "date_to":          self.date_to,
            "triggered_by":     self.triggered_by,
            "total_tasks":      self.total_tasks,
            "result":           self.result or {},
            "progress":         self.progress or {},
            "error_message":    self.error_message,
            "duration_seconds": self.duration_seconds,
        }


class PipelineTaskRun(Base):
    """Tracks each (source, date) task within a Cloud Tasks-based PipelineRun."""
    __tablename__ = "pipeline_task_runs"

    id             = Column(Integer, primary_key=True, index=True)
    run_id         = Column(Integer, ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    source         = Column(String(50), nullable=False)   # "hn", "reddit", "arxiv", "rss"
    date           = Column(Date, nullable=False)
    status         = Column(String(20), nullable=False, default="pending", index=True)  # pending|running|success|failed|cancelled
    articles_saved = Column(Integer, nullable=True)
    error_message  = Column(Text, nullable=True)
    updated_at     = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    pipeline_run = relationship("PipelineRun", back_populates="task_runs")

    __table_args__ = (
        UniqueConstraint("run_id", "source", "date", name="uq_task_run_source_date"),
    )

    def to_dict(self):
        return {
            "id":             self.id,
            "run_id":         self.run_id,
            "source":         self.source,
            "date":           str(self.date),
            "status":         self.status,
            "articles_saved": self.articles_saved,
            "error_message":  self.error_message,
            "updated_at":     self.updated_at.isoformat() if self.updated_at else None,
        }


class RssFeed(Base):
    __tablename__ = "rss_feeds"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    url = Column(String(2000), nullable=False, unique=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
