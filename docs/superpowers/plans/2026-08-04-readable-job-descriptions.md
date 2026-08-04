# Readable Job Descriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render cached job descriptions as conservative semantic sections, paragraphs and lists while preserving every source word and improving future LinkedIn text separators.

**Architecture:** A pure TypeScript parser converts the unchanged API description string into typed display blocks. A focused React component renders those blocks safely as text, while the LinkedIn scraper preserves block separators for future cached descriptions. The API and database contracts remain unchanged.

**Tech Stack:** React 19, TypeScript 5.9, Vitest, Testing Library, Python 3.12, BeautifulSoup, pytest, Playwright.

## Global Constraints

- Never summarize, translate, reformulate or delete recruiter-provided text.
- Keep the original description string as the database and API source of truth.
- Never inject source HTML; React must render source content as text nodes.
- Ambiguous structure remains a paragraph.
- Existing cached descriptions must improve without a migration or re-scrape.
- Do not add runtime dependencies or change the detail API schema.
- Preserve the current drawer focus trap, keyboard navigation, scrolling and mobile behavior.
- Before frontend commands, use `PATH=/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH`.

---

## File Structure

- `frontend/src/features/details/job-description-parser.ts`: pure text-to-block parser with no React, browser, network or API dependency.
- `frontend/src/features/details/job-description-parser.test.ts`: parser conservation, headings, lists, ambiguity and hostile-text contracts.
- `frontend/src/features/details/JobDescription.tsx`: semantic React renderer for parsed blocks.
- `frontend/src/features/details/JobDescription.test.tsx`: component semantics and safe text-rendering tests.
- `frontend/src/features/details/JobDetailsDrawer.tsx`: replace the existing double-newline paragraph loop with `JobDescription`.
- `frontend/src/styles/drawer.css`: description headings, paragraphs, lists and responsive spacing.
- `src/jobscraper/scrapers/linkedin.py`: preserve meaningful description separators during LinkedIn detail extraction.
- `tests/services/test_details.py`: exercise LinkedIn detail extraction through the existing detail-service path.
- `src/jobscraper/testing/fake_scrapers.py`: deterministic structured description for the browser journey.
- `frontend/e2e/job-flow.spec.ts`: assert semantic sections and lists in the real production journey.

---

### Task 1: Conservative description parser

**Files:**
- Create: `frontend/src/features/details/job-description-parser.ts`
- Create: `frontend/src/features/details/job-description-parser.test.ts`

**Interfaces:**
- Consumes: `parseJobDescription(description: string)` receives the unchanged API description.
- Produces: exported `DescriptionBlock` union and `parseJobDescription(description: string): DescriptionBlock[]` for the React renderer.

- [ ] **Step 1: Write failing parser tests for headings and concatenated LinkedIn text**

Create `job-description-parser.test.ts` with the exact public contract:

```ts
import { describe, expect, it } from "vitest";

import { parseJobDescription } from "./job-description-parser";

describe("parseJobDescription", () => {
  it("sépare les titres connus concaténés sans reformuler le contenu", () => {
    expect(
      parseJobDescription(
        "PRÉSENTATION DE L’ENTREPRISEL’entreprise compte 150 personnes." +
          "DESCRIPTION DU POSTEIntégré(e) à l’équipe Scrum, vous développez le produit.",
      ),
    ).toEqual([
      { type: "heading", text: "PRÉSENTATION DE L’ENTREPRISE" },
      { type: "paragraph", text: "L’entreprise compte 150 personnes." },
      { type: "heading", text: "DESCRIPTION DU POSTE" },
      {
        type: "paragraph",
        text: "Intégré(e) à l’équipe Scrum, vous développez le produit.",
      },
    ]);
  });

  it("reconnaît les titres français et anglais sur leurs propres lignes", () => {
    expect(
      parseJobDescription("Missions\nConstruire le produit.\nABOUT THE ROLE\nOwn the API."),
    ).toEqual([
      { type: "heading", text: "Missions" },
      { type: "paragraph", text: "Construire le produit." },
      { type: "heading", text: "ABOUT THE ROLE" },
      { type: "paragraph", text: "Own the API." },
    ]);
  });
});
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
cd frontend
PATH=/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm test --run src/features/details/job-description-parser.test.ts
```

Expected: FAIL because `job-description-parser` does not exist.

- [ ] **Step 3: Add failing list, fallback and conservation tests**

Add tests that require:

