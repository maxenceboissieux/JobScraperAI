# Configurable Source Result Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist a 1–1,000 result limit per saved search, default existing and new searches to 500, apply it independently to every source, and classify a reached limit as an expected partial sync without a traceback.

**Architecture:** A new non-null `saved_searches.max_results` column is carried through SQLAlchemy, repository, camelCase API schemas, and `SearchCriteria`. `SyncService` uses `progress.exhausted` to distinguish an intentional consumer cap from a genuinely incomplete strict scraper. The React editor exposes a fixed select with 100, 250, 500, and 1,000.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, FastAPI/Pydantic 2, pytest, React 19, TypeScript, TanStack Query, Vitest/Testing Library, pnpm/Vite.

## Global Constraints

- `max_results` is required in persistence and constrained to 1 through 1,000 at the HTTP boundary.
- Existing rows and new API-created searches default automatically to 500.
- The limit applies per source, not across the whole synchronization run.
- A capped scan is `partial`, emits no exception traceback, and cannot deactivate unseen listings.
- A genuinely exhausted strict scraper with `search_complete=False` remains an error.
- The frontend offers exactly 100, 250, 500, and 1,000 under the label `Offres maximum par source`.
- There is no unlimited mode and no change to job-list display pagination.
- Preserve all user-owned untracked files and all non-related scraper behavior.

---

## File Structure

- Create `alembic/versions/0003_saved_search_max_results.py`: migrate every existing saved search to 500.
- Modify `src/jobscraper/db/models.py`: declare persisted `SavedSearch.max_results`.
- Modify `src/jobscraper/repositories/saved_searches.py`: persist the domain value.
- Modify `src/jobscraper/api/schemas.py` and `src/jobscraper/api/routes/searches.py`: expose `maxResults` with validation.
- Modify `src/jobscraper/services/sync.py`: reconstruct the configured limit and classify caps before strict completeness checks.
- Modify `frontend/src/api/types.ts` and `frontend/src/features/searches/SearchEditor.tsx`: carry and edit the value.
- Update focused backend/frontend tests and typed SavedSearch fixtures.

### Task 1: Database Migration and Repository Persistence

**Files:**
- Create: `alembic/versions/0003_saved_search_max_results.py`
- Modify: `src/jobscraper/db/models.py`
- Modify: `src/jobscraper/repositories/saved_searches.py`
- Test: `tests/db/test_schema.py`
- Test: `tests/repositories/test_saved_searches.py`

**Interfaces:**
- Consumes: `SearchCriteria.max_results: int`.
- Produces: `SavedSearch.max_results: int`, default 500 in new ORM rows and existing migrated rows.

- [ ] **Step 1: Write failing migration and repository tests**

Add a migration regression to `tests/db/test_schema.py` that upgrades a temporary database to revision `0002`, inserts a valid legacy search without `max_results`, upgrades to `head`, and verifies 500:

```python
def test_max_results_migration_defaults_existing_saved_searches_to_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'legacy-limit.db'}"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    monkeypatch.setenv("JOBSCRAPER_DATABASE_URL", database_url)
    command.upgrade(config, "0002")
    engine, _ = create_engine_and_session(database_url)
    with engine.begin() as connection:
        connection.execute(sa.text("""
            INSERT INTO saved_searches
                (id, name, keywords, location, contract_types,
                 experience_levels, workplace_types, companies,
                 exclude_companies, sources, active, created_at, updated_at)
            VALUES
                ('legacy', 'Legacy', '[\"python\"]', 'France', '[]',
                 '[]', '[]', '[]', '[]', '[\"hellowork\"]', 1,
                 CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(
            sa.text("SELECT max_results FROM saved_searches WHERE id='legacy'")
        ) == 500
```

