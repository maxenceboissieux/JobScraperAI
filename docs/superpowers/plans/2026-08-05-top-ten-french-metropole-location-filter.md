# Top Ten French Metropole Location Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a location filter for each selected major French city include every job in its official metropolitan perimeter while keeping ordinary commune filters municipal.

**Architecture:** Commit an official, versioned JSON snapshot containing ten metropolitan groups and load it through a small validated data layer. A focused matcher normalizes job locations, expands only city-center and explicit metropole aliases, and falls back to municipal equality. `JobRepository.list_jobs` delegates location decisions to that matcher without changing the API or frontend contract.

**Tech Stack:** Python 3.11/3.12, standard-library `json`, `importlib.resources`, `urllib.request`, pytest, SQLAlchemy, FastAPI, setuptools package data.

## Global Constraints

- The configured groups are Grand Paris, Aix-Marseille-Provence, Lyon, Lille, Bordeaux, Toulouse, Nantes, Nice Cote d'Azur, Montpellier, and Strasbourg.
- Only a city-center tag or an explicit metropole alias expands to a metropolitan group; a member commune entered directly remains municipal.
- Location comparison ignores case, accents, punctuation, extra whitespace, department suffixes, and a separately delimited `France` suffix.
- Paris, Lyon, and Marseille arrondissement labels resolve to their city center, with valid ranges 1-20, 1-9, and 1-16 respectively.
- Multiple location tags retain OR semantics.
- Unknown location strings fall back to normalized equality and never broaden a search.
- Metropolitan membership is loaded locally; filtering and application startup make no network request.
- Invalid bundled reference data fails eagerly with a clear configuration error.
- No database migration, frontend change, scraping change, or ingestion-normalization change.

---

## File structure

- Create `scripts/update_metropole_data.py`: maintenance-only generator that downloads the nine EPCI memberships and combines them with Lyon's official 58-commune list.
- Create `src/jobscraper/data/__init__.py`: marks the packaged data directory.
- Create `src/jobscraper/data/french_metropolises.json`: deterministic official snapshot used at runtime.
- Create `src/jobscraper/services/location_matching.py`: validates the snapshot and exposes `location_matches(candidate, requested)`.
- Create `tests/services/test_location_matching.py`: dataset and pure matching tests.
- Modify `pyproject.toml`: include the JSON snapshot in wheels.
- Modify `src/jobscraper/repositories/jobs.py`: delegate location filtering to `location_matches`.
- Modify `tests/repositories/test_jobs.py`: repository-level metropolitan and OR regressions.
- Modify `tests/api/test_jobs.py`: public API regression for `location=Lyon`.

### Task 1: Generate and validate the local metropolitan reference

**Files:**
- Create: `scripts/update_metropole_data.py`
- Create: `src/jobscraper/data/__init__.py`
- Create: `src/jobscraper/data/french_metropolises.json`
- Create: `src/jobscraper/services/location_matching.py`
- Create: `tests/services/test_location_matching.py`
- Modify: `pyproject.toml:66-71`

**Interfaces:**
- Consumes: `jobscraper.services.normalization.normalize_location(value: str) -> str`.
- Produces: a packaged JSON object with `reference_date: str`, `groups: list[object]`; private `_load_metropolises() -> tuple[Metropole, ...]`; module constant `_METROPOLES: tuple[Metropole, ...]`.

- [ ] **Step 1: Write failing reference-validation tests**

Create `tests/services/test_location_matching.py` with the expected keys,
commune counts, city centers, and rejection cases:

