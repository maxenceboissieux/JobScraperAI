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
unavailable-details behavior for genuinely unusable pages.

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

No search, pagination, saved-search, database, or frontend behavior changes.

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

Run the focused HelloWork tests, the detail-service tests, and then the complete
non-live backend suite.
