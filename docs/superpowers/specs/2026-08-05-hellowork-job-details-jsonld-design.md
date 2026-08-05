# HelloWork job details JSON-LD design

## Context

HelloWork still serves the affected job page, but its current detail markup no
longer exposes the description through the legacy selectors used by
`HelloWorkScraper`. The page provides a Schema.org `JobPosting` JSON-LD node
containing the title, organization, location, contract, salary, and rich-text
description. The existing parser therefore returns a `JobOffer` without usable
detail groups, and `JobDetailsService` correctly responds with HTTP 503.

## Goal

Restore lazy HelloWork detail loading from the current public page format while
keeping compatibility with historical HTML fixtures and preserving the existing
unavailable-details behavior for genuinely unusable pages. Also ensure every
HelloWork synchronization prioritizes the newest offers and never persists a
dated offer older than 30 days.

## Design

`HelloWorkScraper._parse_job_details` will prefer the first valid JSON-LD node
whose `@type` includes `JobPosting`. It will normalize:

- `title`;
- `hiringOrganization.name`;
- `jobLocation.address`, favoring locality and postal code;
- `description`, converting rich HTML to readable plain text with block and list
  separation preserved;
- `employmentType` when it maps unambiguously to an existing `ContractType`;
- `baseSalary.value.minValue` and `maxValue` when numeric.

Missing structured fields will fall back individually to the legacy HTML
selectors. A valid title alone is not sufficient for a successful detail
refresh: the resulting offer must contain at least one detail group consumed by
`JobDetailsService`, notably a non-empty description or salary. Malformed JSON-LD
will be ignored so the HTML fallback remains available.

The detail-parser change does not alter detail-service caching or API behavior.

## Search recency and result cap

Every HelloWork search URL will request date ordering with the current upstream
parameter `st=date`. The requested publication window will also be clamped to 30
days: searches asking for 24 hours or 7 days keep their stricter window, while a
30-day or unrestricted search uses `d=30`.

The scraper will enforce the 30-day cutoff locally as a defensive check. A
listing with a parsed publication date strictly older than 30 days at sync time
is skipped. A listing without a usable date is retained, as requested.

The configured `max_results` limit counts only yielded listings. Skipped old
listings do not consume the limit, so pagination continues until either 500
eligible listings have been yielded (for the default saved-search limit) or the
HelloWork result set is exhausted. Retained undated listings count toward the
limit. The scraper preserves HelloWork's newest-first page order rather than
reordering the accumulated results locally.

These recency rules are specific to HelloWork. No database, saved-search,
frontend, or other source behavior changes.

## Error handling

Network failures and pages without usable structured or HTML details continue to
return `None` from the HelloWork adapter. `JobDetailsService` then uses a stale
cached detail when one exists, or returns the existing 503 response when none
exists. The scraper must not persist page chrome as a job description.

## Testing

Add scraper-level regression tests before production changes:

1. A current-format `JobPosting` fixture yields the expected title, company,
   location, readable description, salary range, and contract.
2. Rich description markup preserves word and list separation.
3. Malformed or absent JSON-LD still permits the legacy HTML fallback.
4. A page with no usable detail data returns `None`.
5. Search URLs always include `st=date`, clamp unrestricted searches to `d=30`,
   and preserve stricter 24-hour or 7-day periods.
6. Dated listings older than 30 days are skipped without consuming
   `max_results`; pagination can still fill the cap with newer or undated
   listings.
7. Boundary coverage fixes the sync clock and verifies that an offer exactly 30
   days old is retained while an older offer is rejected.

Run the focused HelloWork tests, the detail-service tests, and then the complete
non-live backend suite.
