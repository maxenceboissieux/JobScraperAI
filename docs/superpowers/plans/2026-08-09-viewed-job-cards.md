# Viewed Job Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the first click on each canonical job, visibly attenuate viewed cards, and let users show only unseen offers with immediate optimistic removal.

**Architecture:** Store one nullable UTC `viewed_at` timestamp on `CanonicalJob` and expose it through the existing repository and job API. Keep click ownership in `JobGrid`; a focused React Query mutation hook updates every cached jobs page optimistically, while `JobCard` and `JobFilters` remain presentation and URL-state components.

**Tech Stack:** Python 3.11/3.12, SQLAlchemy 2, Alembic, FastAPI/Pydantic v2, React 19, TypeScript, TanStack React Query 5, React Router 7, Vitest, Testing Library, MSW, pnpm.

## Global Constraints

- A job is marked viewed only from a job-grid card click, never from a direct `?job=...` URL or possible-duplicate navigation.
- Persist the first successful click timestamp in UTC; repeated or competing requests must not overwrite it.
- Existing canonical jobs remain unseen after migration (`viewed_at IS NULL`).
- Viewed state is global to the canonical job and shared across saved searches and source listings.
- The enabled URL state is exactly `unseenOnly=true`; false, missing, and invalid values are omitted from the canonical URL.
- The visible French label is exactly `✓ Déjà vue`; the filter label is exactly `Non vues uniquement`.
- When the unseen-only filter is active, optimistically remove the clicked card and decrement the cached total without going below zero while leaving the detail drawer open.
- A failed mark request restores all affected jobs-page cache snapshots and presents an accessible error.
- There is no reset/unmark action, view counter, history screen, user model, or mark-on-detail-open behavior.
- Preserve the existing untracked `.env`, `.idea/`, `.pnpm-store/`, and `jobscraper.db` paths.

---

## File Structure

- Create `alembic/versions/0004_canonical_job_viewed_at.py`: nullable-column migration for existing databases.
- Modify `src/jobscraper/db/models.py`: ORM definition for `CanonicalJob.viewed_at`.
- Modify `src/jobscraper/repositories/jobs.py`: atomic first-view persistence and unseen filtering.
- Modify `src/jobscraper/api/schemas.py`: viewed timestamp response fields and mark response model.
- Modify `src/jobscraper/api/routes/jobs.py`: serialize viewed state, accept the filter, and expose the idempotent POST endpoint.
- Modify `frontend/src/api/types.ts`: camel-case DTO and filter types.
- Modify `frontend/src/api/client.ts`: query serialization and mark-viewed request.
- Modify `frontend/src/features/jobs/useJobFilters.ts`: canonical URL state for the unseen-only filter.
- Modify `frontend/src/features/jobs/JobFilters.tsx`: accessible French checkbox control.
- Modify `frontend/src/features/jobs/JobCard.tsx`: viewed modifier class and label only.
- Create `frontend/src/features/jobs/useMarkJobViewed.ts`: all cross-cache optimistic mutation, reconciliation, and rollback logic.
- Modify `frontend/src/features/jobs/JobGrid.tsx`: card-click orchestration and accessible mutation error.
- Modify `frontend/src/styles/base.css`: filter control and attenuated-card styling within the existing stylesheet.
- Modify backend and frontend test files listed below; fixture DTOs must all explicitly include `viewedAt`.

### Task 1: Persist the first viewed timestamp and filter unseen jobs

**Files:**
- Create: `alembic/versions/0004_canonical_job_viewed_at.py`
- Modify: `src/jobscraper/db/models.py:72-108`
- Modify: `src/jobscraper/repositories/jobs.py:181-285`
- Test: `tests/db/test_schema.py`
- Test: `tests/repositories/test_jobs.py`

**Interfaces:**
- Consumes: `UTCDateTime`, `utc_now()`, `CanonicalJob.id`, and `JobRepository.get_job(job_id)`.
- Produces: `CanonicalJob.viewed_at: datetime | None`, `JobRepository.mark_viewed(job_id: str, viewed_at: datetime | None = None) -> CanonicalJob`, and `JobRepository.list_jobs(..., unseen_only: bool = False)`.

- [ ] **Step 1: Write migration and ORM schema tests that fail before the column exists**

Add a metadata assertion and an upgrade-from-`0003` regression to `tests/db/test_schema.py`:

```python
def test_canonical_job_viewed_at_is_nullable_utc_timestamp() -> None:
    column = Base.metadata.tables["canonical_jobs"].c.viewed_at

    assert isinstance(column.type, UTCDateTime)
    assert column.nullable


def test_viewed_at_migration_keeps_existing_jobs_unseen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'legacy-viewed.db'}"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    monkeypatch.setenv("JOBSCRAPER_DATABASE_URL", database_url)
    command.upgrade(config, "0003")
    engine, _ = create_engine_and_session(database_url)
    with engine.begin() as connection:
        connection.execute(sa.text("""
            INSERT INTO canonical_jobs
                (id, title, normalized_title, company, normalized_company,
                 location, normalized_location, salary_currency, skills,
                 benefits, detail_provenance, created_at, updated_at)
            VALUES
                ('legacy-job', 'Backend', 'backend', 'Acme', 'acme',
                 'Lyon', 'lyon', 'EUR', '[]', '[]', '{}',
                 CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))

    command.upgrade(config, "head")

    reflected = {
        column["name"]: column for column in inspect(engine).get_columns("canonical_jobs")
    }
    assert reflected["viewed_at"]["nullable"]
    with engine.connect() as connection:
        assert connection.scalar(
            sa.text("SELECT viewed_at FROM canonical_jobs WHERE id='legacy-job'")
        ) is None
```

