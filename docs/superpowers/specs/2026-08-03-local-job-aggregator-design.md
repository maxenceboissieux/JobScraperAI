# Agrégateur local d'offres d'emploi — Design

## Objectif

Transformer le projet CLI existant en une application locale fiable qui agrège des offres d'emploi françaises, ajoute Free-Work comme nouvelle source, conserve les données dans SQLite, réduit l'impact des doublons et fournit une interface web fluide en français.

L'application doit fonctionner sur le Mac de l'utilisateur, effectuer une synchronisation quotidienne, permettre une actualisation manuelle et rester utile lorsque certaines sources sont temporairement indisponibles.

## État initial

Le dépôt contient un CLI Python synchrone et cinq scrapers : LinkedIn, HelloWork, France Travail, Welcome to the Jungle et Adzuna. HelloWork existe donc déjà et reste pris en charge ; la nouvelle source demandée est Free-Work.

Le dépôt ne contient actuellement ni vraie suite de tests, ni base de données, ni API, ni frontend, ni déduplication inter-sources. L'environnement local inspecté n'avait pas encore les dépendances Python déclarées, ce qui empêchait de lancer le CLI et `pytest`. La mise en place d'un environnement reproductible fait partie du travail.

## Architecture retenue

### Scrapers Python

Chaque source implémente la même interface de recherche et de récupération des détails. Les scrapers existants sont conservés et testés. Un `FreeWorkScraper` est ajouté en suivant la structure du projet.

Le scraper Free-Work privilégie les données structurées publiques rendues par le site et utilise un parseur HTML de secours. Il respecte une cadence configurable, un délai maximal et un nombre limité de tentatives.

### Service d'agrégation FastAPI

FastAPI devient la façade de l'application. Le service :

- gère les recherches enregistrées ;
- orchestre les synchronisations quotidiennes et manuelles ;
- normalise les résultats ;
- applique la déduplication ;
- lit et écrit les données SQLite ;
- récupère et met en cache les détails à la demande ;
- expose l'état des synchronisations au frontend.

Une défaillance de source n'interrompt pas les autres sources. Les tâches de scraping s'exécutent hors du chemin de réponse HTTP afin que l'interface reste utilisable pendant une synchronisation.

### Stockage SQLite

SQLite conserve au minimum :

- les recherches enregistrées et leur état actif ou suspendu ;
- les offres canoniques normalisées ;
- les annonces propres à chaque source et leurs URLs ;
- les détails mis en cache et leur date de fraîcheur ;
- les relations de doublon confirmé ou possible ;
- les exécutions de synchronisation et leur résultat par source.

Les offres ne sont pas supprimées dès qu'elles disparaissent d'une source. Elles deviennent inactives après vérification, ce qui protège l'historique contre les erreurs temporaires de scraping.

### Frontend React et TypeScript

Le frontend est une application React/TypeScript en français. Il consomme uniquement l'API locale FastAPI. La vue principale utilise une grille de cartes responsive et ouvre les détails dans un panneau latéral. Sur mobile, ce panneau devient une fiche plein écran.

### Exécution locale et automatisation macOS

Une commande unique lance l'API et le frontend. Une commande d'installation dédiée génère et charge un agent `launchd` utilisateur pour une synchronisation quotidienne. L'heure par défaut est 08:00 dans le fuseau local du Mac et reste configurable.

Le job planifié fonctionne lorsque le Mac est disponible. Si l'heure planifiée est manquée parce que le Mac était éteint ou en veille, l'application détecte au démarrage que la dernière synchronisation est trop ancienne et déclenche un rattrapage. Le bouton « Actualiser » reste disponible à tout moment.

## Modèle de données et flux

### Recherches enregistrées

L'utilisateur peut enregistrer plusieurs recherches. Chaque recherche contient :

- un nom ;
- des mots-clés et éventuellement un titre ;
- un lieu et un rayon ;
- des types de contrat ;
- des préférences de télétravail et d'expérience ;
- une sélection de sources ;
- un état actif ou suspendu.

La synchronisation quotidienne exécute toutes les recherches actives. L'actualisation manuelle peut lancer toutes les recherches ou une recherche précise.

### Synchronisation

Pour chaque résultat, le système :

1. valide les champs essentiels ;
2. normalise titre, entreprise, lieu, contrat et date ;
3. recherche l'annonce par son couple source/identifiant externe ;
4. crée ou met à jour l'annonce source ;
5. associe l'annonce à une offre canonique ;
6. calcule les relations de doublons ;
7. enregistre la première détection, la dernière détection et la dernière vérification.

Une offre trouvée par plusieurs recherches n'est stockée qu'une fois, tout en gardant ses associations aux recherches concernées.

### Détails mis en cache

La liste ne récupère que les champs nécessaires aux cartes. À la première ouverture d'une offre, l'API charge les détails auprès de la meilleure annonce source, puis les stocke avec leur date de récupération.

Les ouvertures suivantes utilisent le cache. Un cache devenu ancien peut être rafraîchi en arrière-plan. Si le rafraîchissement échoue, les derniers détails disponibles restent affichés avec leur date de mise à jour.

## Déduplication

La déduplication s'appuie sur des versions normalisées du titre, de l'entreprise et du lieu, enrichies par les données disponibles comme le contrat, la description ou le salaire.