```python
from __future__ import annotations

import json
from importlib import resources

import pytest

from jobscraper.services import location_matching


EXPECTED_COUNTS = {
    "grand_paris": 130,
    "aix_marseille_provence": 92,
    "lyon": 58,
    "lille": 95,
    "bordeaux": 28,
    "toulouse": 37,
    "nantes": 24,
    "nice_cote_d_azur": 51,
    "montpellier": 31,
    "strasbourg": 33,
}

EXPECTED_CENTERS = {
    "grand_paris": "Paris",
    "aix_marseille_provence": "Marseille",
    "lyon": "Lyon",
    "lille": "Lille",
    "bordeaux": "Bordeaux",
    "toulouse": "Toulouse",
    "nantes": "Nantes",
    "nice_cote_d_azur": "Nice",
    "montpellier": "Montpellier",
    "strasbourg": "Strasbourg",
}


def test_bundled_metropole_snapshot_has_expected_groups_and_counts() -> None:
    groups = {group.key: group for group in location_matching._METROPOLES}

    assert {key: len(group.communes) for key, group in groups.items()} == EXPECTED_COUNTS
    assert {key: group.city_center for key, group in groups.items()} == {
        key: location_matching.normalize_location(value)
        for key, value in EXPECTED_CENTERS.items()
    }
    assert all(group.city_center in group.communes for group in groups.values())


def test_reference_validation_rejects_duplicate_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = resources.files("jobscraper.data").joinpath(
        "french_metropolises.json"
    )
    payload = json.loads(resource.read_text(encoding="utf-8"))
    duplicate = payload["groups"][0]["activation_aliases"][0]
    payload["groups"][1]["activation_aliases"].append(duplicate)
    monkeypatch.setattr(location_matching, "_read_payload", lambda: payload)

    with pytest.raises(location_matching.LocationReferenceError, match="alias"):
        location_matching._load_metropolises()


def test_snapshot_is_valid_json_package_data() -> None:
    resource = resources.files("jobscraper.data").joinpath("french_metropolises.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    assert payload["reference_date"] == "2026-01-01"
```

- [ ] **Step 2: Run the tests and verify the reference layer is absent**

Run:

```bash
pytest tests/services/test_location_matching.py -v
```

Expected: collection fails because `jobscraper.services.location_matching` does not exist.

- [ ] **Step 3: Add the deterministic maintenance generator**

Create `scripts/update_metropole_data.py`. Define these exact EPCI inputs:

```python
EPCI_GROUPS = (
    ("grand_paris", "Métropole du Grand Paris", "Paris", "200054781", 130),
    ("aix_marseille_provence", "Métropole d'Aix-Marseille-Provence", "Marseille", "200054807", 92),
    ("lille", "Métropole Européenne de Lille", "Lille", "200093201", 95),
    ("bordeaux", "Bordeaux Métropole", "Bordeaux", "243300316", 28),
    ("toulouse", "Toulouse Métropole", "Toulouse", "243100518", 37),
    ("nantes", "Nantes Métropole", "Nantes", "244400404", 24),
    ("nice_cote_d_azur", "Métropole Nice Côte d'Azur", "Nice", "200030195", 51),
    ("montpellier", "Montpellier Méditerranée Métropole", "Montpellier", "243400017", 31),
    ("strasbourg", "Eurométropole de Strasbourg", "Strasbourg", "246700488", 33),
)

LYON_GROUP = (
    "lyon",
    "Métropole de Lyon",
    "Lyon",
    "200046977",
    58,
)

ALIASES = {
    "grand_paris": ["Paris", "Grand Paris", "Métropole du Grand Paris"],
    "aix_marseille_provence": ["Marseille", "Aix-Marseille", "Aix-Marseille-Provence", "Métropole d'Aix-Marseille-Provence"],
    "lyon": ["Lyon", "Grand Lyon", "Métropole de Lyon"],
    "lille": ["Lille", "Métropole Européenne de Lille"],
    "bordeaux": ["Bordeaux", "Bordeaux Métropole"],
    "toulouse": ["Toulouse", "Toulouse Métropole"],
    "nantes": ["Nantes", "Nantes Métropole"],
    "nice_cote_d_azur": ["Nice", "Nice Côte d'Azur", "Métropole Nice Côte d'Azur"],
    "montpellier": ["Montpellier", "Montpellier Méditerranée Métropole"],
    "strasbourg": ["Strasbourg", "Eurométropole de Strasbourg"],
}
```

Use `urllib.request.urlopen` with a 30-second timeout against
`https://geo.api.gouv.fr/epcis/{code}/communes?fields=nom,code`, sort each
group by `(insee_code, name)`, assert its expected count and city-center
presence, then write stable UTF-8 JSON with `ensure_ascii=False`,
`indent=2`, and a trailing newline. For Lyon, fetch code `200046977`, but
validate the returned normalized names against this exact list from the
official Grand Lyon page before writing it:

