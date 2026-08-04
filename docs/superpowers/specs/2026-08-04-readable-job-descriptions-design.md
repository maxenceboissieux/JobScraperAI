# Conception — descriptions d’offres plus lisibles

**Date :** 4 août 2026  
**Statut :** validé oralement, en attente de revue du document  
**Direction retenue :** approche hybride conservatrice, rendu visuel « sections et listes »

## Objectif

Rendre les descriptions d’offres faciles à parcourir dans le panneau de détails, y compris lorsque la source concatène les titres, paragraphes et listes. Le système ne doit ni résumer, ni reformuler, ni supprimer le texte fourni par le recruteur.

## Principes

- Le texte original reste la source de vérité et demeure stocké tel quel dans la base locale.
- La structuration d’affichage est déterministe, locale et réversible.
- Une structure ambiguë reste un paragraphe normal.
- Le contenu est rendu comme texte React, jamais injecté comme HTML.
- Les nouvelles collectes préservent autant que possible les séparateurs fournis par les pages sources.
- Les descriptions déjà mises en cache bénéficient immédiatement du parseur d’affichage, sans migration ni nouveau scraping.

## Architecture

### 1. Parseur frontend pur

Créer un module dédié qui transforme une chaîne brute en une suite ordonnée de blocs typés :

- `heading` : titre de section reconnu ;
- `paragraph` : texte courant ;
- `list` : énumération dont chaque élément conserve son texte source.

Le parseur n’accède ni au réseau, ni à React, ni à la base. Son interface accepte le texte brut et retourne des blocs sérialisables. Cette séparation permet de tester la conservation du contenu indépendamment du composant visuel.

La détection utilise uniquement des signaux explicites :

- titres usuels d’annonces, avec variantes françaises et anglaises, par exemple « Description du poste », « Missions », « Profil recherché », « Compétences », « Avantages », « À propos » et « About the role » ;
- lignes courtes majoritairement ou entièrement en majuscules ;
- marqueurs de liste existants (`-`, `•`, `*`, numérotation) ;
- énumérations introduites par un titre ou une phrase se terminant par deux-points, puis séparées par des points-virgules ou des retours à la ligne.

Pour les textes concaténés, le parseur peut insérer une frontière avant un titre reconnu même si la source n’a fourni aucun espace, par exemple `ENTREPRISEDESCRIPTION DU POSTE`. Il ne tente pas de segmenter arbitrairement les mots ordinaires.

### 2. Rendu React

Créer un composant de description qui reçoit les blocs du parseur et rend :

- les titres avec une hiérarchie visuelle stable ;
- les paragraphes avec une largeur et un interlignage adaptés à la lecture ;
- les listes avec des puces et un espacement régulier.

Le composant remplace le découpage actuel fondé uniquement sur les doubles retours à la ligne dans `JobDetailsDrawer`. Le panneau, son défilement, son accessibilité clavier et le reste des détails restent inchangés.

Le rendu ne masque aucun contenu et ne génère aucun résumé. Les descriptions longues restent entièrement accessibles par défilement. Sur mobile, la même structure est conservée avec des marges réduites.

### 3. Préservation côté scrapers

Lorsqu’un scraper extrait une description depuis un arbre HTML, il doit utiliser un séparateur textuel qui préserve les frontières significatives entre titres, paragraphes et éléments de liste, puis normaliser uniquement les espaces excédentaires. Cette amélioration s’applique en priorité aux sources dont les descriptions concaténées ont été observées, notamment LinkedIn.

Les scrapers ne produisent pas les blocs frontend et ne réécrivent pas sémantiquement le contenu. Ils fournissent seulement un texte brut mieux séparé pour les futurs rafraîchissements.

## Flux de données

1. Le scraper récupère et met en cache le texte original avec ses séparateurs utiles.
2. L’API renvoie toujours une simple chaîne `description`; le contrat HTTP ne change pas.
3. Le panneau transmet cette chaîne au parseur frontend.
4. Le parseur retourne les blocs structurés.
5. Le composant affiche chaque bloc en conservant son ordre et son contenu.

Cette architecture ne requiert ni migration de base, ni nouveau champ API, ni dépendance d’intelligence artificielle.

## Comportements de repli

- Description absente ou vide : la section n’est pas affichée, comme aujourd’hui.
- Aucun motif reconnu : un seul paragraphe contenant tout le texte est rendu.
- Ligne ou segment ambigu : il reste dans le paragraphe voisin.
- Énumération ambiguë : elle reste du texte courant.
- Texte extrêmement long : le parseur reste linéaire et le panneau conserve son défilement normal.
- Balises ou chaînes ressemblant à du HTML : elles sont affichées comme texte et ne sont jamais interprétées par le navigateur.

## Présentation visuelle

- Titres de section en couleur de marque, clairement distincts du corps du texte.
- Filet vertical ou espacement structurel léger pour guider la lecture sans alourdir le panneau.
- Paragraphes d’environ `0.94rem`, interligne proche de `1.7` et largeur de ligne confortable.
- Listes alignées avec les paragraphes, puces sobres et espace entre les éléments.
- Espacement vertical cohérent entre sections, réduit sur les petits écrans.
- Respect de la palette, de la typographie et des variables CSS existantes.

## Tests

### Tests unitaires du parseur

- description LinkedIn concaténée contenant des titres français ;
- titres anglais et accents ;
- paragraphes Free-Work ou WTTJ déjà correctement séparés ;
- listes à puces, numérotées et séparées par points-virgules ;
- contenu ambigu conservé en paragraphe ;
- description très longue ;
- conservation de l’ordre et de chaque segment textuel ;
- texte ressemblant à du HTML non interprété.

### Tests du composant

- rendu des titres, paragraphes et listes avec les bons éléments sémantiques ;
- absence de section pour une description vide ;
- contenu complet accessible ;
- maintien du comportement du panneau, du focus et des métadonnées.

### Tests des scrapers

- extraction LinkedIn préservant les frontières entre paragraphes et éléments ;
- absence de régression sur les descriptions des autres sources concernées.

### Validation globale

- suites frontend et backend existantes ;
- typecheck et build de production ;
- parcours E2E d’ouverture d’une offre ;
- contrôle visuel desktop et mobile avec une description concaténée réelle.

## Hors périmètre

- résumé généré ;
- reformulation ou traduction ;
- édition manuelle des descriptions ;
- stockage de HTML provenant des sources ;
- migration ou réécriture en masse des descriptions existantes ;
- modification du contrat de l’API de détails.

## Critères d’acceptation

- Une description LinkedIn concaténée présente des sections et listes lisibles.
- Une description déjà bien formatée conserve son contenu et son ordre.
- Aucun mot source n’est supprimé ou remplacé par le parseur.
- Les cas ambigus restent lisibles sous forme de paragraphes.
- Aucun HTML source n’est exécuté.
- Le rendu fonctionne sur desktop et mobile.
- Les nouvelles descriptions LinkedIn conservent davantage de séparateurs utiles.
- Toutes les vérifications ciblées et globales restent vertes.
