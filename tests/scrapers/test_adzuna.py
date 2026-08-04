from urllib.parse import parse_qs, urlparse

import pytest
import requests
from loguru import logger

from jobscraper.models.job import ContractType, SearchCriteria
from jobscraper.scrapers.adzuna import AdzunaScraper


@pytest.fixture
def scraper() -> AdzunaScraper:
    return AdzunaScraper({"app_id": "id", "app_key": "key"})


class JsonResponse:
    def __init__(self, results: list[dict], count: int | None = None):
        self._payload = {
            "results": results,
            "count": len(results) if count is None else count,
        }

    def json(self) -> dict:
        return self._payload


def result(identifier: str) -> dict:
    return {
        "id": identifier,
        "title": f"Offer {identifier}",
        "company": {"display_name": "Acme"},
        "location": {"display_name": "Paris"},
        "redirect_url": f"https://example.com/{identifier}",
    }


def test_mixed_contracts_run_separate_queries_and_deduplicate(
    scraper: AdzunaScraper, monkeypatch: pytest.MonkeyPatch
) -> None:
    urls: list[str] = []
    responses = iter(
        [
            JsonResponse([result("shared"), result("cdd")]),
            JsonResponse([result("shared"), result("cdi")]),
        ]
    )

    def request(_operation):
        response = next(responses)
        return response

    original_build = scraper._build_search_url
    monkeypatch.setattr(
        scraper,
        "_build_search_url",
        lambda *args, **kwargs: (
            urls.append(original_build(*args, **kwargs)) or urls[-1]
        ),
    )
    monkeypatch.setattr(scraper, "_request_with_retry", request)

    jobs = list(
        scraper.search(
            SearchCriteria(
                contract_types=[ContractType.CDD, ContractType.CDI],
                max_results=10,
            )
        )
    )

    assert [job.id for job in jobs] == ["adzuna_shared", "adzuna_cdd", "adzuna_cdi"]
    queries = [parse_qs(urlparse(url).query) for url in urls]
    assert [query.get("contract") for query in queries] == [["1"], None]
    assert [query.get("permanent") for query in queries] == [None, ["1"]]
    assert scraper.search_complete is True