Import `UTCDateTime` alongside `Base` at the top of the test.

- [ ] **Step 2: Run the schema tests and confirm RED**

Run:

```bash
.venv/bin/python -m pytest tests/db/test_schema.py::test_canonical_job_viewed_at_is_nullable_utc_timestamp tests/db/test_schema.py::test_viewed_at_migration_keeps_existing_jobs_unseen -q
```

Expected: both tests fail because neither the ORM column nor migration `0004` exists.

- [ ] **Step 3: Add the nullable ORM column and migration**

Add beside `posted_at`/detail cache timestamps in `CanonicalJob`:

```python
viewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
```

Create `alembic/versions/0004_canonical_job_viewed_at.py`:

```python
"""add canonical job viewed timestamp

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "canonical_jobs",
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("canonical_jobs", "viewed_at")
```

- [ ] **Step 4: Run the schema tests and confirm GREEN**

Run the command from Step 2.

Expected: `2 passed`.

- [ ] **Step 5: Write repository tests for first-write-wins, unknown IDs, competing sessions, and unseen filtering**

Add to `tests/repositories/test_jobs.py`:

```python
def test_mark_viewed_persists_only_the_first_timestamp(session: Session) -> None:
    jobs = JobRepository(session)
    job = jobs.upsert_listing(offer("viewed-once"), seen_at=NOW)
    first_view = NOW + timedelta(minutes=1)
    later_view = NOW + timedelta(minutes=5)

    first = jobs.mark_viewed(job.id, viewed_at=first_view)
    second = jobs.mark_viewed(job.id, viewed_at=later_view)

    assert first.viewed_at == first_view
    assert second.viewed_at == first_view
    with pytest.raises(LookupError, match="Canonical job does not exist"):
        jobs.mark_viewed("00000000-0000-0000-0000-000000000000")


def test_competing_mark_viewed_requests_preserve_the_first_commit(tmp_path: Path) -> None:
    engine, session_factory = create_engine_and_session(
        f"sqlite:///{tmp_path / 'viewed-race.db'}"
    )
    Base.metadata.create_all(engine)
    with session_factory.begin() as seed_session:
        seeded = JobRepository(seed_session).upsert_listing(
            offer("viewed-race"), seen_at=NOW
        )
        job_id = seeded.id

    first_view = NOW + timedelta(minutes=1)
    later_view = NOW + timedelta(minutes=2)
    with session_factory() as first_session, session_factory() as second_session:
        assert JobRepository(second_session).get_job(job_id) is not None
        JobRepository(first_session).mark_viewed(job_id, viewed_at=first_view)
        first_session.commit()
        result = JobRepository(second_session).mark_viewed(
            job_id, viewed_at=later_view
        )
        second_session.commit()

    with session_factory() as verification_session:
        persisted = JobRepository(verification_session).get_job(job_id)
        assert persisted is not None
        assert persisted.viewed_at == first_view


def test_unseen_only_excludes_viewed_jobs_before_pagination(session: Session) -> None:
    jobs = JobRepository(session)
    viewed = jobs.upsert_listing(offer("viewed-filter", posted_at=NOW), seen_at=NOW)
    unseen = jobs.upsert_listing(
        offer("unseen-filter", posted_at=NOW - timedelta(hours=1)), seen_at=NOW
    )
    jobs.mark_viewed(viewed.id, viewed_at=NOW + timedelta(minutes=1))

    assert [job.id for job in jobs.list_jobs(unseen_only=True, limit=1)] == [
        unseen.id
    ]
    assert {job.id for job in jobs.list_jobs(unseen_only=False)} == {
        viewed.id,
        unseen.id,
    }
```

- [ ] **Step 6: Run the repository tests and confirm RED**

Run:

```bash
.venv/bin/python -m pytest tests/repositories/test_jobs.py -k 'mark_viewed or unseen_only' -q
```

Expected: failures report missing `mark_viewed` and the unsupported `unseen_only` argument.

- [ ] **Step 7: Implement the atomic repository operation and filter**

Add immediately after `get_job`:

```python
def mark_viewed(
    self, job_id: str, viewed_at: datetime | None = None
) -> CanonicalJob:
    """Persist the first observed card click for a canonical job."""

    job = self.get_job(job_id)
    if job is None:
        raise LookupError("Canonical job does not exist")
    observed_at = viewed_at or utc_now()
    self.session.execute(
        update(CanonicalJob)
        .where(CanonicalJob.pk == job.pk, CanonicalJob.viewed_at.is_(None))
        .values(viewed_at=observed_at)
    )
    self.session.flush()
    self.session.refresh(job, attribute_names=["viewed_at"])
    return job
```

