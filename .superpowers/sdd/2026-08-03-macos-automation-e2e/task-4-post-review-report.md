# Task 4 — Correctifs post-revue

## Défaut reproduit

Depuis un répertoire temporaire, l’installation editable échouait en mode fake
avec `ModuleNotFoundError: No module named 'tests'`. Le runtime importait
`tests.e2e.fake_scrapers`, alors que seul `src/` est exposé par l’installation
editable et que `tests` n’est pas un package distribué.

## Correction

- Le registry déterministe se trouve désormais dans le package installable
  `jobscraper.testing.fake_scrapers`.
- Son import reste tardif et n’a lieu que pour
  `JOBSCRAPER_SCRAPER_MODE=fake`.
- Le mode live demeure la valeur par défaut et `fake` reste refusé avant toute
  création de base lorsque `JOBSCRAPER_ENV=production`.
- Un test subprocess retire `PYTHONPATH`, change le répertoire courant et
  compose réellement le runtime via l’installation editable.
- Les traces Playwright sont conservées sous `.artifacts/playwright`, répertoire
  workspace ignoré par Git. En cas d’échec, le runner affiche ce chemin après
  avoir arrêté le serveur et supprimé uniquement son SQLite temporaire.

## TDD et vérifications

RED observés :

- le subprocess hors dépôt échouait sur l’import de `tests` ;
- le contrat du runner ne trouvait ni chemin workspace persistant ni message
  d’artefacts en échec.

GREEN frais :

- tests ciblés runtime/runner : 17 réussis ;
- backend non-live : 613 réussis, 4 désélectionnés ;
- mypy : 43 fichiers source sans erreur ;
- frontend Vitest : 81 réussis ;
- E2E réel : 1 réussi en 6,7 s, avec build React, CLI `serve`, FastAPI et
  SQLite temporaire ;
- isort, Black, `sh -n` et `git diff --check` : propres.
