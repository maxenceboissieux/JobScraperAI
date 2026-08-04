# Reliable HelloWork Searches Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make HelloWork return useful offers for saved searches containing a title and alternative keywords while preserving strict synchronization completeness and current card metadata.

**Architecture:** `HelloWorkScraper` derives an ordered set of independent search queries, paginates each query, and deduplicates offers globally. Existing card parsing remains in the same scraper but adds stable `data-cy` selectors for current location and contract metadata.

**Tech Stack:** Python 3.12, requests, BeautifulSoup/lxml, pytest, mypy, Black, isort.

## Global Constraints

- Treat saved-search keywords as alternatives for HelloWork, not mandatory terms in one query.
- Keep `criteria.max_results` as one global limit across every query variant.
- Deduplicate globally by HelloWork offer identifier.
- Confirm a complete search only after every required variant reaches a reliable end.
- Preserve strict-mode failures for network errors, partial parsing, and duplicate-only pagination within one variant.
- Do not change the database schema, API, frontend, inter-source deduplication, or detail loading.
- Preserve existing legacy selectors while adding current HelloWork metadata selectors.
- Do not modify `.env`, `.idea/`, `.pnpm-store/`, `jobscraper.db`, or `data/jobscraper.db`.

---

## File Structure

- `src/jobscraper/scrapers/hellowork.py`: query derivation, per-query pagination, global deduplication, and current card metadata selectors.
- `tests/scrapers/test_existing_scrapers.py`: query variant and current-card parsing contracts.
- `tests/scrapers/test_strict_search_health.py`: multi-query ordering, overlap, global limit, and incomplete-search contracts.
- `tests/fixtures/hellowork/search.html`: representative current HelloWork `data-cy` metadata markup.

### Task 1: Alternative queries and strict aggregation

**Files:**
- Modify: `src/jobscraper/scrapers/hellowork.py:70-218`
- Modify: `tests/scrapers/test_existing_scrapers.py:150-175`
- Modify: `tests/scrapers/test_strict_search_health.py:230-275`

**Interfaces:**
- Produces: `HelloWorkScraper._search_queries(criteria: SearchCriteria) -> list[str]`.
- Changes: `HelloWorkScraper._build_search_url(criteria: SearchCriteria, *, query: str | None = None) -> str`; `None` selects the first derived query for backward-compatible direct callers, while `""` intentionally omits `k`.
- Preserves: `search(criteria: SearchCriteria) -> Iterator[JobOffer]` and the `search_complete` contract used by `SyncService`.

- [ ] **Step 1: Write failing query-variant tests**

Add to `tests/scrapers/test_existing_scrapers.py`:

```python
def test_hellowork_builds_ordered_alternative_queries() -> None:
    scraper = HelloWorkScraper({"delay": 0})
    criteria = SearchCriteria(
        title="Developpeur fullstack",
        keywords=["react", "nextjs", "React", "reactjs"],
        location="France",
    )

    assert scraper._search_queries(criteria) == [
        "Developpeur fullstack",
        "Developpeur fullstack react",
        "Developpeur fullstack nextjs",
        "Developpeur fullstack reactjs",
    ]
    assert "k=Developpeur+fullstack" in scraper._build_search_url(criteria)


def test_hellowork_uses_each_keyword_without_a_title_and_supports_no_terms() -> None:
    scraper = HelloWorkScraper({"delay": 0})

    assert scraper._search_queries(SearchCriteria(keywords=["react", "nextjs"])) == [
        "react",
        "nextjs",
    ]
    assert scraper._search_queries(SearchCriteria()) == [""]
    assert "k=" not in scraper._build_search_url(SearchCriteria(), query="")
```

- [ ] **Step 2: Run the query tests and verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scrapers/test_existing_scrapers.py::test_hellowork_builds_ordered_alternative_queries \
  tests/scrapers/test_existing_scrapers.py::test_hellowork_uses_each_keyword_without_a_title_and_supports_no_terms -v
