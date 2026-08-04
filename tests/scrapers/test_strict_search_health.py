"""Offline contracts for authoritative full-scan detection."""

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from jobscraper.models.job import (
    ContractType,
    DatePosted,
    ExperienceLevel,
    JobOffer,
    SearchCriteria,
    WorkplaceType,
)
from jobscraper.scrapers.adzuna import AdzunaScraper
from jobscraper.scrapers.base import IncompleteSearchError
from jobscraper.scrapers.francetravail import FranceTravailScraper
from jobscraper.scrapers.freework import FreeWorkScraper
from jobscraper.scrapers.hellowork import HelloWorkScraper
from jobscraper.scrapers.linkedin import LinkedInScraper
from jobscraper.scrapers.wttj import WTTJScraper


def offer(source: str, suffix: str = "1") -> JobOffer:
    return JobOffer(
        id=f"{source}_{suffix}",
        source=source,
        url=f"https://example.com/{source}/{suffix}",
        title="Python developer",
        company="Example",
        location="Paris",
    )


def hellowork_card(identifier: str) -> str:
    return (
        f'<li data-id-storage-item-id="{identifier}">'
        f'<input name="title" value="Offer {identifier}">'
        f'<input name="company" value="Acme">'
        f'<a href="/fr-fr/emplois/{identifier}.html">Offer</a></li>'
    )


@pytest.mark.parametrize(
    "scraper_type", [LinkedInScraper, HelloWorkScraper, FranceTravailScraper]
)
def test_html_sources_reject_any_partially_parsed_page(
    scraper_type: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    scraper = scraper_type({"delay": 0, "propagate_search_errors": True})
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: "<html></html>")
    monkeypatch.setattr(scraper, "_extract_job_cards", lambda _soup: [1, 2])
    parsed = iter([offer(scraper.name), None])
    monkeypatch.setattr(scraper, "_parse_job_card", lambda _card: next(parsed))

    iterator = scraper.search(SearchCriteria(max_results=10))
    assert next(iterator).id == f"{scraper.name}_1"
    with pytest.raises(IncompleteSearchError):
        next(iterator)


def test_wttj_rejects_partially_parsed_page(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = WTTJScraper({"propagate_search_errors": True})
    monkeypatch.setattr(
        scraper,
        "_fetch_algolia",
        lambda *_args: {"hits": [{}, {}], "nbHits": 2, "nbPages": 1},
    )
    parsed = iter([offer("wttj"), None])
    monkeypatch.setattr(scraper, "_parse_hit", lambda _hit: next(parsed))

    iterator = scraper.search(SearchCriteria(max_results=10))
    assert next(iterator).id == "wttj_1"
    with pytest.raises(IncompleteSearchError):
        next(iterator)


class _JsonResponse:
    def __init__(self, payload: object):
        self.payload = payload

    def json(self) -> object:
        return self.payload

    def raise_for_status(self) -> None:
        return None


def test_adzuna_rejects_partially_parsed_page(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = AdzunaScraper(
        {"app_id": "id", "app_key": "key", "propagate_search_errors": True}
    )
    monkeypatch.setattr(
        scraper,
        "_request_with_retry",
        lambda _operation: _JsonResponse({"results": [{}, {}], "count": 2}),
    )
    parsed = iter([offer("adzuna"), None])
    monkeypatch.setattr(scraper, "_parse_result", lambda _result: next(parsed))

    iterator = scraper.search(SearchCriteria(max_results=10))
    assert next(iterator).id == "adzuna_1"
    with pytest.raises(IncompleteSearchError):
        next(iterator)


def test_freework_rejects_partially_parsed_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = FreeWorkScraper(
        {"delay": 0, "page_size": 2, "propagate_search_errors": True}
    )
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: "<html></html>")
    monkeypatch.setattr(scraper, "_extract_nuxt_jobs", lambda _soup: [{}, {}])
    parsed = iter([offer("freework"), None])
    monkeypatch.setattr(scraper, "_parse_job_card", lambda _result: next(parsed))

    iterator = scraper.search(SearchCriteria(max_results=10))
    assert next(iterator).id == "freework_1"
    with pytest.raises(IncompleteSearchError):
        next(iterator)


def test_freework_strict_mode_keeps_partial_evidence_across_fallback_extractors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = FreeWorkScraper({"delay": 0, "propagate_search_errors": True})
    invalid_nuxt = {"representation": "invalid-nuxt"}
    valid_json_ld = {"representation": "valid-json-ld"}
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: "<html></html>")
    monkeypatch.setattr(scraper, "_extract_nuxt_jobs", lambda _soup: [invalid_nuxt])
    monkeypatch.setattr(scraper, "_extract_json_ld_jobs", lambda _soup: [valid_json_ld])
    monkeypatch.setattr(
        scraper,
        "_parse_job_card",
        lambda candidate: offer("freework") if candidate is valid_json_ld else None,
    )

    iterator = scraper.search(SearchCriteria(max_results=10))
    assert next(iterator).id == "freework_1"
    with pytest.raises(IncompleteSearchError):
        next(iterator)


