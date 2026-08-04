# French React Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved French card-grid interface with instant local filters, saved-search management, a sliding cached-detail drawer, duplicate links, and live sync progress.

**Architecture:** A Vite React single-page application consumes the stable `/api` contract. TanStack Query owns server state, URL search parameters own shareable filters, and focused feature components keep search management, result browsing, detail display, and synchronization independent.

**Tech Stack:** Node.js 20.19+ or 22.12+, React 19, TypeScript 5, Vite 7, TanStack Query 5, React Router 7, Vitest, Testing Library, MSW.

## Global Constraints

- Every user-facing label, validation message, empty state, loading state and error is French.
- Layout B is mandatory: responsive card grid plus right-side drawer; the drawer is full-screen on mobile.
- Period shortcuts are 24 h, 3 days, 7 days and Toutes.
- Filters never launch a scraper; they only query locally persisted data.
- Suspected duplicates remain separate and link to each other.
- The interface remains usable while synchronization runs.
- Before running frontend commands in this workspace, run `export PATH="/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH"`; then verify `node --version` satisfies the stated floor.

---

### Task 1: Frontend workspace, test harness, and typed API client

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/app/App.tsx`
- Create: `frontend/src/app/providers.tsx`
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/api/client.test.ts`

**Interfaces:**
- Consumes: FastAPI endpoints from the aggregation plan.
- Produces: `api.getSearches`, `createSearch`, `updateSearch`, `getJobs`, `getJob`, `startSync`, `retrySyncSource`, `getLatestSync`; shared `SavedSearch`, `JobCard`, `JobDetails`, `SyncRun` types.

- [x] **Step 1: Create the package scripts and dependencies**

Define scripts `dev`, `build`, `typecheck`, `test`, and `test:watch`. Add React, React DOM, React Router, TanStack Query; add Vite, TypeScript, Vitest, jsdom, Testing Library, user-event and MSW as dev dependencies.

- [x] **Step 2: Write the failing API-client test**

```tsx
it("encode les filtres d'offres dans la requête", async () => {
  server.use(http.get("/api/jobs", ({ request }) => {
    const url = new URL(request.url)
    expect(url.searchParams.get("period")).toBe("3d")
    expect(url.searchParams.getAll("source")).toEqual(["freework", "linkedin"])
    return HttpResponse.json({ items: [], total: 0, limit: 24, offset: 0 })
  }))
  await api.getJobs({ period: "3d", sources: ["freework", "linkedin"], limit: 24, offset: 0 })
})
```

- [x] **Step 3: Verify failure**

Run: `cd frontend && pnpm test src/api/client.test.ts`

Expected: FAIL because the client does not exist.

- [x] **Step 4: Implement types and fetch wrapper**

```ts
export type JobFilters = {
  savedSearchId?: string; period: "24h" | "3d" | "7d" | "all";
  query?: string; locations?: string[]; contracts?: string[]; remote?: boolean;
  experience?: string[]; salaryMin?: number; companies?: string[]; sources?: string[];
  skills?: string[]; duplicateState?: "confirmed" | "possible" | "none"; sort?: "date" | "relevance";
  limit: number; offset: number;
}
```

The fetch wrapper throws `ApiError(status, detail)` from FastAPI error payloads and supports `AbortSignal`.

- [x] **Step 5: Verify tests and types**

Run: `cd frontend && pnpm test src/api/client.test.ts && pnpm typecheck`

Expected: client test and typecheck pass.

- [x] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat: scaffold typed React frontend"
```

### Task 2: App shell and saved-search management

**Files:**
- Create: `frontend/src/features/searches/SearchSelector.tsx`
- Create: `frontend/src/features/searches/SearchEditor.tsx`
- Create: `frontend/src/features/searches/searches.test.tsx`
- Create: `frontend/src/components/AppHeader.tsx`
- Create: `frontend/src/styles/base.css`
- Modify: `frontend/src/app/App.tsx`

**Interfaces:**
- Consumes: saved-search client methods.
- Produces: selected search ID in route `/?search=<uuid>`; create/edit/suspend interactions; header slots for sync status and refresh action.

- [x] **Step 1: Write the failing French saved-search flow**

```tsx
it("crée puis sélectionne une recherche enregistrée", async () => {
  renderApp()
  await user.click(screen.getByRole("button", { name: "Nouvelle recherche" }))
  await user.type(screen.getByLabelText("Nom"), "Backend remote")
  await user.type(screen.getByLabelText("Mots-clés"), "backend")
  await user.click(screen.getByLabelText("Free-Work"))
  await user.click(screen.getByRole("button", { name: "Enregistrer" }))
  expect(await screen.findByRole("combobox", { name: "Recherche enregistrée" })).toHaveValue(expect.any(String))
})
```

- [x] **Step 2: Verify failure**

Run: `cd frontend && pnpm test src/features/searches/searches.test.tsx`

- [x] **Step 3: Implement shell, selector, and accessible editor**

Editor fields are name, keywords, title, location, radius, contracts, workplace, experience, sources and active state. Use semantic labels, fieldset/legend groups, inline French validation, Escape-to-close and focus restoration.

- [x] **Step 4: Verify behavior and responsive shell**

Run: `cd frontend && pnpm test src/features/searches/searches.test.tsx && pnpm typecheck`

Expected: create, edit, suspend and selection tests pass.

- [x] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: manage saved searches in French UI"
```