Trois résultats sont possibles :

- **correspondance très fiable** : les annonces sont regroupées dans une offre canonique unique, avec un badge et un lien pour chaque source ;
- **correspondance proche mais incertaine** : les offres restent séparées, portent toutes les deux l'étiquette « Doublon possible » et contiennent un lien réciproque ;
- **correspondance faible** : aucune relation n'est créée.

La logique reste volontairement conservatrice. Elle ne fusionne pas automatiquement une paire lorsqu'une différence significative existe, par exemple deux lieux distincts ou deux niveaux de séniorité incompatibles.

## Interface utilisateur

### Navigation principale

L'en-tête affiche :

- la recherche enregistrée active ;
- la date et l'état de la dernière synchronisation ;
- le bouton « Actualiser » ;
- l'accès à la gestion des recherches enregistrées.

### Périodes et filtres

Les raccourcis temporels sont « 24 h », « 3 jours », « 7 jours » et « Toutes ».

Les filtres couvrent :

- texte libre ;
- lieu et rayon ;
- contrat ;
- télétravail ;
- niveau d'expérience ;
- salaire ;
- entreprise ;
- source ;
- compétences ;
- présence ou absence de doublons possibles ;
- tri par date ou pertinence.

Ils agissent immédiatement sur les données locales et ne relancent pas les scrapers. Les offres sans date de publication restent visibles dans « Toutes », mais sont exclues des périodes 24 h, 3 jours et 7 jours.

### Cartes et panneau de détails

Chaque carte affiche les informations disponibles parmi le titre, l'entreprise, le lieu, le contrat, la date, le télétravail, le salaire, les sources et l'état de doublon.

Un clic ouvre un panneau latéral sans quitter la grille. Il contient la description, les compétences, les avantages, les métadonnées, tous les liens sources et les offres marquées comme doublons possibles. Le chargement initial des détails et l'utilisation du cache sont indiqués sans bloquer le reste de l'interface.

### État de synchronisation

Pendant une actualisation, l'utilisateur peut continuer à consulter les offres. Une zone de progression présente pour chaque source :

- état en attente, en cours, réussi, partiel ou échoué ;
- nombre d'offres ajoutées et mises à jour ;
- heure de fin ;
- message d'erreur utile ;
- action pour relancer uniquement la source en échec.

## Gestion des erreurs

Les erreurs sont isolées par recherche et par source. Une source qui échoue ne fait pas perdre les résultats des autres sources et ne rend pas l'application indisponible.

Les requêtes réseau utilisent des délais maximaux, des tentatives bornées, une cadence configurable et des en-têtes adaptés. Les erreurs de parsing conservent suffisamment de contexte technique dans les logs locaux tout en présentant un message compréhensible dans l'interface.

Les offres et détails déjà stockés restent consultables lors d'une panne réseau ou d'un changement de structure d'un site.

## Stratégie de tests

### Tests Python

- modèles et validation ;
- construction des requêtes de chaque source ;
- parsing de fixtures HTML ou JSON enregistrées localement ;
- pagination, dates, contrats et détails Free-Work ;
- normalisation ;
- doublons confirmés, possibles et absents ;
- dépôt SQLite et migrations ;
- fraîcheur et repli du cache ;
- endpoints FastAPI ;
- synchronisation complète, partielle et échouée ;
- génération de la configuration `launchd`.

### Tests frontend

- rendu des cartes ;
- filtres et périodes ;
- gestion des recherches enregistrées ;
- ouverture, chargement et fermeture du panneau de détails ;
- affichage des badges sources et doublons possibles ;
- progression et erreurs de synchronisation ;
- comportement responsive essentiel.

### Tests de parcours

Un parcours automatisé couvre : créer une recherche, lancer une synchronisation simulée, filtrer les résultats, ouvrir une offre, utiliser des détails mis en cache et suivre un lien vers un doublon possible.

Les tests automatisés ordinaires ne dépendent pas du réseau. Des smoke tests réels, explicitement activés et limités à quelques résultats, vérifient séparément les intégrations publiques sans surcharger les sites.

## Critères d'acceptation

Le travail est accepté lorsque :

1. l'environnement reproductible permet d'installer et de tester le projet ;
2. les scrapers existants disposent d'une couverture de régression utile ;
3. Free-Work renvoie des offres réelles et leurs détails ;
4. les recherches enregistrées se synchronisent dans SQLite ;
5. les doublons certains sont regroupés et les doublons possibles sont reliés sans fusion ;
6. la collecte quotidienne et l'actualisation manuelle fonctionnent ;
7. l'interface française permet de filtrer, consulter et ouvrir les offres selon le design validé ;
8. les détails sont chargés à la demande et réutilisés depuis le cache ;
9. une panne de source est visible mais n'empêche pas les autres sources de réussir ;
10. les suites de tests backend, frontend et de parcours passent.

## Hors périmètre initial

- comptes utilisateurs et authentification ;
- synchronisation cloud ou accès depuis Internet ;
- candidature automatique ;
- notifications par email ou mobile ;
- apprentissage automatique pour classer les offres ;
- déploiement sur un serveur distant.

Ces fonctionnalités pourront être ajoutées ultérieurement sans être nécessaires à la première version locale.