Add `unseen_only: bool = False` to `list_jobs`, then place this check at the top of `matches`:

```python
if unseen_only and job.viewed_at is not None:
    return False
```

- [ ] **Step 8: Run Task 1 tests and confirm GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/db/test_schema.py tests/repositories/test_jobs.py -q
```

Expected: all selected tests pass.

- [ ] **Step 9: Commit the persistence unit**

```bash
git add alembic/versions/0004_canonical_job_viewed_at.py src/jobscraper/db/models.py src/jobscraper/repositories/jobs.py tests/db/test_schema.py tests/repositories/test_jobs.py
git commit -m "feat: persist viewed job state"
```

### Task 2: Expose viewed state and unseen filtering through the API

**Files:**
- Modify: `src/jobscraper/api/schemas.py:150-190`
- Modify: `src/jobscraper/api/routes/jobs.py:50-180`
- Test: `tests/api/test_jobs.py`

**Interfaces:**
- Consumes: `CanonicalJob.viewed_at`, `JobRepository.mark_viewed(...)`, and `JobRepository.list_jobs(..., unseen_only: bool)` from Task 1.
- Produces: `JobViewedResponse(id: str, viewed_at: datetime)`, `POST /api/jobs/{canonical_job_id}/viewed`, `viewedAt` on `JobCard`/`JobDetails`, and `GET /api/jobs?unseenOnly=true`.

- [ ] **Step 1: Write failing API contract tests**

Add to `tests/api/test_jobs.py`:

```python
def test_mark_viewed_is_idempotent_and_serialized_on_cards_and_details(
    client: TestClient, session: Session
) -> None:
    _search_id, recent_id, _older_id, _undated_id = seed_jobs(session)
    recent = JobRepository(session).get_job(recent_id)
    assert recent is not None
    recent.details_fetched_at = utc_now()
    recent.detail_provenance = {
        group: recent.details_fetched_at.isoformat()
        for group in ("description", "salary", "skills", "benefits")
    }
    session.commit()

    before = client.get("/api/jobs", params={"period": "all"})
    first = client.post(f"/api/jobs/{recent_id}/viewed")
    second = client.post(f"/api/jobs/{recent_id}/viewed")
    after = client.get("/api/jobs", params={"period": "all"})
    details = client.get(f"/api/jobs/{recent_id}")

    assert before.status_code == first.status_code == second.status_code == 200
    assert next(item for item in before.json()["items"] if item["id"] == recent_id)[
        "viewedAt"
    ] is None
    assert first.json()["id"] == recent_id
    assert first.json()["viewedAt"] == second.json()["viewedAt"]
    assert next(item for item in after.json()["items"] if item["id"] == recent_id)[
        "viewedAt"
    ] == first.json()["viewedAt"]
    assert details.status_code == 200
    assert details.json()["viewedAt"] == first.json()["viewedAt"]


def test_mark_viewed_returns_404_for_unknown_job(client: TestClient) -> None:
    response = client.post(
        "/api/jobs/00000000-0000-0000-0000-000000000000/viewed"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "L’offre demandée n’existe pas."}


def test_unseen_only_filters_totals_saved_search_and_pagination(
    client: TestClient, session: Session
) -> None:
    search_id, recent_id, older_id, _undated_id = seed_jobs(session)
    marked = client.post(f"/api/jobs/{recent_id}/viewed")

    first_page = client.get(
        "/api/jobs",
        params={
            "savedSearchId": search_id,
            "period": "all",
            "unseenOnly": "true",
            "limit": 1,
            "offset": 0,
        },
    )
    second_page = client.get(
        "/api/jobs",
        params={
            "savedSearchId": search_id,
            "period": "all",
            "unseenOnly": "true",
            "limit": 1,
            "offset": 1,
        },
    )

    assert marked.status_code == 200
    assert first_page.status_code == second_page.status_code == 200
    assert first_page.json()["total"] == second_page.json()["total"] == 1
    assert [item["id"] for item in first_page.json()["items"]] == [older_id]
    assert second_page.json()["items"] == []
```

- [ ] **Step 2: Run the new API tests and confirm RED**

Run:

```bash
.venv/bin/python -m pytest tests/api/test_jobs.py -k 'mark_viewed or unseen_only' -q
```

Expected: POST returns 405/404 and card responses have no `viewedAt` field.

- [ ] **Step 3: Extend the Pydantic schemas**

Add `viewed_at` to `JobCard` after `posted_at`, so `JobDetails` inherits it:

```python
viewed_at: datetime | None
```

Add the focused mutation response near `JobsPage`:

```python
class JobViewedResponse(ApiModel):
    id: str
    viewed_at: datetime