### Task 3: Period shortcuts, filter bar, and URL state

**Files:**
- Create: `frontend/src/features/jobs/PeriodTabs.tsx`
- Create: `frontend/src/features/jobs/JobFilters.tsx`
- Create: `frontend/src/features/jobs/useJobFilters.ts`
- Create: `frontend/src/features/jobs/filters.test.tsx`
- Modify: `frontend/src/app/App.tsx`

**Interfaces:**
- Produces: `useJobFilters() -> { filters: JobFilters; setFilter; clearFilters; activeCount }`; URL keys `period`, `q`, `lieu`, `contrat`, `remote`, `experience`, `salaire`, `entreprise`, `source`, `competence`, `doublon`, `tri`.

- [x] **Step 1: Write failing period and reset tests**

```tsx
it("applique 3 jours et réinitialise les filtres", async () => {
  renderApp({ initialUrl: "/?period=24h&source=freework" })
  await user.click(screen.getByRole("button", { name: "3 jours" }))
  expect(window.location.search).toContain("period=3d")
  await user.click(screen.getByRole("button", { name: "Effacer les filtres" }))
  expect(window.location.search).toBe("?period=3d")
})
```

- [x] **Step 2: Verify failure**

Run: `cd frontend && pnpm test src/features/jobs/filters.test.tsx`

- [x] **Step 3: Implement URL-backed filters**

Default period is `3d`; debounce text search by 250 ms; preserve selected saved search when clearing filters. Render filters in one horizontal desktop bar and an accessible collapsible panel below 768 px.

- [x] **Step 4: Verify filter serialization and accessibility**

Run: `cd frontend && pnpm test src/features/jobs/filters.test.tsx && pnpm typecheck`

- [x] **Step 5: Commit**

```bash
git add frontend/src/features/jobs frontend/src/app/App.tsx
git commit -m "feat: add instant local job filters"
```

### Task 4: Responsive job-card grid, pagination, and states

**Files:**
- Create: `frontend/src/features/jobs/JobGrid.tsx`
- Create: `frontend/src/features/jobs/JobCard.tsx`
- Create: `frontend/src/features/jobs/JobGridSkeleton.tsx`
- Create: `frontend/src/features/jobs/job-grid.test.tsx`
- Create: `frontend/src/styles/jobs.css`
- Modify: `frontend/src/app/App.tsx`

**Interfaces:**
- Consumes: `api.getJobs(filters)` and `JobCard` DTO.
- Produces: selectable cards, source badges, possible-duplicate badge, empty/error/retry states, 24-item pages.

- [x] **Step 1: Write failing grid-state tests**

```tsx
it("affiche les sources et le doublon possible", async () => {
  renderAppWithJobs([POSSIBLE_DUPLICATE_JOB])
  expect(await screen.findByText("Développeur Python")).toBeVisible()
  expect(screen.getByText("Free-Work")).toBeVisible()
  expect(screen.getByText("LinkedIn")).toBeVisible()
  expect(screen.getByText("Doublon possible")).toBeVisible()
})
```

Add tests for `Aucune offre ne correspond à ces filtres`, API error with `Réessayer`, and next-page query.

- [x] **Step 2: Verify failure**

Run: `cd frontend && pnpm test src/features/jobs/job-grid.test.tsx`

- [x] **Step 3: Implement cards and CSS grid**

Cards show title, company, location, contract, relative date, remote, salary and source badges when present. Use `grid-template-columns: repeat(auto-fill, minmax(280px, 1fr))`; do not invent missing values.

- [x] **Step 4: Verify tests and production build**

Run: `cd frontend && pnpm test src/features/jobs/job-grid.test.tsx && pnpm build`

Expected: tests pass and Vite produces `frontend/dist`.