```python
LYON_OFFICIAL_NAMES = (
    "Albigny-sur-Saône", "Bron", "Cailloux-sur-Fontaines",
    "Caluire-et-Cuire", "Champagne-au-Mont-d'Or",
    "Charbonnières-les-Bains", "Charly", "Chassieu",
    "Collonges-au-Mont-d'Or", "Corbas", "Couzon-au-Mont-d'Or", "Craponne",
    "Curis-au-Mont-d'Or", "Dardilly", "Décines-Charpieu", "Écully",
    "Feyzin", "Fleurieu-sur-Saône", "Fontaines-Saint-Martin",
    "Fontaines-sur-Saône", "Francheville", "Genay", "Givors",
    "Grigny-sur-Rhône", "Irigny", "Jonage", "La Mulatière",
    "La Tour-de-Salvagny", "Limonest", "Lissieu", "Lyon",
    "Marcy-l'Étoile", "Meyzieu", "Mions", "Montanay",
    "Neuville-sur-Saône", "Oullins-Pierre-Bénite",
    "Poleymieux-au-Mont-d'Or", "Quincieux", "Rillieux-la-Pape",
    "Rochetaillée-sur-Saône", "Saint-Cyr-au-Mont-d'Or",
    "Saint-Didier-au-Mont-d'Or", "Saint-Fons", "Saint-Genis-Laval",
    "Saint-Genis-les-Ollières", "Saint-Germain-au-Mont-d'Or",
    "Saint-Priest", "Saint-Romain-au-Mont-d'Or", "Sainte-Foy-lès-Lyon",
    "Sathonay-Camp", "Sathonay-Village", "Solaize",
    "Tassin-la-Demi-Lune", "Vaulx-en-Velin", "Vénissieux", "Vernaison",
    "Villeurbanne",
)
```

Store `epci_code` as `200046977`, and use the official Grand Lyon page as the
group's `source_url`; the Geo API URL remains the snapshot's machine-readable
source. The script must accept `--output`, defaulting to
`src/jobscraper/data/french_metropolises.json`, so generation never occurs on
import.

- [ ] **Step 4: Generate and inspect the snapshot**

Run:

```bash
python scripts/update_metropole_data.py
python -m json.tool src/jobscraper/data/french_metropolises.json >/dev/null
```

Expected: the file contains exactly 10 groups and the counts from
`EXPECTED_COUNTS`; the command exits 0. Review `git diff` to confirm that only
official names, aliases, metadata, and commune records are present.

- [ ] **Step 5: Implement the validated packaged-data loader**

Add package marker `src/jobscraper/data/__init__.py`, then implement the data
boundary in `location_matching.py`:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Any

from jobscraper.services.normalization import normalize_location

_INSEE_CODE = re.compile(r"^(?:[0-9]{5}|2[AB][0-9]{3})$")


class LocationReferenceError(RuntimeError):
    """Raised when bundled metropolitan reference data is invalid."""


@dataclass(frozen=True)
class Metropole:
    key: str
    official_name: str
    city_center: str
    activation_aliases: frozenset[str]
    communes: frozenset[str]


def _read_payload() -> dict[str, Any]:
    resource = resources.files("jobscraper.data").joinpath(
        "french_metropolises.json"
    )
    try:
        value = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocationReferenceError(
            "Bundled French metropole reference data is unreadable"
        ) from exc
    if not isinstance(value, dict):
        raise LocationReferenceError("Metropole reference root must be an object")
    return value