```

- [ ] **Step 4: Wire serialization, query alias, and POST endpoint**

Import `JobViewedResponse` in `routes/jobs.py`. Add `viewed_at=job.viewed_at` to `_card`.

Add this query parameter to `list_jobs`:

```python
unseen_only: bool = Query(default=False, alias="unseenOnly"),
```

Pass `unseen_only=unseen_only` to the repository. Filtering must occur in the repository before the route calculates `total` and slices the page.

Add the endpoint before the detail endpoint:

```python
@router.post("/{canonical_job_id}/viewed", response_model=JobViewedResponse)
def mark_job_viewed(
    canonical_job_id: str,
    session: Session = Depends(get_session),
) -> JobViewedResponse:
    try:
        job = JobRepository(session).mark_viewed(canonical_job_id)
    except LookupError:
        raise HTTPException(
            status_code=404, detail="L’offre demandée n’existe pas."
        ) from None
    session.commit()
    if job.viewed_at is None:
        raise RuntimeError("Viewed timestamp was not persisted")
    return JobViewedResponse(id=job.id, viewed_at=job.viewed_at)
```

- [ ] **Step 5: Run the API tests and confirm GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/api/test_jobs.py -q
```

Expected: all job API tests pass, including exact camel-case `viewedAt` output.

- [ ] **Step 6: Run backend formatting and focused regression tests**

Run:

```bash
.venv/bin/python -m black --check src/jobscraper/db/models.py src/jobscraper/repositories/jobs.py src/jobscraper/api/schemas.py src/jobscraper/api/routes/jobs.py tests/db/test_schema.py tests/repositories/test_jobs.py tests/api/test_jobs.py alembic/versions/0004_canonical_job_viewed_at.py
.venv/bin/python -m pytest tests/db/test_schema.py tests/repositories/test_jobs.py tests/api/test_jobs.py -q
```

Expected: Black reports no changes required and all selected tests pass.

- [ ] **Step 7: Commit the API unit**

```bash
git add src/jobscraper/api/schemas.py src/jobscraper/api/routes/jobs.py tests/api/test_jobs.py
git commit -m "feat: expose viewed jobs API"
```

### Task 3: Add the unseen-only URL filter and viewed card presentation

**Files:**
- Modify: `frontend/src/api/types.ts:105-160`
- Modify: `frontend/src/api/client.ts:178-235`
- Modify: `frontend/src/features/jobs/useJobFilters.ts`
- Modify: `frontend/src/features/jobs/JobFilters.tsx:145-375`
- Modify: `frontend/src/features/jobs/JobCard.tsx`
- Modify: `frontend/src/styles/base.css:411-505` and the existing `.job-card` rules
- Test: `frontend/src/features/jobs/filters.test.tsx`
- Test: `frontend/src/features/jobs/job-grid.test.tsx`
- Test fixtures: `frontend/src/features/details/details.test.tsx`
- Test fixtures: `frontend/src/features/sync/sync.test.tsx`

**Interfaces:**
- Consumes: backend JSON fields `viewedAt` and query alias `unseenOnly` from Task 2.
- Produces: `JobCard.viewedAt: string | null`, `JobFilters.unseenOnly?: boolean`, `ViewedJob`, URL serialization, the checkbox, and `.job-card--viewed`/`.job-card__viewed-label` presentation hooks.

- [ ] **Step 1: Add failing URL-filter tests**

Extend the existing filter harness in `filters.test.tsx` with:

```tsx
<button
  type="button"
  onClick={() => setFilter("unseenOnly", filters.unseenOnly ? undefined : true)}
>
  Non vues uniquement
</button>
```

Add tests that exercise canonical URL behavior:

```tsx
it("serializes and restores the unseen-only filter", async () => {
  const user = userEvent.setup();
  renderFilters("/?period=3d");

  await user.click(screen.getByRole("button", { name: "Non vues uniquement" }));

  expect(window.location.search).toContain("unseenOnly=true");
  expect(renderedFilters()).toMatchObject({ unseenOnly: true, offset: 0 });
});

it("removes false or invalid unseen-only values from the canonical URL", async () => {
  renderFilters("/?period=3d&unseenOnly=false");

  await waitFor(() => expect(window.location.search).not.toContain("unseenOnly"));
  expect(renderedFilters()).not.toHaveProperty("unseenOnly");
});
```

Add `unseenOnly?: boolean` to the exact return annotation of the existing `renderedFilters()` helper.

- [ ] **Step 2: Add failing card presentation tests and update fixture shapes**

Add `viewedAt: null` to every `JobCard`/`JobDetails` fixture in frontend tests. In `job-grid.test.tsx`, add:

