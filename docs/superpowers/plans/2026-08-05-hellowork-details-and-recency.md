# HelloWork Details and Recency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore HelloWork job details from `JobPosting` JSON-LD and make every HelloWork sync yield newest-first listings no older than 30 days, without letting rejected old listings consume the configured result cap.

**Architecture:** Keep both behaviors inside `HelloWorkScraper`, where upstream HTML is converted into `JobOffer` instances. Detail parsing becomes structured-data-first with field-level legacy HTML fallbacks; search URLs request the upstream date sort and 30-day maximum while a local cutoff defensively filters parsed listings before incrementing `jobs_found`.

**Tech Stack:** Python 3.12, BeautifulSoup/lxml, Pydantic models, pytest, Loguru.

## Global Constraints

- HelloWork detail parsing prefers the first valid Schema.org `JobPosting` node and retains the legacy HTML fallback.
- Malformed JSON-LD must not prevent a valid legacy HTML page from being parsed.
- A page without a usable description or salary remains unavailable; do not persist page chrome as description text.
- Every HelloWork request uses `st=date`.
- HelloWork date windows are clamped to 30 days: `1` and `7` remain stricter; missing, any-time, and past-month criteria use `30`.
- A dated offer strictly older than 30 days is skipped; an offer exactly 30 days old and an undated offer are retained.
- Only yielded offers consume `SearchCriteria.max_results`; skipped old offers do not.
- These changes do not alter other sources, database schemas, saved-search contracts, frontend behavior, or detail-cache semantics.

---

### Task 1: Parse Current HelloWork Job Details

**Files:**
- Create: `tests/fixtures/hellowork/details.html`
- Modify: `tests/scrapers/test_existing_scrapers.py`
- Modify: `tests/services/test_details.py`
- Modify: `src/jobscraper/scrapers/hellowork.py:1-20,484-566`

**Interfaces:**
- Consumes: `HelloWorkScraper.get_job_details(job_id: str) -> JobOffer | None` and `JobDetailsService.get(canonical_job_id: str) -> JobDetailsResult`.
- Produces: `HelloWorkScraper._extract_json_ld_jobs(soup: BeautifulSoup) -> list[dict[str, Any]]`, `_clean_rich_text(value: Any) -> str | None`, `_structured_location(value: Any) -> str | None`, and structured-data-first `_parse_job_details(soup: BeautifulSoup, job_id: str, url: str) -> JobOffer | None` behavior.

- [ ] **Step 1: Create a representative current-format fixture**

Create `tests/fixtures/hellowork/details.html` with a decoy non-job script and a real job node:

```html
<!doctype html>
<html lang="fr">
  <head>
    <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"WebSite","name":"Hellowork"}
    </script>
    <script type="application/ld+json">
      {
        "@context":"https://schema.org",
        "@type":"JobPosting",
        "title":"Développeur Fullstack Java - React Confirmé H/F",
        "hiringOrganization":{"@type":"Organization","name":"Geser Best"},
        "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"Nantes","postalCode":"44000"}},
        "employmentType":"CDI",
        "baseSalary":{"@type":"MonetaryAmount","currency":"EUR","value":{"@type":"QuantitativeValue","minValue":38000,"maxValue":42000,"unitText":"YEAR"}},
        "description":"<h2>Les missions du poste</h2><p>Construire le <strong>produit</strong>.</p><p>Vos missions :</p><ul><li>Concevoir</li><li>Tester</li></ul>"
      }
    </script>
  </head>
  <body><h1>Texte de page à ne pas utiliser comme description</h1></body>
</html>
```

- [ ] **Step 2: Write failing scraper regressions**

Append to `tests/scrapers/test_existing_scrapers.py`:

