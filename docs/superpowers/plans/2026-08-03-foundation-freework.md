# Python Foundation and Free-Work Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing Python package reproducible and regression-tested, then add Free-Work as a first-class CLI source with fixture-based and opt-in live verification.

**Architecture:** Keep `BaseScraper.search()` and `get_job_details()` as the source contract. Add small shared parsing helpers only where two or more scrapers use them; Free-Work owns its URL mapping and HTML/structured-data parsing.

**Tech Stack:** Python 3.11 or 3.12, Pydantic 2, Requests, BeautifulSoup/lxml, pytest, pytest-cov, responses.

## Global Constraints

- Preserve all five existing sources; Free-Work is a sixth source.
- Automated tests must not require network access.
- Live smoke tests are explicit, bounded to three results, and skipped by default.
- User-facing copy remains French.
- Do not commit `.venv`, `__pycache__`, `.pytest_cache`, coverage output, `.superpowers`, or local databases.

---

### Task 1: Reproducible test environment and package baseline

**Files:**
- Create: `.gitignore`
- Modify: `pyproject.toml`
- Create: `tests/test_package.py`

**Interfaces:**
- Consumes: existing `jobscraper.__version__`, `JobOffer`, and `SearchCriteria`.
- Produces: `python -m pytest` as the canonical backend test command and a `live` pytest marker.

- [ ] **Step 1: Write the failing package smoke test**

```python
from jobscraper import JobOffer, SearchCriteria, __version__


def test_package_exports_are_importable() -> None:
    assert __version__ == "1.0.0"
    assert JobOffer.__name__ == "JobOffer"
    assert SearchCriteria(location="France").location == "France"
```

- [ ] **Step 2: Verify the unprovisioned baseline fails**

Run: `python3.12 -m pytest tests/test_package.py -v`

Expected before environment setup: failure because pytest or project dependencies are unavailable.

- [ ] **Step 3: Declare development dependencies and ignored artifacts**