```tsx
it("attenuates a viewed card and exposes the explicit label", async () => {
  server.use(
    http.get("*/api/jobs", () =>
      HttpResponse.json({
        items: [
          {
            ...POSSIBLE_DUPLICATE_JOB,
            viewedAt: "2026-08-09T10:00:00Z",
          },
        ],
        total: 1,
        limit: 24,
        offset: 0,
      }),
    ),
  );

  renderAppWithJobs([{ ...POSSIBLE_DUPLICATE_JOB, viewedAt: "2026-08-09T10:00:00Z" }]);

  const card = await screen.findByRole("article");
  expect(card).toHaveClass("job-card--viewed");
  expect(within(card).getByText("✓ Déjà vue")).toBeVisible();
});

it("does not change the presentation of an unseen card", async () => {
  renderAppWithJobs([{ ...POSSIBLE_DUPLICATE_JOB, viewedAt: null }]);

  const card = await screen.findByRole("article");
  expect(card).not.toHaveClass("job-card--viewed");
  expect(within(card).queryByText("✓ Déjà vue")).not.toBeInTheDocument();
});
```

Use the suite's existing MSW server, `POSSIBLE_DUPLICATE_JOB` fixture, and `renderAppWithJobs` helper. `within` is already imported in this file.

- [ ] **Step 3: Run frontend tests and confirm RED**

Run from `frontend/`:

```bash
pnpm test src/features/jobs/filters.test.tsx src/features/jobs/job-grid.test.tsx
```

Expected: TypeScript/tests fail because `unseenOnly`, `viewedAt`, and the viewed modifier UI do not exist.

- [ ] **Step 4: Extend API types and client serialization**

Add to `JobCard` in `frontend/src/api/types.ts`:

```ts
viewedAt: string | null;
```

Add to `JobFilters`:

```ts
unseenOnly?: boolean;
```

Add:

```ts
export type ViewedJob = {
  id: string;
  viewedAt: string;
};
```

In `jobsQuery`, append:

```ts
appendValue(params, "unseenOnly", filters.unseenOnly);
```

The POST client is introduced in Task 4; Task 3 only establishes the shared response type and query parameter.

- [ ] **Step 5: Implement canonical URL state and filter counting**

In `useJobFilters.ts`:

```ts
// FILTER_KEYS
"unseenOnly",

// ParsedFilters and JobFilterValues
unseenOnly?: boolean;

// parseFilters
const unseenOnly = params.get("unseenOnly") === "true" ? true : undefined;

// returned parsed object
...(unseenOnly === undefined ? {} : { unseenOnly }),

// canonicalParams
if (parsed.unseenOnly === true) next.append("unseenOnly", "true");

// writeFilter URL map
unseenOnly: "unseenOnly",
```

Include `parsed.unseenOnly` in `countActiveFilters`. Because `canonicalParams` first deletes every `FILTER_KEYS` entry, `false` and invalid values disappear automatically.

- [ ] **Step 6: Add the accessible checkbox and card state**

Add before the sort field in `JobFilters.tsx`:

```tsx
<div className="job-filter-field job-filter-field--toggle">
  <label className="job-filter-toggle">
    <input
      type="checkbox"
      checked={filters.unseenOnly === true}
      onChange={(event) =>
        setFilter("unseenOnly", event.currentTarget.checked ? true : undefined)
      }
    />
    <span>Non vues uniquement</span>
  </label>
</div>
```

Change `JobCard`'s article and add the visible label as the first child of its button:

```tsx
<article className={`job-card${job.viewedAt ? " job-card--viewed" : ""}`}>
  <button ...>
    {job.viewedAt ? (
      <span className="job-card__viewed-label">✓ Déjà vue</span>
    ) : null}
```

Do not change the button's `aria-label`; it must continue to be `Voir l’offre ${job.title}`.

- [ ] **Step 7: Implement the approved attenuated styling**

Add focused rules to `base.css`, using existing custom properties:

```css
.job-filter-field--toggle {
  align-self: flex-end;
}

.job-filter-toggle {
  display: flex;
  min-height: 40px;
  align-items: center;
  gap: 8px;
  margin: 0;
  cursor: pointer;
}

.job-filter-toggle input {
  width: 18px;
  min-height: 18px;
  margin: 0;
}

.job-card__button {
  position: relative;
}

.job-card--viewed {
  border-color: var(--line);
  background: color-mix(in srgb, var(--paper) 88%, var(--line));
}

.job-card--viewed .job-card__button > :not(.job-card__viewed-label) {
  opacity: 0.62;
}

.job-card__viewed-label {
  display: inline-flex;
  margin: 0 0 10px auto;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  padding: 3px 8px;
  color: var(--muted);
  font-size: 0.7rem;
  font-weight: 800;
}
```

If the existing `.job-card__button` declaration already has `position`, merge rather than duplicate the selector. Verify the label occupies the upper-right area without covering the title at desktop and mobile widths.

- [ ] **Step 8: Run focused tests, typecheck, and confirm GREEN**

Run from `frontend/`:

```bash
pnpm test src/features/jobs/filters.test.tsx src/features/jobs/job-grid.test.tsx src/features/details/details.test.tsx src/features/sync/sync.test.tsx
pnpm typecheck
```

Expected: all selected tests pass and TypeScript reports no errors.

