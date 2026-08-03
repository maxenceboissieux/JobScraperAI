"""Tests live opt-in des sources publiques d'emploi."""

import os

import pytest

from jobscraper import SearchCriteria
from jobscraper.scrapers import (
    FranceTravailScraper,
    FreeWorkScraper,
    HelloWorkScraper,
)

RUN_LIVE = os.getenv("RUN_LIVE_SCRAPER_TESTS") == "1"


@pytest.mark.live
@pytest.mark.skipif(not RUN_LIVE, reason="set RUN_LIVE_SCRAPER_TESTS=1")
@pytest.mark.parametrize(
    "scraper_cls",
    [FreeWorkScraper, HelloWorkScraper, FranceTravailScraper],
)
def test_public_source_returns_valid_offer(scraper_cls):
    """Chaque source publique active renvoie au plus trois offres utilisables."""
    jobs = list(
        scraper_cls({"delay": 1}).search(
            SearchCriteria(keywords=["python"], max_results=3)
        )
    )

    assert jobs
    assert len(jobs) <= 3
    assert all(job.title and str(job.url).startswith("https://") for job in jobs)
