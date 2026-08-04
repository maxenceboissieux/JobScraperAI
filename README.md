# JobScraper

Agrégateur d'offres d'emploi en France. Recherchez simultanément sur LinkedIn, HelloWork, France Travail, Welcome to the Jungle, Adzuna (Indeed, Monster...) et Free-Work.

## Fonctionnalités

- **6 sources d'emploi** : LinkedIn, HelloWork, France Travail, WTTJ, Adzuna, Free-Work
- **Recherche géolocalisée** : Filtrage par ville et rayon (5-100 km)
- **Filtres avancés** : Type de contrat, expérience, télétravail, date de publication
- **Export flexible** : JSON, CSV ou affichage tableau
- **CLI intuitive** : Interface en ligne de commande avec Rich
- **Interface web locale** : Application React servie par l'API FastAPI

## Installation locale (macOS)

Prérequis : macOS, Python 3.12, Node.js 20.19 ou plus récent et pnpm.

```bash
# Cloner le repository
git clone https://github.com/zeffut/jobscraper.git
cd jobscraper

# Vérifier les prérequis
python3.12 --version
node --version
pnpm --version

# Créer l'environnement Python local
python3.12 -m venv .venv
source .venv/bin/activate

# Installer le projet et les dépendances de développement en mode éditable
python -m pip install -e '.[dev]'

# Installer et construire l'interface
cd frontend
pnpm install
pnpm build
cd ..

# Préparer la base SQLite locale
.venv/bin/alembic upgrade head
```

