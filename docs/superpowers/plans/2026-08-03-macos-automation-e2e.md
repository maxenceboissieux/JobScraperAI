# macOS Automation and End-to-End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide one-command local operation, install a configurable daily macOS job with catch-up behavior, and verify the complete saved-search-to-detail workflow.

**Architecture:** A Click `serve` command owns database migration, optional frontend build validation, and Uvicorn startup. A separate `sync-saved-searches` command is safe for `launchd`; a plist generator installs a user agent at 08:00 local time by default. Playwright tests run against fake scraper adapters and a temporary SQLite database.

**Tech Stack:** Python Click, launchd property lists, FastAPI/Uvicorn, SQLite/Alembic, Playwright, pytest.

## Global Constraints

- Default daily schedule is 08:00 in the Mac's local timezone and is configurable.
- Installation is user-scoped; no administrator privileges or system daemon is required.
- A missed daily run is caught up at the next application startup.
- Manual refresh remains available regardless of scheduler installation.
- Automated end-to-end tests never scrape public websites.
- Documentation and command output are French.
- Before running frontend commands in this workspace, run `export PATH="/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH"`.

---

### Task 1: Headless saved-search synchronization command

**Files:**
- Modify: `src/jobscraper/cli.py`
- Create: `src/jobscraper/runtime.py`
- Create: `tests/test_sync_command.py`

**Interfaces:**
- Produces: `jobscraper sync-saved-searches [--search-id UUID] [--source NAME]`; `build_runtime(database_url) -> RuntimeServices` shared by CLI and API.

- [x] **Step 1: Write the failing command test**

```python
def test_sync_saved_searches_runs_all_active_searches(runner, runtime):
    result = runner.invoke(main, ["sync-saved-searches"], obj={"runtime": runtime})
    assert result.exit_code == 0
    assert runtime.sync_service.calls == [(ACTIVE_SEARCH_ID, None)]
    assert "Synchronisation terminée" in result.output
```

Add tests for inactive searches, `--search-id`, `--source freework`, partial failure exit code `2`, and total failure exit code `1`.

- [x] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/test_sync_command.py -v`

- [x] **Step 3: Implement shared runtime composition and command**

`build_runtime()` creates engine/session factory, repositories, registry, deduplicator, sync service and detail service exactly once. The command migrates the configured database before reading active searches and prints a compact Rich table per source.

- [x] **Step 4: Verify command tests**

Run: `.venv/bin/python -m pytest tests/test_sync_command.py -v`

- [x] **Step 5: Commit**

```bash
git add src/jobscraper/cli.py src/jobscraper/runtime.py tests/test_sync_command.py
git commit -m "feat: add headless saved-search sync command"
```

### Task 2: launchd plist generation, installation, and removal

**Files:**
- Create: `src/jobscraper/automation/launchd.py`
- Modify: `src/jobscraper/cli.py`
- Create: `tests/automation/test_launchd.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `render_launch_agent(project_dir: Path, python_path: Path, hour: int, minute: int) -> bytes`; CLI commands `automation install [--hour 8 --minute 0]`, `automation status`, `automation uninstall`.

- [x] **Step 1: Write deterministic plist tests**

```python
plist = plistlib.loads(render_launch_agent(PROJECT, PYTHON, hour=8, minute=0))
assert plist["Label"] == "com.jobscraper.daily-sync"
assert plist["ProgramArguments"] == [str(PYTHON), "-m", "jobscraper.cli", "sync-saved-searches"]
assert plist["StartCalendarInterval"] == {"Hour": 8, "Minute": 0}
assert plist["WorkingDirectory"] == str(PROJECT)
```

Assert logs go to `data/logs/launchd.out.log` and `launchd.err.log`, and hour/minute validation rejects 24/60.