```

Expected: FAIL because `_search_queries` and the keyword-only URL override do not exist.

- [ ] **Step 3: Implement minimal query derivation**

Add ordered case-insensitive deduplication without changing visible query words:

```python
    @staticmethod
    def _search_queries(criteria: SearchCriteria) -> list[str]:
        title = (criteria.title or "").strip()
        keywords = [keyword.strip() for keyword in criteria.keywords if keyword.strip()]
        candidates = ([title] if title else []) + [
            " ".join(filter(None, [title, keyword])) for keyword in keywords
        ]
        if not candidates:
            return [""]

        queries: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = " ".join(candidate.split()).casefold()
            if normalized and normalized not in seen:
                seen.add(normalized)
                queries.append(" ".join(candidate.split()))
        return queries or [""]
```

Update `_build_search_url` so `query=None` uses `_search_queries(criteria)[0]` and an explicit empty query omits `k`. Keep location, contract, date, and radius parameters unchanged.

- [ ] **Step 4: Run query tests and verify GREEN**

Run the Step 2 command. Expected: both tests pass.

- [ ] **Step 5: Write failing aggregation tests**

Add focused tests to `tests/scrapers/test_strict_search_health.py` using small HTML cards distinguished by `data-id-storage-item-id`:

```python
def hellowork_card(identifier: str) -> str:
    return (
        f'<li data-id-storage-item-id="{identifier}">'
        f'<input name="title" value="Offer {identifier}">'
        f'<input name="company" value="Acme">'
        f'<a href="/fr-fr/emplois/{identifier}.html">Offer</a></li>'
    )


def test_hellowork_aggregates_alternative_queries_and_deduplicates_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = HelloWorkScraper({"delay": 0, "propagate_search_errors": True})
    responses = iter([
        hellowork_card("1") + hellowork_card("2"), "",
        hellowork_card("2") + hellowork_card("3"), "",
    ])
    fetched: list[str] = []

    def fetch(url: str) -> str:
        fetched.append(url)
        return next(responses)

    monkeypatch.setattr(scraper, "_fetch_page", fetch)
    jobs = list(scraper.search(SearchCriteria(keywords=["react", "nextjs"], max_results=10)))

    assert [job.id for job in jobs] == ["hellowork_1", "hellowork_2", "hellowork_3"]
    assert ["k=react" in fetched[0], "k=nextjs" in fetched[2]] == [True, True]
    assert scraper.search_complete is True
```

Add a separate global-limit test:

```python
def test_hellowork_applies_max_results_across_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = HelloWorkScraper({"delay": 0, "propagate_search_errors": True})
    monkeypatch.setattr(
        scraper,
        "_fetch_page",
        lambda _url: hellowork_card("1") + hellowork_card("2") + hellowork_card("3"),
    )

    jobs = list(scraper.search(SearchCriteria(keywords=["react", "nextjs"], max_results=2)))

    assert [job.id for job in jobs] == ["hellowork_1", "hellowork_2"]
    assert scraper.search_complete is False
```

Remove `HelloWorkScraper` from the generic `test_html_sources_reject_duplicate_only_page` parametrization and add its explicit same-query pagination contract:

```python
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
```

- [ ] **Step 6: Run aggregation tests and verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scrapers/test_strict_search_health.py -k 'hellowork' -v
```

Expected: the new tests fail because `search` still uses a single combined URL.

- [ ] **Step 7: Implement per-query pagination and global deduplication**

Refactor only `HelloWorkScraper.search`:

- loop over `_search_queries(criteria)`;
- reset `page` and `seen_ids_in_query` for each query;
- keep `seen_ids` and `jobs_found` global;
- treat an empty first page as the reliable end of that query;
- treat a later query's first page containing only globally seen identifiers as a reliable overlap boundary;
- call `_incomplete_search` when a later page contains only identifiers already seen in the same query;
- call `_mark_search_complete()` only after the outer query loop finishes;
- return immediately at `max_results` without marking complete.

Keep the existing exception boundary and strict-mode propagation. Sleep only between fetched non-terminal pages or before the next query when the configured delay is positive.

- [ ] **Step 8: Run all HelloWork and synchronization tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scrapers/test_existing_scrapers.py \
  tests/scrapers/test_strict_search_health.py \
  tests/services/test_sync.py -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit query aggregation**

