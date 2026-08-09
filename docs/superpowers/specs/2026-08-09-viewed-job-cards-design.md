# Viewed Job Cards Design

## Context and goal

The application does not currently remember which job cards have already been
opened. A user returning to a search therefore cannot distinguish new offers
from offers they have already inspected.

The application will persist the first card click in the local database,
visually de-emphasize viewed offers, and optionally hide them with a new
`Non vues uniquement` filter.

## User-visible behavior

- A job becomes viewed as soon as its card is clicked in the job grid.
- The details drawer opens immediately; it does not wait for the persistence
  request.
- A viewed card uses the approved attenuated presentation: muted content, a
  subtle state accent, and the explicit label `✓ Déjà vue` in the upper-right
  area.
- The existing filter area gains a `Non vues uniquement` toggle, disabled by
  default.
- When that filter is active, clicking a card removes it from the grid and
  decrements the visible result total immediately. Its details drawer remains
  open.
- Viewed state is global to the canonical job. A job merged from multiple
  sources therefore has one shared state in every saved search.
- Opening a job through a direct `?job=...` URL or selecting a possible
  duplicate from the details drawer does not mark it viewed. Only a click on a
  grid card does so.

## Persistence model

Add nullable `viewed_at` to `CanonicalJob` through an Alembic migration.
Existing rows receive `NULL` and are treated as unseen. The first successful
card click stores the current UTC timestamp. Later clicks are idempotent and
must not replace that first timestamp.

No separate history table or user identifier is introduced. This application
is a local, single-user system; a per-user event history would add unused
complexity.

## Repository and API

The job repository gains:

- `mark_viewed(job_id: str, viewed_at: datetime | None = None) -> CanonicalJob`,
  which raises `LookupError` for an unknown public UUID and stamps only a
  previously unseen job;
- an `unseen_only: bool = False` option on job listing. When true, only jobs
  whose `viewed_at` is `NULL` are returned and counted.

The API contract gains:

- idempotent `POST /api/jobs/{job_id}/viewed`, returning the public job ID and
  its persisted `viewedAt` timestamp;
- `viewedAt: string | null` on both job-card and job-detail payloads;
- optional `unseenOnly=true` on `GET /api/jobs`.

An unknown job returns 404. Database failures use the API's existing error
handling and do not produce a false successful viewed state.

## Frontend state and data flow

`JobFilters` gains `unseenOnly?: boolean`. The filter hook serializes the
enabled state as `unseenOnly=true` in the URL and omits it when disabled, so
back/forward navigation and copied filtered URLs remain consistent.

`JobGrid` owns the viewed mutation because it is the only component authorized
to mark a job from a card click. The click flow is:

1. save the affected React Query cache snapshots;
2. optimistically set `viewedAt` on that canonical job in cached job pages;
3. when `unseenOnly` is active, remove the job from the active page and
   decrement its total without going below zero;
4. call the existing `onSelectJob` callback immediately to open the drawer;
5. send `POST /api/jobs/{id}/viewed`;
6. reconcile job queries with the server response.

If the request fails, the job-page snapshots are restored and the grid shows a
small accessible error message. The details drawer stays open because reading
the job remains useful even when recording its viewed state fails.

The mutation must update every cached job page containing that canonical ID,
not only the currently visible saved search. This keeps the state coherent
when the same canonical job appears in several searches. Invalidating the job
query family after success reconciles totals and pagination with the database.

## Components and styling

- `JobCard` receives its viewed state from `job.viewedAt`; it does not own
  persistence.
- Viewed cards receive a modifier class and the visible `Déjà vue` label.
- The button's accessible name continues to identify the job. The viewed label
  remains available to assistive technology rather than being decorative only.
- The filter is added to the existing `JobFilters` control group and follows
  its responsive layout and keyboard behavior.
- Unseen cards keep the current visual design unchanged.

## Error handling and edge cases

- Repeated or concurrent mark requests preserve the first timestamp through an
  atomic update conditioned on `viewed_at IS NULL`.
- A card already viewed remains visible when `Non vues uniquement` is off.
- A failed optimistic mutation restores the card, total, and previous
  `viewedAt` value.
- Removing the last unseen card may show the existing empty state after the
  drawer closes or while the grid remains visible behind it.
- Pagination is reconciled after a successful request, so removing one card
  cannot permanently leave page totals or subsequent pages stale.
- No automatic reset or `Marquer comme non vue` action is included.

## Testing and acceptance criteria

Backend tests will verify:

- migration and schema compatibility for existing databases;
- first-click timestamp persistence and idempotent repeated/concurrent marks;
- 404 for an unknown job;
- `viewedAt` serialization on cards and details;
- `unseenOnly=true` filtering, totals, saved searches, and pagination.

Frontend tests will verify:

- the attenuated card and explicit `Déjà vue` label;
- unchanged appearance for unseen cards;
- filter URL serialization and restoration;
- immediate drawer opening and optimistic viewed state;
- immediate removal and total decrement under `Non vues uniquement`;
- rollback and accessible error feedback after a failed request;
- server reconciliation after success;
- direct URL and details-drawer duplicate navigation do not mark a job.

The complete backend non-live suite, frontend tests, frontend typecheck, and
frontend production build must remain green.

## Out of scope

- Multiple users or cross-device accounts;
- view counts or a chronological viewing-history screen;
- resetting a job to unseen;
- marking a job when opened outside the grid;
- filtering by the date on which a job was viewed.
