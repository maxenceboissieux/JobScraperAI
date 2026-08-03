"""Classe de base abstraite pour tous les scrapers."""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import AsyncIterator, Callable, Dict, Iterator, Optional, Self

import requests
from loguru import logger
from tenacity import Retrying, stop_after_attempt, wait_exponential

from jobscraper.models.job import JobOffer, SearchCriteria


class IncompleteSearchError(RuntimeError):
    """A strict search stopped without authoritative complete-scan evidence."""


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
        self.timeout = float(self.config.get("timeout", 30))
        self.max_retries = max(1, int(self.config.get("max_retries", 3)))
        self._search_complete = False
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

    def _fetch_page(self, url: str) -> str:
        """
        Récupère le contenu d'une page avec retry automatique.

        Args:
            url: URL de la page à récupérer

        Returns:
            Contenu HTML de la page
        """
        headers = self._get_headers()
        response = self._request_with_retry(
            lambda: requests.get(url, headers=headers, timeout=self.timeout)
        )
        return response.text

    def _request_with_retry(
        self, operation: Callable[[], requests.Response]
    ) -> requests.Response:
        """Run one configured HTTP operation and validate its response."""

        response: requests.Response | None = None
        for attempt in Retrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            reraise=True,
        ):
            with attempt:
                response = operation()
                response.raise_for_status()
        if response is None:  # pragma: no cover - Retrying always attempts once.
            raise RuntimeError("Aucune tentative HTTP exécutée")
        return response

    @property
    def strict_search(self) -> bool:
        """Whether incomplete scans must surface to the orchestration boundary."""

        return bool(self.config.get("propagate_search_errors"))

    @property
    def search_complete(self) -> bool:
        """Whether the current search reached an authoritative source boundary."""

        return self._search_complete

    def _begin_search(self) -> None:
        self._search_complete = False

    def _mark_search_complete(self) -> None:
        self._search_complete = True

    def _incomplete_search(self, message: str) -> None:
        """Raise the shared strict-mode signal while preserving legacy behavior."""

        self._search_complete = False
        if self.strict_search:
            raise IncompleteSearchError(message)
        logger.warning(message)

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

    def __enter__(self) -> Self:
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Context manager exit."""
        self.close()

    def close(self) -> None:
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

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Async context manager exit."""
        await self.close_async()

    async def close_async(self) -> None:
        """Ferme les ressources de manière asynchrone."""
        self.close()