```ts
it("convertit les marqueurs explicites en liste", () => {
  expect(parseJobDescription("Vos missions :\n- Concevoir\n• Tester\n* Documenter")).toEqual([
    { type: "heading", text: "Vos missions" },
    { type: "list", items: ["Concevoir", "Tester", "Documenter"] },
  ]);
});

it("convertit une énumération au point-virgule uniquement après une introduction", () => {
  expect(
    parseJobDescription("Vos missions : Comprendre le besoin ; Développer ; Livrer."),
  ).toEqual([
    { type: "heading", text: "Vos missions" },
    { type: "list", items: ["Comprendre le besoin", "Développer", "Livrer."] },
  ]);
});

it("laisse un texte ambigu dans un paragraphe", () => {
  expect(parseJobDescription("Paris ; Lyon ; télétravail possible")).toEqual([
    { type: "paragraph", text: "Paris ; Lyon ; télétravail possible" },
  ]);
});

it("conserve les chaînes ressemblant à du HTML comme texte", () => {
  expect(parseJobDescription("<img src=x onerror=alert(1)> Profil recherché")).toEqual([
    { type: "paragraph", text: "<img src=x onerror=alert(1)>" },
    { type: "heading", text: "Profil recherché" },
  ]);
});
```

Add a conservation helper inside the test file which joins heading text, paragraph text and list items, then assert every non-structural source segment remains present and ordered for one 10,000-character description.

- [ ] **Step 4: Implement the minimal pure parser**

Create `job-description-parser.ts` with these types and deterministic stages:

```ts
export type DescriptionBlock =
  | { type: "heading"; text: string }
  | { type: "paragraph"; text: string }
  | { type: "list"; items: string[] };

const SECTION_LABELS = [
  "présentation de l’entreprise",
  "présentation de l'entreprise",
  "description du poste",
  "missions",
  "vos missions",
  "missions principales",
  "profil recherché",
  "votre profil",
  "compétences",
  "avantages",
  "à propos",
  "about the role",
  "about us",
  "responsibilities",
  "requirements",
  "benefits",
] as const;

export function parseJobDescription(description: string): DescriptionBlock[] {
  // 1. Normalize CRLF and whitespace-only lines, without changing visible words.
  // 2. Insert line boundaries immediately before and after exact SECTION_LABELS,
  //    including labels glued to adjacent text.
  // 3. Classify exact labels and short uppercase lines as headings.
  // 4. Group consecutive explicit list markers into one list block.
  // 5. Split semicolon lists only when introduced by a recognized heading plus ':'.
  // 6. Merge consecutive ordinary lines into paragraphs and return them in order.
}
```

Implement matching case-insensitively with escaped literal labels, require uppercase headings to contain 2–8 words and at least 70% letters in uppercase, and strip only boundary whitespace plus explicit list markers. Do not use `dangerouslySetInnerHTML`, DOM APIs or an NLP dependency.

- [ ] **Step 5: Run parser tests and frontend typecheck**

Run:

```bash
cd frontend
PATH=/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm test --run src/features/details/job-description-parser.test.ts
PATH=/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm typecheck
```

Expected: all parser tests pass and TypeScript reports no errors.

- [ ] **Step 6: Commit the parser**

```bash
git add frontend/src/features/details/job-description-parser.ts frontend/src/features/details/job-description-parser.test.ts
git commit -m "feat: parse job descriptions into readable blocks"
```

---

### Task 2: Semantic description renderer

**Files:**
- Create: `frontend/src/features/details/JobDescription.tsx`
- Create: `frontend/src/features/details/JobDescription.test.tsx`
- Modify: `frontend/src/features/details/JobDetailsDrawer.tsx`
- Modify: `frontend/src/styles/drawer.css`
- Modify: `frontend/src/features/details/details.test.tsx`

**Interfaces:**
- Consumes: `parseJobDescription(description)` and `DescriptionBlock` from Task 1.
- Produces: `JobDescription({ description }: { description: string }): JSX.Element | null` used by `JobDetailsDrawer`.

- [ ] **Step 1: Write failing semantic renderer tests**

Create `JobDescription.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { JobDescription } from "./JobDescription";

describe("JobDescription", () => {
  it("rend les sections et listes avec une sémantique accessible", () => {
    render(
      <JobDescription description={"MISSIONS\n- Concevoir\n- Tester"} />,
    );
    const region = screen.getByRole("region", { name: "Description" });
    expect(within(region).getByRole("heading", { name: "MISSIONS" })).toBeVisible();
    expect(within(region).getByRole("list")).toBeVisible();
    expect(within(region).getAllByRole("listitem")).toHaveLength(2);
  });

  it("affiche le pseudo-HTML comme texte inerte", () => {
    const { container } = render(
      <JobDescription description={'<img src="x" onerror="alert(1)">'} />,
    );
    expect(screen.getByText('<img src="x" onerror="alert(1)">')).toBeVisible();
    expect(container.querySelector("img")).toBeNull();
  });

  it("ne rend rien pour une description vide", () => {
    const { container } = render(<JobDescription description="   " />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run the component test and verify RED**

Run:

```bash
cd frontend
PATH=/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm test --run src/features/details/JobDescription.test.tsx
```

Expected: FAIL because `JobDescription` does not exist.

- [ ] **Step 3: Implement `JobDescription` and integrate it into the drawer**

Implement semantic text-only rendering:

```tsx
import { parseJobDescription } from "./job-description-parser";