- [x] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: display responsive job-card grid"
```

### Task 5: Sliding detail drawer and duplicate navigation

**Files:**
- Create: `frontend/src/features/details/JobDetailsDrawer.tsx`
- Create: `frontend/src/features/details/SourceLinks.tsx`
- Create: `frontend/src/features/details/PossibleDuplicates.tsx`
- Create: `frontend/src/features/details/details.test.tsx`
- Create: `frontend/src/styles/drawer.css`
- Modify: `frontend/src/app/App.tsx`

**Interfaces:**
- Consumes: `api.getJob(id)` returning `cacheState`, `updatedAt`, `warning`, source links and possible duplicates.
- Produces: route query `job=<uuid>`, right drawer on desktop, full-screen sheet below 768 px, focus trap and return-to-card behavior.

- [ ] **Step 1: Write failing cached-detail flow**

```tsx
it("ouvre les détails et suit un doublon possible", async () => {
  renderAppWithJobs([JOB], { details: DETAILS_WITH_DUPLICATE })
  await user.click(await screen.findByRole("button", { name: "Voir Développeur Python" }))
  expect(await screen.findByRole("dialog", { name: "Détails de l’offre" })).toBeVisible()
  expect(screen.getByText("Détails mis à jour aujourd’hui")).toBeVisible()
  await user.click(screen.getByRole("button", { name: "Voir l’offre similaire Backend Python" }))
  expect(window.location.search).toContain(`job=${POSSIBLE_DUPLICATE_ID}`)
})
```

- [ ] **Step 2: Verify failure**

Run: `cd frontend && pnpm test src/features/details/details.test.tsx`

- [ ] **Step 3: Implement drawer states and source links**

Render skeleton while the API loads cached/fresh details, a non-blocking warning for stale fallback, sanitized plain-text description formatting, skills/benefits chips, and one external link per source with `target="_blank" rel="noreferrer"`.

- [ ] **Step 4: Verify keyboard and mobile behavior**

Test Escape, close button, focus restoration, missing description, stale warning and possible-duplicate navigation. Run: `cd frontend && pnpm test src/features/details/details.test.tsx && pnpm typecheck`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: add cached job-detail drawer"
```

### Task 6: Manual refresh and source-by-source progress

**Files:**
- Create: `frontend/src/features/sync/RefreshButton.tsx`
- Create: `frontend/src/features/sync/SyncProgress.tsx`
- Create: `frontend/src/features/sync/useSyncRun.ts`
- Create: `frontend/src/features/sync/sync.test.tsx`
- Modify: `frontend/src/components/AppHeader.tsx`

**Interfaces:**
- Consumes: sync API methods and statuses.
- Produces: manual refresh, five-second polling while active, source retry, and latest-sync summary.

- [ ] **Step 1: Write failing partial-sync test**

```tsx
it("reste utilisable et relance uniquement la source en échec", async () => {
  renderAppWithSync(PARTIAL_SYNC)
  expect(await screen.findByText("Free-Work : terminée")).toBeVisible()
  expect(screen.getByText("LinkedIn : échec")).toBeVisible()
  await user.click(screen.getByRole("button", { name: "Relancer LinkedIn" }))
  expect(retrySyncSource).toHaveBeenCalledWith(PARTIAL_SYNC.id, "linkedin")
  expect(screen.getByText("Développeur Python")).toBeVisible()
})
```

- [ ] **Step 2: Verify failure**

Run: `cd frontend && pnpm test src/features/sync/sync.test.tsx`

- [ ] **Step 3: Implement refresh and progress**

Disable only duplicate launch actions, not the result grid. Poll every five seconds while status is pending/running and stop on succeeded/partial/failed. Invalidate job queries after any source completes successfully.

- [ ] **Step 4: Verify sync UI**

Run: `cd frontend && pnpm test src/features/sync/sync.test.tsx && pnpm typecheck`

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: show manual synchronization progress"
```

### Task 7: Frontend verification and API static hosting

**Files:**
- Modify: `src/jobscraper/api/app.py`
- Modify: `pyproject.toml`
- Create: `tests/api/test_frontend_hosting.py`
- Modify: `README.md`

**Interfaces:**
- Produces: built SPA served by FastAPI at `/`, `/assets/*`, and fallback client routes; `/api/*` remains API-only.

- [ ] **Step 1: Write failing static-hosting test**

```python
def test_frontend_index_is_served(client_with_built_frontend):
    response = client_with_built_frontend.get("/")
    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
```

- [ ] **Step 2: Build and verify the failure**

Run: `cd frontend && pnpm build`

Run: `.venv/bin/python -m pytest tests/api/test_frontend_hosting.py -v`

- [ ] **Step 3: Mount the built frontend safely**

Serve `frontend/dist/assets` with `StaticFiles`; return `index.html` only for non-API GET routes. If `dist` is absent, API startup remains valid and `/` returns a French development hint instead of crashing.

- [ ] **Step 4: Run complete frontend gates**

Run: `cd frontend && pnpm test --run`

Run: `cd frontend && pnpm typecheck`

Run: `cd frontend && pnpm build`

Expected: all commands pass.

- [ ] **Step 5: Run backend hosting test**

Run: `.venv/bin/python -m pytest tests/api/test_frontend_hosting.py -v`

- [ ] **Step 6: Commit**

```bash
git add frontend src/jobscraper/api/app.py tests/api/test_frontend_hosting.py pyproject.toml README.md
git commit -m "feat: serve production React interface"
```
