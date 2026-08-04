"""Pydantic request and response schemas for the local API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from jobscraper.models.job import ContractType, ExperienceLevel, WorkplaceType

SOURCES = frozenset(
    {"linkedin", "hellowork", "francetravail", "wttj", "freework", "adzuna"}
)
SourceName = Literal[
    "linkedin", "hellowork", "francetravail", "wttj", "freework", "adzuna"
]
SyncStatus = Literal["pending", "running", "succeeded", "partial", "failed"]


def to_camel(value: str) -> str:
    """Translate Python names without leaking them into the browser contract."""

    head, *tail = value.split("_")
    return head + "".join(part.title() for part in tail)


class ApiModel(BaseModel):
    """Use camelCase at the HTTP boundary while keeping Python idiomatic."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SearchFields(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    keywords: list[str] = Field(min_length=1)
    title: str | None = Field(default=None, max_length=300)
    location: str = Field(default="France", min_length=1, max_length=300)
    radius_km: int | None = Field(default=None, ge=1)
    contract_types: list[ContractType] = Field(default_factory=list)
    experience_levels: list[ExperienceLevel] = Field(default_factory=list)
    workplace_types: list[WorkplaceType] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    exclude_companies: list[str] = Field(default_factory=list)
    salary_min: int | None = Field(default=None, ge=0)
    sources: list[SourceName] = Field(min_length=1)
    active: bool = True

    @field_validator("name")
    @classmethod
    def name_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Le nom ne peut pas être vide.")
        return value.strip()

    @field_validator("sources")
    @classmethod
    def sources_are_unique(cls, value: list[SourceName]) -> list[SourceName]:
        if len(value) != len(set(value)):
            raise ValueError("Une source ne peut être sélectionnée qu’une fois.")
        return value


class SearchCreate(SearchFields):
    """Complete payload for creating a saved search."""


class SearchUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    keywords: list[str] | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, min_length=1, max_length=300)
    radius_km: int | None = Field(default=None, ge=1)
    contract_types: list[ContractType] | None = None
    experience_levels: list[ExperienceLevel] | None = None
    workplace_types: list[WorkplaceType] | None = None
    companies: list[str] | None = None
    exclude_companies: list[str] | None = None
    salary_min: int | None = Field(default=None, ge=0)
    sources: list[SourceName] | None = Field(default=None, min_length=1)
    active: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_null_for_persisted_fields(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        non_nullable = {
            "name",
            "keywords",
            "location",
            "contractTypes",
            "contract_types",
            "experienceLevels",
            "experience_levels",
            "workplaceTypes",
            "workplace_types",
            "companies",
            "excludeCompanies",
            "exclude_companies",
            "sources",
            "active",
        }
        if any(key in value and value[key] is None for key in non_nullable):
            raise ValueError("Ce champ ne peut pas être nul.")
        return value

    @field_validator("name")
    @classmethod
    def update_name_is_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Le nom ne peut pas être vide.")
        return value.strip() if value is not None else None

    @field_validator("sources")
    @classmethod
    def update_sources_are_unique(
        cls, value: list[SourceName] | None
    ) -> list[SourceName] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("Une source ne peut être sélectionnée qu’une fois.")
        return value


class SavedSearchResponse(SearchFields):
    id: str
    created_at: datetime
    updated_at: datetime


class SourceLink(ApiModel):
    source: str
    url: str
    active: bool


class PossibleDuplicate(ApiModel):
    id: str
    title: str
    company: str
    location: str
    score: float
    reasons: list[str]


class JobCard(ApiModel):
    id: str
    title: str
    company: str
    location: str
    salary_min: float | None
    salary_max: float | None
    salary_currency: str
    contract_type: str | None
    experience_level: str | None
    remote: bool | None
    posted_at: datetime | None
    sources: list[SourceLink]
    duplicate_state: Literal["confirmed", "possible", "none"]
    possible_duplicates: list[PossibleDuplicate]


class JobDetails(JobCard):
    description: str | None
    skills: list[str]
    benefits: list[str]
    cache_state: Literal["fresh", "refreshed", "stale"]
    updated_at: datetime
    warning: str | None


class JobsPage(ApiModel):
    items: list[JobCard]
    total: int
    limit: int
    offset: int


class StartSyncRequest(ApiModel):
    saved_search_id: str = Field(min_length=1)
    sources: list[SourceName] | None = Field(default=None, min_length=1)


class RetrySyncRequest(ApiModel):
    source: SourceName


class SourceProgress(ApiModel):
    source: str
    status: SyncStatus
    offers_seen: int = 0
    offers_persisted: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class SyncRunResponse(ApiModel):
    id: str
    saved_search_id: str
    status: SyncStatus
    requested_sources: list[str]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    sources: list[SourceProgress]
