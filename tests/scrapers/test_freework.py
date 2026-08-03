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


def test_live_shape_search_url_enriches_after_scraper_restart(
    load_fixture, monkeypatch
) -> None:
    search_scraper = FreeWorkScraper({"delay": 0})
    monkeypatch.setattr(
        search_scraper,
        "_fetch_page",
        lambda _url: load_fixture("freework/search-live.html"),
    )

    jobs = list(search_scraper.search(SearchCriteria(max_results=1)))

    assert len(jobs) == 1
    stored_url = str(jobs[0].url)
    assert stored_url == (
        "https://www.free-work.com/fr/tech-it/job-mission/"
        "developpeur-python/developpeur-python-exemple"
    )

    detail_scraper = FreeWorkScraper({"delay": 0})
    requested_urls = []

    def fetch_detail(url: str) -> str:
        requested_urls.append(url)
        return load_fixture("freework/details-live.html")

    monkeypatch.setattr(detail_scraper, "_fetch_page", fetch_detail)

    detailed = detail_scraper.get_job_details(stored_url)

    assert detailed is not None
    assert detailed.id == jobs[0].id == "freework_659066"
    assert detailed.title == "Développeur Python confirmé"
    assert requested_urls == [stored_url]


def test_detail_jobposting_with_standalone_data_id_preserves_search_identity(
    load_fixture, monkeypatch
) -> None:
    search_scraper = FreeWorkScraper({"delay": 0})
    search_soup = BeautifulSoup(load_fixture("freework/search-live.html"), "lxml")
    search_job = search_scraper._parse_job_card(
        search_scraper._extract_job_cards(search_soup)[0]
    )
    assert search_job is not None

    detail_html = f"""
    <script type="application/ld+json">
      {{"@type": "JobPosting", "title": "Développeur Python confirmé",
       "url": "{search_job.url}"}}
    </script>
    <main data-id="659066">
      <h1>Développeur Python confirmé</h1>
      <div class="job-description">Construire des services Python.</div>
    </main>
    """
    detail_scraper = FreeWorkScraper({"delay": 0})
    monkeypatch.setattr(detail_scraper, "_fetch_page", lambda _url: detail_html)

    detailed = detail_scraper.get_job_details(str(search_job.url))

    assert detailed is not None
    assert detailed.id == search_job.id == "freework_659066"


def test_generic_page_with_unrelated_data_id_is_not_an_offer(monkeypatch) -> None:
    html = """
    <main data-id="659066">
      <h1>Page générique</h1>
      <p>Ce contenu ne décrit pas une offre.</p>
    </main>
    """
    scraper = FreeWorkScraper({"delay": 0})
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: html)

    detail = scraper.get_job_details(
        "https://www.free-work.com/fr/tech-it/job-mission/python/page-generique"
    )

    assert detail is None


def test_get_job_details_parses_description_salary_and_skills(
    load_fixture, monkeypatch
):
    scraper = FreeWorkScraper({"delay": 0})
    soup = BeautifulSoup(load_fixture("freework/search.html"), "lxml")
    search_job = scraper._parse_job_card(scraper._extract_job_cards(soup)[0])
    requested_urls = []

    def fetch_page(url: str) -> str:
        requested_urls.append(url)
        return load_fixture("freework/details.html")

    monkeypatch.setattr(scraper, "_fetch_page", fetch_page)

    assert search_job is not None
    job = scraper.get_job_details(str(search_job.url))

    assert job is not None
    assert "Python" in job.description
    assert job.salary_min == 500.0
    assert "Django" in job.skills
    assert requested_urls == [
        "https://www.free-work.com/fr/tech-it/developpeur-python/job-mission/12345"
    ]


def test_get_job_details_falls_back_to_focused_html_fields(monkeypatch) -> None:
    canonical_url = (
        "https://www.free-work.com/fr/tech-it/ingenieur-plateforme/" "job-mission/54321"
    )
    html = """
    <main data-job-id="54321">
      <h1>Ingénieur plateforme</h1>
      <a class="job-company">Société Démo</a>
      <span class="job-location">Lyon</span>
      <div class="job-description">Construire une plateforme FastAPI.</div>
      <span class="job-contract">CDI</span>
      <span class="job-salary">55 000 - 65 000 EUR</span>
      <ul class="job-skills"><li>FastAPI</li><li>Docker</li></ul>
      <ul class="job-benefits"><li>RTT</li><li>Mutuelle</li></ul>
    </main>
    """
    scraper = FreeWorkScraper({"delay": 0})
    requested_urls = []

    def fetch_page(url: str) -> str:
        requested_urls.append(url)
        return html

    monkeypatch.setattr(scraper, "_fetch_page", fetch_page)

    job = scraper.get_job_details(canonical_url)

    assert job is not None
    assert job.title == "Ingénieur plateforme"
    assert job.company == "Société Démo"
    assert job.location == "Lyon"
    assert job.description == "Construire une plateforme FastAPI."
    assert job.contract_type == ContractType.CDI
    assert job.salary_min == 55000.0
    assert job.salary_max == 65000.0
    assert job.skills == ["FastAPI", "Docker"]
    assert job.benefits == ["RTT", "Mutuelle"]
    assert requested_urls == [canonical_url]


