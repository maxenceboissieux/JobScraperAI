# Top Ten French Metropole Location Filter Design

## Context and goal

The job location filter currently compares normalized strings for exact
equality. A filter value of `Lyon` therefore excludes a stored location such as
`Lyon - 69`, and it cannot include neighboring communes such as Villeurbanne.

The filter will support the official metropolitan perimeter of the ten largest
French metropolitan groups selected for this product:

1. Metropole du Grand Paris;
2. Metropole d'Aix-Marseille-Provence;
3. Metropole de Lyon;
4. Metropole Europeenne de Lille;
5. Bordeaux Metropole;
6. Toulouse Metropole;
7. Nantes Metropole;
8. Metropole Nice Cote d'Azur;
9. Montpellier Mediterranee Metropole;
10. Eurometropole de Strasbourg.

The selection is fixed and versioned with the application. It is based on the
2026 population ranking published by the Direction generale des collectivites
locales (DGCL), with the Metropole de Lyon inserted because its special local
authority status keeps it out of the DGCL EPCI table.

Official sources:

- DGCL, populations and commune counts of metropolitan EPCIs on 1 January
  2026: <https://www.collectivites-locales.gouv.fr/files/files/Etudes-et-statistiques/DESL/2026/EPCI/listem%C3%A9tropolejanvier2026.pdf>
- French government administrative boundaries API, including the endpoint
  `/epcis/{code}/communes`: <https://geo.api.gouv.fr/decoupage-administratif/communes>
- Metropole de Lyon, official list of its 58 communes:
  <https://www.grandlyon.com/metropole/les-58-communes-de-la-metropole>

## User-visible behavior

A city-center tag activates its whole official metropolitan group. Full
metropole names and the explicit common aliases below activate the same group:

| City-center tag | Accepted metropole aliases |
| --- | --- |
| `Paris` | `Grand Paris`, `Metropole du Grand Paris` |
| `Marseille` | `Aix-Marseille`, `Aix-Marseille-Provence`, `Metropole d'Aix-Marseille-Provence` |
| `Lyon` | `Grand Lyon`, `Metropole de Lyon` |
| `Lille` | `Metropole Europeenne de Lille` |
| `Bordeaux` | `Bordeaux Metropole` |
| `Toulouse` | `Toulouse Metropole` |
| `Nantes` | `Nantes Metropole` |
| `Nice` | `Nice Cote d'Azur`, `Metropole Nice Cote d'Azur` |
| `Montpellier` | `Montpellier Mediterranee Metropole` |
| `Strasbourg` | `Eurometropole de Strasbourg` |

Matching ignores case, accents, punctuation, extra whitespace, department
suffixes such as `- 69` or `(69)`, and country suffixes such as `, France`.
Paris, Lyon, and Marseille arrondissement forms are members of their respective
groups.

A member commune typed directly remains a municipal filter. For example,
`Villeurbanne` matches Villeurbanne offers only; it does not expand to the
whole Metropole de Lyon. This prevents surprising broad results for ordinary
city searches.

Multiple location tags keep their existing OR semantics. A commune outside an
official perimeter remains excluded even when it is geographically close or
in the same department. Examples include Melun for Paris, Avignon for
Marseille, and Villefranche-sur-Saone for Lyon.

## Architecture

Add a focused `jobscraper.services.location_matching` module with one public
operation:

```python
location_matches(candidate: str, requested: str) -> bool
```

The module loads immutable, versioned local reference data and uses the
existing `normalize_location` function for both values. It resolves the
requested value to either:

- one metropolitan group when it equals an activation alias; or
- one normalized municipality for all other values.

It then tests the candidate against the resolved set. Arrondissement variants
are reduced to their city center before the membership check. Unrecognized or
malformed values safely fall back to normalized equality; they never broaden a
search.

`JobRepository.list_jobs` will replace its private exact location comparison
with this matcher. API query parameters, saved-search records, frontend state,
and filter controls remain unchanged.

## Local reference data

Store the metropolitan definitions in a dedicated versioned JSON file under
`src/jobscraper/data`. Each entry contains:

- a stable internal key;
- the official name;
- activation aliases;
- the official EPCI code where applicable;
- the reference date and source URL;
- commune names and INSEE codes.

For the nine EPCI-based groups, commune membership is obtained during
development from the government endpoint `/epcis/{code}/communes`. The
Metropole de Lyon entry uses its official 58-commune list. There is no network
request at application startup or while filtering.

The reference metadata makes future updates auditable. Updating metropolitan
perimeters is an explicit maintenance change: regenerate or edit the JSON,
review its diff, and run the membership tests. The implementation plan will
include a small validation step that rejects duplicate aliases, duplicate
communes inside a group, missing city centers, empty groups, and malformed
INSEE codes.

## Data flow and failure behavior

1. The frontend sends the existing repeated `location` query parameter.
2. The API forwards the requested tags unchanged.
3. The repository calls `location_matches` for each candidate and requested
   tag, preserving OR behavior.
4. The matcher normalizes both values, expands only recognized activation
   aliases, and checks group membership or municipal equality.

If the reference file cannot be parsed or fails validation, application
startup must fail with a clear configuration error rather than silently return
incorrect jobs. Individual unknown location strings still use exact normalized
matching.

## Testing and acceptance criteria

Unit tests for the matcher will cover normalization, activation aliases,
municipal fallback, arrondissement handling, and every configured group.
Representative acceptance cases are:

- `Paris` matches Boulogne-Billancourt but not Melun;
- `Marseille` matches Aix-en-Provence and Aubagne but not Avignon;
- `Lyon` matches `Lyon - 69`, `Lyon 7e - 69`, Villeurbanne, and Bron, but not
  Villefranche-sur-Saone;
- `Lille` matches Roubaix and Tourcoing;
- `Bordeaux` matches Merignac;
- `Toulouse` matches Blagnac;
- `Nantes` matches Saint-Herblain;
- `Nice` matches Cagnes-sur-Mer;
- `Montpellier` matches Lattes;
- `Strasbourg` matches Schiltigheim;
- accents, case, punctuation, department suffixes, and `France` suffixes do not
  alter the result;
- `Villeurbanne` matches Villeurbanne but does not match Bron;
- multiple requested tags preserve OR behavior.

Data-validation tests will assert the ten expected group keys, each official
city center, unique aliases, unique INSEE codes within each group, and the
published commune count for every reference snapshot.

Repository tests will prove that the matcher is used by `list_jobs`. An API
regression test will pass `location=Lyon` and verify that a metropolitan
commune is returned while an outside commune is excluded. The complete
non-live backend suite must remain green. No database migration or frontend
change is required.

## Scope exclusions

- No radius, travel-time, department, region, or free-form geocoding search.
- No automatic expansion for a member commune that is not a city-center alias.
- No runtime dependency on an external geographic service.
- No change to scraping, job normalization at ingestion, or the saved-search
  schema.
