# Viewed Card Layout Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the empty band above viewed-card titles and the white strip below shorter cards while preserving the approved upper-right viewed indicator.

**Architecture:** Keep `JobCard` as the sole presentation component and introduce a focused header wrapper around the title and optional viewed label. Use CSS grid only when the label exists, and make both the article and its button fill the grid-row height so unequal content lengths cannot expose page background below a shorter button.

**Tech Stack:** React 19, TypeScript 5.9, CSS Grid/Flexbox, Vitest 3, Testing Library, MSW, pnpm, in-app browser verification.

## Global Constraints

- The exact visible viewed label remains `✓ Déjà vue` in the upper-right area.
- The viewed button accessible name remains `Voir l’offre {title}, déjà vue`; unseen accessible names remain unchanged.
- Unseen cards do not reserve an empty label column and retain their current visual presentation.
- Long titles wrap naturally and never overlap the viewed label.
- Every card button and bottom border fill the complete height of its grid row.
- Metadata, salary, source badges, duplicate badges, clicks, filters, persistence, API, and database behavior remain unchanged.
- No backend, API, database, grid-column sizing, typography, or color changes are in scope.
- Preserve the user-owned untracked `.env`, `.idea/`, `.pnpm-store/`, and `jobscraper.db` paths.

---

## File Structure

- Modify `frontend/src/features/jobs/JobCard.tsx`: group the existing title and optional label in a state-aware header; do not add behavior.
- Modify `frontend/src/styles/jobs.css`: define the viewed header layout and full-height card chain.
- Modify `frontend/src/features/jobs/job-grid.test.tsx`: prove the DOM relationship, state-specific header modifier, full-height rules, and preserved accessibility.

### Task 1: Align the viewed-card header and bottom borders

**Files:**
- Modify: `frontend/src/features/jobs/JobCard.tsx:26-43`
- Modify: `frontend/src/styles/jobs.css:14-80`
- Test: `frontend/src/features/jobs/job-grid.test.tsx:160-205`

**Interfaces:**
- Consumes: `JobCardDto.viewedAt: string | null`, `JobCardDto.title: string`, and the existing `onSelect(jobId: string)` callback.
- Produces: `.job-card__header` on every card, `.job-card__header--viewed` only on viewed cards, and full-height `.job-card`/`.job-card__button` layout.

- [ ] **Step 1: Extend the viewed-card test with failing structure and layout assertions**

In `frontend/src/features/jobs/job-grid.test.tsx`, keep the existing viewed-card accessibility assertions and extend the test named `attenuates a viewed card and exposes the explicit label` after `const card = ...`:

```tsx
const button = within(card).getByRole("button", {
  name: "Voir l’offre Développeur Python, déjà vue",
});
const header = card.querySelector<HTMLElement>(".job-card__header");
expect(header).not.toBeNull();
expect(header).toHaveClass("job-card__header--viewed");
expect(
  within(header as HTMLElement).getByRole("heading", {
    name: "Développeur Python",
  }),
).toBeVisible();
expect(within(header as HTMLElement).getByText("✓ Déjà vue")).toBeVisible();

const cardStyle = getComputedStyle(card);
const buttonStyle = getComputedStyle(button);
const headerStyle = getComputedStyle(header as HTMLElement);
const labelStyle = getComputedStyle(
  within(header as HTMLElement).getByText("✓ Déjà vue"),
);
expect(cardStyle.height).toBe("100%");
expect(buttonStyle.height).toBe("100%");
expect(headerStyle.display).toBe("grid");
expect(headerStyle.gridTemplateColumns).toBe("minmax(0, 1fr) auto");
expect(labelStyle.marginTop).toBe("0px");
expect(labelStyle.marginBottom).toBe("0px");
```

Remove the duplicate declaration of the viewed button later in the existing test and continue using the `button` constant above for the accessible-name assertion.

- [ ] **Step 2: Extend the unseen-card test with a failing no-placeholder assertion**

In the existing test `does not change the presentation of an unseen card`, install `jobsCss`, then add:

```tsx
const header = card.querySelector<HTMLElement>(".job-card__header");
expect(header).not.toBeNull();
expect(header).not.toHaveClass("job-card__header--viewed");
expect(within(header as HTMLElement).getByRole("heading")).toHaveTextContent(
  "Développeur Python",
);
expect(getComputedStyle(header as HTMLElement).display).not.toBe("grid");
```

The final assertion proves the explicit two-column layout is not applied when there is no label, so the unseen title retains the complete card width.

- [ ] **Step 3: Run the focused tests and confirm RED**

Run from `frontend/`:

```bash
env CI=true pnpm test src/features/jobs/job-grid.test.tsx
```