export function JobDescription({ description }: { description: string }) {
  const blocks = parseJobDescription(description);
  if (blocks.length === 0) return null;
  return (
    <section className="job-drawer__description" aria-labelledby="job-description-title">
      <h3 id="job-description-title">Description</h3>
      <div className="job-description__blocks">
        {blocks.map((block, index) => {
          if (block.type === "heading") {
            return <h4 key={`${index}:${block.text}`}>{block.text}</h4>;
          }
          if (block.type === "list") {
            return <ul key={index}>{block.items.map((item, itemIndex) => <li key={`${itemIndex}:${item}`}>{item}</li>)}</ul>;
          }
          return <p key={`${index}:${block.text}`}>{block.text}</p>;
        })}
      </div>
    </section>
  );
}
```

In `JobDetailsDrawer.tsx`, replace the existing `.split(...).map(<p>)` block with:

```tsx
{detailsQuery.data.description?.trim() ? (
  <JobDescription description={detailsQuery.data.description} />
) : null}
```

- [ ] **Step 4: Add the approved visual hierarchy and responsive rules**

In `drawer.css`, retain the existing section border and add focused rules:

```css
.job-description__blocks {
  border-left: 3px solid var(--brand);
  padding-left: 16px;
}

.job-description__blocks h4 {
  margin: 24px 0 9px;
  color: var(--brand-dark);
  font-size: 0.86rem;
  letter-spacing: 0.025em;
  line-height: 1.35;
}

.job-description__blocks h4:first-child,
.job-description__blocks > :first-child {
  margin-top: 0;
}

.job-description__blocks p,
.job-description__blocks li {
  color: #314148;
  font-size: 0.94rem;
  line-height: 1.7;
}

.job-description__blocks p { margin: 0 0 15px; }
.job-description__blocks ul { margin: 0 0 17px; padding-left: 20px; }
.job-description__blocks li + li { margin-top: 7px; }

@media (max-width: 767px) {
  .job-description__blocks { padding-left: 12px; }
  .job-description__blocks h4 { margin-top: 20px; }
}
```

Remove or narrow the old `.job-drawer__description p` rule so it does not conflict.

- [ ] **Step 5: Update drawer integration tests**

Add a structured description fixture to `details.test.tsx`, open the existing drawer and assert that `Description du poste` is a level-4 heading, its missions are list items, the details title remains level 2, and closing the drawer still restores focus. Keep all existing history, duplicate and cache tests unchanged.

- [ ] **Step 6: Run focused and full frontend verification**

Run:

```bash
cd frontend
PATH=/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm test --run src/features/details/job-description-parser.test.ts src/features/details/JobDescription.test.tsx src/features/details/details.test.tsx
PATH=/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm test --run
PATH=/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm typecheck
PATH=/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm build
```

Expected: all tests, typecheck and build pass.

- [ ] **Step 7: Commit the renderer**

```bash
git add frontend/src/features/details frontend/src/styles/drawer.css
git commit -m "feat: render structured job descriptions"
```

---

### Task 3: Preserve LinkedIn description separators

**Files:**
- Modify: `src/jobscraper/scrapers/linkedin.py`
- Modify: `tests/services/test_details.py`

**Interfaces:**
- Consumes: LinkedIn detail `Tag` selected by `_parse_job_details`.
- Produces: `_extract_description_text(element: Tag | None) -> str | None`, still assigned to `JobOffer.description`.

- [ ] **Step 1: Write a failing LinkedIn detail preservation test**

Extend the existing numeric LinkedIn detail test with representative block markup:

```python
return """
<h1 class="top-card-layout__title">Python engineer</h1>
<a class="topcard__org-name-link">Acme</a>
<span class="topcard__flavor--bullet">Paris</span>
<div class="description__text">
  <h2>Description du poste</h2>
  <p>Construire le produit.</p>
  <p>Vos missions :</p>
  <ul><li>Concevoir</li><li>Tester</li></ul>
</div>
"""
```

Assert:

```python
assert result.job.description == (
    "Description du poste\n"
    "Construire le produit.\n"
    "Vos missions :\n"
    "Concevoir\n"
    "Tester"
)
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/services/test_details.py::test_linkedin_persisted_identifier_builds_real_numeric_detail_url -v
```

Expected: FAIL because `get_text(strip=True)` concatenates the blocks.

- [ ] **Step 3: Implement block-preserving extraction**

Add a static helper on `LinkedInScraper`:

```python
@staticmethod
def _extract_description_text(element: Tag | None) -> str | None:
    if element is None:
        return None
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in element.get_text("\n", strip=True).splitlines()
    ]
    text = "\n".join(line for line in lines if line)
    return text or None
