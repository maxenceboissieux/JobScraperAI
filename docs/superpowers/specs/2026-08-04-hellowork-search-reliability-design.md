# Fiabilisation des recherches HelloWork

## Contexte

La recherche enregistrée « React front » combine le titre `Developpeur fullstack`
et les mots-clés `react`, `nextjs`, `reactjs`. Le scraper les transmet actuellement
comme une seule valeur `k`. Le moteur HelloWork traite cette combinaison de façon
très restrictive : le titre seul renvoie des offres, tandis que l'ajout de tous les
mots-clés renvoie zéro résultat. La synchronisation est alors enregistrée comme
réussie avec zéro offre.

Le HTML actuel contient toujours des cartes exploitables, mais les classes utilisées
pour le lieu et le contrat ont changé. Une carte affichant `Civrieux - 01` et `CDI`
est donc normalisée à tort avec le lieu `France` et sans contrat.

## Comportement retenu

HelloWork exécute plusieurs requêtes alternatives au lieu d'exiger tous les
mots-clés dans une seule requête :

- une requête avec le titre seul lorsqu'un titre est renseigné ;
- une requête `titre + mot-clé` pour chaque mot-clé ;
- si aucun titre n'est renseigné, une requête par mot-clé ;
- si ni titre ni mot-clé n'est renseigné, une requête sans paramètre `k`.

Les autres filtres HelloWork pris en charge restent identiques sur chaque variante.
Les variantes vides ou identiques après normalisation sont supprimées en conservant
leur ordre.

## Agrégation et pagination

Le scraper parcourt les variantes dans un ordre déterministe. Chaque variante garde
sa propre pagination. Les offres sont dédupliquées globalement par identifiant
HelloWork et sont produites jusqu'à `criteria.max_results`, qui reste une limite
globale et non une limite par variante.

Une page sans carte confirme la fin de la variante courante. Une page contenant
uniquement des identifiants déjà vus termine cette variante sans invalider les
autres : ce cas est normal lorsque deux requêtes alternatives se recouvrent.

La recherche complète n'est confirmée que lorsque toutes les variantes nécessaires
ont atteint une fin fiable. Une erreur réseau, une page partiellement inexploitable
ou une interruption interne conserve le comportement strict existant et empêche la
désactivation abusive des offres non vues.

## Parsing des cartes actuelles

L'extraction continue de privilégier les champs cachés stables pour l'identifiant,
le titre et l'entreprise. Pour le lieu et le contrat, elle reconnaît les éléments
actuels de métadonnées de la carte en plus des anciens sélecteurs. La classification
reste conservatrice : seuls les libellés de contrat connus sont convertis et le lieu
n'est pas déduit d'un texte ambigu.

Aucune modification n'est apportée au schéma de base de données, à l'API, au
frontend, à la déduplication inter-sources ou au chargement des détails.

## Tests et validation

Les tests hors réseau couvrent :

- les variantes avec titre et plusieurs mots-clés ;
- les variantes sans titre et le cas sans terme ;
- l'ordre, la déduplication globale et la limite globale ;
- le chevauchement normal entre variantes ;
- la propagation d'une recherche incomplète ;
- le parsing d'une carte représentative du HTML actuel, notamment
  `Civrieux - 01` et `CDI`.

La validation finale exécute les tests ciblés, la suite backend complète, mypy,
Black et isort, puis une vérification live bornée de la recherche enregistrée. La
base locale de l'utilisateur n'est pas modifiée par les tests.
