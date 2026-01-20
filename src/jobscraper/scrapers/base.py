"""Classe de base abstraite pour tous les scrapers."""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Iterator, Optional

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from jobscraper.models.job import JobOffer, SearchCriteria


class BaseScraper(ABC):
    """Classe de base pour tous les scrapers d'offres d'emploi."""

    # Nom du scraper (à définir dans les sous-classes)
    name: str = "base"

    # URL de base du site
    base_url: str = ""

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialise le scraper.

        Args:
            config: Configuration optionnelle du scraper
        """
        self.config = config or {}
        self._session = None
        logger.info(f"Scraper {self.name} initialisé")

    @abstractmethod
    def search(self, criteria: SearchCriteria) -> Iterator[JobOffer]:
        """
        Recherche des offres d'emploi selon les critères donnés.

        Args:
            criteria: Critères de recherche

        Yields:
            JobOffer: Les offres d'emploi trouvées
        """
        pass

    @abstractmethod
    def get_job_details(self, job_id: str) -> Optional[JobOffer]:
        """
        Récupère les détails complets d'une offre d'emploi.

        Args:
            job_id: Identifiant de l'offre

        Returns:
            JobOffer ou None si non trouvée
        """
        pass

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def _fetch_page(self, url: str) -> str:
        """
        Récupère le contenu d'une page avec retry automatique.

        Args:
            url: URL de la page à récupérer

        Returns:
            Contenu HTML de la page
        """
        import requests

        headers = self._get_headers()
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text

    def _get_headers(self) -> dict:
        """
        Retourne les headers HTTP à utiliser pour les requêtes.

        Returns:
            Dictionnaire des headers
        """
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def close(self):
        """Ferme les ressources du scraper."""
        if self._session:
            self._session.close()
            self._session = None
        logger.info(f"Scraper {self.name} fermé")


class AsyncBaseScraper(BaseScraper):
    """Classe de base pour les scrapers asynchrones."""

    @abstractmethod
    async def search_async(self, criteria: SearchCriteria) -> AsyncIterator[JobOffer]:
        """
        Recherche asynchrone des offres d'emploi.

        Args:
            criteria: Critères de recherche

        Yields:
            JobOffer: Les offres d'emploi trouvées
        """
        pass

    @abstractmethod
    async def get_job_details_async(self, job_id: str) -> Optional[JobOffer]:
        """
        Récupère les détails d'une offre de manière asynchrone.

        Args:
            job_id: Identifiant de l'offre

        Returns:
            JobOffer ou None si non trouvée
        """
        pass

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close_async()

    async def close_async(self):
        """Ferme les ressources de manière asynchrone."""
        self.close()
