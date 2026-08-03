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
@pytest.mark.skipif(
    not RUN_LIVE,
    reason="définir RUN_LIVE_SCRAPER_TESTS=1 pour lancer les tests réseau",
)
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


@pytest.mark.live
@pytest.mark.skipif(
    not RUN_LIVE,
    reason="définir RUN_LIVE_SCRAPER_TESTS=1 pour lancer les tests réseau",
)
def test_freework_search_offer_can_be_enriched_from_stored_url():
    """L'URL conservée par la recherche suffit à recharger une offre détaillée."""
    search_scraper = FreeWorkScraper({"delay": 1})
    jobs = list(
        search_scraper.search(SearchCriteria(keywords=["python"], max_results=1))
    )

    assert len(jobs) == 1
    stored_url = str(jobs[0].url)

    detail = FreeWorkScraper({"delay": 1}).get_job_details(stored_url)

    assert detail is not None
    assert detail.title
    assert str(detail.url).startswith("https://www.free-work.com/")