```bash
git add src/jobscraper/scrapers/hellowork.py \
  tests/scrapers/test_existing_scrapers.py \
  tests/scrapers/test_strict_search_health.py
git commit -m "fix: search HelloWork keywords independently"
```

### Task 2: Current HelloWork card metadata and final validation

**Files:**
- Modify: `src/jobscraper/scrapers/hellowork.py:250-330`
- Modify: `tests/fixtures/hellowork/search.html`
- Modify: `tests/scrapers/test_existing_scrapers.py:35-105`

**Interfaces:**
- Consumes: a HelloWork result-card `Tag` with stable hidden identity fields and either legacy tag classes or current `data-cy` metadata.
- Preserves: `_parse_job_card(card: Tag) -> JobOffer | None`.

- [ ] **Step 1: Update the fixture first and verify the current test fails**

Replace the two legacy metadata elements in `tests/fixtures/hellowork/search.html` with current representative markup:

```html
<div class="readonly tag-secondary-s w-fit border-0" data-cy="localisationCard">
  Civrieux - 01
</div>
<div class="readonly tag-secondary-s w-fit border-0" data-cy="contractCard">
  CDI
</div>
```

Update the HelloWork expected location in the parametrized test to `Civrieux - 01`.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scrapers/test_existing_scrapers.py::test_html_scraper_parses_representative_card -v
```

Expected: FAIL with location `France` or missing contract because current `data-cy` elements are not selected.

- [ ] **Step 2: Implement stable current metadata selectors**

In `_parse_job_card`, prefer explicit current attributes and retain the legacy fallback:

```python
            location_elem = card.select_one('[data-cy="localisationCard"]')
            contract_elem = card.select_one('[data-cy="contractCard"]')
            location = location_elem.get_text(" ", strip=True) if location_elem else None
            contract_type = (
                self._map_contract_type(contract_elem.get_text(" ", strip=True))
                if contract_elem
                else None
            )
```

Run the existing legacy tag loop only to fill fields still missing, including salary. Do not infer contract or location from arbitrary whole-card text.

- [ ] **Step 3: Run parsing tests and verify GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/scrapers/test_existing_scrapers.py -v
```

Expected: the current-card and legacy source contracts pass.

- [ ] **Step 4: Run complete offline gates**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -m 'not live'
PYTHONPATH=src .venv/bin/python -m mypy src/jobscraper
.venv/bin/python -m black --check src/jobscraper/scrapers/hellowork.py \
  tests/scrapers/test_existing_scrapers.py tests/scrapers/test_strict_search_health.py
.venv/bin/python -m isort --check-only src/jobscraper/scrapers/hellowork.py \
  tests/scrapers/test_existing_scrapers.py tests/scrapers/test_strict_search_health.py
git diff --check
```

Expected: every command exits zero. The known FastAPI TestClient deprecation warning is external and non-blocking.

- [ ] **Step 5: Run a bounded live verification without touching SQLite**

Use the real saved-search terms directly with `max_results=10` and no service/database call:

```bash
PYTHONPATH=src .venv/bin/python -c '
from jobscraper.models.job import ContractType, SearchCriteria
from jobscraper.scrapers.hellowork import HelloWorkScraper
criteria = SearchCriteria(
    title="Developpeur fullstack",
    keywords=["react", "nextjs", "reactjs"],
    location="France",
    contract_types=[ContractType.CDD, ContractType.CDI, ContractType.FREELANCE],
    max_results=10,
)
scraper = HelloWorkScraper({"delay": 0, "propagate_search_errors": True})
jobs = list(scraper.search(criteria))
assert jobs
assert all(job.title and str(job.url).startswith("https://www.hellowork.com/") for job in jobs)
print(len(jobs), [(job.title, job.location, job.contract_type) for job in jobs[:3]])
'
```

Expected: at least one valid HelloWork offer and no database modification.

- [ ] **Step 6: Commit metadata support**

```bash
git add src/jobscraper/scrapers/hellowork.py \
  tests/fixtures/hellowork/search.html \
  tests/scrapers/test_existing_scrapers.py
git commit -m "fix: parse current HelloWork card metadata"
```
