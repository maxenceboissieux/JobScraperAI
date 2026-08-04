# Task 2 report — French shell and saved-search management

## Delivered

- Replaced the placeholder with a responsive French application shell. The
  header exposes stable slots for saved-search controls, synchronization state,
  and the future refresh action without implementing Task 3.
- Added a selector backed by `/?search=<uuid>`. Explicit choices use history,
  automatic fallback uses replacement, and unrelated or repeated parameters
  are preserved. Suspended searches stay visible and can be reactivated.
- Added a native modal editor for create and edit flows with all backend fields
  in Task 2, exact enum/source mappings, keyword normalization, French inline
  validation, first-error focus, focus trapping/restoration, Escape/backdrop
  dismissal, and duplicate-submit protection.
- Create requests send the complete camelCase payload. Edit requests compare
  normalized current values with the initial form and PATCH only effective
  changes; empty optional title/radius values become `null`. Unknown legacy
  enum/source values remain untouched when their field has no effective change.
- Added suspend/reactivate actions using only `{ active: false }` or
  `{ active: true }`, plus French success and failure feedback.
- TanStack Query passes its abort signal, cancels older list reads before cache
  replacement, installs the returned server DTO before URL selection, and
  invalidates in the background so a blocked reload cannot hold the editor
  open. A defensive client guard handles jsdom/Node cross-realm AbortSignals
  while native cancellation remains covered.
- Added responsive, reduced-motion-aware styling for desktop, tablet, and a
  full-screen mobile editor using the approved Layout B visual foundation.

## TDD and review evidence

- RED: the initial 8 saved-search scenarios all failed against the placeholder
  application.
- RED: focused regressions reproduced legacy-array loss after reverting a
  checkbox, two same-turn POSTs, a blocked post-mutation reload, detached CTA
  focus restoration, and verbatim English HTTP 500 text.
- GREEN: 13 saved-search integration/accessibility scenarios cover create,
  effective dirty-only edit, tolerant legacy rows, selection/deep-link repair,
  repeated URL parameters, suspend/reactivate, validation, modal keyboard and
  focus behavior, pending requests, cache races, and French failures.
- Independent review found no critical issues. Its three important findings
  (effective dirty comparison, guaranteed-French failures, and stable focus
  after the empty-state CTA disappears) were fixed with RED/GREEN regressions.
  Its minor cross-realm cancellation branch is also covered.

## Verification

- Node runtime: `v24.14.0` (satisfies the declared floor).
- `pnpm test` — 34 passed in 3 test files.
- `pnpm typecheck` — passed with strict TypeScript.
- `pnpm build` — passed; Vite transformed 93 modules and emitted the production
  bundle.
- `.venv/bin/python -m pytest tests/api/test_searches.py -q` — 26 passed (one
  upstream Starlette deprecation warning).
- `git diff --check` — passed.

The in-app browser had no available browser instance, so screenshot-based
visual QA could not be completed in this session. Responsive CSS, DOM behavior,
accessibility interactions, strict types, and the production build were still
verified locally.
