# Correctif des filtres de contrat Adzuna

## Contexte

Une recherche sauvegardée contenant CDI, CDD et freelance échoue avec un HTTP 400. Le scraper envoie `contract_type=contract`, alors que `contract_type` est un champ de réponse Adzuna et non un filtre de recherche accepté. Des essais minimaux avec les identifiants locaux ont confirmé que `contract_type=contract` renvoie 400, tandis que `permanent=1` et `contract=1` renvoient 200 lorsqu'ils sont utilisés séparément. Adzuna refuse également de combiner `permanent=1` et `contract=1` dans une même requête.

## Objectif

Permettre aux recherches Adzuna simples ou mixtes contenant CDI, CDD, intérim ou freelance de terminer sans paramètre invalide, tout en conservant un plafond global de résultats et en supprimant les doublons entre requêtes.

## Conception

Le scraper regroupe les contrats sélectionnés dans les familles qu'Adzuna sait filtrer :

- CDI utilise `permanent=1` ;
- CDD, intérim et freelance utilisent `contract=1`.

Une seule requête est exécutée lorsqu'une seule famille est demandée. Lorsque les deux familles sont présentes, le scraper exécute deux recherches indépendantes, puis fusionne leurs résultats. Il ne combine jamais `permanent=1` et `contract=1` dans la même requête.

Le filtre `full_time=1` est supprimé : un CDI ne signifie pas nécessairement temps plein, et ce filtre ne doit pas être déduit du type de contrat. Le paramètre invalide `contract_type` n'est plus envoyé.

Adzuna ne fournit pas de filtre public vérifié pour stage ou alternance : `graduate=1` renvoie également 400. Ces types ne créent donc pas de famille de requête Adzuna. S'ils sont les seuls types sélectionnés, la source Adzuna termine proprement sans offre plutôt que de lancer une recherche large et incorrecte. S'ils accompagnent une famille prise en charge, seule cette famille est recherchée.

## Pagination, limite et dédoublonnage

`max_results` reste un plafond global pour toute la recherche Adzuna. Les familles sont parcourues dans un ordre déterministe correspondant à leur première apparition dans les critères. Les identifiants Adzuna déjà émis sont conservés entre les familles afin qu'une offre ne soit produite qu'une fois.

Chaque famille pagine normalement tant que le plafond global n'est pas atteint. Une fois `max_results` atteint, aucune page ni famille supplémentaire n'est appelée.

## Erreurs et complétude

Une réponse invalide, une page partiellement inexploitable, une pagination incohérente ou un échec HTTP conserve le comportement strict existant. Si une famille échoue après qu'une autre a produit des offres, la recherche reste incomplète ; en mode de propagation, l'erreur remonte au service de synchronisation.

Le journal de débogage ne doit plus inclure l'URL complète, car elle contient `app_id` et `app_key`. Il peut indiquer la page et la famille de contrat sans afficher les secrets.

## Tests

Les tests unitaires vérifient :

- CDI seul produit `permanent=1`, sans `contract_type` ni `full_time` ;
- CDD seul produit `contract=1` ;
- CDD, intérim et freelance partagent une seule famille ;
- CDI avec CDD ou freelance déclenche deux requêtes séparées ;
- les résultats des familles sont dédoublonnés et respectent une limite globale ;
- stage ou alternance seuls ne déclenchent pas de requête large ;
- les mots-clés et autres paramètres sont encodés correctement ;
- une erreur sur l'une des familles conserve l'état incomplet et la propagation configurée.

La validation finale exécute les tests Adzuna ciblés, puis l'ensemble des tests hors tests réseau optionnels.

## Hors périmètre

Ce correctif n'ajoute pas de classification locale de stage, alternance, CDD, intérim ou freelance à partir du texte des offres. Il ne modifie ni le modèle de données, ni l'API du frontend, ni la recherche des autres sources.