def test_freework_legacy_mode_keeps_valid_fallback_after_partial_representation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = FreeWorkScraper({"delay": 0})
    invalid_nuxt = {"representation": "invalid-nuxt"}
    valid_card = {"representation": "valid-card"}
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: "<html></html>")
    monkeypatch.setattr(scraper, "_extract_nuxt_jobs", lambda _soup: [invalid_nuxt])
    monkeypatch.setattr(scraper, "_extract_json_ld_jobs", lambda _soup: [])
    monkeypatch.setattr(scraper, "_extract_job_cards", lambda _soup: [valid_card])
    monkeypatch.setattr(
        scraper,
        "_parse_job_card",
        lambda candidate: offer("freework") if candidate is valid_card else None,
    )

    jobs = list(scraper.search(SearchCriteria(max_results=10)))

    assert [job.id for job in jobs] == ["freework_1"]


@pytest.mark.parametrize(
    ("scraper", "payload"),
    [
        (
            WTTJScraper({"propagate_search_errors": True}),
            {"hits": [], "nbHits": 4, "nbPages": 1},
        ),
        (
            AdzunaScraper(
                {
                    "app_id": "id",
                    "app_key": "key",
                    "propagate_search_errors": True,
                }
            ),
            {"results": [], "count": 4},
        ),
    ],
)
def test_api_sources_reject_positive_total_with_empty_page(
    scraper: Any, payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    if isinstance(scraper, WTTJScraper):
        monkeypatch.setattr(scraper, "_fetch_algolia", lambda *_args: payload)
    else:
        monkeypatch.setattr(
            scraper, "_request_with_retry", lambda _operation: _JsonResponse(payload)
        )

    with pytest.raises(IncompleteSearchError):
        list(scraper.search(SearchCriteria(max_results=10)))


def test_freework_rejects_malformed_structured_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = FreeWorkScraper({"delay": 0, "propagate_search_errors": True})
    monkeypatch.setattr(
        scraper,
        "_fetch_page",
        lambda _url: '<script id="__NUXT_DATA__">{broken</script>',
    )

    with pytest.raises(IncompleteSearchError):
        list(scraper.search(SearchCriteria(max_results=10)))


def test_freework_rejects_internal_page_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = FreeWorkScraper(
        {
            "delay": 0,
            "page_size": 1,
            "max_pages": 1,
            "propagate_search_errors": True,
        }
    )
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: "<html></html>")
    monkeypatch.setattr(scraper, "_extract_nuxt_jobs", lambda _soup: [{}])
    monkeypatch.setattr(
        scraper, "_parse_job_card", lambda _candidate: offer("freework")
    )

    iterator = scraper.search(SearchCriteria(max_results=10))
    assert next(iterator).id == "freework_1"
    with pytest.raises(IncompleteSearchError):
        next(iterator)


def test_wttj_strict_radius_requires_geocoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = WTTJScraper({"propagate_search_errors": True})
    monkeypatch.setattr("jobscraper.scrapers.wttj.geocode", lambda _location: None)

    with pytest.raises(IncompleteSearchError):
        list(
            scraper.search(
                SearchCriteria(location="Unknown", radius_km=25, max_results=10)
            )
        )


@pytest.mark.parametrize(
    "scraper",
    [
        LinkedInScraper({"delay": 0, "propagate_search_errors": True}),
        FranceTravailScraper({"delay": 0, "propagate_search_errors": True}),
    ],
)
def test_html_sources_reject_duplicate_only_page(
    scraper: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: "<html></html>")
    monkeypatch.setattr(scraper, "_extract_job_cards", lambda _soup: [object()])
    monkeypatch.setattr(scraper, "_parse_job_card", lambda _card: offer(scraper.name))

    iterator = scraper.search(SearchCriteria(max_results=10))
    assert next(iterator).id == f"{scraper.name}_1"
    with pytest.raises(IncompleteSearchError):
        next(iterator)


