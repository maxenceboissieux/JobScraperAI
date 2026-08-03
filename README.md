# JobScraper

Agrégateur d'offres d'emploi en France. Recherchez simultanément sur LinkedIn, HelloWork, France Travail, Welcome to the Jungle, Adzuna (Indeed, Monster...) et Free-Work.

## Fonctionnalités

- **6 sources d'emploi** : LinkedIn, HelloWork, France Travail, WTTJ, Adzuna, Free-Work
- **Recherche géolocalisée** : Filtrage par ville et rayon (5-100 km)
- **Filtres avancés** : Type de contrat, expérience, télétravail, date de publication
- **Export flexible** : JSON, CSV ou affichage tableau
- **CLI intuitive** : Interface en ligne de commande avec Rich

## Installation

```bash
# Cloner le repository
git clone https://github.com/zeffut/jobscraper.git
cd jobscraper

# Utiliser Python 3.11 ou 3.12 et créer un environnement virtuel
python3.12 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# ou .venv\Scripts\activate  # Windows

# Installer le projet et les dépendances de développement en mode éditable
python -m pip install -e ".[dev]"
```

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

Free-Work utilise ses pages publiques et ne requiert pas de clé API. Les variables suivantes permettent de l'activer ou d'ajuster le délai entre les requêtes :

```env
FREEWORK_ENABLED=true
FREEWORK_DELAY=2.0
```

Conservez un délai raisonnable pour les recherches habituelles afin de respecter le site source.

## Utilisation

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

# Lancer les tests live opt-in (au plus trois offres par source)
RUN_LIVE_SCRAPER_TESTS=1 .venv/bin/python -m pytest -m live -v

# Vérifier uniquement Free-Work, avec une recherche bornée
RUN_LIVE_SCRAPER_TESTS=1 .venv/bin/python -m pytest tests/live/test_sources_live.py -k FreeWork -v

# Formater le code
.venv/bin/python -m black src/
.venv/bin/python -m isort src/
```

Les tests live sont désactivés par défaut afin que la suite ordinaire reste déterministe et ne contacte aucune source externe. Ils utilisent le mot-clé `python`, un délai d'une seconde et `max_results=3` ; activez-les uniquement pour un contrôle opérateur ponctuel.

## Contribution

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une issue ou une pull request.