def _load_metropolises() -> tuple[Metropole, ...]:
    payload = _read_payload()
    if payload.get("reference_date") != "2026-01-01":
        raise LocationReferenceError("Metropole reference date must be 2026-01-01")
    raw_groups = payload.get("groups")
    if not isinstance(raw_groups, list) or len(raw_groups) != 10:
        raise LocationReferenceError("Metropole reference must contain 10 groups")

    result: list[Metropole] = []
    aliases_seen: set[str] = set()
    for raw in raw_groups:
        if not isinstance(raw, dict):
            raise LocationReferenceError("Each metropole group must be an object")
        try:
            key = str(raw["key"])
            official_name = str(raw["official_name"])
            source_url = str(raw["source_url"])
            city_center = normalize_location(str(raw["city_center"]))
            aliases = frozenset(
                normalize_location(str(alias))
                for alias in raw["activation_aliases"]
            )
            commune_rows = raw["communes"]
        except (KeyError, TypeError) as exc:
            raise LocationReferenceError("Metropole group fields are invalid") from exc
        if not key or not official_name or not source_url.startswith("https://"):
            raise LocationReferenceError("Metropole metadata is invalid")
        if not isinstance(commune_rows, list) or not commune_rows:
            raise LocationReferenceError(f"Metropole {key} has no communes")
        codes: set[str] = set()
        communes: set[str] = set()
        for row in commune_rows:
            code = str(row.get("insee_code", ""))
            name = normalize_location(str(row.get("name", "")))
            if not _INSEE_CODE.fullmatch(code.upper()) or not name:
                raise LocationReferenceError(f"Metropole {key} has an invalid commune")
            if code in codes or name in communes:
                raise LocationReferenceError(f"Metropole {key} has duplicate communes")
            codes.add(code)
            communes.add(name)
        if not aliases or city_center not in aliases or city_center not in communes:
            raise LocationReferenceError(f"Metropole {key} is missing its city center")
        duplicate_aliases = aliases_seen.intersection(aliases)
        if duplicate_aliases:
            raise LocationReferenceError("Metropole activation alias is duplicated")
        aliases_seen.update(aliases)
        result.append(
            Metropole(
                key=key,
                official_name=official_name,
                city_center=city_center,
                activation_aliases=aliases,
                communes=frozenset(communes),
            )
        )
    return tuple(result)


_METROPOLES = _load_metropolises()
```

Add this setuptools rule after `[tool.setuptools]` in `pyproject.toml`:

```toml
[tool.setuptools.package-data]
"jobscraper.data" = ["*.json"]
```

- [ ] **Step 6: Run focused tests and build-package verification**

Run:

```bash
pytest tests/services/test_location_matching.py -v
python -m build --wheel
python -c 'import glob, zipfile; p=glob.glob("dist/jobscraper-*.whl")[-1]; z=zipfile.ZipFile(p); assert any(n.endswith("jobscraper/data/french_metropolises.json") for n in z.namelist())'
```

Expected: tests pass, wheel builds, and the package-data assertion exits 0.

- [ ] **Step 7: Commit the reference layer**

```bash
git add pyproject.toml scripts/update_metropole_data.py src/jobscraper/data src/jobscraper/services/location_matching.py tests/services/test_location_matching.py
git commit -m "feat: add French metropole reference data"
```

### Task 2: Implement metropolitan and municipal matching

**Files:**
- Modify: `src/jobscraper/services/location_matching.py`
- Modify: `tests/services/test_location_matching.py`

**Interfaces:**
- Consumes: `_METROPOLES: tuple[Metropole, ...]` from Task 1 and `normalize_location(value: str) -> str`.
- Produces: `location_matches(candidate: str, requested: str) -> bool` for repository use in Task 3.

- [ ] **Step 1: Add failing behavior tests for all ten groups**

Append these table-driven tests:

```python
from jobscraper.services.location_matching import location_matches


@pytest.mark.parametrize(
    ("requested", "candidate"),
    [
        ("Paris", "Boulogne-Billancourt - 92"),
        ("Métropole du Grand Paris", "Saint-Denis, France"),
        ("Marseille", "Aix-en-Provence - 13"),
        ("Aix-Marseille", "Aubagne"),
        ("Lyon", "Villeurbanne - 69"),
        ("Grand Lyon", "Bron"),
        ("Lille", "Roubaix"),
        ("Métropole Européenne de Lille", "Tourcoing"),
        ("Bordeaux", "Mérignac"),
        ("Toulouse", "Blagnac"),
        ("Nantes", "Saint-Herblain"),
        ("Nice", "Cagnes-sur-Mer"),
        ("Montpellier", "Lattes"),
        ("Strasbourg", "Schiltigheim"),
    ],
)
def test_city_centers_and_aliases_expand_to_official_metropole(
    requested: str, candidate: str
) -> None:
    assert location_matches(candidate, requested)


@pytest.mark.parametrize(
    ("requested", "candidate"),
    [
        ("Paris", "Melun"),
        ("Marseille", "Avignon"),
        ("Lyon", "Villefranche-sur-Saône"),
        ("Villeurbanne", "Bron"),
        ("Roubaix", "Lille"),
        ("Unknownville", "Paris"),
    ],
)
def test_metropole_matching_does_not_broaden_unrecognized_or_member_tags(
    requested: str, candidate: str
) -> None:
    assert not location_matches(candidate, requested)