- [ ] **Step 9: Commit the presentation and filter unit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/features/jobs/useJobFilters.ts frontend/src/features/jobs/JobFilters.tsx frontend/src/features/jobs/JobCard.tsx frontend/src/styles/base.css frontend/src/features/jobs/filters.test.tsx frontend/src/features/jobs/job-grid.test.tsx frontend/src/features/details/details.test.tsx frontend/src/features/sync/sync.test.tsx
git commit -m "feat: show viewed jobs and unseen filter"
```

### Task 4: Mark card clicks optimistically across every cached job page

**Files:**
- Modify: `frontend/src/api/client.ts:220-245`
- Create: `frontend/src/features/jobs/useMarkJobViewed.ts`
- Modify: `frontend/src/features/jobs/JobGrid.tsx`
- Test: `frontend/src/features/jobs/job-grid.test.tsx`
- Test: `frontend/src/features/details/details.test.tsx`

**Interfaces:**
- Consumes: `api.markJobViewed(id: string, signal?: AbortSignal) -> Promise<ViewedJob>`, `JobsPage`, `JobFilters.unseenOnly`, and `JobGrid.onSelectJob`.
- Produces: `useMarkJobViewed() -> { markViewed(jobId: string): void; errorMessage: string | null }`; no other component can mark a job viewed.

- [ ] **Step 1: Write failing click, optimistic removal, rollback, and navigation-boundary tests**

In `job-grid.test.tsx`, add MSW handlers and tests with these observable assertions:

```tsx
it("opens details immediately and posts viewed state from a grid card", async () => {
  const user = userEvent.setup();
  let markRequests = 0;
  server.use(
    http.post("*/api/jobs/:id/viewed", ({ params }) => {
      markRequests += 1;
      return HttpResponse.json({
        id: String(params.id),
        viewedAt: "2026-08-09T10:00:00Z",
      });
    }),
  );

  renderAppWithJobs([{ ...POSSIBLE_DUPLICATE_JOB, viewedAt: null }]);
  await user.click(await screen.findByRole("button", { name: `Voir l’offre ${POSSIBLE_DUPLICATE_JOB.title}` }));

  expect(window.location.search).toContain(`job=${POSSIBLE_DUPLICATE_JOB.id}`);
  await waitFor(() => expect(markRequests).toBe(1));
  expect(await screen.findByText("✓ Déjà vue")).toBeVisible();
});

it("removes the card and decrements total immediately with unseen-only enabled", async () => {
  const user = userEvent.setup();
  let releaseRequest: (() => void) | undefined;
  server.use(
    http.post("*/api/jobs/:id/viewed", async ({ params }) => {
      await new Promise<void>((resolve) => {
        releaseRequest = resolve;
      });
      return HttpResponse.json({
        id: String(params.id),
        viewedAt: "2026-08-09T10:00:00Z",
      });
    }),
  );

  renderAppWithJobs([{ ...POSSIBLE_DUPLICATE_JOB, viewedAt: null }], {
    initialUrl: "/?period=3d&unseenOnly=true",
  });
  await user.click(await screen.findByRole("button", { name: `Voir l’offre ${POSSIBLE_DUPLICATE_JOB.title}` }));

  expect(screen.queryByRole("button", { name: `Voir l’offre ${POSSIBLE_DUPLICATE_JOB.title}` })).not.toBeInTheDocument();
  expect(window.location.search).toContain(`job=${POSSIBLE_DUPLICATE_JOB.id}`);
  releaseRequest?.();
});