def test_global_limit_stops_before_next_contract_family(
    scraper: AdzunaScraper, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def request(_operation):
        nonlocal calls
        calls += 1
        return JsonResponse([result("one")], count=100)

    monkeypatch.setattr(scraper, "_request_with_retry", request)
    jobs = list(
        scraper.search(
            SearchCriteria(
                contract_types=[ContractType.CDD, ContractType.CDI],
                max_results=1,
            )
        )
    )

    assert [job.id for job in jobs] == ["adzuna_one"]
    assert calls == 1
    assert scraper.search_complete is True


def test_unsupported_contracts_complete_without_credentials_or_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    strict = AdzunaScraper({"propagate_search_errors": True})
    monkeypatch.setattr(
        strict,
        "_request_with_retry",
        lambda _operation: pytest.fail("Adzuna must not receive a broad query"),
    )

    assert (
        list(
            strict.search(
                SearchCriteria(
                    contract_types=[ContractType.STAGE, ContractType.ALTERNANCE]
                )
            )
        )
        == []
    )
    assert strict.search_complete is True


def test_http_error_logs_no_authenticated_url(
    scraper: AdzunaScraper, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = requests.HTTPError(
        "404 Client Error: Not Found for url: "
        "https://api.adzuna.com/search?app_id=secret-id&app_key=secret-key"
    )
    messages: list[str] = []
    handler_id = logger.add(
        lambda message: messages.append(str(message)), format="{message}"
    )

    def request(_operation):
        raise error

    monkeypatch.setattr(
        scraper,
        "_request_with_retry",
        request,
    )

    try:
        assert list(scraper.search(SearchCriteria(max_results=1))) == []
    finally:
        logger.remove(handler_id)

    log_output = "\n".join(messages)
    assert "secret-id" not in log_output
    assert "secret-key" not in log_output


def test_later_contract_family_failure_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strict = AdzunaScraper(
        {
            "app_id": "secret-id",
            "app_key": "secret-key",
            "max_retries": 1,
            "propagate_search_errors": True,
        }
    )
    responses = iter(
        [JsonResponse([result("cdd")]), requests.HTTPError("second family failed")]
    )

    def request(_operation):
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(strict, "_request_with_retry", request)
    iterator = strict.search(
        SearchCriteria(
            contract_types=[ContractType.CDD, ContractType.CDI],
            max_results=10,
        )
    )

    assert next(iterator).id == "adzuna_cdd"
    with pytest.raises(requests.RequestException, match="Échec de la requête Adzuna"):
        next(iterator)
    assert strict.search_complete is False


def test_debug_logs_never_contain_adzuna_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = AdzunaScraper({"app_id": "secret-id", "app_key": "secret-key"})
    monkeypatch.setattr(
        secret, "_request_with_retry", lambda _operation: JsonResponse([])
    )
    messages: list[str] = []
    handler_id = logger.add(
        lambda message: messages.append(str(message)),
        level="DEBUG",
        format="{message}",
    )
    try:
        list(secret.search(SearchCriteria(max_results=1)))
    finally:
        logger.remove(handler_id)

    combined = "".join(messages)
    assert "secret-id" not in combined
    assert "secret-key" not in combined


def test_second_contract_family_paginates_past_globally_seen_ids(
    scraper: AdzunaScraper, monkeypatch: pytest.MonkeyPatch
) -> None:
    urls: list[str] = []
    responses = iter(
        [
            JsonResponse([result("shared")]),
            JsonResponse([result("shared")], count=100),
            JsonResponse([result("cdi-page-two")], count=100),
        ]
    )

    original_build = scraper._build_search_url
    monkeypatch.setattr(
        scraper,
        "_build_search_url",
        lambda *args, **kwargs: (
            urls.append(original_build(*args, **kwargs)) or urls[-1]
        ),
    )
    monkeypatch.setattr(
        scraper, "_request_with_retry", lambda _operation: next(responses)
    )

    jobs = list(
        scraper.search(
            SearchCriteria(
                contract_types=[ContractType.CDD, ContractType.CDI],
                max_results=10,
            )
        )
    )

    assert [job.id for job in jobs] == ["adzuna_shared", "adzuna_cdi-page-two"]
    assert [urlparse(url).path.rsplit("/", 1)[-1] for url in urls] == ["1", "1", "2"]
    assert [parse_qs(urlparse(url).query).get("permanent") for url in urls] == [
        None,
        ["1"],
        ["1"],
    ]


@pytest.mark.parametrize(
    ("contracts", "expected"),
    [
        ([ContractType.CDI], ["permanent"]),
        ([ContractType.CDD], ["contract"]),
        (
            [ContractType.CDD, ContractType.INTERIM, ContractType.FREELANCE],
            ["contract"],
        ),
        (
            [ContractType.CDD, ContractType.CDI, ContractType.FREELANCE],
            ["contract", "permanent"],
        ),
        ([ContractType.STAGE, ContractType.ALTERNANCE], []),
        ([], [None]),
    ],
)
def test_contract_filter_families_preserve_supported_first_seen_order(
    scraper: AdzunaScraper,
    contracts: list[ContractType],
    expected: list[str | None],
) -> None:
    assert (
        scraper._contract_filter_families(SearchCriteria(contract_types=contracts))
        == expected
    )


@pytest.mark.parametrize(
    ("family", "expected_key"),
    [("permanent", "permanent"), ("contract", "contract")],
)
def test_build_search_url_uses_supported_contract_flag(
    scraper: AdzunaScraper, family: str, expected_key: str
) -> None:
    criteria = SearchCriteria(
        title="Développeur React & Next.js",
        contract_types=[ContractType.CDI, ContractType.CDD],
    )
    query = parse_qs(
        urlparse(
            scraper._build_search_url(criteria, 1, 50, contract_filter=family)
        ).query
    )

    assert query[expected_key] == ["1"]
    assert query["what"] == ["Développeur React & Next.js"]
    assert "contract_type" not in query
    assert "full_time" not in query
    assert not ({"permanent", "contract"} <= query.keys())