@pytest.mark.parametrize(
    ("requested", "candidate"),
    [
        ("lyon", "Lyon 7e - 69"),
        ("Métropole de Lyon", "Lyon 7ème arrondissement, France"),
        ("Paris", "Paris 20e arrondissement - 75"),
        ("Marseille", "Marseille 16ème (13)"),
        ("MÉTROPOLE NICE CÔTE D'AZUR", "Nice - 06"),
        ("Villeurbanne", "VILLEURBANNE, France"),
    ],
)
def test_location_matching_handles_arrondissements_and_normalization(
    requested: str, candidate: str
) -> None:
    assert location_matches(candidate, requested)


@pytest.mark.parametrize(
    ("requested", "candidate"),
    [("Lyon", "Lyon 10e"), ("Marseille", "Marseille 17e"), ("Paris", "Paris 21e")],
)
def test_out_of_range_arrondissements_are_not_collapsed(
    requested: str, candidate: str
) -> None:
    assert not location_matches(candidate, requested)
```

- [ ] **Step 2: Run matcher tests and verify `location_matches` is missing**

Run:

```bash
pytest tests/services/test_location_matching.py -v
```

Expected: collection fails because `location_matches` is not defined.

- [ ] **Step 3: Implement alias expansion and bounded arrondissement reduction**

Append the following shape to `location_matching.py`; keep the alias index
immutable after import:

```python
_BY_ALIAS = {
    alias: metropole
    for metropole in _METROPOLES
    for alias in metropole.activation_aliases
}
_ARRONDISSEMENT = re.compile(
    r"^(paris|lyon|marseille)\s+([0-9]{1,2})(?:er|e|eme)?(?:\s+arrondissement)?$"
)
_ARRONDISSEMENT_MAX = {"paris": 20, "lyon": 9, "marseille": 16}


def _municipality_key(value: str) -> str:
    normalized = normalize_location(value)
    match = _ARRONDISSEMENT.fullmatch(normalized)
    if match is None:
        return normalized
    city, raw_number = match.groups()
    number = int(raw_number)
    return city if 1 <= number <= _ARRONDISSEMENT_MAX[city] else normalized


def location_matches(candidate: str, requested: str) -> bool:
    """Match one job location against one municipal or metropolitan request."""

    requested_key = _municipality_key(requested)
    candidate_key = _municipality_key(candidate)
    metropole = _BY_ALIAS.get(requested_key)
    if metropole is None:
        return candidate_key == requested_key
    return candidate_key in metropole.communes
```

Do not add fuzzy matching, substring matching, radius logic, or automatic
expansion for member communes.

- [ ] **Step 4: Run the complete matcher and normalization tests**

Run:

```bash
pytest tests/services/test_location_matching.py tests/services/test_normalization.py -v
mypy src/jobscraper/services/location_matching.py
```

Expected: all tests pass and mypy reports success.

- [ ] **Step 5: Commit the matching engine**

```bash
git add src/jobscraper/services/location_matching.py tests/services/test_location_matching.py
git commit -m "feat: match jobs across major French metropoles"
```

### Task 3: Integrate metropolitan matching into job queries

**Files:**
- Modify: `src/jobscraper/repositories/jobs.py:14-20,245-259`
- Modify: `tests/repositories/test_jobs.py:83-150`
- Modify: `tests/api/test_jobs.py:84-104`

**Interfaces:**
- Consumes: `location_matches(candidate: str, requested: str) -> bool` from Task 2.
- Produces: unchanged `JobRepository.list_jobs(..., locations: Sequence[str] | None = None, ...) -> list[CanonicalJob]` behavior with metropolitan expansion and OR semantics; unchanged `GET /api/jobs?location=...` contract.

- [ ] **Step 1: Add failing repository regressions**

Add focused tests outside the broad all-filter test so failures identify the
location behavior precisely:

```python
def test_location_filter_expands_center_alias_and_keeps_member_filter_municipal(
    session: Session,
) -> None:
    jobs = JobRepository(session)
    lyon = jobs.upsert_listing(offer("lyon", location="Lyon - 69"), seen_at=NOW)
    villeurbanne = jobs.upsert_listing(
        offer("villeurbanne", location="Villeurbanne"), seen_at=NOW
    )
    bron = jobs.upsert_listing(offer("bron", location="Bron"), seen_at=NOW)
    outside = jobs.upsert_listing(
        offer("outside", location="Villefranche-sur-Saône"), seen_at=NOW
    )

    assert {job.id for job in jobs.list_jobs(locations=["Lyon"])} == {
        lyon.id,
        villeurbanne.id,
        bron.id,
    }
    assert [job.id for job in jobs.list_jobs(locations=["Villeurbanne"])] == [
        villeurbanne.id
    ]
    assert outside.id not in {
        job.id for job in jobs.list_jobs(locations=["Métropole de Lyon"])
    }


