# Correctif post-installation — état launchd multi-mots

## Cause

La sortie réelle de `launchctl print` contient `state = not running`. Le motif
`(\S+)` ne conservait que `not`, ensuite affiché tel quel par le CLI.

## Correction TDD

- Un test reproduit une sortie `launchctl` multi-lignes et vérifie les états
  `not running`, `waiting` et `running`.
- Le parseur capture désormais toute la valeur non vide jusqu'à la fin de la
  ligne, puis retire ses espaces périphériques.
- Le CLI traduit les états connus :
  - `not running` et `waiting` : « chargée et en attente » ;
  - `running` : « active (état : en cours) ».
- Un état inconnu reste affiché comme état launchd brut afin de conserver
  l'information de diagnostic.

## Vérifications fraîches

- RED : `not running` était parsé en `not` et les trois libellés restaient en
  anglais.
- `tests/automation/test_launchd.py` : 55 réussis, y compris install/uninstall.
- Backend non-live : 619 réussis, 4 désélectionnés.
- Mypy : 43 fichiers source sans erreur.
- Isort, Black et `git diff --check` : propres.
- Statut utilisateur réel :
  `Automatisation chargée et en attente. Planification : 08:00.`