```

Use the helper only for the LinkedIn detail description. Do not alter title, company, location, criteria or card parsing.

- [ ] **Step 4: Add inline-markup and empty-description tests**

Test that `<p>TypeScript <strong>senior</strong></p>` remains readable and ordered, allowing either one normalized line or adjacent lines that the frontend recombines without word loss. Test that an empty description container produces `None` and triggers the existing unavailable/stale behavior rather than an empty cached refresh.

- [ ] **Step 5: Run scraper and detail-service gates**

Run:

```bash
.venv/bin/python -m pytest tests/services/test_details.py tests/scrapers/test_existing_scrapers.py tests/scrapers/test_strict_search_health.py -v
.venv/bin/python -m mypy src/jobscraper
.venv/bin/python -m black --check src/jobscraper/scrapers/linkedin.py tests/services/test_details.py
.venv/bin/python -m isort --check-only src/jobscraper/scrapers/linkedin.py tests/services/test_details.py
```

Expected: all tests and static checks pass.

- [ ] **Step 6: Commit source preservation**

```bash
git add src/jobscraper/scrapers/linkedin.py tests/services/test_details.py
git commit -m "fix: preserve LinkedIn description structure"
```

---

### Task 4: Production journey and final validation

**Files:**
- Modify: `src/jobscraper/testing/fake_scrapers.py`
- Modify: `frontend/e2e/job-flow.spec.ts`

**Interfaces:**
- Consumes: production `jobscraper serve`, real FastAPI/SQLite/React build and fake scraper mode.
- Produces: browser evidence that semantic descriptions work in the complete local workflow.

- [ ] **Step 1: Make the E2E fixture structurally representative**

Change the fake detailed offer description to this deterministic text:

```python
description=(
    "DESCRIPTION DU POSTE"
    "Vous rejoignez une équipe produit."
    "VOS MISSIONS : Comprendre le besoin ; Développer ; Tester."
)
```

Keep the existing stable source URLs, dates, duplicate relations and detail-call counter unchanged.

- [ ] **Step 2: Add failing E2E assertions for semantic output**

After opening the detail drawer in `job-flow.spec.ts`, assert:

```ts
const dialog = page.getByRole("dialog", { name: "Détails de l’offre" });
await expect(dialog.getByRole("heading", { name: "DESCRIPTION DU POSTE" })).toBeVisible();
await expect(dialog.getByRole("heading", { name: "VOS MISSIONS" })).toBeVisible();
await expect(dialog.getByRole("listitem", { name: "Développer" })).toBeVisible();
```

Retain the existing assertion that two API detail requests cause only one fake scraper detail call.

- [ ] **Step 3: Run E2E and verify RED before the integrated feature**

Run:

```bash
cd frontend
PATH=/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm e2e
```

Expected before Tasks 1–3 are present: FAIL because headings and list items are not rendered semantically. When executing sequentially after Tasks 1–3, document the earlier focused RED evidence and proceed to GREEN.

- [ ] **Step 4: Run every final gate**

Run:

```bash
.venv/bin/python -m pytest -m 'not live' --cov=jobscraper
.venv/bin/python -m mypy src/jobscraper
cd frontend
PATH=/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm test --run
PATH=/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm typecheck
PATH=/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm build
PATH=/Users/maxence/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm e2e
```

Expected: backend, mypy, frontend tests, typecheck, production build and E2E all pass.

- [ ] **Step 5: Perform visual desktop and mobile checks**

Start the production app with a temporary database and fake scraper using `scripts/run-e2e.sh` or its exact environment setup. Inspect the detail drawer at a desktop viewport and below 767 px. Confirm the approved option-B hierarchy, no horizontal overflow, complete text, usable scrolling, visible bullets and unchanged close/focus behavior.

- [ ] **Step 6: Commit the production journey**

```bash
git add src/jobscraper/testing/fake_scrapers.py frontend/e2e/job-flow.spec.ts
git commit -m "test: cover readable job descriptions end to end"
```

- [ ] **Step 7: Record completion evidence**

Update the plan checkboxes and add exact test totals, build result, E2E result and visual viewport evidence to the active SDD ledger or completion report. Run `git status --short` and `git diff --check`; preserve `.env`, `.idea/`, `.pnpm-store/` and local database files as untracked user state.