```python
def test_hellowork_parses_current_jobposting_details(load_fixture) -> None:
    scraper = HelloWorkScraper({"delay": 0})
    soup = BeautifulSoup(load_fixture("hellowork/details.html"), "lxml")

    job = scraper._parse_job_details(
        soup,
        "78679641",
        "https://www.hellowork.com/fr-fr/emplois/78679641.html",
    )

    assert job is not None
    assert job.title == "Développeur Fullstack Java - React Confirmé H/F"
    assert job.company == "Geser Best"
    assert job.location == "Nantes (44000)"
    assert job.description == (
        "Les missions du poste\nConstruire le\nproduit\n.\n"
        "Vos missions :\nConcevoir\nTester"
    )
    assert job.contract_type == ContractType.CDI
    assert (job.salary_min, job.salary_max) == (38_000, 42_000)


def test_hellowork_malformed_jsonld_falls_back_to_legacy_html() -> None:
    scraper = HelloWorkScraper({"delay": 0})
    soup = BeautifulSoup(
        """
        <script type="application/ld+json">{invalid</script>
        <h1>Legacy Python engineer</h1>
        <div itemprop="description"><p>Construire</p><p>Tester</p></div>
        """,
        "lxml",
    )

    job = scraper._parse_job_details(
        soup, "42", "https://www.hellowork.com/fr-fr/emplois/42.html"
    )

    assert job is not None
    assert job.title == "Legacy Python engineer"
    assert job.description == "Construire\nTester"


def test_hellowork_rejects_a_page_without_usable_detail_groups() -> None:
    scraper = HelloWorkScraper({"delay": 0})
    soup = BeautifulSoup("<h1>Page générique</h1>", "lxml")

    assert (
        scraper._parse_job_details(
            soup, "42", "https://www.hellowork.com/fr-fr/emplois/42.html"
        )
        is None
    )
```

- [ ] **Step 3: Write the failing service-level reproduction of the HTTP 503 cause**

Append to `tests/services/test_details.py`:

```python
def test_hellowork_jsonld_details_refresh_the_empty_canonical_job(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = JobRepository(session).upsert_listing(
        listing_offer("hellowork_78679641", source="hellowork"), seen_at=NOW
    )
    fixture = (
        Path(__file__).parents[1] / "fixtures" / "hellowork" / "details.html"
    ).read_text(encoding="utf-8")
    scraper = HelloWorkScraper({"delay": 0})
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: fixture)
    service = JobDetailsService(
        session,
        registry=FixedRegistry("hellowork", scraper),
        clock=Clock(),
    )

    result = service.get(job.id)

    assert result.cache_state == "refreshed"
    assert result.job.description is not None
    assert "Les missions du poste" in result.job.description
    assert (result.job.salary_min, result.job.salary_max) == (38_000, 42_000)
```

Add `HelloWorkScraper` beside the existing `LinkedInScraper` import in this test module.

- [ ] **Step 4: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scrapers/test_existing_scrapers.py::test_hellowork_parses_current_jobposting_details \
  tests/scrapers/test_existing_scrapers.py::test_hellowork_malformed_jsonld_falls_back_to_legacy_html \
  tests/scrapers/test_existing_scrapers.py::test_hellowork_rejects_a_page_without_usable_detail_groups \
  tests/services/test_details.py::test_hellowork_jsonld_details_refresh_the_empty_canonical_job -q
