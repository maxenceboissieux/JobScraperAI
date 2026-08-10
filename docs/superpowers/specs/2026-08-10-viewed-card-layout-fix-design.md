# Viewed Card Layout Fix Design

## Context and problem

Viewed job cards currently render the `✓ Déjà vue` label as the first item in
the card button's vertical flex flow. The label therefore consumes its own row
above the title and creates an unnecessary empty-looking band at the top of
every viewed card.

The grid also stretches each `.job-card` article to the height of the tallest
card in its row, while `.job-card__button` has only a minimum height. When one
card contains more wrapped text than its neighbors, the shorter buttons stop
before the bottom of their stretched articles. The page background then
appears as a white strip below those cards' bottom borders.

## Approved layout

`JobCard` will group the title and optional viewed label in a dedicated
`.job-card__header` element.

- The header uses a two-column layout: a flexible, shrinkable title column and
  a compact label column.
- The title begins at the normal top content position rather than below a
  dedicated badge row.
- The label remains in the approved upper-right area, never overlaps the
  title, and keeps the exact visible copy `✓ Déjà vue`.
- Unseen cards render the same header with only the title. They do not reserve
  an empty label column and retain their current visual presentation.
- Long titles may wrap naturally within their available column.

The card article and its button will both occupy the full grid-row height.
The button's bottom border and background therefore extend to the bottom of
every card, including rows whose tallest card contains additional wrapped
content.

## Component and CSS changes

`frontend/src/features/jobs/JobCard.tsx` will:

- introduce `.job-card__header` around the existing `h2` and conditional
  `.job-card__viewed-label`;
- preserve the existing click handler and accessible name, including the
  `déjà vue` state for viewed cards;
- leave metadata, salary, source, and duplicate badges unchanged.

`frontend/src/styles/jobs.css` will:

- make `.job-card` fill its grid area vertically;
- make `.job-card__button` fill the article height;
- define the header as `grid-template-columns: minmax(0, 1fr) auto` with a
  small horizontal gap and top alignment;
- move the title's existing bottom spacing from assumptions about direct
  button children into the header layout;
- remove the viewed label's auto left margin and vertical row spacing that
  caused the top gap.

No backend, API, database, filtering, or viewed-state behavior changes are in
scope.

## Responsive and accessibility behavior

The existing minimum card width gives the title and compact label enough room
to coexist. The `minmax(0, 1fr)` title column prevents overflow and allows long
French job titles to wrap. The label remains readable at full contrast.

The button remains the single interactive element. Its accessible name
continues to identify the offer and includes `déjà vue` only when appropriate.
The visible label is not made decorative or hidden from assistive technology.

## Testing and acceptance criteria

Frontend regressions will verify:

- a viewed card renders the title and `✓ Déjà vue` inside the shared header;
- an unseen card renders the title without a viewed label or empty placeholder;
- the article and button both use full-height layout rules;
- the viewed label no longer has the vertical-flow margin that created the top
  gap;
- existing viewed-state accessibility assertions remain valid.

The focused job-grid tests, complete frontend test suite, TypeScript typecheck,
and production build must pass. Browser verification will use one row
containing cards with different title and metadata lengths and confirm that:

- titles start at the same top content position;
- labels occupy the upper-right of viewed cards;
- every bottom border aligns with the grid row bottom;
- no white strip appears below shorter cards.

## Out of scope

- Changing the viewed-state persistence or optimistic mutation behavior;
- changing card content, typography, colors, or grid column sizing;
- moving the viewed label to the bottom badge group;
- redesigning filters or job details.
