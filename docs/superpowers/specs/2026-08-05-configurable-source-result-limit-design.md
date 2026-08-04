# Limite configurable de résultats par source

## Contexte

Les synchronisations construisent actuellement un `SearchCriteria` sans limite explicite et héritent donc du plafond par défaut de 100 résultats. Lorsqu'un scraper strict comme HelloWork produit exactement 100 offres, le consommateur s'arrête volontairement sans épuiser le générateur. `SyncService` contrôle toutefois `search_complete` avant de traiter ce plafond attendu : il transforme alors la troncature en `IncompleteSearchError`, journalise un traceback et enregistre une erreur générique.

La synchronisation observée confirme ce chemin : HelloWork a persisté exactement 100 offres avant d'être classé `partial`. Le plafond doit rester non autoritaire afin de ne pas désactiver des offres non parcourues, mais il ne doit pas être traité comme une panne.

## Objectifs

- Permettre de choisir le nombre maximum d'offres parcourues par source pour chaque recherche sauvegardée.
- Appliquer automatiquement 500 aux recherches existantes et aux nouvelles recherches par défaut.
- Classer un plafond atteint comme une synchronisation partielle attendue, sans exception ni traceback.
- Préserver les contrôles stricts pour toute source réellement épuisée qui n'a pas confirmé sa complétude.

## Modèle de données et migration

La table `saved_searches` reçoit une colonne entière non nulle `max_results` avec une valeur par défaut de 500. La migration Alembic ajoute la colonne avec un `server_default` de 500 afin que toutes les lignes existantes obtiennent automatiquement cette valeur. Le modèle SQLAlchemy conserve également 500 comme valeur par défaut applicative.

La valeur doit être comprise entre 1 et 1 000 inclus. Aucune valeur « illimitée » n'est ajoutée : elle rendrait la durée, les quotas API et la terminaison des scrapers imprévisibles.

## Contrat API

Le champ HTTP s'appelle `maxResults` grâce à la conversion camelCase existante.

- Création : champ optionnel, valeur par défaut 500.
- Mise à jour : champ optionnel ; lorsqu'il est présent, il ne peut pas être nul.
- Lecture : champ entier obligatoire dans `SavedSearchResponse`.
- Validation : minimum 1, maximum 1 000.

Le repository copie `SearchCriteria.max_results` vers `SavedSearch.max_results` à la création et à la mise à jour. La reconstruction des critères dans `SyncService._criteria` transmet la valeur persistée, de sorte que le plafond s'applique séparément à chaque source demandée.

## Comportement de synchronisation

Après `_consume_offers`, `SyncService` distingue deux situations dans cet ordre :

1. `progress.exhausted` est faux : le consommateur a atteint `max_results`. La source est enregistrée `partial` avec le message existant indiquant que la limite a été atteinte. Aucun `IncompleteSearchError` n'est levé, aucun traceback n'est journalisé et aucune offre non vue n'est désactivée.
2. `progress.exhausted` est vrai : le générateur s'est terminé. Pour un scraper strict, `search_complete` doit alors être vrai ; sinon le comportement d'erreur actuel est conservé.

Le scraper HelloWork reste honnête : atteindre la limite ne marque pas sa pagination comme complète. La correction est centralisée dans le service et bénéficie à tous les scrapers stricts.

## Interface

Le formulaire de création et de modification d'une recherche affiche un sélecteur intitulé « Offres maximum par source » avec quatre valeurs :

- 100 ;
- 250 ;
- 500 ;
- 1 000.

La valeur initiale d'une nouvelle recherche est 500. Une recherche existante affiche la valeur renvoyée par l'API. Le champ participe à la détection des modifications, à la validation du formulaire, au payload de création et au patch de mise à jour.

## Compatibilité et erreurs

- La migration locale est exécutée par le mécanisme Alembic existant ; aucun script manuel de mise à jour de la base n'est nécessaire.
- Les anciennes lignes reçoivent 500 automatiquement.
- Les clients envoyant une valeur hors intervalle reçoivent une erreur de validation HTTP 422.
- Les autres critères, les filtres d'affichage des offres et la pagination du frontend ne changent pas.
- Les erreurs réseau, parsing, pagination incohérente et fermeture de scraper conservent leur comportement actuel.

## Tests et validation

Les tests couvrent :

- migration d'une base existante et valeur 500 sur les lignes antérieures ;
- valeur par défaut SQLAlchemy et persistance repository ;
- création, lecture et mise à jour API avec `maxResults` ;
- rejet des valeurs 0, supérieures à 1 000 et nulles en mise à jour ;
- reconstruction de `SearchCriteria.max_results` par le service ;
- scraper strict plafonné classé `partial` avec le message de limite, sans traceback et sans désactivation ;
- vraie fin incomplète toujours signalée comme erreur ;
- formulaire frontend par défaut à 500, édition des quatre valeurs et payloads corrects ;
- suites backend hors réseau, typecheck, tests frontend et build de production.

## Hors périmètre

Ce changement ne propose pas de mode illimité, ne modifie pas les quotas des fournisseurs, ne garantit pas qu'une source possède autant d'offres que la limite choisie et ne change pas le nombre de cartes affichées par page dans le frontend.