Expected: the two presentation tests fail because `.job-card__header` does not exist and the article/button computed heights are not `100%`.

- [ ] **Step 4: Add the state-aware header markup**

In `frontend/src/features/jobs/JobCard.tsx`, replace the separate label and title children with:

```tsx
<div
  className={`job-card__header${
    job.viewedAt ? " job-card__header--viewed" : ""
  }`}
>
  <h2>{job.title}</h2>
  {job.viewedAt ? (
    <span className="job-card__viewed-label">✓ Déjà vue</span>
  ) : null}
</div>
```

Leave the button, `aria-label`, metadata, salary, badges, and click handler byte-for-byte behaviorally unchanged.

- [ ] **Step 5: Make the card chain full-height and lay out only viewed headers as two columns**

In `frontend/src/styles/jobs.css`, update `.job-card` and `.job-card__button`:

```css
.job-card {
  min-width: 0;
  height: 100%;
}

.job-card__button {
  position: relative;
  display: flex;
  width: 100%;
  min-height: 210px;
  height: 100%;
  flex-direction: column;
  align-items: flex-start;
  /* keep the existing border, background, padding, shadow, and cursor rules */
}
```

Add immediately before `.job-card__viewed-label`:

```css
.job-card__header {
  width: 100%;
  margin-bottom: 10px;
}

.job-card__header--viewed {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 12px;
}

.job-card__header h2 {
  min-width: 0;
  margin-bottom: 0;
}
```

Replace the viewed-label margin declaration with:

```css
margin: 0;
```

Keep `.job-card h2` typography unchanged; the more specific header rule owns only its bottom margin.

- [ ] **Step 6: Run the focused tests and confirm GREEN**

Run from `frontend/`:

```bash
env CI=true pnpm test src/features/jobs/job-grid.test.tsx
```

Expected: all job-grid tests pass, including the two new layout regressions and existing accessibility checks.

- [ ] **Step 7: Run the complete automated frontend verification**

Run from `frontend/`:

```bash
env CI=true pnpm test
env CI=true pnpm typecheck
env CI=true pnpm build
```

Expected: all Vitest tests pass, TypeScript exits with no errors, and Vite produces the production bundle.

- [ ] **Step 8: Verify the actual unequal-content row in the browser**

Start or reuse the local application at `http://localhost:8000/`, reload after the production build, and select a saved search containing viewed cards with different title lengths. Inspect the first populated grid row with this read-only browser evaluation:

```js
Array.from(document.querySelectorAll(".job-card"))
  .slice(0, 4)
  .map((card) => {
  const button = card.querySelector(".job-card__button");
  const header = card.querySelector(".job-card__header");
  const title = card.querySelector("h2");
  const label = card.querySelector(".job-card__viewed-label");
  if (!(button instanceof HTMLElement) || !(header instanceof HTMLElement)) {
    throw new Error("Card layout structure is missing");
  }
  if (!(title instanceof HTMLElement)) {
    throw new Error("Card title is missing");
  }
  const cardRect = card.getBoundingClientRect();
  const buttonRect = button.getBoundingClientRect();
  const titleRect = title.getBoundingClientRect();
  const labelRect =
    label instanceof HTMLElement ? label.getBoundingClientRect() : undefined;
  return {
    bottomGap: Math.abs(cardRect.bottom - buttonRect.bottom),
    titleTop: titleRect.top,
    labelTop: labelRect?.top,
    overlap:
      labelRect === undefined
        ? false
        : !(
            titleRect.right <= labelRect.left ||
            labelRect.right <= titleRect.left ||
            titleRect.bottom <= labelRect.top ||
            labelRect.bottom <= titleRect.top
          ),
  };
});
```

Acceptance:

- every `bottomGap` is at most `1` CSS pixel;
- viewed `titleTop` and `labelTop` differ by at most `1` CSS pixel;
- every `overlap` is `false`;
- the screenshot shows aligned bottom borders with no page-background strip.

- [ ] **Step 9: Run final diff checks and commit**

Run from the repository root:

```bash
git diff --check
git status --short
```

Confirm only the three planned frontend files are modified and the four user-owned untracked paths remain untouched. Then commit:

```bash
git add frontend/src/features/jobs/JobCard.tsx frontend/src/styles/jobs.css frontend/src/features/jobs/job-grid.test.tsx
git commit -m "fix: align viewed job card layout"
```

- [ ] **Step 10: Apply completion verification and review gates**

Invoke `superpowers:verification-before-completion` using fresh focused/full test, typecheck, build, browser-measurement, and diff-check evidence. Then invoke `superpowers:requesting-code-review`; fix any Critical or Important finding with a regression test and rerun every affected check before offering integration through `superpowers:finishing-a-development-branch`.