Import SQLAlchemy as `sa`. Add repository assertions that a `SearchCriteria(max_results=250)` is saved as 250 on create and becomes 1,000 on update.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/db/test_schema.py tests/repositories/test_saved_searches.py -v`

Expected: FAIL because revision `0003` and `SavedSearch.max_results` do not exist.

- [ ] **Step 3: Add the migration, model field, and repository mapping**

Create revision `0003`:

```python
"""add saved-search source result limit

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-05
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.add_column(
        "saved_searches",
        sa.Column("max_results", sa.Integer(), server_default="500", nullable=False),
    )

def downgrade() -> None:
    op.drop_column("saved_searches", "max_results")
```

Add to `SavedSearch`:

```python
max_results: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
```

In repository `create` and `update`, assign `criteria.max_results` alongside the other scalar criteria.

- [ ] **Step 4: Run migration and repository tests GREEN**

Run: `.venv/bin/python -m pytest tests/db/test_schema.py tests/repositories/test_saved_searches.py -v`

Expected: all focused tests PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add alembic/versions/0003_saved_search_max_results.py src/jobscraper/db/models.py src/jobscraper/repositories/saved_searches.py tests/db/test_schema.py tests/repositories/test_saved_searches.py
git commit -m "feat: persist saved search result limits"
```

### Task 2: API Contract and Criteria Propagation

**Files:**
- Modify: `src/jobscraper/api/schemas.py`
- Modify: `src/jobscraper/api/routes/searches.py`
- Modify: `src/jobscraper/services/sync.py`
- Test: `tests/api/test_searches.py`
- Test: `tests/services/test_sync.py`

**Interfaces:**
- Consumes: `SavedSearch.max_results` from Task 1.
- Produces: camelCase `maxResults` on create/update/read and `SyncService._criteria(...).max_results`.

- [ ] **Step 1: Write failing API validation and propagation tests**

Extend `SEARCH_PAYLOAD` with `"maxResults": 250`. Assert create/list responses return 250. Add:

```python
def test_search_defaults_max_results_to_500(client: TestClient) -> None:
    payload = {key: value for key, value in SEARCH_PAYLOAD.items()
               if key != "maxResults"}
    response = client.post("/api/searches", json=payload)
    assert response.status_code == 201
    assert response.json()["maxResults"] == 500


@pytest.mark.parametrize("value", [0, 1001])
def test_search_rejects_out_of_range_max_results(
    client: TestClient, value: int
) -> None:
    assert client.post(
        "/api/searches", json={**SEARCH_PAYLOAD, "maxResults": value}
    ).status_code == 422


def test_patch_rejects_null_max_results(client: TestClient) -> None:
    search_id = client.post("/api/searches", json=SEARCH_PAYLOAD).json()["id"]
    assert client.patch(
        f"/api/searches/{search_id}", json={"maxResults": None}
    ).status_code == 422


def test_patch_updates_max_results(client: TestClient) -> None:
    search_id = client.post("/api/searches", json=SEARCH_PAYLOAD).json()["id"]
    response = client.patch(
        f"/api/searches/{search_id}", json={"maxResults": 1000}
    )
    assert response.status_code == 200
    assert response.json()["maxResults"] == 1000
```

In `tests/services/test_sync.py`, create a persisted search with `SearchCriteria(max_results=250)` and assert `SyncService._criteria(saved_search).max_results == 250`.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/api/test_searches.py tests/services/test_sync.py -v`

Expected: response and propagation assertions FAIL because the field is absent.

- [ ] **Step 3: Implement schemas, routes, and service reconstruction**

Add to `SearchFields`:

```python
max_results: int = Field(default=500, ge=1, le=1000)
```

Add to `SearchUpdate`:

```python
max_results: int | None = Field(default=None, ge=1, le=1000)
```

Include both `maxResults` and `max_results` in the patch null-rejection set. Add `max_results: int` to `SavedSearchResponse`.

In `routes/searches.py`, pass `max_results` into `SearchCriteria`, return it from `_response`, and include `max_results` in `criteria_fields`. In `SyncService._criteria`, add:

```python
max_results=saved_search.max_results,
```

- [ ] **Step 4: Run API/service tests GREEN**

Run: `.venv/bin/python -m pytest tests/api/test_searches.py tests/services/test_sync.py -v`

Expected: all focused tests PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/jobscraper/api/schemas.py src/jobscraper/api/routes/searches.py src/jobscraper/services/sync.py tests/api/test_searches.py tests/services/test_sync.py
git commit -m "feat: expose saved search result limits"
```

### Task 3: Expected Partial Status for Capped Strict Scrapers

**Files:**
- Modify: `src/jobscraper/services/sync.py:213-285`
- Test: `tests/services/test_sync.py`
- Preserve: `tests/scrapers/test_strict_search_health.py::test_hellowork_applies_max_results_across_queries`

**Interfaces:**
- Consumes: `criteria.max_results`, `_SourceProgress.exhausted`, and `scraper.search_complete`.
- Produces: source result `partial` with the existing limit message, without entering the exception boundary when `progress.exhausted` is false.

- [ ] **Step 1: Write the failing strict capped-source regression**

Add a strict scraper fixture that intentionally does not claim complete pagination:

```python
class StrictCappedScraper(BaseScraper):
    name = "hellowork"

    def __init__(self) -> None:
        super().__init__({"propagate_search_errors": True})

    def search(self, criteria: SearchCriteria) -> Iterator[JobOffer]:
        self._begin_search()
        for index in range(criteria.max_results):
            yield offer(f"cap-{index}", source=self.name)

    def get_job_details(self, job_id: str) -> JobOffer | None:
        return None
```

Then test the real service boundary:

```python
def test_strict_source_cap_is_expected_partial_without_error_log(
    session: Session,
) -> None:
    saved_search = SavedSearchRepository(session).create(
        name="Cap",
        criteria=SearchCriteria(keywords=["react"], max_results=2),
        sources=["hellowork"],
    )
    scraper = StrictCappedScraper()
    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)))
    try:
        run_id = SyncService(
            session, registry=FixedScraperRegistry(scraper)
        ).run(saved_search.id)
    finally:
        logger.remove(sink)

    result = source_results(session, run_id)["hellowork"]
    assert result.status == "partial"
    assert result.offers_seen == 2
    assert result.error_message == (
        "La limite de résultats a été atteinte; "
        "la vérification de la source est incomplète."
    )
    assert scraper.search_complete is False
    assert not any("Échec de la source" in message for message in messages)
```

- [ ] **Step 2: Run the regression and confirm RED**

Run: `.venv/bin/python -m pytest tests/services/test_sync.py::test_strict_source_cap_is_expected_partial_without_error_log -v`

Expected: FAIL because the current strict completeness check raises before the expected partial branch.

- [ ] **Step 3: Gate strict completeness on actual iterator exhaustion**

Change the post-consumption condition to:

```python
if (
    progress.exhausted
    and scraper.strict_search
    and not scraper.search_complete
):
    scraper._incomplete_search(
        "La source n’a pas confirmé une recherche complète"
    )
```

Do not mark the scraper complete and do not change the later `if not progress.exhausted` partial branch.

- [ ] **Step 4: Run service and strict scraper regressions GREEN**

Run: `.venv/bin/python -m pytest tests/services/test_sync.py tests/scrapers/test_strict_search_health.py -v`

Expected: capped strict source PASS; existing operational/incomplete scans still PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/jobscraper/services/sync.py tests/services/test_sync.py
git commit -m "fix: classify capped source scans without exceptions"
```

### Task 4: Frontend Limit Selector and End-to-End Contract

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/features/searches/SearchEditor.tsx`
- Modify: `frontend/src/features/searches/searches.test.tsx`
- Modify: `frontend/src/api/client.test.ts`
- Modify: every frontend test fixture constructing a required `SavedSearch`

**Interfaces:**
- Consumes: API `maxResults: number` from Task 2.
- Produces: create/update payloads with one of 100, 250, 500, or 1,000.

- [ ] **Step 1: Write failing editor tests**

Add `maxResults: 500` to the shared `savedSearch()` fixture. In the create test, assert:

```typescript
expect(screen.getByLabelText("Offres maximum par source")).toHaveValue("500");
```

and include `maxResults: 500` in the expected create payload. Add an edit test that opens a search with 250, selects 1,000, submits, and expects exactly `{ maxResults: 1000 }` in the PATCH payload.

- [ ] **Step 2: Run focused frontend tests and confirm RED**

Run from `frontend`: `pnpm test src/features/searches/searches.test.tsx src/api/client.test.ts`

Expected: FAIL because the selector and typed field do not exist.

- [ ] **Step 3: Add types and editor state**

Add `maxResults?: number` to `SearchCreate` and `SearchUpdate`, and required `maxResults: number` to `SavedSearch`.

In `SearchEditor.tsx`, add:

```typescript
const RESULT_LIMIT_CHOICES = [100, 250, 500, 1000] as const;
```

Add `maxResults: number` to `EditorValues`, `EDITOR_FIELDS`, new-search initial values (500), and existing-search initial values (`search.maxResults`). Add a direct numeric dirty comparison. Include `maxResults` in create payloads and only in edit patches when dirty.

Render beside the radius field:

```tsx
<div className="form-field">
  <label htmlFor="search-max-results">Offres maximum par source</label>
  <select
    id="search-max-results"
    value={values.maxResults}
    disabled={isSubmitting}
    onChange={(event) =>
      setValues((current) => ({
        ...current,
        maxResults: Number(event.currentTarget.value),
      }))
    }
  >
    {RESULT_LIMIT_CHOICES.map((limit) => (
      <option value={limit} key={limit}>{limit.toLocaleString("fr-FR")}</option>
    ))}
  </select>
</div>
```

Add `maxResults: 500` (or the test-specific value) to every `SavedSearch` fixture required by TypeScript.

- [ ] **Step 4: Run frontend tests, typecheck, and build GREEN**

Run from `frontend`:

```bash
pnpm test
pnpm typecheck
pnpm build
```

Expected: all Vitest tests PASS, TypeScript reports no errors, and Vite build succeeds.

- [ ] **Step 5: Run complete backend and isolated migration validation**

Run from repository root:

```bash
.venv/bin/python -m pytest tests/db/test_schema.py -v
.venv/bin/python -m pytest -m 'not live'
```

Expected: the migration regression and complete offline backend suite PASS. Do not migrate or inspect the user's main-checkout SQLite file from the isolated worktree. `jobscraper serve` invokes `RuntimeServices.migrate()` automatically; after integration, run the application from the main checkout and verify there that the existing search received 500:

```bash
sqlite3 data/jobscraper.db "SELECT max_results FROM saved_searches WHERE id='64a565fb-5a6a-40ad-b31a-3055e93cec17';"
```

Expected output: `500`.

- [ ] **Step 6: Commit Task 4**

```bash
git add frontend/src alembic src tests
git commit -m "feat: configure source result limits in search editor"
```

- [ ] **Step 7: Inspect final state**

Run: `git status --short --branch`

Expected: implementation files are committed; only the user's pre-existing local untracked files remain in the main checkout.
