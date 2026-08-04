"""Deterministic, offline scraper registry used only by the browser fixture mode."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobscraper.models.job import (
    ContractType,
    ExperienceLevel,
    JobOffer,
    SearchCriteria,
)
from jobscraper.scrapers.base import BaseScraper
from jobscraper.scrapers.registry import ScraperRegistry

_SUPPORTED_SOURCES = frozenset(
    {"linkedin", "hellowork", "francetravail", "wttj", "adzuna", "freework"}
)


def _fixture_now() -> datetime:
    raw = os.environ["JOBSCRAPER_FAKE_NOW"]
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("JOBSCRAPER_FAKE_NOW doit contenir un fuseau UTC.")
    return parsed.astimezone(timezone.utc)


def _offer(source: str, now: datetime, *, detailed: bool) -> JobOffer | None:
    if source == "freework":
        return JobOffer(
            id="freework-developpeur-python",
            source=source,
            url="https://example.invalid/freework/developpeur-python",
            title="Développeur Python",
            company="Example Labs",
            location="Paris",
            description="Description mise en cache" if detailed else None,
            salary_min=58_000,
            salary_max=68_000,
            contract_type=ContractType.CDI,
            experience_level=ExperienceLevel.SENIOR,
            remote=True,
            posted_at=now - timedelta(hours=6),
            scraped_at=now,
            skills=["Python", "FastAPI", "SQLite"] if detailed else [],
            benefits=["Télétravail", "Budget formation"] if detailed else [],
        )
    if source == "hellowork":
        return JobOffer(
            id="hellowork-backend-python",
            source=source,
            url="https://example.invalid/hellowork/developpeur-backend-python",
            title="Développeur Backend Python",
            company="Example Labs",
            location="Paris",
            description=(
                "Description Backend Python fournie par le fixture HelloWork."
                if detailed
                else None
            ),
            salary_min=56_000,
            salary_max=66_000,
            contract_type=ContractType.CDI,
            experience_level=ExperienceLevel.SENIOR,
            remote=True,
            posted_at=now - timedelta(hours=36),
            scraped_at=now,
            skills=["Python", "PostgreSQL"] if detailed else [],
            benefits=["Télétravail"] if detailed else [],
        )
    return None


class _FakeScraper(BaseScraper):
    """One source-shaped adapter with no network-capable dependency."""

    def __init__(self, source: str, now: datetime, detail_log: Path) -> None:
        self.name = source
        self._source = source
        self._now = now
        self._detail_log = detail_log
        super().__init__({"propagate_search_errors": True})

    def search(self, criteria: SearchCriteria) -> Iterator[JobOffer]:
        del criteria
        self._begin_search()
        offer = _offer(self._source, self._now, detailed=False)
        if offer is not None:
            yield offer
        self._mark_search_complete()

    def get_job_details(self, job_id: str) -> JobOffer | None:
        expected_identifiers = {
            "freework": "https://example.invalid/freework/developpeur-python",
            "hellowork": "hellowork-backend-python",
        }
        expected = expected_identifiers.get(self._source)
        if expected is None:
            return None
        if job_id != expected:
            raise ValueError(f"Identifiant fake inattendu pour {self._source}.")
        with self._detail_log.open("a", encoding="utf-8") as log:
            log.write(f"{self._source}\n")
        return _offer(self._source, self._now, detailed=True)


class FakeScraperRegistry(ScraperRegistry):
    """Create only deterministic adapters for every recognized source."""

    def __init__(self, now: datetime, detail_log: Path) -> None:
        self._now = now
        self._detail_log = detail_log

    def create(self, source: str) -> BaseScraper:
        if source not in _SUPPORTED_SOURCES:
            raise ValueError(f"Source de scraping inconnue: {source}")
        return _FakeScraper(source, self._now, self._detail_log)


def build_fake_registry() -> ScraperRegistry:
    """Build the fixture registry from runner-owned deterministic inputs."""

    return FakeScraperRegistry(
        now=_fixture_now(),
        detail_log=Path(os.environ["JOBSCRAPER_FAKE_DETAIL_LOG"]),
    )