Add `pytest-cov>=5.0`, `responses>=0.25`, and the marker below to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = ["live: opt-in tests that contact public job sites"]
addopts = "--strict-markers"
```

Create `.gitignore` with `.venv/`, `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.coverage`, `htmlcov/`, `data/*.db`, `frontend/node_modules/`, `frontend/dist/`, and `.superpowers/`.

- [ ] **Step 4: Create and provision the virtual environment**

Run: `/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3.12 -m venv .venv`

Run: `.venv/bin/python -m pip install -U pip`

Run: `.venv/bin/python -m pip install -e '.[dev]'`

- [ ] **Step 5: Verify the package baseline passes**

Run: `.venv/bin/python -m pytest tests/test_package.py -v`

Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add .gitignore pyproject.toml tests/test_package.py
git commit -m "test: establish reproducible Python baseline"
```

### Task 2: Fixture regression contract for existing scrapers

**Files:**
- Create: `tests/fixtures/linkedin/search.html`
- Create: `tests/fixtures/hellowork/search.html`
- Create: `tests/fixtures/francetravail/search.html`
- Create: `tests/fixtures/wttj/search.json`
- Create: `tests/fixtures/adzuna/search.json`
- Create: `tests/scrapers/test_existing_scrapers.py`
- Modify: `src/jobscraper/scrapers/linkedin.py`
- Modify: `src/jobscraper/scrapers/hellowork.py`
- Modify: `src/jobscraper/scrapers/francetravail.py`
- Modify: `src/jobscraper/scrapers/wttj.py`
- Modify: `src/jobscraper/scrapers/adzuna.py`

**Interfaces:**
- Consumes: each scraper's private parser and `SearchCriteria` URL builder.
- Produces: one stable, network-free representative contract per existing source.

- [ ] **Step 1: Save minimal sanitized fixtures**

Each fixture contains exactly one realistic offer with ID, URL, title, company, location, contract and publication date. JSON fixtures retain only fields read by the parser.

- [ ] **Step 2: Write parameterized regression tests**

```python
@pytest.mark.parametrize(
    ("scraper", "fixture", "expected_source"),
    [
        (LinkedInScraper(), "linkedin/search.html", "linkedin"),
        (HelloWorkScraper({"delay": 0}), "hellowork/search.html", "hellowork"),
        (FranceTravailScraper({"delay": 0}), "francetravail/search.html", "francetravail"),
    ],
)
def test_html_scraper_parses_representative_card(scraper, fixture, expected_source, load_fixture):
    soup = BeautifulSoup(load_fixture(fixture), "lxml")
    cards = scraper._extract_job_cards(soup)
    job = scraper._parse_job_card(cards[0])
    assert job is not None
    assert job.source == expected_source
    assert job.id.startswith(f"{expected_source}_")
    assert str(job.url).startswith("https://")
```

Add source-specific assertions for WTTJ `_parse_hit()` and Adzuna `_parse_result()`.

- [ ] **Step 3: Run tests and record every failure without editing code**

Run: `.venv/bin/python -m pytest tests/scrapers/test_existing_scrapers.py -v`

Expected: the run produces one explicit pass/fail result per source. Preserve every failure as a regression test and trace its selector or field to the fixture before changing implementation.

- [ ] **Step 4: Make the smallest source-specific corrections**

Keep fallback selectors scoped inside the affected scraper. Do not refactor unrelated scraper logic. Preserve the `Iterator[JobOffer]` and `Optional[JobOffer]` public signatures.

- [ ] **Step 5: Verify regressions**

Run: `.venv/bin/python -m pytest tests/scrapers/test_existing_scrapers.py -v`

Expected: all representative source contracts pass.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures tests/scrapers src/jobscraper/scrapers
git commit -m "test: cover existing scraper contracts"
```

### Task 3: Free-Work search URL, pagination, and cards

**Files:**
- Create: `src/jobscraper/scrapers/freework.py`
- Create: `tests/fixtures/freework/search.html`
- Create: `tests/fixtures/freework/search-page-2.html`
- Create: `tests/scrapers/test_freework.py`

**Interfaces:**
- Consumes: `BaseScraper`, `SearchCriteria`, `JobOffer`, `ContractType`, `DatePosted`.
- Produces: `FreeWorkScraper.search(criteria) -> Iterator[JobOffer]`, `_build_search_url(criteria, page: int = 1) -> str`, `_parse_job_card(card) -> Optional[JobOffer]`, and `_matches_criteria(job, criteria) -> bool`.

- [ ] **Step 1: Write failing URL-mapping tests**

```python
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
```

- [ ] **Step 2: Run the focused test to verify failure**

Run: `.venv/bin/python -m pytest tests/scrapers/test_freework.py::test_build_search_url_maps_keywords_location_and_contract -v`

Expected: FAIL because `FreeWorkScraper` does not exist.

- [ ] **Step 3: Implement the scraper shell and URL mapping**

```python
class FreeWorkScraper(BaseScraper):
    name = "freework"
    base_url = "https://www.free-work.com"

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)
        self.delay_between_requests = float(self.config.get("delay", 2))

    def _build_search_url(self, criteria: SearchCriteria, page: int = 1) -> str:
        path = "/fr/tech-it/jobs"
        if criteria.location and criteria.location.casefold() != "france":
            path += f"/{slugify(criteria.location)}"
        query = " ".join(filter(None, [criteria.title, *criteria.keywords]))
        params = {"query": query} if query else {}
        if page > 1:
            params["page"] = str(page)
        suffix = f"?{urlencode(params)}" if params else ""
        return f"{self.base_url}{path}{suffix}"
```

The public page inspected on 2026-08-03 uses `/fr/tech-it/jobs`, optional location slugs such as `/paris`, `query` for text, and `page` for pagination. Apply contract, date and radius criteria after parsing through `_matches_criteria()` rather than inventing unsupported URL keys.

- [ ] **Step 4: Write failing fixture parsing and pagination tests**

```python
def test_parse_search_fixture(load_fixture) -> None:
    scraper = FreeWorkScraper({"delay": 0})
    soup = BeautifulSoup(load_fixture("freework/search.html"), "lxml")
    cards = scraper._extract_job_cards(soup)
    job = scraper._parse_job_card(cards[0])
    assert job == JobOffer(
        id="freework_12345",
        source="freework",
        url="https://www.free-work.com/fr/tech-it/developpeur-python/job-mission/12345",
        title="Développeur Python",
        company="Exemple Conseil",
        location="Paris",
        contract_type=ContractType.FREELANCE,
        posted_at=job.posted_at,
    )
```

Mock `_fetch_page()` with the two page fixtures and assert `search()` stops at `max_results`, never emits the same source ID twice, and requests page 2 only when page 1 is full.

- [ ] **Step 5: Implement structured-data-first parsing with HTML fallback**

Add focused helpers `_extract_nuxt_jobs(soup)`, `_extract_json_ld_jobs(soup)`, `_extract_job_cards(soup)`, `_parse_job_card(card)`, `_parse_posted_date(value)`, `_map_contract_type(value)`, and `_matches_criteria(job, criteria)`. Prefer the Nuxt payload already rendered into the public HTML, then JSON-LD, then cards. Required fields are source ID, absolute URL and title; company/location fall back to `"Non spécifié"`/`"France"`.

- [ ] **Step 6: Run Free-Work tests**

Run: `.venv/bin/python -m pytest tests/scrapers/test_freework.py -v`

Expected: all URL, parsing, pagination and deduplication tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/jobscraper/scrapers/freework.py tests/fixtures/freework tests/scrapers/test_freework.py
git commit -m "feat: add Free-Work search scraper"
```

### Task 4: Free-Work details and CLI registration

**Files:**
- Modify: `src/jobscraper/scrapers/freework.py`
- Modify: `src/jobscraper/scrapers/__init__.py`
- Modify: `src/jobscraper/config.py`
- Modify: `src/jobscraper/cli.py`
- Create: `tests/fixtures/freework/details.html`
- Modify: `tests/scrapers/test_freework.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: `FreeWorkScraper` from Task 3 and existing Click CLI.
- Produces: `get_job_details(job_id: str) -> Optional[JobOffer]`, `Config.freework`, and `jobscraper search -s freework`.

- [ ] **Step 1: Write failing detail and CLI tests**

```python
def test_get_job_details_parses_description_salary_and_skills(load_fixture, monkeypatch):
    scraper = FreeWorkScraper({"delay": 0})
    monkeypatch.setattr(scraper, "_fetch_page", lambda _: load_fixture("freework/details.html"))
    job = scraper.get_job_details("freework_12345")
    assert job is not None
    assert "Python" in job.description
    assert job.salary_min == 500.0
    assert "Django" in job.skills


def test_cli_accepts_freework_source(runner):
    result = runner.invoke(main, ["search", "-k", "python", "-s", "freework", "-n", "1"])
    assert "Invalid value for '--source'" not in result.output
```

- [ ] **Step 2: Verify both tests fail**

Run: `.venv/bin/python -m pytest tests/scrapers/test_freework.py tests/test_cli.py -v`

Expected: details are absent and Click rejects `freework`.

- [ ] **Step 3: Implement detail parsing and configuration**

Parse JSON-LD `JobPosting` first, then HTML fallbacks for description, company, location, employment type, salary, skills and benefits. Add `FreeWorkConfig`, `Config.freework`, `FREEWORK_ENABLED`, and `FREEWORK_DELAY` environment mappings.

- [ ] **Step 4: Register Free-Work in exports and CLI**

Add `freework` to the Click choice, default/all source sets, `sources()` table, and CLI execution branch. The registry refactor is intentionally deferred to the aggregation/API plan, where both CLI and API consume it.

- [ ] **Step 5: Verify focused and full backend tests**

Run: `.venv/bin/python -m pytest tests/scrapers/test_freework.py tests/test_cli.py -v`

Run: `.venv/bin/python -m pytest -v`

Expected: all tests pass without network access.

- [ ] **Step 6: Commit**

```bash
git add src/jobscraper tests pyproject.toml
git commit -m "feat: expose Free-Work through CLI"
```

### Task 5: Opt-in live smoke tests and operator documentation

**Files:**
- Create: `tests/live/test_sources_live.py`
- Modify: `README.md`
- Create: `.env.example`

**Interfaces:**
- Consumes: scraper classes and `SearchCriteria`.
- Produces: `RUN_LIVE_SCRAPER_TESTS=1 pytest -m live` with at most three results per source.

- [ ] **Step 1: Write skipped-by-default live tests**

```python
RUN_LIVE = os.getenv("RUN_LIVE_SCRAPER_TESTS") == "1"


@pytest.mark.live
@pytest.mark.skipif(not RUN_LIVE, reason="set RUN_LIVE_SCRAPER_TESTS=1")
@pytest.mark.parametrize("scraper_cls", [FreeWorkScraper, HelloWorkScraper, FranceTravailScraper])
def test_public_source_returns_valid_offer(scraper_cls):
    jobs = list(scraper_cls({"delay": 1}).search(SearchCriteria(keywords=["python"], max_results=3)))
    assert jobs
    assert all(job.title and str(job.url).startswith("https://") for job in jobs)
```

- [ ] **Step 2: Verify ordinary tests do not contact the network**

Run: `.venv/bin/python -m pytest -m 'not live' -v`

Expected: all tests pass and live tests are deselected or skipped.

- [ ] **Step 3: Run the bounded Free-Work live smoke test**

Run: `RUN_LIVE_SCRAPER_TESTS=1 .venv/bin/python -m pytest tests/live/test_sources_live.py -k FreeWork -v`

Expected: one to three valid offers, or a documented source-specific block with HTTP status and response evidence before any parser change.

- [ ] **Step 4: Document setup and smoke-test commands**

Update README installation to Python 3.11/3.12, `.venv`, editable dev install, ordinary tests, live tests, Free-Work configuration and CLI examples.

- [ ] **Step 5: Commit**

```bash
git add tests/live README.md .env.example
git commit -m "docs: document scraper verification workflow"
```

### Task 6: Phase verification

**Files:**
- Verify only.

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: a tested six-source Python package ready for persistence/API work.

- [ ] **Step 1: Run quality gates**

Run: `.venv/bin/python -m pytest -m 'not live' --cov=jobscraper --cov-report=term-missing`

Run: `.venv/bin/python -m mypy src/jobscraper`

Run: `.venv/bin/python -m compileall -q src main.py`

Expected: tests pass, mypy reports no new errors, compilation exits zero.

- [ ] **Step 2: Run CLI smoke commands**

Run: `.venv/bin/jobscraper --help`

Run: `.venv/bin/jobscraper sources`

Expected: commands exit zero and Free-Work appears as active.

- [ ] **Step 3: Record phase result**

Run: `git status --short`

Expected: no tracked changes remain; ignored local environment artifacts may exist.