- [x] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/automation/test_launchd.py -v`

- [x] **Step 3: Implement pure plist rendering**

Use `plistlib`; resolve absolute project and interpreter paths; include `RunAtLoad: false`; never embed shell strings or secrets. Write files atomically through a temporary sibling and `Path.replace()`.

- [x] **Step 4: Implement user-scoped CLI lifecycle**

Install at `~/Library/LaunchAgents/com.jobscraper.daily-sync.plist` and run `launchctl bootstrap gui/<uid> <plist>`. Installation does not trigger an immediate scrape; the existing manual refresh handles that choice. Uninstall with `launchctl bootout` before deleting only that exact plist. `status` reads `launchctl print` and reports French state.

- [x] **Step 5: Test subprocess boundaries without touching real launchd**

Mock `subprocess.run` and assert exact argument arrays, error propagation, idempotent reinstall, and no deletion outside the exact user plist path.

- [x] **Step 6: Verify tests**

Run: `.venv/bin/python -m pytest tests/automation/test_launchd.py -v`

- [x] **Step 7: Commit**

```bash
git add src/jobscraper/automation src/jobscraper/cli.py tests/automation .gitignore
git commit -m "feat: automate daily sync with launchd"
```

### Task 3: Missed-run catch-up and single serve command

**Files:**
- Create: `src/jobscraper/services/catchup.py`
- Modify: `src/jobscraper/cli.py`
- Modify: `src/jobscraper/api/app.py`
- Create: `tests/services/test_catchup.py`
- Create: `tests/test_serve_command.py`

**Interfaces:**
- Produces: `CatchupService.is_due(now: datetime, last_completed_at: datetime | None, scheduled_hour: int = 8) -> bool`; `jobscraper serve [--host 127.0.0.1 --port 8000] [--no-open]`.

- [x] **Step 1: Write due/not-due boundary tests**

```python
assert service.is_due(datetime(2026, 8, 3, 9, tzinfo=PARIS), None, 8)
assert service.is_due(datetime(2026, 8, 3, 9, tzinfo=PARIS), datetime(2026, 8, 2, 8, tzinfo=PARIS), 8)
assert not service.is_due(datetime(2026, 8, 3, 9, tzinfo=PARIS), datetime(2026, 8, 3, 8, 5, tzinfo=PARIS), 8)
```

- [x] **Step 2: Write failing serve-command test**

Assert `serve` upgrades Alembic, checks the built frontend, schedules catch-up in the bounded executor when due, starts Uvicorn and opens `http://127.0.0.1:8000` unless `--no-open` is supplied.

- [x] **Step 3: Verify failures**

Run: `.venv/bin/python -m pytest tests/services/test_catchup.py tests/test_serve_command.py -v`

- [x] **Step 4: Implement timezone-safe catch-up**

Use `zoneinfo.ZoneInfo` with the configured local timezone; compare calendar schedule instants rather than elapsed 24-hour durations. Catch-up triggers at most once per process startup and uses the same sync service as manual/daily runs.

- [x] **Step 5: Implement `serve` orchestration**

Fail with a French actionable message if migrations or frontend assets are invalid. Browser opening uses Python `webbrowser.open()` after the socket becomes reachable; `--no-open` suppresses it for automation and tests.

- [x] **Step 6: Verify tests**

Run: `.venv/bin/python -m pytest tests/services/test_catchup.py tests/test_serve_command.py -v`

- [x] **Step 7: Commit**

```bash
git add src/jobscraper/services/catchup.py src/jobscraper/cli.py src/jobscraper/api/app.py tests
git commit -m "feat: catch up missed daily synchronization"
```

### Task 4: Deterministic end-to-end browser fixture mode

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/job-flow.spec.ts`
- Create: `tests/e2e/fake_scrapers.py`
- Create: `scripts/run-e2e.sh`

**Interfaces:**
- Consumes: production CLI/API/frontend with `JOBSCRAPER_SCRAPER_MODE=fake` and temporary SQLite URL.
- Produces: `pnpm e2e` verifying saved search, sync, filters, detail cache, source links and possible duplicate navigation.

- [ ] **Step 1: Add Playwright and an isolated web-server command**

The test command creates a temporary directory, upgrades its SQLite database, builds the frontend, starts `jobscraper serve --no-open` on an available localhost port with fake adapters, and tears down the process on exit.

- [ ] **Step 2: Write the failing complete user journey**

```ts
test("recherche, synchronisation, filtres, cache et doublon possible", async ({ page }) => {
  await page.goto("/")
  await page.getByRole("button", { name: "Nouvelle recherche" }).click()
  await page.getByLabel("Nom").fill("Backend remote")
  await page.getByLabel("Mots-clés").fill("backend")
  await page.getByLabel("Free-Work").check()
  await page.getByRole("button", { name: "Enregistrer" }).click()
  await page.getByRole("button", { name: "Actualiser" }).click()
  await expect(page.getByText("Free-Work : terminée")).toBeVisible()
  await page.getByRole("button", { name: "3 jours" }).click()
  await page.getByRole("button", { name: "Voir Développeur Python" }).click()
  await expect(page.getByRole("dialog", { name: "Détails de l’offre" })).toContainText("Description mise en cache")
  await page.getByRole("button", { name: "Voir l’offre similaire Backend Python" }).click()
  await expect(page.getByRole("dialog", { name: "Détails de l’offre" })).toContainText("Backend Python")
})
```

- [ ] **Step 3: Verify the journey fails before fake adapter wiring**

Run: `cd frontend && pnpm e2e`

- [ ] **Step 4: Implement deterministic fake adapters**

Return two close-but-not-confirmed jobs from different sources, fixed UTC dates within three days, one cached description, and stable source URLs under `https://example.invalid/`. Enable fakes only when `JOBSCRAPER_SCRAPER_MODE=fake`; reject that value when `JOBSCRAPER_ENV=production`.