def test_hellowork_aggregates_alternative_queries_and_deduplicates_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = HelloWorkScraper({"delay": 0, "propagate_search_errors": True})
    responses = iter(
        [
            hellowork_card("1") + hellowork_card("2"),
            "",
            hellowork_card("2") + hellowork_card("3"),
            "",
        ]
    )
    fetched: list[str] = []

    def fetch(url: str) -> str:
        fetched.append(url)
        return next(responses)

    monkeypatch.setattr(scraper, "_fetch_page", fetch)
    jobs = list(
        scraper.search(SearchCriteria(keywords=["react", "nextjs"], max_results=10))
    )

    assert [job.id for job in jobs] == ["hellowork_1", "hellowork_2", "hellowork_3"]
    assert ["k=react" in fetched[0], "k=nextjs" in fetched[2]] == [True, True]
    assert scraper.search_complete is True


def test_hellowork_applies_max_results_across_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = HelloWorkScraper({"delay": 0, "propagate_search_errors": True})
    monkeypatch.setattr(
        scraper,
        "_fetch_page",
        lambda _url: hellowork_card("1") + hellowork_card("2") + hellowork_card("3"),
    )

    jobs = list(
        scraper.search(SearchCriteria(keywords=["react", "nextjs"], max_results=2))
    )

    assert [job.id for job in jobs] == ["hellowork_1", "hellowork_2"]
    assert scraper.search_complete is False


def test_hellowork_rejects_duplicate_only_later_page_in_one_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = HelloWorkScraper({"delay": 0, "propagate_search_errors": True})
    responses = iter([hellowork_card("1"), hellowork_card("1")])
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: next(responses))

    iterator = scraper.search(SearchCriteria(keywords=["react"], max_results=10))
    assert next(iterator).id == "hellowork_1"
    with pytest.raises(IncompleteSearchError):
        next(iterator)


def test_linkedin_uses_full_initial_page_then_dynamic_guest_offsets_and_confirms_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails if LinkedIn truncates, skips, or trusts one transient empty page."""

    scraper = LinkedInScraper({"delay": 0, "propagate_search_errors": True})
    fetched_urls: list[str] = []
    responses = iter(
        [
            (
                '<div class="base-card" data-test-id="first"></div>'
                '<div class="base-card" data-test-id="first"></div>'
            ),
            '<div class="base-card" data-test-id="third"></div>',
            "",
            '<div class="base-card" data-test-id="fourth"></div>',
            "",
            "",
        ]
    )

    def fetch_page(url: str) -> str:
        fetched_urls.append(url)
        return next(responses)

    monkeypatch.setattr(scraper, "_fetch_page", fetch_page)
    monkeypatch.setattr(
        scraper,
        "_parse_job_card",
        lambda card: offer("linkedin", str(card["data-test-id"])),
    )

    jobs = list(
        scraper.search(
            SearchCriteria(
                keywords=["python"],
                location="Paris",
                contract_types=[ContractType.CDI],
                experience_levels=[ExperienceLevel.SENIOR],
                workplace_types=[WorkplaceType.REMOTE],
                date_posted=DatePosted.PAST_WEEK,
                max_results=10,
            )
        )
    )

    parsed_urls = [urlparse(url) for url in fetched_urls]
    assert [job.id for job in jobs] == [
        "linkedin_first",
        "linkedin_third",
        "linkedin_fourth",
    ]
    assert [url.path for url in parsed_urls] == [
        "/jobs/search",
        "/jobs-guest/jobs/api/seeMoreJobPostings/search",
        "/jobs-guest/jobs/api/seeMoreJobPostings/search",
        "/jobs-guest/jobs/api/seeMoreJobPostings/search",
        "/jobs-guest/jobs/api/seeMoreJobPostings/search",
        "/jobs-guest/jobs/api/seeMoreJobPostings/search",
    ]
    assert [parse_qs(url.query)["start"] for url in parsed_urls] == [
        ["0"],
        ["2"],
        ["3"],
        ["3"],
        ["4"],
        ["4"],
    ]
    assert parse_qs(parsed_urls[0].query)["pageNum"] == ["0"]
    assert all("pageNum" not in parse_qs(url.query) for url in parsed_urls[1:])
    assert all(parse_qs(url.query)["keywords"] == ["python"] for url in parsed_urls)
    assert all(parse_qs(url.query)["location"] == ["Paris"] for url in parsed_urls)
    assert all(parse_qs(url.query)["f_JT"] == ["F"] for url in parsed_urls)
    assert all(parse_qs(url.query)["f_E"] == ["4"] for url in parsed_urls)
    assert all(parse_qs(url.query)["f_WT"] == ["2"] for url in parsed_urls)
    assert all(parse_qs(url.query)["f_TPR"] == ["r604800"] for url in parsed_urls)
    assert scraper.search_complete is True


def test_linkedin_does_not_sleep_after_reaching_result_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails if a completed capped iteration waits before returning to its caller."""

    scraper = LinkedInScraper({"delay": 2, "propagate_search_errors": True})
    sleep_delays: list[float] = []
    monkeypatch.setattr(
        scraper,
        "_fetch_page",
        lambda _url: '<div class="base-card" data-test-id="first"></div>',
    )
    monkeypatch.setattr(
        scraper,
        "_parse_job_card",
        lambda card: offer("linkedin", str(card["data-test-id"])),
    )
    monkeypatch.setattr("jobscraper.scrapers.linkedin.time.sleep", sleep_delays.append)

    jobs = list(scraper.search(SearchCriteria(max_results=1)))

    assert [job.id for job in jobs] == ["linkedin_first"]
    assert sleep_delays == []