Le projet accepte aussi Python 3.11, mais Python 3.12 est le parcours macOS
recommandé et vérifié. Consultez le [guide d'exploitation macOS](docs/macOS-automation.md)
pour le démarrage quotidien, les journaux et le dépannage.

## Configuration

Copiez le fichier d'exemple et modifiez selon vos besoins :

```bash
cp .env.example .env
```

### Adzuna (optionnel)

Pour utiliser Adzuna (agrégateur Indeed, Monster, etc.), obtenez des clés API gratuites sur [developer.adzuna.com](https://developer.adzuna.com/) et ajoutez-les dans `.env` :

```env
ADZUNA_APP_ID=votre_app_id
ADZUNA_APP_KEY=votre_app_key
```

### Free-Work

Free-Work utilise ses pages publiques et ne requiert pas de clé API. Choisissez cette source avec `-s freework` ; la variable suivante ajuste le délai entre les requêtes :

```env
FREEWORK_DELAY=2.0
```

Conservez un délai raisonnable pour les recherches habituelles afin de respecter le site source.

## Utilisation

### Interface web locale

Depuis la racine du dépôt, construisez l'interface si nécessaire puis utilisez la
commande unique de démarrage :

```bash
cd frontend
pnpm build
cd ..
.venv/bin/jobscraper serve
```

La commande applique les migrations, démarre l'API et ouvre
<http://127.0.0.1:8000>. Utilisez `--no-open` pour ne pas ouvrir automatiquement
le navigateur. Les routes de l'API restent disponibles sous `/api`. Si le build
manque, `serve` s'arrête avec la commande de reconstruction à exécuter.

Dans l'interface, cliquez sur **Nouvelle recherche**, renseignez les critères et
choisissez les sources, puis enregistrez. Le bouton **Actualiser** déclenche une
synchronisation manuelle à tout moment. Les offres restent consultables et
filtrables localement (24 h, 3 jours ou 7 jours) ; ouvrir une offre charge et met
en cache ses détails.

### Synchronisation quotidienne sur macOS

Installez un agent utilisateur launchd, sans droits administrateur :

```bash
.venv/bin/jobscraper automation install --hour 8 --minute 0
.venv/bin/jobscraper automation status
```

Par défaut, launchd demande une synchronisation chaque jour à 08:00, heure locale.
Si le Mac dort, le prochain lancement de `jobscraper serve` rattrape la
synchronisation manquée. Le bouton **Actualiser** reste disponible, que
l'automatisation soit installée ou non.

```bash
# Journaux de l'agent
tail -f data/logs/launchd.out.log data/logs/launchd.err.log

# Désinstallation complète de l'agent JobScraper
.venv/bin/jobscraper automation uninstall
```

Le détail du fonctionnement et des procédures de récupération figure dans le
[guide d'automatisation macOS](docs/macOS-automation.md).

Le dossier `frontend/dist` est un artefact local ignoré par Git et n'est pas
inclus dans le paquet Python. L'interface doit donc être construite dans le dépôt
avant de lancer `jobscraper serve` ; une installation wheel seule ne fournit pas
l'interface React.

### Recherche simple

```bash
# Recherche "python" à Paris
jobscraper search -k python -l Paris

# Recherche "data engineer" en CDI
jobscraper search -k "data engineer" -c cdi

# Recherche avec rayon de 25km autour de Lyon
jobscraper search -k développeur -l Lyon -r 25
```

### Options de recherche

```bash
jobscraper search [OPTIONS]

Options:
  -k, --keywords TEXT       Mots-clés de recherche (peut être répété)
  -t, --title TEXT          Titre de poste exact
  -l, --location TEXT       Localisation (ville, région) [défaut: France]
  -r, --radius [5|10|25|50|100]  Rayon de recherche en km
  -c, --contract [cdi|cdd|stage|alternance|interim|freelance]  Type de contrat
  -e, --experience [internship|junior|mid|senior|lead|director]  Niveau d'expérience
  -w, --workplace [on_site|remote|hybrid]  Type de lieu de travail
  --date [past_24h|past_week|past_month|any_time]  Date de publication
  --sort [relevance|date]   Tri des résultats
  -n, --max-results INT     Nombre maximum de résultats [défaut: 50]
  -s, --source [linkedin|hellowork|francetravail|adzuna|wttj|freework|all]  Sources
  -o, --output PATH         Fichier de sortie
  --format [json|csv|table] Format de sortie [défaut: table]
  -d, --details             Récupérer les détails complets
```

### Exemples avancés

```bash
# CDI senior en remote, export JSON
jobscraper search -k "data engineer" -c cdi -e senior -w remote -o jobs.json

# Recherche sur WTTJ uniquement
jobscraper search -k python -l Paris -s wttj

# Recherche sur Free-Work uniquement
jobscraper search -k python -l Paris -s freework

# Recherche sur toutes les sources
jobscraper search -k développeur -l Toulouse -s all

# Offres des 7 derniers jours, triées par date
jobscraper search -k devops --date past_week --sort date

# 100 résultats avec détails complets
jobscraper search -k react -n 100 --details -o react_jobs.json
```

### Lister les sources

```bash
jobscraper sources
```

## Sources supportées

| Source | Statut | Description |
|--------|--------|-------------|
| LinkedIn | Actif | Offres d'emploi LinkedIn |
| HelloWork | Actif | Portail d'emploi français |
| France Travail | Actif | Ex Pôle Emploi |
| WTTJ | Actif | Welcome to the Jungle (startups) |
| Adzuna | Actif* | Agrégateur (Indeed, Monster...) |
| Free-Work | Actif | Offres IT et missions freelance |

\* Nécessite des clés API gratuites

## Structure du projet

```
jobscraper/
├── src/jobscraper/
│   ├── cli.py              # Interface ligne de commande
│   ├── config.py           # Configuration
│   ├── models/
│   │   └── job.py          # Modèles de données
│   ├── scrapers/
│   │   ├── base.py         # Classe de base
│   │   ├── linkedin.py     # Scraper LinkedIn
│   │   ├── hellowork.py    # Scraper HelloWork
│   │   ├── francetravail.py # Scraper France Travail
│   │   ├── wttj.py         # Scraper WTTJ (Algolia)
│   │   ├── adzuna.py       # Client API Adzuna
│   │   └── freework.py     # Scraper Free-Work
│   └── utils/
│       └── geocoding.py    # Géocodage pour recherche par rayon
├── .env.example            # Template de configuration
├── pyproject.toml          # Configuration du projet
└── requirements.txt        # Dépendances
```

## Développement

```bash
# Lancer la suite habituelle, sans accès réseau
.venv/bin/python -m pytest -m 'not live' -v

# Vérifications Python complètes
.venv/bin/python -m pytest -m 'not live' --cov=jobscraper
.venv/bin/python -m mypy src/jobscraper

# Vérifications de l'interface et parcours navigateur local déterministe
cd frontend
pnpm test --run
pnpm typecheck
pnpm build
pnpm e2e
cd ..

# Lancer les tests live opt-in (au plus trois offres par source)
RUN_LIVE_SCRAPER_TESTS=1 .venv/bin/python -m pytest -m live -v

# Vérifier uniquement Free-Work, avec une recherche bornée
RUN_LIVE_SCRAPER_TESTS=1 .venv/bin/python -m pytest tests/live/test_sources_live.py -k FreeWork -v

# Formater le code
.venv/bin/python -m black src/
.venv/bin/python -m isort src/
```

Les tests live sont désactivés par défaut afin que la suite ordinaire reste déterministe et ne contacte aucune source externe. Ils utilisent le mot-clé `python`, un délai d'une seconde et `max_results=3` ; activez-les uniquement pour un contrôle opérateur ponctuel.

`pnpm e2e` utilise des scrapers factices, une base SQLite temporaire et des URL
réservées sous `example.invalid` : il ne contacte pas les sites d'emploi publics.

## Données locales et limites

La base, le cache des détails et les journaux restent dans `data/` par défaut.
Vous pouvez déplacer la base avec `JOBSCRAPER_DATABASE_URL`. Les structures HTML
des sources publiques peuvent évoluer et interrompre temporairement un scraper.
Utilisez des délais raisonnables et respectez les conditions d'utilisation et les
limites de requêtes de chaque site. Un rapprochement incertain n'est pas fusionné :
les deux offres restent visibles avec le tag **Peut-être doublon** et un lien
croisé.

## Contribution

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une issue ou une pull request.