- [ ] **Step 5: Verify the full journey**

Run: `cd frontend && pnpm e2e`

Expected: the complete browser test passes without external network access.

- [ ] **Step 6: Commit**

```bash
git add frontend tests/e2e scripts/run-e2e.sh
git commit -m "test: cover local job aggregation journey"
```

### Task 5: Operator documentation and clean-machine verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Create: `docs/macOS-automation.md`

**Interfaces:**
- Produces: documented install, run, schedule, logs, recovery and uninstall procedures.

- [ ] **Step 1: Document the exact local workflow**

Include Python 3.12 and Node 20 prerequisites; `.venv` creation; `pip install -e '.[dev]'`; `pnpm install`; frontend build; `alembic upgrade head`; `jobscraper serve`; saved-search creation; manual refresh; `jobscraper automation install --hour 8 --minute 0`; status, logs and uninstall.

- [ ] **Step 2: Document scheduler behavior and limits**

State that the Mac must eventually wake, missed schedules catch up at application startup, data stays local under `data/`, source HTML can change, and public-site terms/rate limits must be respected.

- [ ] **Step 3: Run every automated gate from a clean environment**

Run: `.venv/bin/python -m pytest -m 'not live' --cov=jobscraper`

Run: `.venv/bin/python -m mypy src/jobscraper`

Run: `cd frontend && pnpm test --run && pnpm typecheck && pnpm build && pnpm e2e`

Expected: all commands pass.

- [ ] **Step 4: Perform bounded live Free-Work verification**

Run: `RUN_LIVE_SCRAPER_TESTS=1 .venv/bin/python -m pytest tests/live/test_sources_live.py -k FreeWork -v`

Expected: Free-Work returns at least one valid current offer and details; if blocked externally, retain passing fixture tests and record the exact HTTP evidence without claiming live success.

- [ ] **Step 5: Install and inspect the real user agent with confirmation**

Run: `.venv/bin/jobscraper automation install --hour 8 --minute 0`

Run: `.venv/bin/jobscraper automation status`

Expected: `com.jobscraper.daily-sync` is loaded for the current GUI user and points to the project `.venv` interpreter.

- [ ] **Step 6: Commit**

```bash
git add README.md .env.example docs/macOS-automation.md
git commit -m "docs: explain local operation and automation"
```

### Task 6: Final verification

**Files:**
- Verify only.

**Interfaces:**
- Produces: evidence that the approved design is complete.

- [ ] **Step 1: Verify repository state and migrations**

Run: `git status --short`

Run: `.venv/bin/alembic current`

Expected: no tracked changes remain and database revision equals migration head.

- [ ] **Step 2: Verify the user-facing app**

Run: `.venv/bin/jobscraper serve --no-open`

Open `http://127.0.0.1:8000`, create a saved search, manually refresh, select each period, apply source and contract filters, open details, follow a possible duplicate, and confirm the page remains usable during refresh.

- [ ] **Step 3: Verify schedule recovery**

With a test database whose last successful run predates today's 08:00 schedule, start `jobscraper serve --no-open` and assert one catch-up run is created. Restart after completion and assert no second catch-up run is created that day.

- [ ] **Step 4: Record final evidence**

Capture exact test totals, build result, live Free-Work outcome, launchd status, and any externally blocked source in the completion report. Do not describe externally blocked sources as working.