def test_wttj_rejects_duplicate_only_page(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = WTTJScraper({"propagate_search_errors": True})
    pages = iter(
        [
            {"hits": [{}], "nbHits": 2, "nbPages": 2},
            {"hits": [{}], "nbHits": 2, "nbPages": 2},
        ]
    )
    monkeypatch.setattr(scraper, "_fetch_algolia", lambda *_args: next(pages))
    monkeypatch.setattr(scraper, "_parse_hit", lambda _hit: offer("wttj"))

    iterator = scraper.search(SearchCriteria(max_results=10))
    assert next(iterator).id == "wttj_1"
    with pytest.raises(IncompleteSearchError):
        next(iterator)


def test_adzuna_rejects_duplicate_only_page(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = AdzunaScraper(
        {"app_id": "id", "app_key": "key", "propagate_search_errors": True}
    )
    responses = iter(
        [
            _JsonResponse({"results": [{}], "count": 100}),
            _JsonResponse({"results": [{}], "count": 100}),
        ]
    )
    monkeypatch.setattr(scraper, "_request_with_retry", lambda _op: next(responses))
    monkeypatch.setattr(scraper, "_parse_result", lambda _result: offer("adzuna"))

    iterator = scraper.search(SearchCriteria(max_results=10))
    assert next(iterator).id == "adzuna_1"
    with pytest.raises(IncompleteSearchError):
        next(iterator)


def test_freework_rejects_duplicate_only_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = FreeWorkScraper(
        {"delay": 0, "page_size": 1, "propagate_search_errors": True}
    )
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: "<html></html>")
    monkeypatch.setattr(scraper, "_extract_nuxt_jobs", lambda _soup: [{}])
    monkeypatch.setattr(
        scraper, "_parse_job_card", lambda _candidate: offer("freework")
    )

    iterator = scraper.search(SearchCriteria(max_results=10))
    assert next(iterator).id == "freework_1"
    with pytest.raises(IncompleteSearchError):
        next(iterator)


def test_base_transport_honors_timeout_and_retry_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import requests
    from tenacity import wait_none

    scraper = FreeWorkScraper({"timeout": 7, "max_retries": 2})
    timeouts: list[float] = []

    def flaky_get(_url: str, **kwargs: Any) -> _JsonResponse:
        timeouts.append(kwargs["timeout"])
        if len(timeouts) == 1:
            raise requests.Timeout("temporary")
        response = _JsonResponse({})
        response.text = "ok"  # type: ignore[attr-defined]
        return response

    monkeypatch.setattr(
        "jobscraper.scrapers.base.wait_exponential", lambda **_kwargs: wait_none()
    )
    monkeypatch.setattr("jobscraper.scrapers.base.requests.get", flaky_get)

    assert scraper._fetch_page("https://example.com") == "ok"
    assert timeouts == [7, 7]


def test_api_transports_use_configured_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, float]] = []

    def fake_post(_url: str, **kwargs: Any) -> _JsonResponse:
        observed.append(("wttj", kwargs["timeout"]))
        return _JsonResponse({"hits": [], "nbHits": 0, "nbPages": 1})

    def fake_get(_url: str, **kwargs: Any) -> _JsonResponse:
        observed.append(("adzuna", kwargs["timeout"]))
        return _JsonResponse({"results": [], "count": 0})

    wttj = WTTJScraper({"timeout": 9, "max_retries": 1})
    adzuna = AdzunaScraper(
        {"app_id": "id", "app_key": "key", "timeout": 11, "max_retries": 1}
    )
    monkeypatch.setattr("jobscraper.scrapers.wttj.requests.post", fake_post)
    monkeypatch.setattr("jobscraper.scrapers.adzuna.requests.get", fake_get)

    wttj._fetch_algolia("", "", 0)
    list(adzuna.search(SearchCriteria(max_results=10)))

    assert observed == [("wttj", 9), ("adzuna", 11)]
