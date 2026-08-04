# Adzuna Contract Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace invalid Adzuna contract query parameters with separate supported searches that merge and deduplicate results under one global limit.

**Architecture:** `AdzunaScraper` will translate selected application contracts into an ordered list of supported Adzuna filter families. The existing search loop will run once per family, share a global emitted-ID set and result counter, but keep a per-family seen-ID set so expected overlap between families is not mistaken for broken pagination.

**Tech Stack:** Python 3.11/3.12, requests, Pydantic models, pytest, `urllib.parse.urlencode`.

## Global Constraints

- `max_results` is a global ceiling across every Adzuna contract family.
- Never combine `permanent=1` and `contract=1` in one request.
- Never derive `full_time=1` from CDI.
- Never log a URL containing `app_id` or `app_key`.
- Stage and alternance alone complete without an unfiltered Adzuna request.
- Preserve strict incomplete-search propagation and all non-Adzuna behavior.

---

## File Structure

- Modify `src/jobscraper/scrapers/adzuna.py`: contract-family translation, encoded URL construction, multi-family pagination, global deduplication, and secret-safe logging.
- Create `tests/scrapers/test_adzuna.py`: focused URL, family orchestration, limit, deduplication, unsupported-contract, logging, and failure regressions.
- Reuse `tests/scrapers/test_strict_search_health.py`: run existing Adzuna completeness contracts unchanged as regression coverage.

### Task 1: Supported Contract Family Translation and URL Encoding

**Files:**
- Create: `tests/scrapers/test_adzuna.py`
- Modify: `src/jobscraper/scrapers/adzuna.py:1-48,176-246`

**Interfaces:**
- Consumes: `SearchCriteria.contract_types: list[ContractType]`.
- Produces: `AdzunaScraper._contract_filter_families(criteria: SearchCriteria) -> list[str | None]` and `AdzunaScraper._build_search_url(criteria, page, results_per_page, contract_filter=None) -> str`.

- [ ] **Step 1: Write failing family and URL tests**

```python
from urllib.parse import parse_qs, urlparse

import pytest

from jobscraper.models.job import ContractType, SearchCriteria
from jobscraper.scrapers.adzuna import AdzunaScraper


@pytest.fixture
def scraper() -> AdzunaScraper:
    return AdzunaScraper({"app_id": "id", "app_key": "key"})


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
    assert scraper._contract_filter_families(
        SearchCriteria(contract_types=contracts)
    ) == expected


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
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/scrapers/test_adzuna.py -v`

Expected: FAIL because `_contract_filter_families` and the `contract_filter` argument do not exist, and the old URL contains `contract_type`/`full_time`.

- [ ] **Step 3: Implement the minimal translation and encoded URL**

In `src/jobscraper/scrapers/adzuna.py`, import `urlencode`, replace the value mapping with a family mapping, and add:

```python
from urllib.parse import urlencode

CONTRACT_FILTER_MAPPING = {
    ContractType.CDI: "permanent",
    ContractType.CDD: "contract",
    ContractType.INTERIM: "contract",
    ContractType.FREELANCE: "contract",
}

def _contract_filter_families(
    self, criteria: SearchCriteria
) -> list[str | None]:
    if not criteria.contract_types:
        return [None]

    families: list[str | None] = []
    for contract_type in criteria.contract_types:
        family = self.CONTRACT_FILTER_MAPPING.get(contract_type)
        if family is not None and family not in families:
            families.append(family)
    return families
```

Extend `_build_search_url` with `contract_filter: str | None = None`, remove the old `contract_type` and `full_time` blocks, add only a validated family flag, and encode all parameters:

```python
if contract_filter in {"permanent", "contract"}:
    params[contract_filter] = 1

return f"{base}?{urlencode(params)}"
```

- [ ] **Step 4: Run the focused tests and confirm GREEN**

Run: `.venv/bin/python -m pytest tests/scrapers/test_adzuna.py -v`

Expected: all Task 1 tests PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/jobscraper/scrapers/adzuna.py tests/scrapers/test_adzuna.py
git commit -m "fix: use supported Adzuna contract filters"
```

### Task 2: Multi-Family Search, Global Limit, and Deduplication

**Files:**
- Modify: `tests/scrapers/test_adzuna.py`
- Modify: `src/jobscraper/scrapers/adzuna.py:68-166`

**Interfaces:**
- Consumes: `_contract_filter_families()` and `_build_search_url(..., contract_filter=...)` from Task 1.
- Produces: `search(criteria)` that iterates all supported families, emits at most `criteria.max_results`, and marks complete only after a complete scan or the global cap.

- [ ] **Step 1: Write failing orchestration tests**

Add a response helper and deterministic offers to `tests/scrapers/test_adzuna.py`:

```python
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
        [JsonResponse([result("shared"), result("cdd")]),
         JsonResponse([result("shared"), result("cdi")])]
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

    assert [job.id for job in jobs] == [
        "adzuna_shared", "adzuna_cdd", "adzuna_cdi"
    ]
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


