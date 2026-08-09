"""SQLAlchemy models for saved searches and aggregated job listings."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from jobscraper.db.base import Base, UTCDateTime, utc_now


def new_public_id() -> str:
    """Generate a portable UUID string for externally visible identifiers."""

    return str(uuid4())


class SavedSearch(Base):
    """A reusable set of source and job-filter criteria."""

    __tablename__ = "saved_searches"

    pk: Mapped[int] = mapped_column(Integer, primary_key=True)
    id: Mapped[str] = mapped_column(
        String(36), default=new_public_id, unique=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    location: Mapped[str] = mapped_column(String(300), default="France", nullable=False)
    radius_km: Mapped[int | None] = mapped_column(Integer)
    contract_types: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    experience_levels: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    workplace_types: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    companies: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    exclude_companies: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    salary_min: Mapped[int | None] = mapped_column(Integer)
    max_results: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    sources: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class CanonicalJob(Base):
    """The locally canonical representation shared by one or more listings."""

    __tablename__ = "canonical_jobs"

    pk: Mapped[int] = mapped_column(Integer, primary_key=True)
    id: Mapped[str] = mapped_column(
        String(36), default=new_public_id, unique=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(500), nullable=False)
    company: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_company: Mapped[str] = mapped_column(String(300), nullable=False)
    location: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_location: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    salary_currency: Mapped[str] = mapped_column(
        String(3), default="EUR", nullable=False
    )
    contract_type: Mapped[str | None] = mapped_column(String(50))
    experience_level: Mapped[str | None] = mapped_column(String(50))
    remote: Mapped[bool | None] = mapped_column(Boolean)
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    viewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    benefits: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    details_fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    detail_provenance: Mapped[dict[str, str]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class SourceListing(Base):
    """A source-specific appearance of a canonical job."""

    __tablename__ = "source_listings"
    __table_args__ = (
        UniqueConstraint(
            "source", "external_id", name="uq_source_listings_source_external_id"
        ),
    )

    pk: Mapped[int] = mapped_column(Integer, primary_key=True)
    id: Mapped[str] = mapped_column(
        String(36), default=new_public_id, unique=True, nullable=False
    )
    canonical_job_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_jobs.pk", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company: Mapped[str] = mapped_column(String(300), nullable=False)
    location: Mapped[str] = mapped_column(String(300), nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class SearchListing(Base):
    """Association between a saved search and a canonical job."""

    __tablename__ = "search_listings"
    __table_args__ = (
        UniqueConstraint(
            "saved_search_id",
            "canonical_job_id",
            name="uq_search_listings_search_job",
        ),
    )

    pk: Mapped[int] = mapped_column(Integer, primary_key=True)
    saved_search_id: Mapped[int] = mapped_column(
        ForeignKey("saved_searches.pk", ondelete="CASCADE"), nullable=False
    )
    canonical_job_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_jobs.pk", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )


class DuplicateRelation(Base):
    """A classified relationship between two canonical jobs."""

    __tablename__ = "duplicate_relations"
    __table_args__ = (
        CheckConstraint(
            "left_job_id < right_job_id",
            name="canonical_order",
        ),
        UniqueConstraint(
            "left_job_id",
            "right_job_id",
            name="uq_duplicate_relations_left_right",
        ),
    )

    pk: Mapped[int] = mapped_column(Integer, primary_key=True)
    left_job_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_jobs.pk", ondelete="CASCADE"), nullable=False
    )
    right_job_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_jobs.pk", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class SyncRun(Base):
    """One synchronization attempt for a saved search."""

    __tablename__ = "sync_runs"
    __table_args__ = (
        Index(
            "uq_sync_runs_one_active_search",
            "saved_search_id",
            unique=True,
            sqlite_where=text("status IN ('pending', 'running')"),
        ),
    )

    pk: Mapped[int] = mapped_column(Integer, primary_key=True)
    id: Mapped[str] = mapped_column(
        String(36), default=new_public_id, unique=True, nullable=False
    )
    saved_search_id: Mapped[int] = mapped_column(
        ForeignKey("saved_searches.pk", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    requested_sources: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class SourceSyncResult(Base):
    """Per-source progress and outcome within a synchronization run."""

    __tablename__ = "source_sync_results"
    __table_args__ = (
        UniqueConstraint(
            "sync_run_id", "source", name="uq_source_sync_results_run_source"
        ),
    )

    pk: Mapped[int] = mapped_column(Integer, primary_key=True)
    id: Mapped[str] = mapped_column(
        String(36), default=new_public_id, unique=True, nullable=False
    )
    sync_run_id: Mapped[int] = mapped_column(
        ForeignKey("sync_runs.pk", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    offers_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    offers_persisted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


ALL_MODELS: tuple[type[Any], ...] = (
    SavedSearch,
    CanonicalJob,
    SourceListing,
    SearchListing,
    DuplicateRelation,
    SyncRun,
    SourceSyncResult,
)