it("restores every cached page and reports an accessible error when marking fails", async () => {
  const user = userEvent.setup();
  server.use(
    http.post("*/api/jobs/:id/viewed", () =>
      HttpResponse.json({ detail: "database unavailable" }, { status: 500 }),
    ),
  );

  renderAppWithJobs([{ ...POSSIBLE_DUPLICATE_JOB, viewedAt: null }], {
    initialUrl: "/?period=3d&unseenOnly=true",
  });
  await user.click(await screen.findByRole("button", { name: `Voir l’offre ${POSSIBLE_DUPLICATE_JOB.title}` }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Impossible d’enregistrer cette offre comme déjà vue."
  );
  expect(await screen.findByRole("button", { name: `Voir l’offre ${POSSIBLE_DUPLICATE_JOB.title}` })).toBeVisible();
  expect(window.location.search).toContain(`job=${POSSIBLE_DUPLICATE_JOB.id}`);
});
```

Add a direct-navigation assertion in `frontend/src/features/details/details.test.tsx`:

```tsx
it("does not mark a job viewed when details are opened from the URL", async () => {
  let markRequests = 0;
  server.use(
    http.post("*/api/jobs/:id/viewed", () => {
      markRequests += 1;
      return HttpResponse.json({ id: JOB.id, viewedAt: "2026-08-09T10:00:00Z" });
    }),
  );

  renderAppWithJobs([JOB], {
    details: DETAILS_WITH_DUPLICATE,
    initialUrl: `/?period=3d&job=${JOB.id}`,
  });
  await screen.findByRole("dialog", { name: "Détails de l’offre" });

  expect(markRequests).toBe(0);
});
```

In the existing test named `ouvre les détails et suit un doublon possible`, register the same POST counter before rendering and assert `markRequests === 1` after the initial grid-card click and still `markRequests === 1` after clicking the possible duplicate. This proves duplicate navigation does not trigger a second mark while preserving the authorized initial card mark.

- [ ] **Step 2: Run the interaction tests and confirm RED**

Run from `frontend/`:

```bash
pnpm test src/features/jobs/job-grid.test.tsx src/features/details/details.test.tsx
```

Expected: no POST occurs, optimistic removal/rollback are absent, and the error message is absent.

- [ ] **Step 3: Add the API mutation method**

Import `ViewedJob` in `client.ts` and add beside `getJob`:

```ts
markJobViewed(id: string, signal?: AbortSignal): Promise<ViewedJob> {
  return request(`/api/jobs/${encodeURIComponent(id)}/viewed`, {
    method: "POST",
    signal,
  });
},
```

- [ ] **Step 4: Implement the focused cross-cache mutation hook**

Create `frontend/src/features/jobs/useMarkJobViewed.ts`:

```ts
import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { api } from "../../api/client";
import type { JobFilters, JobsPage } from "../../api/types";

const ERROR_MESSAGE = "Impossible d’enregistrer cette offre comme déjà vue.";
type Snapshot = readonly [QueryKey, JobsPage | undefined];

function filtersFromKey(queryKey: QueryKey): JobFilters | undefined {
  const candidate = queryKey[1];
  return typeof candidate === "object" && candidate !== null
    ? (candidate as JobFilters)
    : undefined;
}

function markPageViewed(
  page: JobsPage | undefined,
  jobId: string,
  viewedAt: string,
  unseenOnly: boolean,
  replaceViewedAt = false,
): JobsPage | undefined {
  if (page === undefined || !page.items.some((job) => job.id === jobId)) {
    return page;
  }
  if (unseenOnly) {
    return {
      ...page,
      items: page.items.filter((job) => job.id !== jobId),
      total: Math.max(0, page.total - 1),
    };
  }
  return {
    ...page,
    items: page.items.map((job) =>
      job.id === jobId
        ? {
            ...job,
            viewedAt: replaceViewedAt ? viewedAt : (job.viewedAt ?? viewedAt),
          }
        : job,
    ),
  };
}

export function useMarkJobViewed() {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (jobId: string) => api.markJobViewed(jobId),
    onMutate: async (jobId) => {
      await queryClient.cancelQueries({ queryKey: ["jobs"] });
      const snapshots = queryClient.getQueriesData<JobsPage>({
        queryKey: ["jobs"],
      }) as Snapshot[];
      const optimisticViewedAt = new Date().toISOString();
      for (const [queryKey, page] of snapshots) {
        const unseenOnly = filtersFromKey(queryKey)?.unseenOnly === true;
        queryClient.setQueryData(
          queryKey,
          markPageViewed(page, jobId, optimisticViewedAt, unseenOnly),
        );
      }
      return { snapshots };
    },
    onSuccess: (viewed) => {
      const pages = queryClient.getQueriesData<JobsPage>({ queryKey: ["jobs"] });
      for (const [queryKey, page] of pages) {
        queryClient.setQueryData(
          queryKey,
          markPageViewed(
            page,
            viewed.id,
            viewed.viewedAt,
            filtersFromKey(queryKey)?.unseenOnly === true,
            true,
          ),
        );
      }
    },
    onError: (_error, _jobId, context) => {
      for (const [queryKey, page] of context?.snapshots ?? []) {
        queryClient.setQueryData(queryKey, page);
      }
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });

  return {
    markViewed(jobId: string) {
      mutation.reset();
      mutation.mutate(jobId);
    },
    errorMessage: mutation.isError ? ERROR_MESSAGE : null,
  };
}
```

The default nullish-coalescing branch preserves a first timestamp already cached from the server during optimism; `replaceViewedAt=true` on success reconciles the optimistic value to the authoritative timestamp returned by the server. The rollback restores the complete prior page objects, including totals and pagination.

- [ ] **Step 5: Orchestrate click-only marking in `JobGrid`**

Import and initialize the hook:

```tsx
const { markViewed, errorMessage } = useMarkJobViewed();
const selectFromCard = (jobId: string) => {
  onSelectJob(jobId);
  markViewed(jobId);
};
```

Pass `selectFromCard` to each `JobCard`, never replace `App`'s general `onSelectJob` callback. This boundary is what prevents direct URLs and possible-duplicate navigation from marking jobs.

Render the error in the grid result section before the count:

```tsx
{errorMessage ? (
  <p className="status-banner status-banner--error" role="alert">
    {errorMessage}
  </p>
) : null}
```

For the empty-page branch, render the same alert above the existing empty-state copy so a failure after removing the final card becomes visible as soon as rollback completes.

- [ ] **Step 6: Add an explicit cross-cache reconciliation test**

In `job-grid.test.tsx`, seed two jobs queries in the suite's `QueryClient` before rendering—one normal and one with `{ unseenOnly: true }`—then click the shared job and assert:

```tsx
expect(queryClient.getQueryData<JobsPage>(["jobs", normalFilters])?.items[0]).toMatchObject({
  id: POSSIBLE_DUPLICATE_JOB.id,
  viewedAt: "2026-08-09T10:00:00Z",
});
expect(queryClient.getQueryData<JobsPage>(["jobs", unseenFilters])).toMatchObject({
  items: [],
  total: 0,
});
```

Use a deferred successful MSW response to assert the optimistic state first. Back the jobs GET handler with a mutable `viewedAt` variable; set it to `2026-08-09T10:00:00Z` when releasing the POST, then assert both the immediate success patch and the invalidation refetch retain that server timestamp.

- [ ] **Step 7: Run interaction tests and confirm GREEN**

Run from `frontend/`:

```bash
pnpm test src/features/jobs/job-grid.test.tsx src/features/details/details.test.tsx
```

Expected: all click, removal, rollback, cross-cache, direct-URL, and duplicate-navigation tests pass.

- [ ] **Step 8: Commit the optimistic interaction unit**

```bash
git add frontend/src/api/client.ts frontend/src/features/jobs/useMarkJobViewed.ts frontend/src/features/jobs/JobGrid.tsx frontend/src/features/jobs/job-grid.test.tsx frontend/src/features/details/details.test.tsx
git commit -m "feat: mark job cards viewed optimistically"
```

### Task 5: Full verification and delivery review

**Files:**
- Review: every file changed in Tasks 1-4
- Update only if verification finds a concrete defect: the smallest owning source/test file

**Interfaces:**
- Consumes: the complete persistence, API, URL filter, presentation, and optimistic mutation units.
- Produces: a verified implementation matching `docs/superpowers/specs/2026-08-09-viewed-job-cards-design.md`.

- [ ] **Step 1: Run the complete backend non-live suite**

Run:

```bash
.venv/bin/python -m pytest -m "not live" -q
```

Expected: all non-live tests pass; only tests marked `live` are deselected.

- [ ] **Step 2: Run backend static checks**

Run:

```bash
.venv/bin/python -m black --check src tests alembic
.venv/bin/python -m mypy src
```

Expected: Black reports no changes required and mypy reports success with no errors.

- [ ] **Step 3: Run the complete frontend suite**

Run from `frontend/`:

```bash
pnpm test
pnpm typecheck
pnpm build
```

Expected: all Vitest tests pass, TypeScript reports no errors, and Vite creates a production build successfully.

- [ ] **Step 4: Verify the migration chain both forward and backward on a disposable database**

Run with a disposable path under `/tmp`:

```bash
JOBSCRAPER_DATABASE_URL=sqlite:////tmp/jobscraper-viewed-verification.db .venv/bin/alembic upgrade head
JOBSCRAPER_DATABASE_URL=sqlite:////tmp/jobscraper-viewed-verification.db .venv/bin/alembic downgrade 0003
JOBSCRAPER_DATABASE_URL=sqlite:////tmp/jobscraper-viewed-verification.db .venv/bin/alembic upgrade head
```

Expected: all three Alembic commands complete successfully. Remove only this exact disposable file after verification.

- [ ] **Step 5: Review the diff against every acceptance criterion**

Run:

```bash
git diff --check
git status --short
git log --oneline -5
```

Confirm from the diff and tests that:

- first-click persistence is atomic and UTC;
- `viewedAt` appears on list and detail payloads;
- unseen filtering precedes total/pagination calculations;
- card clicks alone own the POST;
- every jobs query cache is patched and rollback restores each snapshot;
- the viewed label and error are accessible;
- direct detail and duplicate navigation remain read-only;
- the four user-owned untracked paths remain untouched.

- [ ] **Step 6: Apply the completion verification skill and prepare integration**

Invoke `superpowers:verification-before-completion`, report the fresh command outputs, then invoke `superpowers:requesting-code-review`. Address only verified findings and rerun the affected checks plus the complete suites from Steps 1-3.

- [ ] **Step 7: Commit any review-only corrections**

If review required a correction, stage the feature's known owning files and commit:

```bash
git add alembic/versions/0004_canonical_job_viewed_at.py src/jobscraper/db/models.py src/jobscraper/repositories/jobs.py src/jobscraper/api/schemas.py src/jobscraper/api/routes/jobs.py tests/db/test_schema.py tests/repositories/test_jobs.py tests/api/test_jobs.py frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/features/jobs/useJobFilters.ts frontend/src/features/jobs/JobFilters.tsx frontend/src/features/jobs/JobCard.tsx frontend/src/features/jobs/useMarkJobViewed.ts frontend/src/features/jobs/JobGrid.tsx frontend/src/styles/base.css frontend/src/features/jobs/filters.test.tsx frontend/src/features/jobs/job-grid.test.tsx frontend/src/features/details/details.test.tsx frontend/src/features/sync/sync.test.tsx
git commit -m "fix: address viewed job review"
```

If no correction was required, do not create an empty commit. Use `superpowers:finishing-a-development-branch` to present the integration choices; merge or push only when the user selects that action.
