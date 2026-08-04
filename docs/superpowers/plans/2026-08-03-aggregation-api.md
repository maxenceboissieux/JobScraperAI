# SQLite Aggregation and FastAPI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist saved searches and normalized offers, classify cross-source duplicates, orchestrate resilient syncs, cache details, and expose the complete local API.

**Architecture:** SQLAlchemy 2 repositories own SQLite access; pure services own normalization and deduplication; a sync service coordinates scraper adapters; FastAPI routes translate HTTP schemas to service calls. Scraping never runs in a request handler's event loop.

**Tech Stack:** Python 3.11/3.12, FastAPI, Uvicorn, SQLAlchemy 2, Alembic, Pydantic 2, pytest, HTTPX.

## Global Constraints

- SQLite is the only database for the local version.
- Existing offers remain readable when a source fails.
- Exact duplicates merge; uncertain near-matches remain separate with reciprocal links.
- Missing publication dates are excluded from 24 h, 3 day and 7 day filters.
- Details are loaded lazily, cached locally, and served stale when refresh fails.
- API and validation errors use French user-facing messages.

---

### Task 1: Database engine, schema, and first migration

**Files:**
- Modify: `pyproject.toml`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/0001_initial.py`
- Create: `src/jobscraper/db/base.py`
- Create: `src/jobscraper/db/models.py`
- Create: `src/jobscraper/db/session.py`
- Create: `tests/db/test_schema.py`

**Interfaces:**
- Produces: `create_engine_and_session(database_url: str) -> tuple[Engine, sessionmaker[Session]]`; ORM entities `SavedSearch`, `CanonicalJob`, `SourceListing`, `SearchListing`, `DuplicateRelation`, `SyncRun`, `SourceSyncResult`.

- [ ] **Step 1: Add FastAPI/database test dependencies**

Add `fastapi>=0.116`, `uvicorn[standard]>=0.35`, `sqlalchemy>=2.0`, `alembic>=1.16`, `httpx>=0.28`, and `anyio>=4.0` to the appropriate project dependency groups.

- [ ] **Step 2: Write the failing schema test**

```python
def test_initial_schema_has_expected_tables(tmp_path):
    engine, _ = create_engine_and_session(f"sqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(engine)
    assert set(inspect(engine).get_table_names()) == {
        "saved_searches", "canonical_jobs", "source_listings", "search_listings",
        "duplicate_relations", "sync_runs", "source_sync_results",
    }
```

- [ ] **Step 3: Verify failure**

Run: `.venv/bin/python -m pytest tests/db/test_schema.py -v`

Expected: FAIL because database modules do not exist.

- [ ] **Step 4: Implement focused ORM entities**

Use UUID strings for public IDs, integer primary keys internally, timezone-aware UTC timestamps, JSON columns for list-valued search filters, unique `(source, external_id)` on listings, unique `(left_job_id, right_job_id)` on duplicate relations, and indexed `posted_at`, `active`, `last_seen_at` fields.

- [ ] **Step 5: Generate and inspect migration**

Run: `.venv/bin/alembic revision --autogenerate -m 'initial schema'`

Ensure `0001_initial.py` creates exactly the seven tested tables and constraints; remove backend-specific generated noise.

- [ ] **Step 6: Verify schema and migration**

Run: `.venv/bin/python -m pytest tests/db/test_schema.py -v`

Run: `JOBSCRAPER_DATABASE_URL=sqlite:////tmp/jobscraper-plan.db .venv/bin/alembic upgrade head`

Expected: schema test passes and migration exits zero.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml alembic.ini alembic src/jobscraper/db tests/db
git commit -m "feat: add SQLite persistence schema"
```

### Task 2: Saved-search and offer repositories

**Files:**
- Create: `src/jobscraper/repositories/saved_searches.py`
- Create: `src/jobscraper/repositories/jobs.py`
- Create: `src/jobscraper/repositories/sync_runs.py`
- Create: `tests/repositories/test_saved_searches.py`
- Create: `tests/repositories/test_jobs.py`

**Interfaces:**
- Produces: `SavedSearchRepository.create/update/list/get`; `JobRepository.upsert_listing`, `attach_search`, `list_jobs`, `get_job`; `SyncRunRepository.start`, `record_source_result`, `finish`.

- [ ] **Step 1: Write failing saved-search CRUD tests**

```python
created = repo.create(name="Backend remote", criteria=SearchCriteria(keywords=["backend"]), sources=["freework"])
assert repo.get(created.id).name == "Backend remote"
repo.update(created.id, active=False)
assert repo.list(active=False)[0].id == created.id
```

- [ ] **Step 2: Write failing idempotent listing tests**

```python
first = jobs.upsert_listing(job_offer, seen_at=NOW)
second = jobs.upsert_listing(job_offer.model_copy(update={"title": "Titre corrigé"}), seen_at=LATER)
assert first.id == second.id
assert jobs.get_listing(first.id).title == "Titre corrigé"
```

- [ ] **Step 3: Run focused tests**

Run: `.venv/bin/python -m pytest tests/repositories -v`

Expected: FAIL because repositories do not exist.

- [ ] **Step 4: Implement repositories with transaction boundaries**

Construct each repository with `Session`; methods flush but do not silently swallow exceptions. `list_jobs` accepts `saved_search_id`, `posted_since`, `query`, `locations`, `contracts`, `remote`, `experience`, `salary_min`, `companies`, `sources`, `skills`, `duplicate_state`, `sort`, `limit`, and `offset`.

- [ ] **Step 5: Verify repository behavior**

Run: `.venv/bin/python -m pytest tests/repositories -v`

Expected: CRUD, idempotency, search association and pagination tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/jobscraper/repositories tests/repositories
git commit -m "feat: add job aggregation repositories"
```

### Task 3: Normalization and duplicate classification

**Files:**
- Create: `src/jobscraper/services/normalization.py`
- Create: `src/jobscraper/services/deduplication.py`
- Create: `tests/services/test_normalization.py`
- Create: `tests/services/test_deduplication.py`

**Interfaces:**
- Produces: `normalize_text(value: str) -> str`, `normalize_title`, `normalize_company`, `normalize_location`; `DuplicateDecision(kind: Literal['confirmed','possible','none'], score: float, reasons: tuple[str, ...])`; `classify_duplicate(left, right) -> DuplicateDecision`.

- [ ] **Step 1: Write failing normalization cases**

```python
@pytest.mark.parametrize(("value", "expected"), [
    ("Développeur Python H/F", "developpeur python"),
    ("  ACME S.A.S. ", "acme"),
    ("Paris (75)", "paris"),
])
def test_normalization(value, expected):
    assert normalize_text(value) == expected
```

- [ ] **Step 2: Write the three duplicate outcomes**

```python
assert classify_duplicate(EXACT_LEFT, EXACT_RIGHT).kind == "confirmed"
assert classify_duplicate(CLOSE_LEFT, CLOSE_RIGHT).kind == "possible"
assert classify_duplicate(DIFFERENT_LOCATION_LEFT, DIFFERENT_LOCATION_RIGHT).kind == "none"
```

Exact matching requires identical normalized company and location plus a title score at or above `0.92`. Possible matching requires identical company, compatible location, and title score from `0.78` through `0.9199`. Different explicit cities or incompatible seniority force `none`.

- [ ] **Step 3: Verify tests fail**

Run: `.venv/bin/python -m pytest tests/services/test_normalization.py tests/services/test_deduplication.py -v`

- [ ] **Step 4: Implement pure deterministic services**

Use `unicodedata`, regex token cleanup and `difflib.SequenceMatcher`; do not add machine-learning or external fuzzy-search dependencies. Always order duplicate pair IDs before persistence so relations are reciprocal without duplicate rows.

- [ ] **Step 5: Verify boundary values**

Run: `.venv/bin/python -m pytest tests/services/test_normalization.py tests/services/test_deduplication.py -v`

Expected: confirmed/possible/none cases and threshold boundaries pass.

- [ ] **Step 6: Commit**

```bash
git add src/jobscraper/services tests/services
git commit -m "feat: classify cross-source duplicates"
```

### Task 4: Resilient synchronization orchestration

**Files:**
- Create: `src/jobscraper/scrapers/registry.py`
- Create: `src/jobscraper/services/sync.py`
- Create: `tests/services/test_sync.py`

**Interfaces:**
- Produces: `ScraperRegistry.create(source: str) -> BaseScraper`; `SyncService.create_run(saved_search_id: str, only_sources: set[str] | None = None) -> str`; `SyncService.execute(run_id: str) -> None`; `SyncService.run(saved_search_id: str, only_sources: set[str] | None = None) -> str` as the synchronous CLI convenience; statuses `pending/running/succeeded/partial/failed`.

- [x] **Step 1: Write a failing mixed-success orchestration test**

```python
run_id = service.run(saved_search.id)
run = sync_runs.get(run_id)
assert run.status == "partial"
assert run.results["freework"].status == "succeeded"
assert run.results["linkedin"].status == "failed"
assert jobs.count() == 1
```

The fake Free-Work scraper yields one job; the fake LinkedIn scraper raises `requests.Timeout`.

- [x] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/services/test_sync.py -v`

- [x] **Step 3: Implement registry and sync service**

`create_run()` persists the pending run and its requested sources. `execute()` changes it to running and, for each source, records running state, iterates offers, upserts, attaches the saved search, evaluates same-company candidates for duplicates, records the source result, and closes the scraper in `finally`. `run()` calls both methods synchronously. Catch errors at the source boundary and store a sanitized French summary plus full local log context.

- [x] **Step 4: Add source-only retry and inactive listing tests**

Assert `only_sources={"linkedin"}` does not call other adapters. Assert a successful complete sync updates `last_seen_at`; only a later successful source scan may mark unseen listings inactive.

- [x] **Step 5: Verify sync tests**

Run: `.venv/bin/python -m pytest tests/services/test_sync.py -v`

Expected: success, partial failure, retry and safe-inactivation tests pass.

- [x] **Step 6: Commit**

```bash
git add src/jobscraper/scrapers/registry.py src/jobscraper/services/sync.py tests/services/test_sync.py
git commit -m "feat: orchestrate resilient source synchronization"
```

### Task 5: Lazy detail cache with stale fallback

**Files:**
- Create: `src/jobscraper/services/details.py`
- Create: `tests/services/test_details.py`

**Interfaces:**
- Produces: `JobDetailsService.get(canonical_job_id: str, max_age: timedelta = timedelta(days=1)) -> JobDetailsResult`; result fields `job`, `cache_state: Literal['fresh','refreshed','stale']`, `updated_at`, `warning`.

- [x] **Step 1: Write cache-state tests**

```python
assert service.get(job.id).cache_state == "refreshed"
assert service.get(job.id).cache_state == "fresh"
clock.advance(days=2)
scraper.fail_with(TimeoutError())
result = service.get(job.id)
assert result.cache_state == "stale"
assert result.job.description == "Description conservée"
```

- [x] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/services/test_details.py -v`

- [x] **Step 3: Implement best-source selection and cache persistence**

Prefer an active listing with a known detail parser; otherwise use the newest active source listing. Persist description, salary, skills, benefits and `details_fetched_at`. Never erase cached fields when refresh returns partial data.

- [x] **Step 4: Verify detail cache tests**

Run: `.venv/bin/python -m pytest tests/services/test_details.py -v`

Expected: refreshed, fresh and stale fallback paths pass.

- [x] **Step 5: Commit**

```bash
git add src/jobscraper/services/details.py tests/services/test_details.py
git commit -m "feat: cache job details lazily"
```

### Task 6: FastAPI schemas, routes, and background sync execution

**Files:**
- Create: `src/jobscraper/api/app.py`
- Create: `src/jobscraper/api/dependencies.py`
- Create: `src/jobscraper/api/schemas.py`
- Create: `src/jobscraper/api/routes/searches.py`
- Create: `src/jobscraper/api/routes/jobs.py`
- Create: `src/jobscraper/api/routes/syncs.py`
- Create: `tests/api/test_searches.py`
- Create: `tests/api/test_jobs.py`
- Create: `tests/api/test_syncs.py`

**Interfaces:**
- Produces: `create_app(database_url: str | None = None) -> FastAPI`; endpoints `GET/POST/PATCH /api/searches`, `GET /api/jobs`, `GET /api/jobs/{id}`, `POST /api/syncs`, `POST /api/syncs/{id}/retry`, `GET /api/syncs/{id}`, `GET /api/syncs/latest`.

- [ ] **Step 1: Write failing API contract tests**

```python
response = client.post("/api/searches", json={
    "name": "Backend remote", "keywords": ["backend"], "location": "France",
    "sources": ["freework", "linkedin"], "active": True,
})
assert response.status_code == 201
assert response.json()["name"] == "Backend remote"

response = client.get("/api/jobs", params={"period": "3d", "source": "freework"})
assert response.status_code == 200
assert set(response.json()) == {"items", "total", "limit", "offset"}
```

- [ ] **Step 2: Verify routes are absent**

Run: `.venv/bin/python -m pytest tests/api -v`

Expected: FAIL because `create_app` and routes do not exist.

- [ ] **Step 3: Implement schemas and CRUD/list/detail routes**

Map `period=24h|3d|7d|all` to UTC cutoffs. Return canonical job cards with `sources[]`, `duplicateState`, and `possibleDuplicates[]`. Configure Pydantic response schemas with a camelCase alias generator so Python internals remain snake_case while the React contract is camelCase. The detail route delegates to `JobDetailsService` and returns `cacheState`, `updatedAt`, and `warning`.

- [ ] **Step 4: Implement sync launch outside the request event loop**

`POST /api/syncs` calls `SyncService.create_run()`, returns its pending run ID, and dispatches `SyncService.execute(run_id)` through a bounded application executor. Reject a duplicate concurrent sync for the same saved search with HTTP 409 and `{"detail": "Une synchronisation est déjà en cours."}`.

- [ ] **Step 5: Verify complete API suite**

Run: `.venv/bin/python -m pytest tests/api -v`

Expected: search CRUD, period filters, pagination, detail cache metadata, sync progress, partial error and retry tests pass.

- [ ] **Step 6: Add API entry point**

Add `jobscraper-api = "jobscraper.api.app:run"` to `pyproject.toml`, where `run()` starts Uvicorn on `127.0.0.1:8000` and reads `JOBSCRAPER_DATABASE_URL`.

- [ ] **Step 7: Commit**

```bash
git add src/jobscraper/api tests/api pyproject.toml
git commit -m "feat: expose local job aggregation API"
```

### Task 7: Phase verification

**Files:**
- Verify only.

**Interfaces:**
- Produces: stable API contract consumed by the React plan.

- [ ] **Step 1: Run backend quality gates**

Run: `.venv/bin/python -m pytest -m 'not live' --cov=jobscraper --cov-report=term-missing`

Run: `.venv/bin/python -m mypy src/jobscraper`

Expected: all tests pass and no new type errors remain.

- [ ] **Step 2: Start and probe the API**

Run: `.venv/bin/jobscraper-api`

From another shell run: `curl --fail http://127.0.0.1:8000/api/syncs/latest`

Expected: HTTP 200 with either `null` or a valid latest-run payload.

- [ ] **Step 3: Confirm migration on a clean database**

Run: `JOBSCRAPER_DATABASE_URL=sqlite:////tmp/jobscraper-clean.db .venv/bin/alembic upgrade head`

Expected: migration reaches head with no manual preparation.
