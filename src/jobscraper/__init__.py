"""JobScraper - Agrégateur d'offres d'emploi en France."""

__version__ = "1.0.0"
__author__ = "JobScraper Contributors"

from jobscraper.config import Config, get_config
from jobscraper.models.job import JobOffer, SearchCriteria

__all__ = [
    "Config",
    "get_config",
    "JobOffer",
    "SearchCriteria",
    "__version__",
]
