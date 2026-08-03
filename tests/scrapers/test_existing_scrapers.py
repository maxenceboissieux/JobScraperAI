"""Network-free regression contracts for the pre-existing job sources."""

import json
from datetime import datetime
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from jobscraper.models.job import ContractType, DatePosted, SearchCriteria
from jobscraper.scrapers.adzuna import AdzunaScraper
from jobscraper.scrapers.francetravail import FranceTravailScraper
from jobscraper.scrapers.hellowork import HelloWorkScraper
from jobscraper.scrapers.linkedin import LinkedInScraper
from jobscraper.scrapers.wttj import WTTJScraper

FIXTURES_DIR = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def load_fixture():
    def load(relative_path: str) -> str:
        return (FIXTURES_DIR / relative_path).read_text(encoding="utf-8")

    return load


@pytest.mark.parametrize(
    (
        "scraper",
        "fixture",
        "expected_source",
        "expected_id",
        "expected_url",
        "expected_location",
    ),
    [
        (
            LinkedInScraper({"delay": 0}),
            "linkedin/search.html",
            "linkedin",
            "linkedin_10001",
            "https://www.linkedin.com/jobs/view/developpeur-python-10001",
            "Paris, France",
        ),
        (
            HelloWorkScraper({"delay": 0}),
            "hellowork/search.html",
            "hellowork",
            "hellowork_20002",
            "https://www.hellowork.com/fr-fr/emplois/developpeur-python-20002.html",
            "75001 Paris",
        ),
        (
            FranceTravailScraper({"delay": 0}),
            "francetravail/search.html",
            "francetravail",
            "francetravail_30003",
            "https://candidat.francetravail.fr/offres/recherche/detail/30003",
            "Paris 1er",
        ),
    ],
)
def test_html_scraper_parses_representative_card(
    scraper,
    fixture,
    expected_source,
    expected_id,
    expected_url,
    expected_location,
    load_fixture,
) -> None:
    soup = BeautifulSoup(load_fixture(fixture), "lxml")
    cards = scraper._extract_job_cards(soup)

    assert len(cards) == 1

    job = scraper._parse_job_card(cards[0])

    assert job is not None
    assert job.id == expected_id
    assert job.source == expected_source
    assert str(job.url) == expected_url
    assert job.title == "Développeur Python"
    assert job.company == "Exemple Conseil"
    assert job.location == expected_location
    assert job.contract_type == ContractType.CDI
    assert job.posted_at is not None


def test_hellowork_preserves_an_iso_publication_date(load_fixture) -> None:
    scraper = HelloWorkScraper({"delay": 0})
    soup = BeautifulSoup(load_fixture("hellowork/search.html"), "lxml")

    job = scraper._parse_job_card(scraper._extract_job_cards(soup)[0])

    assert job is not None
    assert job.posted_at == datetime.fromisoformat("2026-08-01T10:00:00+00:00")


@pytest.mark.parametrize(
    ("contract_label", "expected_contract_type"),
    [
        ("CDI", ContractType.CDI),
        ("CDD", ContractType.CDD),
        ("FULL-TIME", None),
        ("CONTRACT", None),
    ],
)
def test_linkedin_only_maps_unambiguous_contract_labels(
    contract_label, expected_contract_type, load_fixture
) -> None:
    scraper = LinkedInScraper({"delay": 0})
    html = load_fixture("linkedin/search.html").replace(
        ">CDI</span>", f">{contract_label}</span>"
    )
    soup = BeautifulSoup(html, "lxml")

    job = scraper._parse_job_card(scraper._extract_job_cards(soup)[0])

    assert job is not None
    assert job.contract_type == expected_contract_type


def test_wttj_parses_representative_hit(load_fixture) -> None:
    scraper = WTTJScraper({"delay": 0})

    job = scraper._parse_hit(json.loads(load_fixture("wttj/search.json")))

    assert job is not None
    assert job.id == "wttj_40004"
    assert job.source == "wttj"
    assert str(job.url) == (
        "https://www.welcometothejungle.com/fr/companies/exemple-conseil/"
        "jobs/developpeur-python"
    )
    assert job.title == "Développeur Python"
    assert job.company == "Exemple Conseil"
    assert job.location == "Paris, France"
    assert job.contract_type == ContractType.CDI
    assert job.posted_at == datetime.fromisoformat("2026-08-01T11:00:00+00:00")


def test_adzuna_parses_representative_result(load_fixture) -> None:
    scraper = AdzunaScraper({"app_id": "test", "app_key": "test"})

    job = scraper._parse_result(json.loads(load_fixture("adzuna/search.json")))

    assert job is not None
    assert job.id == "adzuna_50005"
    assert job.source == "adzuna"
    assert str(job.url) == "https://www.adzuna.fr/details/50005"
    assert job.title == "Développeur Python"
    assert job.company == "Exemple Conseil"
    assert job.location == "Paris"
    assert job.contract_type == ContractType.CDI
    assert job.posted_at == datetime.fromisoformat("2026-08-01T12:00:00+00:00")


@pytest.mark.parametrize(
    ("scraper", "expected_url_fragment"),
    [
        (LinkedInScraper({"delay": 0}), "keywords=%22Python%22+django"),
        (HelloWorkScraper({"delay": 0}), "k=Python+django"),
        (FranceTravailScraper({"delay": 0}), "motsCles=Python+django+Paris"),
    ],
)
def test_html_scrapers_build_urls_from_search_criteria(
    scraper, expected_url_fragment
) -> None:
    criteria = SearchCriteria(
        title="Python",
        keywords=["django"],
        location="Paris",
        contract_types=[ContractType.CDI],
    )

    url = scraper._build_search_url(criteria)

    assert url.startswith("https://")
    assert expected_url_fragment in url


def test_linkedin_explicit_any_time_ignores_deprecated_posted_within_days() -> None:
    criteria = SearchCriteria(
        date_posted=DatePosted.ANY_TIME,
        posted_within_days=1,
    )

    url = LinkedInScraper({"delay": 0})._build_search_url(criteria)

    assert "f_TPR=" not in url
