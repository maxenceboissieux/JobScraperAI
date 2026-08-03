"""Network-free contracts for the Free-Work scraper."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from jobscraper.models.job import ContractType, DatePosted, JobOffer, SearchCriteria
from jobscraper.scrapers.freework import FreeWorkScraper
from jobscraper.utils import geocoding

FIXTURES_DIR = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def load_fixture():
    def load(relative_path: str) -> str:
        return (FIXTURES_DIR / relative_path).read_text(encoding="utf-8")

    return load


def test_build_search_url_maps_keywords_location_and_contract() -> None:
    criteria = SearchCriteria(
        keywords=["python", "django"],
        location="Paris",
        contract_types=[ContractType.CDI],
        date_posted=DatePosted.PAST_WEEK,
        max_results=20,
    )

    url = FreeWorkScraper({"delay": 0})._build_search_url(criteria)

    assert url == "https://www.free-work.com/fr/tech-it/jobs/paris?query=python+django"


def test_build_search_url_includes_title_accents_and_page() -> None:
    criteria = SearchCriteria(
        title="Développeur Python",
        keywords=["API"],
        location="Île de France",
        radius_km=25,
    )

    url = FreeWorkScraper({"delay": 0})._build_search_url(criteria, page=2)

    assert url == (
        "https://www.free-work.com/fr/tech-it/jobs/ile-de-france"
        "?query=D%C3%A9veloppeur+Python+API&page=2"
    )


def test_parse_search_fixture(load_fixture) -> None:
    scraper = FreeWorkScraper({"delay": 0})
    soup = BeautifulSoup(load_fixture("freework/search.html"), "lxml")

    cards = scraper._extract_job_cards(soup)
    job = scraper._parse_job_card(cards[0])

    assert job is not None
    assert job == JobOffer(
        id="freework_12345",
        source="freework",
        url="https://www.free-work.com/fr/tech-it/developpeur-python/job-mission/12345",
        title="Développeur Python",
        company="Exemple Conseil",
        location="Paris",
        contract_type=ContractType.FREELANCE,
        posted_at=job.posted_at,
        scraped_at=job.scraped_at,
    )


def test_search_paginates_full_pages_stops_at_max_and_deduplicates(
    load_fixture, monkeypatch
) -> None:
    scraper = FreeWorkScraper({"delay": 0, "page_size": 2})
    pages = {
        scraper._build_search_url(SearchCriteria(max_results=3)): load_fixture(
            "freework/search.html"
        ),
        scraper._build_search_url(SearchCriteria(max_results=3), page=2): load_fixture(
            "freework/search-page-2.html"
        ),
    }
    requested_urls = []

    def fetch_page(url: str) -> str:
        requested_urls.append(url)
        return pages[url]

    monkeypatch.setattr(scraper, "_fetch_page", fetch_page)

    jobs = list(scraper.search(SearchCriteria(max_results=3)))

    assert [job.id for job in jobs] == [
        "freework_12345",
        "freework_12346",
        "freework_12347",
    ]
    assert requested_urls == [
        "https://www.free-work.com/fr/tech-it/jobs",
        "https://www.free-work.com/fr/tech-it/jobs?page=2",
    ]


def test_search_does_not_request_page_two_when_first_page_is_not_full(
    load_fixture, monkeypatch
) -> None:
    scraper = FreeWorkScraper({"delay": 0, "page_size": 3})
    requested_urls = []

    def fetch_page(url: str) -> str:
        requested_urls.append(url)
        return load_fixture("freework/search.html")

    monkeypatch.setattr(scraper, "_fetch_page", fetch_page)

    jobs = list(scraper.search(SearchCriteria(max_results=10)))

    assert len(jobs) == 2
    assert requested_urls == ["https://www.free-work.com/fr/tech-it/jobs"]


def test_search_stops_when_a_full_page_contains_only_seen_jobs(
    load_fixture, monkeypatch
) -> None:
    scraper = FreeWorkScraper({"delay": 0, "page_size": 2})
    requested_urls = []

    def fetch_page(url: str) -> str:
        requested_urls.append(url)
        if len(requested_urls) > 2:
            raise AssertionError("a repeated full page must stop pagination")
        return load_fixture("freework/search.html")

    monkeypatch.setattr(scraper, "_fetch_page", fetch_page)

    jobs = list(scraper.search(SearchCriteria(max_results=3)))

    assert len(jobs) == 2
    assert requested_urls == [
        "https://www.free-work.com/fr/tech-it/jobs",
        "https://www.free-work.com/fr/tech-it/jobs?page=2",
    ]


def test_search_stops_at_configured_max_pages_when_every_job_is_filtered(
    monkeypatch,
) -> None:
    scraper = FreeWorkScraper({"delay": 0, "page_size": 2, "max_pages": 3})
    requested_urls = []

    def fetch_page(url: str) -> str:
        requested_urls.append(url)
        if len(requested_urls) > 3:
            raise AssertionError("search exceeded the configured page ceiling")
        first_id = len(requested_urls) * 10
        return "".join(
            f'<article data-job-id="{job_id}" data-contract="CDI"><h2>'
            f'<a href="/fr/tech-it/job-mission/{job_id}">Job {job_id}</a>'
            "</h2></article>"
            for job_id in (first_id, first_id + 1)
        )

    monkeypatch.setattr(scraper, "_fetch_page", fetch_page)

    jobs = list(
        scraper.search(
            SearchCriteria(contract_types=[ContractType.FREELANCE], max_results=1)
        )
    )

    assert jobs == []
    assert requested_urls == [
        "https://www.free-work.com/fr/tech-it/jobs",
        "https://www.free-work.com/fr/tech-it/jobs?page=2",
        "https://www.free-work.com/fr/tech-it/jobs?page=3",
    ]


def test_search_prefers_plain_nuxt_jobs_over_other_representations(monkeypatch) -> None:
    html = """
    <script id="__NUXT_DATA__" type="application/json">
      {"jobs": [{"id": 900, "title": "Nuxt title", "url": "/fr/tech-it/job-mission/900"}]}
    </script>
    <script type="application/ld+json">
      {"@type": "JobPosting", "identifier": "901", "title": "JSON-LD title",
       "url": "/fr/tech-it/job-mission/901"}
    </script>
    <article data-job-id="902"><h2><a href="/fr/tech-it/job-mission/902">HTML title</a></h2></article>
    """
    scraper = FreeWorkScraper({"delay": 0, "page_size": 30})
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: html)

    jobs = list(scraper.search(SearchCriteria(max_results=1)))

    assert [job.title for job in jobs] == ["Nuxt title"]


@pytest.mark.parametrize(
    ("html", "expected_title"),
    [
        (
            """
            <script id="__NUXT_DATA__" type="application/json">
              {"filters": [{"id": 900, "title": "Not a job"}]}
            </script>
            <script type="application/ld+json">
              {"@type": "JobPosting", "identifier": "901",
               "title": "JSON-LD title", "url": "/fr/tech-it/job-mission/901"}
            </script>
            <article data-job-id="902"><h2>
              <a href="/fr/tech-it/job-mission/902">HTML title</a>
            </h2></article>
            """,
            "JSON-LD title",
        ),
        (
            """
            <script type="application/ld+json">
              {"@type": "JobPosting", "identifier": "901", "title": "No URL"}
            </script>
            <article data-job-id="902"><h2>
              <a href="/fr/tech-it/job-mission/902">HTML title</a>
            </h2></article>
            """,
            "HTML title",
        ),
    ],
)
def test_search_falls_back_when_a_representation_has_no_valid_jobs(
    html, expected_title, monkeypatch
) -> None:
    scraper = FreeWorkScraper({"delay": 0})
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: html)

    jobs = list(scraper.search(SearchCriteria(max_results=1)))

    assert [job.title for job in jobs] == [expected_title]


def test_search_requests_page_two_after_a_default_full_page(monkeypatch) -> None:
    first_page = "".join(
        f'<article data-job-id="{job_id}"><h2>'
        f'<a href="/fr/tech-it/job-mission/{job_id}">Job {job_id}</a>'
        "</h2></article>"
        for job_id in range(1, 17)
    )
    scraper = FreeWorkScraper({"delay": 0})
    requested_urls = []

    def fetch_page(url: str) -> str:
        requested_urls.append(url)
        return first_page if len(requested_urls) == 1 else ""

    monkeypatch.setattr(scraper, "_fetch_page", fetch_page)

    jobs = list(scraper.search(SearchCriteria(max_results=17)))

    assert len(jobs) == 16
    assert requested_urls == [
        "https://www.free-work.com/fr/tech-it/jobs",
        "https://www.free-work.com/fr/tech-it/jobs?page=2",
    ]


def test_nuxt_extractor_skips_reference_encoded_devalue_payload() -> None:
    soup = BeautifulSoup(
        '<script id="__NUXT_DATA__" type="application/json">'
        '[{"jobs":1},[{"id":2,"title":3,"url":4}],123,"Title","/job-mission/123"]'
        "</script>",
        "lxml",
    )

    jobs = FreeWorkScraper({"delay": 0})._extract_nuxt_jobs(soup)

    assert jobs == []


def test_json_ld_extractor_finds_nested_job_and_uses_field_fallbacks() -> None:
    soup = BeautifulSoup(
        """
        <script type="application/ld+json">
          {"@graph": [{"@type": "WebPage", "name": "Jobs"},
            {"@type": "JobPosting", "identifier": {"value": "777"},
             "title": "Architecte Cloud", "url": "/fr/tech-it/job-mission/777",
             "employmentType": "CDI", "datePosted": "2026-08-02"}]}
        </script>
        """,
        "lxml",
    )
    scraper = FreeWorkScraper({"delay": 0})

    jobs = scraper._extract_json_ld_jobs(soup)
    job = scraper._parse_job_card(jobs[0])

    assert job is not None
    assert job.id == "freework_777"
    assert job.company == "Non spécifié"
    assert job.location == "France"
    assert job.contract_type == ContractType.CDI


def test_parse_structured_job_rejects_missing_required_url() -> None:
    job = FreeWorkScraper({"delay": 0})._parse_job_card(
        {"id": "778", "title": "Architecte Cloud"}
    )

    assert job is None


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Mission freelance", ContractType.FREELANCE),
        ("CDI", ContractType.CDI),
        ("Intérim", ContractType.INTERIM),
        ("Apprentissage", ContractType.ALTERNANCE),
        ("Temps plein", None),
    ],
)
def test_map_contract_type_only_maps_supported_labels(label, expected) -> None:
    assert FreeWorkScraper({"delay": 0})._map_contract_type(label) == expected


def test_parse_posted_date_accepts_iso_and_rendered_french_dates() -> None:
    scraper = FreeWorkScraper({"delay": 0})

    assert scraper._parse_posted_date(
        "2026-08-01T09:30:00+02:00"
    ) == datetime.fromisoformat("2026-08-01T09:30:00+02:00")
    assert scraper._parse_posted_date("01/08/2026") == datetime(2026, 8, 1)


def test_matches_criteria_applies_contract_date_and_radius_locally(monkeypatch) -> None:
    scraper = FreeWorkScraper({"delay": 0})
    monkeypatch.setattr(
        geocoding,
        "_nominatim_geocode",
        lambda _location: pytest.fail("radius matching must remain network-free"),
    )
    fresh_job = JobOffer(
        id="freework_match",
        source="freework",
        url="https://www.free-work.com/fr/tech-it/job-mission/match",
        title="Développeur Python",
        company="Exemple Conseil",
        location="Paris, Île-de-France",
        contract_type=ContractType.FREELANCE,
        posted_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    criteria = SearchCriteria(
        location="Paris",
        radius_km=25,
        contract_types=[ContractType.FREELANCE],
        date_posted=DatePosted.PAST_WEEK,
    )

    assert scraper._matches_criteria(fresh_job, criteria)
    assert not scraper._matches_criteria(
        fresh_job.model_copy(update={"location": "Lyon"}), criteria
    )
    assert not scraper._matches_criteria(
        fresh_job.model_copy(update={"contract_type": ContractType.CDI}), criteria
    )
    assert not scraper._matches_criteria(
        fresh_job.model_copy(
            update={"posted_at": datetime.now(timezone.utc) - timedelta(days=8)}
        ),
        criteria,
    )


def test_known_city_radius_uses_local_coordinates_without_nominatim(
    monkeypatch,
) -> None:
    nominatim_calls = []
    monkeypatch.setattr(
        geocoding,
        "_nominatim_geocode",
        lambda location: nominatim_calls.append(location),
    )
    scraper = FreeWorkScraper({"delay": 0})
    job = JobOffer(
        id="freework_radius",
        source="freework",
        url="https://www.free-work.com/fr/tech-it/job-mission/radius",
        title="Développeur Python",
        company="Exemple Conseil",
        location="Boulogne-Billancourt",
    )
    criteria = SearchCriteria(location="Paris", radius_km=15)

    assert scraper._matches_criteria(job, criteria)
    assert nominatim_calls == []


def test_unknown_city_radius_is_rejected_without_nominatim(monkeypatch) -> None:
    nominatim_calls = []
    monkeypatch.setattr(
        geocoding,
        "_nominatim_geocode",
        lambda location: nominatim_calls.append(location),
    )
    scraper = FreeWorkScraper({"delay": 0})
    job = JobOffer(
        id="freework_unknown_radius",
        source="freework",
        url="https://www.free-work.com/fr/tech-it/job-mission/unknown-radius",
        title="Développeur Python",
        company="Exemple Conseil",
        location="Ville jamais référencée",
    )
    criteria = SearchCriteria(location="Paris", radius_km=15)

    assert not scraper._matches_criteria(job, criteria)
    assert nominatim_calls == []