def test_unsupported_contracts_complete_without_request(
    scraper: AdzunaScraper, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        scraper,
        "_request_with_retry",
        lambda _operation: pytest.fail("Adzuna must not receive a broad query"),
    )

    assert list(
        scraper.search(
            SearchCriteria(
                contract_types=[ContractType.STAGE, ContractType.ALTERNANCE]
            )
        )
    ) == []
    assert scraper.search_complete is True
```

- [ ] **Step 2: Run orchestration tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/scrapers/test_adzuna.py -v`

Expected: mixed-family assertions FAIL because the current search loop issues only one query.

- [ ] **Step 3: Refactor `search` into a family-aware outer loop**

At the start of `search`, obtain `families = self._contract_filter_families(criteria)`. If it is empty, mark the search complete and return. Keep `jobs_found` and `seen_ids` outside the family loop. For each family, reset `page = 1` and `family_seen_ids: set[str] = set()`, then call:

```python
url = self._build_search_url(
    criteria,
    page,
    results_per_page,
    contract_filter=contract_filter,
)
logger.debug(
    "Requête Adzuna: page={}, filtre_contrat={}",
    page,
    contract_filter or "aucun",
)
```

When parsing a page, count an ID as new for pagination when it is absent from `family_seen_ids`; add it to that set before checking global `seen_ids`. Only globally unseen IDs increment `jobs_found` and are yielded. Preserve the existing partial-page, count, empty-page, exception, and strict-mode checks. Break only the current family when its authoritative last page is reached. After every family finishes, or immediately when `max_results` is reached, call `_mark_search_complete()`.

- [ ] **Step 4: Run focused and existing strict Adzuna tests**

Run: `.venv/bin/python -m pytest tests/scrapers/test_adzuna.py tests/scrapers/test_strict_search_health.py -v`

Expected: all tests PASS, including duplicate-only and partial-page regressions.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/jobscraper/scrapers/adzuna.py tests/scrapers/test_adzuna.py
git commit -m "fix: merge Adzuna contract searches"
```

### Task 3: Failure Propagation, Secret-Safe Logging, and Full Verification

**Files:**
- Modify: `tests/scrapers/test_adzuna.py`
- Modify if required: `src/jobscraper/scrapers/adzuna.py`

**Interfaces:**
- Consumes: final family-aware `search` from Task 2.
- Produces: regression evidence that later-family failures propagate and credentials never enter debug messages.

- [ ] **Step 1: Add failure and log-safety tests**

```python
import requests
from loguru import logger


def test_later_contract_family_failure_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strict = AdzunaScraper(
        {"app_id": "secret-id", "app_key": "secret-key", "max_retries": 1,
         "propagate_search_errors": True}
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
    with pytest.raises(requests.HTTPError, match="second family failed"):
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
    sink = logger.add(messages.append, level="DEBUG", format="{message}")
    try:
        list(secret.search(SearchCriteria(max_results=1)))
    finally:
        logger.remove(sink)

    combined = "".join(messages)
    assert "secret-id" not in combined
    assert "secret-key" not in combined
```

- [ ] **Step 2: Run new tests and confirm their result**

Run: `.venv/bin/python -m pytest tests/scrapers/test_adzuna.py -v`

Expected before any final adjustment: tests PASS if Tasks 1-2 fully implemented the design; otherwise the specific failure identifies the missing behavior.

- [ ] **Step 3: Apply only the minimal correction required by failing tests**

If the later-family failure test shows `search_complete=True`, ensure `_mark_search_complete()` is called only after all families or the global cap. If the log test exposes credentials, replace every full-URL debug statement with the page/family structured message shown in Task 2. Do not change shared retry policy or unrelated scrapers.

- [ ] **Step 4: Run formatting and targeted verification**

Run: `.venv/bin/python -m black --check src/jobscraper/scrapers/adzuna.py tests/scrapers/test_adzuna.py`

Run: `.venv/bin/python -m pytest tests/scrapers/test_adzuna.py tests/scrapers/test_existing_scrapers.py tests/scrapers/test_strict_search_health.py -v`

Expected: formatting check succeeds and all targeted tests PASS.

- [ ] **Step 5: Run the complete offline suite**

Run: `.venv/bin/python -m pytest -m 'not live'`

Expected: the full offline suite PASS with live tests deselected.

- [ ] **Step 6: Commit final regression coverage**

```bash
git add src/jobscraper/scrapers/adzuna.py tests/scrapers/test_adzuna.py
git commit -m "test: cover Adzuna contract search failures"
```

- [ ] **Step 7: Inspect repository state before integration**

Run: `git status --short --branch`

Expected: only the user's pre-existing untracked local files remain; no implementation file is unstaged.