@pytest.mark.parametrize(
    ("canonical_url", "expected_id"),
    [
        (
            (
                "https://www.free-work.com/fr/tech-it/job-mission/"
                "python/offre-sans-identifiant"
            ),
            (
                "freework_url_"
                "b091ee471d72b2db94c8c79303448f152d81b781c390c6d835da6290f5cd4c90"
            ),
        ),
        (
            ("https://www.free-work.com/fr/tech-it/" "offre-legacy/job-mission/54321"),
            "freework_54321",
        ),
    ],
)
def test_detail_without_source_identifier_uses_safe_canonical_fallback(
    canonical_url, expected_id, monkeypatch
) -> None:
    html = """
    <main data-testid="job-detail">
      <h1>Développeur Python</h1>
      <div class="job-description">Construire des services Python.</div>
    </main>
    """
    scraper = FreeWorkScraper({"delay": 0})
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: html)

    job = scraper.get_job_details(canonical_url)

    assert job is not None
    assert job.id == expected_id


def test_invalid_structured_source_identifier_uses_current_url_fallback(
    monkeypatch,
) -> None:
    canonical_url = (
        "https://www.free-work.com/fr/tech-it/job-mission/"
        "python/offre-identifiant-invalide"
    )
    html = f"""
    <script type="application/ld+json">
      {{"@type": "JobPosting", "identifier": "../../admin",
       "title": "Développeur Python", "url": "{canonical_url}"}}
    </script>
    """
    scraper = FreeWorkScraper({"delay": 0})
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: html)

    job = scraper.get_job_details(canonical_url)

    assert job is not None
    assert job.id == (
        "freework_url_"
        "1da75d99513de0a6bf155bb11dfc78e9d57f23a1bcfb927cb0e51e6583aa7ad2"
    )


def test_get_job_details_does_not_fetch_an_uncached_bare_id(monkeypatch) -> None:
    scraper = FreeWorkScraper({"delay": 0})
    monkeypatch.setattr(
        scraper,
        "_fetch_page",
        lambda _url: pytest.fail("an uncached ID must not fabricate a detail URL"),
    )

    assert scraper.get_job_details("12345") is None


def test_get_job_details_does_not_fetch_a_slugless_absolute_url(monkeypatch) -> None:
    scraper = FreeWorkScraper({"delay": 0})
    monkeypatch.setattr(
        scraper,
        "_fetch_page",
        lambda _url: pytest.fail("a slugless path is not a canonical offer URL"),
    )

    assert (
        scraper.get_job_details(
            "https://www.free-work.com/fr/tech-it/job-mission/12345"
        )
        is None
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://www.free-work.com/fr/tech-it/job-mission/python/offre-python",
        "https://evil.example/fr/tech-it/job-mission/python/offre-python",
        "https://user:secret@www.free-work.com/fr/tech-it/job-mission/python/offre-python",
        "https://www.free-work.com:444/fr/tech-it/job-mission/python/offre-python",
        "https://www.free-work.com/fr/tech-it/jobs/python/offre-python",
        (
            "https://www.free-work.com/fr/tech-it/jobs"
            "?next=/fr/tech-it/job-mission/python/offre-python"
        ),
        (
            "https://www.free-work.com/fr/tech-it/job-mission/python/offre-python"
            "?source=spoof"
        ),
    ],
)
def test_get_job_details_rejects_noncanonical_offer_urls(url, monkeypatch) -> None:
    scraper = FreeWorkScraper({"delay": 0})
    monkeypatch.setattr(
        scraper,
        "_fetch_page",
        lambda _url: pytest.fail("une URL non canonique ne doit pas être appelée"),
    )

    assert scraper.get_job_details(url) is None


def test_get_job_details_accepts_default_https_port_and_canonicalizes_url(
    load_fixture, monkeypatch
) -> None:
    scraper = FreeWorkScraper({"delay": 0})
    requested_urls = []
    monkeypatch.setattr(
        scraper,
        "_fetch_page",
        lambda url: requested_urls.append(url)
        or load_fixture("freework/details-live.html"),
    )

    job = scraper.get_job_details(
        "https://free-work.com:443/fr/tech-it/job-mission/"
        "developpeur-python/developpeur-python-exemple/"
    )

    assert job is not None
    assert requested_urls == [
        "https://www.free-work.com/fr/tech-it/job-mission/"
        "developpeur-python/developpeur-python-exemple"
    ]


