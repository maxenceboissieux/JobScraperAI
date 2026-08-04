# Task 4 report — Grille responsive des offres

## Statut

DONE

## Commit

- `feat: display responsive job-card grid` (inclut cette tâche et ce rapport)

## Chronologie TDD

- RED : les cinq scénarios initiaux échouaient avec l’aperçu provisoire :
  aucune carte API, aucun état vide/erreur, aucune pagination et aucune
  sélection d’offre dans l’URL.
- GREEN : `JobGrid`, `JobCard` et le squelette ont rendu les cartes et leurs
  états via `api.getJobs(filters, signal)` dans une requête TanStack Query.
  Les cinq scénarios étaient verts.
- RED : le scénario de DTO incomplet levait `RangeError: Invalid currency code`
  pour une devise absente.
- GREEN : le formatage du salaire ignore désormais les montants sans devise ISO
  exploitable ; les six scénarios de la grille sont verts.
- Régression de suite : l’ajout de la grille déclenchait des requêtes jobs sans
  handler dans les tests existants. La cause était l’absence de réponse par
  défaut dans le serveur MSW partagé. Un handler de page vide a supprimé ces
  avertissements, tout en restant surchargeable par les tests de grille.

## Vérifications

- `cd frontend && pnpm test src/features/jobs/job-grid.test.tsx` — 6/6 passés.
- `cd frontend && pnpm test` — 55/55 passés dans 5 fichiers, sans avertissement.
- `cd frontend && pnpm typecheck` — passé (`tsc --noEmit`).
- `cd frontend && pnpm build` — passé ; Vite a produit `frontend/dist`.
- `git diff --check` — passé.

## Fichiers modifiés

- `frontend/src/app/App.tsx`
- `frontend/src/main.tsx`
- `frontend/src/test/server.ts`
- `frontend/src/features/jobs/JobCard.tsx`
- `frontend/src/features/jobs/JobGrid.tsx`
- `frontend/src/features/jobs/JobGridSkeleton.tsx`
- `frontend/src/features/jobs/job-grid.test.tsx`
- `frontend/src/styles/jobs.css`

## Auto-review

- La query key contient les filtres complets, les filtres existants sont transmis
  sans transformation et le `signal` TanStack est propagé à l’API.
- Les cartes n’affichent que les valeurs présentes, incluent les sources, le
  badge de doublon possible et un bouton accessible « Voir l’offre … ».
- La pagination s’appuie sur `limit`, `offset` et `total` retournés par l’API ;
  la sélection ajoute seulement `job` à l’URL existante.
- La grille emploie exactement `repeat(auto-fill, minmax(280px, 1fr))` et les
  liens externes ne sont pas rendus.

## Préoccupations

Aucune.
