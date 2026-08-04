# Exploitation locale et automatisation macOS

Ce guide décrit le fonctionnement quotidien de JobScraper sur un Mac. Toutes les
données restent locales et l'automatisation est installée pour l'utilisateur
courant, sans `sudo`.

## 1. Installer sur un nouveau Mac

Prérequis :

- macOS avec `launchd` ;
- Python 3.12 ;
- Node.js 20.19 ou une version compatible plus récente ;
- pnpm.

Depuis la racine du dépôt :

```bash
python3.12 --version
node --version
pnpm --version

python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

cp .env.example .env

cd frontend
pnpm install
pnpm build
cd ..

.venv/bin/alembic upgrade head
```

Les clés Adzuna sont facultatives. Free-Work n'exige pas de clé ; conservez un
délai raisonnable dans `FREEWORK_DELAY`.

## 2. Démarrer l'application

```bash
.venv/bin/jobscraper serve
```

`serve` vérifie le build React, met la base à niveau, démarre le serveur local et
ouvre <http://127.0.0.1:8000>. Pour un terminal ou un test sans ouverture du
navigateur :

```bash
.venv/bin/jobscraper serve --no-open
```

Dans l'interface :

1. Cliquez sur **Nouvelle recherche**.
2. Donnez-lui un nom, renseignez les mots-clés, la localisation et les sources.
3. Cliquez sur **Enregistrer**, puis sur **Actualiser**.
4. Filtrez les offres sur 24 h, 3 jours ou 7 jours et ouvrez une carte pour voir
   le détail mis en cache.

Le rechargement manuel reste disponible même sans automatisation. Les doublons
certains sont regroupés. Lorsque le rapprochement est seulement probable, les
deux offres sont conservées avec **Peut-être doublon** et un lien vers l'offre
associée.

## 3. Programmer la synchronisation quotidienne

La commande suivante installe l'agent de l'utilisateur courant à 08:00, heure
locale :

```bash
.venv/bin/jobscraper automation install --hour 8 --minute 0
```

L'heure est comprise entre `0` et `23` et la minute entre `0` et `59`. Réexécuter
la commande remplace proprement la planification existante. L'installation ne
lance pas immédiatement de scraping ; utilisez **Actualiser** si vous souhaitez
charger les offres tout de suite.

L'agent est enregistré dans :

```text
~/Library/LaunchAgents/com.jobscraper.daily-sync.plist
```

Il exécute l'interpréteur `.venv` du projet et la commande
`sync-saved-searches`. Il ne synchronise que les recherches enregistrées actives.
Le Mac n'a pas besoin de rester éveillé en permanence : si l'exécution planifiée
est manquée, le prochain démarrage de `jobscraper serve` lance au maximum un
rattrapage pour la journée. Un rattrapage terminé n'est pas relancé au démarrage
suivant le même jour.

Pour modifier l'horaire, réinstallez simplement l'agent :

```bash
.venv/bin/jobscraper automation install --hour 7 --minute 30
```

## 4. Contrôler l'état et les journaux

```bash
.venv/bin/jobscraper automation status
```

La commande distingue un agent actif, installé mais inactif, ou absent. Les
journaux sont locaux :

```bash
tail -f data/logs/launchd.out.log data/logs/launchd.err.log
```

La base SQLite et le cache de détail sont stockés par défaut dans
`data/jobscraper.db`. Pour utiliser un autre fichier local, renseignez par exemple :

```env
JOBSCRAPER_DATABASE_URL=sqlite:////Users/votre-nom/JobScraper-data/jobs.db
```

Utilisez quatre barres après `sqlite:` pour un chemin absolu.

## 5. Désinstaller l'automatisation

```bash
.venv/bin/jobscraper automation uninstall
```

La commande désactive le service puis supprime uniquement le plist JobScraper de
l'utilisateur. Elle ne supprime ni la base, ni le cache, ni les journaux. Elle est
sans effet indésirable si l'agent est déjà absent.

## 6. Dépannage

### Le build frontend est absent ou incomplet

```bash
cd frontend
pnpm install
pnpm build
cd ..
.venv/bin/jobscraper serve
```

### Une migration de base échoue

Vérifiez `JOBSCRAPER_DATABASE_URL`, les droits du dossier cible, puis exécutez :

```bash
.venv/bin/alembic upgrade head
```

### L'agent est installé mais inactif

Consultez d'abord `automation status` et `data/logs/launchd.err.log`. Depuis la
racine du même dépôt, réinstallez ensuite l'agent pour actualiser ses chemins :

```bash
.venv/bin/jobscraper automation install --hour 8 --minute 0
```

Cette étape est nécessaire si le dépôt ou son environnement `.venv` a été déplacé.

### Une source ne renvoie plus d'offres

Les pages publiques et leurs structures HTML peuvent changer. Vérifiez les
journaux, testez une seule source et ne contournez pas les restrictions du site.
Les tests automatisés habituels ne valident pas la disponibilité du site public ;
le test live Free-Work est volontairement manuel et borné :

```bash
RUN_LIVE_SCRAPER_TESTS=1 .venv/bin/python -m pytest \
  tests/live/test_sources_live.py -k FreeWork -v
```

## 7. Vérifier l'installation sans contacter les sources

```bash
.venv/bin/python -m pytest -m 'not live' --cov=jobscraper
.venv/bin/python -m mypy src/jobscraper

cd frontend
pnpm test --run
pnpm typecheck
pnpm build
pnpm e2e
cd ..
```

Le parcours Playwright `pnpm e2e` démarre le vrai serveur avec une base SQLite
temporaire et des scrapers factices. Il ne contacte aucun site d'emploi public et
supprime ses ressources temporaires à la fin.

## 8. Limites et bonnes pratiques

- `launchd` est spécifique à macOS et fonctionne dans la session utilisateur.
- Le Mac doit finir par se réveiller ; sinon, le rattrapage attend le prochain
  lancement de l'application.
- La base, le cache et les logs sont locaux sous `data/` par défaut : sauvegardez
  ce dossier si vous souhaitez conserver l'historique.
- Respectez les conditions d'utilisation, les fichiers robots applicables et les
  limites de requêtes de chaque source. Gardez des délais raisonnables.
- Une modification du HTML d'une source peut nécessiter une mise à jour du scraper.
- Le test E2E prouve le parcours local déterministe, pas la disponibilité actuelle
  d'un site public.