def test_search_rejects_foreign_and_non_offer_structured_urls() -> None:
    scraper = FreeWorkScraper({"delay": 0})

    assert (
        scraper._parse_job_card(
            {
                "id": "foreign",
                "title": "Offre étrangère",
                "url": "https://example.com/fr/tech-it/job-mission/python/offre",
            }
        )
        is None
    )
    assert (
        scraper._parse_job_card(
            {
                "id": "listing",
                "title": "Fausse offre",
                "url": "https://www.free-work.com/fr/tech-it/jobs?job-mission=listing",
            }
        )
        is None
    )


def test_detail_json_ld_cannot_override_with_foreign_url(monkeypatch) -> None:
    canonical_url = (
        "https://www.free-work.com/fr/tech-it/job-mission/python/offre-python"
    )
    html = """
    <script type="application/ld+json">
      {"@type": "JobPosting", "identifier": "123", "title": "Offre Python",
       "url": "https://example.com/fr/tech-it/job-mission/python/offre-python"}
    </script>
    """
    scraper = FreeWorkScraper({"delay": 0})
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: html)

    job = scraper.get_job_details(canonical_url)

    assert job is not None
    assert str(job.url) == canonical_url


def test_get_job_details_rejects_a_headed_error_page(load_fixture, monkeypatch) -> None:
    scraper = FreeWorkScraper({"delay": 0})
    soup = BeautifulSoup(load_fixture("freework/search.html"), "lxml")
    search_job = scraper._parse_job_card(scraper._extract_job_cards(soup)[0])
    monkeypatch.setattr(
        scraper,
        "_fetch_page",
        lambda _url: load_fixture("freework/not-found.html"),
    )

    assert search_job is not None
    assert scraper.get_job_details("12345") is None


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
            f'<a href="/fr/tech-it/job-mission/test/job-{job_id}">Job {job_id}</a>'
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
      {"jobs": [{"id": 900, "title": "Nuxt title", "url": "/fr/tech-it/job-mission/test/job-900"}]}
    </script>
    <script type="application/ld+json">
      {"@type": "JobPosting", "identifier": "901", "title": "JSON-LD title",
       "url": "/fr/tech-it/job-mission/test/job-901"}
    </script>
    <article data-job-id="902"><h2><a href="/fr/tech-it/job-mission/test/job-902">HTML title</a></h2></article>
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
               "title": "JSON-LD title", "url": "/fr/tech-it/job-mission/test/job-901"}
            </script>
            <article data-job-id="902"><h2>
              <a href="/fr/tech-it/job-mission/test/job-902">HTML title</a>
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
              <a href="/fr/tech-it/job-mission/test/job-902">HTML title</a>
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
        f'<a href="/fr/tech-it/job-mission/test/job-{job_id}">Job {job_id}</a>'
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
             "title": "Architecte Cloud", "url": "/fr/tech-it/job-mission/test/job-777",
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
        url="https://www.free-work.com/fr/tech-it/job-mission/test/match",
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


def test_explicit_any_time_ignores_deprecated_posted_within_days() -> None:
    old_job = JobOffer(
        id="freework_old",
        source="freework",
        url=(
            "https://www.free-work.com/fr/tech-it/job-mission/"
            "developpeur-python/offre-ancienne"
        ),
        title="Développeur Python",
        company="Exemple Conseil",
        location="Paris",
        posted_at=datetime.now(timezone.utc) - timedelta(days=365),
    )
    criteria = SearchCriteria(
        date_posted=DatePosted.ANY_TIME,
        posted_within_days=1,
    )

    assert FreeWorkScraper({"delay": 0})._matches_criteria(old_job, criteria)


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
        url="https://www.free-work.com/fr/tech-it/job-mission/test/radius",
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
        url="https://www.free-work.com/fr/tech-it/job-mission/test/unknown-radius",
        title="Développeur Python",
        company="Exemple Conseil",
        location="Ville jamais référencée",
    )
    criteria = SearchCriteria(location="Paris", radius_km=15)

    assert not scraper._matches_criteria(job, criteria)
    assert nominatim_calls == []


@pytest.mark.parametrize(
    ("job_location", "expected"),
    [
        ("Paris (75)", True),
        ("Paris, Île-de-France", True),
        ("Boulogne-Billancourt", True),
        ("Parisien inconnu", False),
        ("Paulette-sur-Mer", False),
        ("Lyonnais imaginaire", False),
    ],
)
def test_radius_locality_matching_requires_city_boundaries(
    job_location, expected, monkeypatch
) -> None:
    nominatim_calls = []
    monkeypatch.setattr(
        geocoding,
        "_nominatim_geocode",
        lambda location: nominatim_calls.append(location),
    )
    scraper = FreeWorkScraper({"delay": 0})
    job = JobOffer(
        id="freework_boundary_radius",
        source="freework",
        url="https://www.free-work.com/fr/tech-it/job-mission/test/boundary-radius",
        title="Développeur Python",
        company="Exemple Conseil",
        location=job_location,
    )
    criteria = SearchCriteria(location="Paris", radius_km=1000)

    assert scraper._matches_criteria(job, criteria) is expected
    assert nominatim_calls == []
