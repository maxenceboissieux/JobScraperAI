# Task 3 report — Period shortcuts and URL-backed job filters

## Delivered

- Added French period shortcuts for 24 hours, 3 days, 7 days, and all dates,
  with the default and canonical period set to `3d`.
- Added an accessible desktop filter bar and a native collapsible mobile panel
  below 768 px. The panel reports the number of active filter dimensions.
- Made the URL the source of truth for every Task 3 key while preserving the
  selected saved search and unrelated, repeated query parameters.
- Added safe parsing and canonicalization for enum, boolean, numeric, scalar,
  and ordered multi-value filters. Empty, duplicate, and invalid values are
  removed without losing valid values; `remote=false` and `salaire=0` remain
  valid filters.
- Added a 250 ms debounced free-text draft that resynchronizes on navigation
  and cancels pending work on navigation or unmount.
- Exposed the exact backend `JobFilters` mapping with `limit: 24` and an
  internal offset that resets only after an effective filter change.
- Clearing filters keeps the active period, saved-search selection, and
  unrelated URL state while restoring the default sort.

## TDD evidence

- RED: the first URL-contract tests failed because `useJobFilters` did not
  exist.
- GREEN: parsing, canonicalization, exact backend mapping, clearing, active
  counts, and offset behavior passed in four focused scenarios.
- RED: debounce, deep-link resynchronization, and timer-cancellation scenarios
  failed before draft state was implemented.
- GREEN: all seven hook scenarios passed after the debounced draft lifecycle
  was added.
- RED: application integration tests could not find period controls or the
  accessible filter disclosure before the components were rendered.
- GREEN: all ten Task 3 scenarios passed. A full-suite accessibility-name
  collision with the Task 2 editor was reproduced and resolved by giving the
  job location and remote controls context-specific French labels.

## Verification

- `vitest run` — 49 passed in 4 test files, including all 13 saved-search
  regression tests and all 15 Task 3 tests.
- `tsc --noEmit` — passed with strict TypeScript.
- `vite build` — passed; Vite transformed 96 modules and emitted the
  production bundle.
- `git diff --check` — passed.

The workspace dependency tree had previously been left incomplete by an
offline package-store miss. Verification therefore used a clean temporary
frontend copy with the already verified locked dependency tree, stayed fully
offline, and copied the final source and configuration immediately before each
gate.

## Formal review round 1

- Reproduced the native `<details>` desktop-visibility failure with a
  `matchMedia` resize test. The disclosure is now controlled: always open from
  768 px, independently collapsible below 768 px, and its mobile state survives
  a desktop round trip. Its accessible name switches between “Afficher” and
  “Masquer” while retaining the active count.
- Reproduced a pending `q` write overwriting a restored history entry when only
  another parameter changed. Every router/search identity change now cancels
  the timer and restores the URL draft; Back and Forward retain both entries.
  Debounced text writes replace the current entry, verified by a mutation test
  that fails when replacement is removed.
- Reproduced the first render of new filters carrying the previous page offset.
  Pagination is now associated with the semantic filter signature, so a new
  filter or saved-search selection exposes offset zero immediately, including
  Back navigation, while unchanged filters retain pagination.
- Reproduced comma-containing locations and companies being split on blur.
  Free-list filters now use unambiguous French tag inputs: repeated URL values
  round-trip unchanged, commas remain literal, Enter adds, remove buttons
  delete a named tag, and Backspace removes the final tag from an empty input.