```

Expected: failures show the current parser ignores JSON-LD, concatenates legacy block text, accepts the generic page, and leaves the service without refreshable details.

- [ ] **Step 5: Implement minimal structured-data-first parsing**

In `src/jobscraper/scrapers/hellowork.py`, import `json` and `Any`, then add these helpers and replace `_parse_job_details` with their structured-first composition:

```python
@staticmethod
def _clean_rich_text(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = BeautifulSoup(value, "lxml").get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text or None

def _extract_json_ld_jobs(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            node_type = value.get("@type")
            types = node_type if isinstance(node_type, list) else [node_type]
            if "JobPosting" in types:
                jobs.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            walk(json.loads(script.string or script.get_text()))
        except (TypeError, json.JSONDecodeError):
            logger.debug("JSON-LD HelloWork invalide ignoré")
    return jobs

@staticmethod
def _structured_location(value: Any) -> Optional[str]:
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, dict):
        return value.strip() if isinstance(value, str) and value.strip() else None
    address = value.get("address", value)
    if not isinstance(address, dict):
        return None
    locality = str(address.get("addressLocality") or "").strip()
    postal_code = str(address.get("postalCode") or "").strip()
    if locality and postal_code:
        return f"{locality} ({postal_code})"
    return locality or postal_code or None

@staticmethod
def _structured_salary(value: Any) -> tuple[Optional[float], Optional[float]]:
    if not isinstance(value, dict):
        return None, None
    quantitative = value.get("value")
    if not isinstance(quantitative, dict):
        return None, None

    def numeric(candidate: Any) -> Optional[float]:
        if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
            return None
        return float(candidate)

    return numeric(quantitative.get("minValue")), numeric(
        quantitative.get("maxValue")
    )
```

The replacement `_parse_job_details` must:

```python
structured_jobs = self._extract_json_ld_jobs(soup)
structured = structured_jobs[0] if structured_jobs else {}
organization = structured.get("hiringOrganization")
structured_company = (
    organization.get("name") if isinstance(organization, dict) else organization
)
salary_min, salary_max = self._structured_salary(structured.get("baseSalary"))

title_element = soup.select_one("h1, [class*='job-title']")
company_element = soup.select_one(
    "[class*='company'], [class*='entreprise'], [itemprop='hiringOrganization']"
)
location_element = soup.select_one(
    "[class*='location'], [class*='lieu'], [itemprop='jobLocation']"
)
description_element = soup.select_one(
    "[class*='description'], [itemprop='description'], "
    ".job-description, #job-description"
)
contract_element = soup.select_one("[itemprop='employmentType']")

title = str(structured.get("title") or "").strip() or (
    title_element.get_text(" ", strip=True) if title_element else ""
)
company = str(structured_company or "").strip() or (
    company_element.get_text(" ", strip=True)
    if company_element
    else "Non spécifié"
)
location = self._structured_location(structured.get("jobLocation")) or (
    location_element.get_text(" ", strip=True) if location_element else "France"
)
description = self._clean_rich_text(structured.get("description")) or (
    self._clean_rich_text(str(description_element)) if description_element else None
)
contract_value = structured.get("employmentType") or (
    contract_element.get_text(" ", strip=True) if contract_element else ""
)
contract_type = self._map_contract_type(str(contract_value))

if salary_min is None and salary_max is None:
    salary_element = soup.select_one(
        "[itemprop='baseSalary'], [class*='salary']"
    )
    if salary_element:
        salary_match = re.search(
            r"(\d[\d\s]*)\s*(?:€|EUR)", salary_element.get_text(" ", strip=True)
        )
        if salary_match:
            salary_min = float(salary_match.group(1).replace(" ", ""))
if not title or (not description and salary_min is None and salary_max is None):
    return None
return JobOffer(
    id=f"hellowork_{job_id}",
    source=self.name,
    url=url,
    title=title,
    company=company,
    location=location,
    description=description,
    contract_type=contract_type,
    salary_min=salary_min,
    salary_max=salary_max,
)
```

Do not add new fields or generic page-wide description fallbacks.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run the Step 4 command again. Expected: `4 passed`.

- [ ] **Step 7: Run neighboring parser and service suites**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scrapers/test_existing_scrapers.py \
  tests/services/test_details.py -q
```

Expected: all selected tests pass; only documented pre-existing dependency deprecation warnings may remain.

- [ ] **Step 8: Commit Task 1**

```bash
git add tests/fixtures/hellowork/details.html \
  tests/scrapers/test_existing_scrapers.py \
  tests/services/test_details.py \
  src/jobscraper/scrapers/hellowork.py
git commit -m "fix: parse current HelloWork job details"
```

---

### Task 2: Enforce Newest-First 30-Day HelloWork Results

**Files:**
- Modify: `tests/scrapers/test_existing_scrapers.py`
- Modify: `tests/scrapers/test_strict_search_health.py`
- Modify: `src/jobscraper/scrapers/hellowork.py:1-25,72-171,215-259,422-482`

**Interfaces:**
- Consumes: `SearchCriteria.date_posted`, `SearchCriteria.max_results`, and parsed `JobOffer.posted_at` values.
- Produces: `HelloWorkScraper._now() -> datetime`, `_is_within_recency_window(posted_at: datetime | None) -> bool`, search URLs containing `st=date` and a clamped `d`, plus search iteration where only eligible yields increment `jobs_found`.

- [ ] **Step 1: Write failing URL policy tests**

Append to `tests/scrapers/test_existing_scrapers.py`:

```python
@pytest.mark.parametrize(
    ("date_posted", "expected_days"),
    [
        (None, "30"),
        (DatePosted.ANY_TIME, "30"),
        (DatePosted.PAST_MONTH, "30"),
        (DatePosted.PAST_WEEK, "7"),
        (DatePosted.PAST_24H, "1"),
    ],
)
def test_hellowork_always_requests_newest_first_with_a_30_day_ceiling(
    date_posted: DatePosted | None, expected_days: str
) -> None:
    criteria = SearchCriteria(date_posted=date_posted)

    query = parse_qs(
        urlparse(HelloWorkScraper({"delay": 0})._build_search_url(criteria)).query
    )

    assert query["st"] == ["date"]
    assert query["d"] == [expected_days]
```

- [ ] **Step 2: Write the failing cap-after-filter regression**

Change the existing helper in `tests/scrapers/test_strict_search_health.py` without changing existing callers:

```python
def hellowork_card(identifier: str, posted_at: str | None = None) -> str:
    time_html = f'<time datetime="{posted_at}"></time>' if posted_at else ""
    return (
        f'<li data-id-storage-item-id="{identifier}">'
        f'<input name="title" value="Offer {identifier}">'
        f'<input name="company" value="Acme">'
        f'<a href="/fr-fr/emplois/{identifier}.html">Offer</a>'
        f"{time_html}</li>"
    )
```

Then append:

```python
def test_hellowork_old_jobs_do_not_consume_the_result_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 5, 12, tzinfo=timezone.utc)
    scraper = HelloWorkScraper(
        {
            "delay": 0,
            "propagate_search_errors": True,
            "clock": lambda: now,
        }
    )
    responses = iter(
        [
            hellowork_card("old", "2026-07-05T11:59:59Z")
            + hellowork_card("undated"),
            hellowork_card("boundary", "2026-07-06T12:00:00Z")
            + hellowork_card("new", "2026-08-05T11:00:00Z"),
        ]
    )
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: next(responses))

    jobs = list(scraper.search(SearchCriteria(max_results=3)))

    assert [job.id for job in jobs] == [
        "hellowork_undated",
        "hellowork_boundary",
        "hellowork_new",
    ]
    assert scraper.search_complete is False
```

Add `datetime` and `timezone` imports from `datetime` at the top of this test module.

- [ ] **Step 3: Update the existing parameter-free pagination expectation**

In `test_hellowork_uses_question_mark_for_page_two_without_search_parameters`, preserve the intent (the second page uses `&p=2` once mandatory parameters exist):

```python
base_url = (
    "https://www.hellowork.com/fr-fr/emploi/recherche.html?st=date&d=30"
)
assert [job.id for job in jobs] == ["hellowork_1"]
assert fetched == [base_url, f"{base_url}&p=2"]
assert scraper.search_complete is True
```

- [ ] **Step 4: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scrapers/test_existing_scrapers.py::test_hellowork_always_requests_newest_first_with_a_30_day_ceiling \
  tests/scrapers/test_strict_search_health.py::test_hellowork_old_jobs_do_not_consume_the_result_cap \
  tests/scrapers/test_strict_search_health.py::test_hellowork_uses_question_mark_for_page_two_without_search_parameters -q
```

Expected: the URL test lacks `st`/the default `d`, the old listing is yielded and consumes the cap, and the pagination URL still lacks mandatory recency parameters.

- [ ] **Step 5: Implement the URL clamp and deterministic cutoff**

In `src/jobscraper/scrapers/hellowork.py`, import `timezone` and add:

```python
MAX_LISTING_AGE = timedelta(days=30)

def _now(self) -> datetime:
    clock = self.config.get("clock")
    value = clock() if callable(clock) else datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def _is_within_recency_window(self, posted_at: Optional[datetime]) -> bool:
    if posted_at is None:
        return True
    normalized = (
        posted_at.replace(tzinfo=timezone.utc)
        if posted_at.tzinfo is None
        else posted_at.astimezone(timezone.utc)
    )
    return normalized >= self._now() - self.MAX_LISTING_AGE
```

Define `MAX_LISTING_AGE` as a class attribute on `HelloWorkScraper` so it is source-specific. Change `_parse_relative_date` to use `now = self._now()`.

Initialize `_build_search_url` parameters with the mandatory upstream policy and then overwrite only `d` with a stricter mapped value:

```python
params: dict[str, str | list[str]] = {"st": "date", "d": "30"}
if criteria.date_posted not in (None, DatePosted.ANY_TIME):
    date_code = self.DATE_POSTED_MAPPING.get(criteria.date_posted)
    if date_code:
        params["d"] = date_code
```

Remove the old conditional date block so it cannot override this clamp.

- [ ] **Step 6: Apply the cutoff before incrementing the result count**

In `search`, keep duplicate tracking but place the local eligibility check before `jobs_found += 1`:

```python
if job.id in seen_ids:
    logger.debug(f"Doublon ignoré: {job.id}")
    continue

seen_ids.add(job.id)
if not self._is_within_recency_window(job.posted_at):
    logger.debug("Offre HelloWork de plus de 30 jours ignorée: {}", job.id)
    continue

jobs_found += 1
yield job
```

Do not move `parsed_jobs_on_page` or `new_ids_in_query`: an old but parseable card remains valid evidence that the page was parsed, while it does not consume `max_results`.

- [ ] **Step 7: Run focused and neighboring HelloWork tests GREEN**

Run the Step 4 command again, then:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scrapers/test_existing_scrapers.py \
  tests/scrapers/test_strict_search_health.py \
  tests/services/test_sync.py -q
```

Expected: all selected tests pass. Confirm the existing capped-search tests still leave `search_complete` false and the strict pagination contracts remain intact.

- [ ] **Step 8: Run the complete non-live backend verification**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -m "not live"
git diff --check
```

Expected: all selected backend tests pass, 4 live tests remain deselected, and `git diff --check` prints nothing.

- [ ] **Step 9: Reproduce the original job detail through the real adapter**

With network permission, run:

```bash
PYTHONPATH=src .venv/bin/python -c "from jobscraper.scrapers.hellowork import HelloWorkScraper; s=HelloWorkScraper({'delay': 0}); j=s.get_job_details('hellowork_78679641'); print(j is not None, len(j.description or '') if j else 0); s.close()"
```

Expected: `True` and a positive description length. If the external offer has disappeared, report that the offline fixture and service regression pass instead of treating source removal as a code failure.

- [ ] **Step 10: Commit Task 2**

```bash
git add tests/scrapers/test_existing_scrapers.py \
  tests/scrapers/test_strict_search_health.py \
  src/jobscraper/scrapers/hellowork.py
git commit -m "fix: keep HelloWork syncs within thirty days"
```