def test_multiple_location_filters_keep_or_semantics(session: Session) -> None:
    jobs = JobRepository(session)
    bron = jobs.upsert_listing(offer("bron-or", location="Bron"), seen_at=NOW)
    rennes = jobs.upsert_listing(offer("rennes-or", location="Rennes"), seen_at=NOW)
    excluded = jobs.upsert_listing(offer("dijon-or", location="Dijon"), seen_at=NOW)

    result = jobs.list_jobs(locations=["Lyon", "Rennes"])

    assert {job.id for job in result} == {bron.id, rennes.id}
    assert excluded.id not in {job.id for job in result}
```

- [ ] **Step 2: Add a failing public API regression**

Add a test proving query forwarding and response totals:

```python
def test_location_query_expands_lyon_metropole(
    client: TestClient, session: Session
) -> None:
    jobs = JobRepository(session)
    villeurbanne = jobs.upsert_listing(
        offer("metro-villeurbanne", location="Villeurbanne"), seen_at=utc_now()
    )
    jobs.upsert_listing(
        offer("metro-outside", location="Villefranche-sur-Saône"),
        seen_at=utc_now(),
    )
    session.commit()

    response = client.get(
        "/api/jobs",
        params={"period": "all", "location": "Lyon"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [item["id"] for item in response.json()["items"]] == [villeurbanne.id]
```

- [ ] **Step 3: Run the focused integration tests and observe exact-match failures**

Run:

```bash
pytest tests/repositories/test_jobs.py -k location -v
pytest tests/api/test_jobs.py -k location -v
```

Expected: the Lyon-expansion assertions fail because the repository still uses
private exact comparison.

- [ ] **Step 4: Delegate repository location decisions to the matcher**

Import the new function:

```python
from jobscraper.services.location_matching import location_matches
```

Replace the existing location condition in `matches` with:

```python
if locations and not any(
    location_matches(job.location, requested) for requested in locations
):
    return False
```

Keep `_normalise` because query, company, skill, and other existing filters
still use it.

- [ ] **Step 5: Run focused repository and API tests**

Run:

```bash
pytest tests/services/test_location_matching.py tests/repositories/test_jobs.py tests/api/test_jobs.py -v
```

Expected: all focused tests pass.

- [ ] **Step 6: Run complete verification**

Run:

```bash
pytest -m "not live"
mypy src/jobscraper
git diff --check
```

Expected: the complete non-live suite passes, mypy reports no errors, and Git
reports no whitespace errors.

- [ ] **Step 7: Commit the integration**

```bash
git add src/jobscraper/repositories/jobs.py tests/repositories/test_jobs.py tests/api/test_jobs.py
git commit -m "feat: expand major-city location filters"
```

- [ ] **Step 8: Manually verify the original Lyon regression**

With the local API running against the user's existing database, request:

```bash
curl --get 'http://127.0.0.1:8000/api/jobs' \
  --data-urlencode 'savedSearchId=64a565fb-5a6a-40ad-b31a-3055e93cec17' \
  --data-urlencode 'period=3d' \
  --data-urlencode 'location=Lyon' \
  --data-urlencode 'limit=100'
```

Expected: HTTP 200, and offer `hellowork_80951443` (canonical job
`087ff419-68b0-4774-987b-a3573e95eebb`, stored as `Lyon - 69`) is present when
it remains active and within the selected period. If the fixture database has
aged past the three-day window, repeat with `period=all` to isolate location
matching from time filtering.
