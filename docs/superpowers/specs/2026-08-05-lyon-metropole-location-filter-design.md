# Lyon Métropole Location Filter Design

## Context

The job location filter currently compares normalized strings for exact
equality. A filter value of `Lyon` therefore excludes a stored location such as
`Lyon - 69`. It also cannot express the user's intended metropolitan scope,
which must include neighboring communes such as Villeurbanne and Bron.

The official Métropole de Lyon page lists 58 communes. The application will use
that authoritative list as a small local reference set, avoiding network calls
during filtering.

Source: <https://www.grandlyon.com/metropole/les-58-communes-de-la-metropole>
(official page last updated 2025-12-23 when this design was written).

## User-visible behavior

- A location tag equal to `Lyon` or `Métropole de Lyon`, ignoring case,
  accents, punctuation, and extra whitespace, activates metropolitan matching.
- Metropolitan matching includes all 58 official communes, including
  Villeurbanne, Bron, Vénissieux, Caluire-et-Cuire, Oullins-Pierre-Bénite, and
  Lyon.
- Lyon arrondissement variants such as `Lyon 7e`, `Lyon 7e - 69`, and
  `Lyon 7e arrondissement` are included.
- Common source suffixes such as `- 69`, `(69)`, and `, France` do not affect
  matching.
- A commune outside the Métropole, such as Villefranche-sur-Saône, remains
  excluded even when it is in the Rhône department.
- Other location tags retain city-level matching. For example, `Paris` matches
  `Paris - 75` but does not activate a regional expansion.
- Multiple location tags retain their existing OR semantics.

## Architecture

Add a focused location-matching module under `jobscraper.services`. It owns:

1. an immutable, normalized set of the 58 official communes;
2. the normalized aliases that activate the metropolitan group;
3. `location_matches(candidate: str, requested: str) -> bool`.

The matcher first uses the existing `normalize_location` function so accents,
department suffixes, France qualifiers, and punctuation are handled
consistently. If the requested value is a Lyon Métropole alias, it checks group
membership and explicit Lyon-arrondissement syntax. Otherwise it performs
normalized city equality.

`JobRepository.list_jobs` will replace its private exact location comparison
with this matcher. API parameters and frontend URL/state formats remain
unchanged.

## Local reference data

The reference set contains the official communes listed by the Métropole de
Lyon: Albigny-sur-Saône, Bron, Cailloux-sur-Fontaines, Caluire-et-Cuire,
Champagne-au-Mont-d'Or, Charbonnières-les-Bains, Charly, Chassieu,
Collonges-au-Mont-d'Or, Corbas, Couzon-au-Mont-d'Or, Craponne,
Curis-au-Mont-d'Or, Dardilly, Décines-Charpieu, Écully, Feyzin,
Fleurieu-sur-Saône, Fontaines-Saint-Martin, Fontaines-sur-Saône, Francheville,
Genay, Givors, Grigny-sur-Rhône, Irigny, Jonage, La Mulatière,
La Tour-de-Salvagny, Limonest, Lissieu, Lyon, Marcy-l'Étoile, Meyzieu, Mions,
Montanay, Neuville-sur-Saône, Oullins-Pierre-Bénite,
Poleymieux-au-Mont-d'Or, Quincieux, Rillieux-la-Pape,
Rochetaillée-sur-Saône, Saint-Cyr-au-Mont-d'Or,
Saint-Didier-au-Mont-d'Or, Saint-Fons, Saint-Genis-Laval,
Saint-Genis-les-Ollières, Saint-Germain-au-Mont-d'Or, Saint-Priest,
Saint-Romain-au-Mont-d'Or, Sainte-Foy-lès-Lyon, Sathonay-Camp,
Sathonay-Village, Solaize, Tassin-la-Demi-Lune, Vaulx-en-Velin, Vénissieux,
Vernaison, and Villeurbanne.

The values are normalized at module load rather than duplicated in normalized
form. Updating the official list is a code/data maintenance change, not a
runtime network dependency.

## Testing

Repository tests will prove:

- `Lyon` matches `Lyon - 69`, `Lyon 7e - 69`, Villeurbanne, and Bron;
- `Métropole de Lyon` activates the same group;
- case and accents do not change results;
- Villefranche-sur-Saône is excluded;
- `Paris` matches `Paris - 75` without matching an unrelated city;
- multiple requested locations keep OR behavior.

An API regression will pass `location=Lyon` and verify that a Lyon Métropole
commune is returned while an outside commune is excluded. The complete non-live
backend suite must remain green. No migration, frontend change, or network test
is required.
