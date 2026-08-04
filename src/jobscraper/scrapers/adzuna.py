"""Scraper pour Adzuna API (agrégateur: Indeed, Monster, etc.)."""

import os
from datetime import datetime
from typing import Dict, Iterator, List, Optional
from urllib.parse import urlencode

import requests
from loguru import logger

from jobscraper.models.job import (
    ContractType,
    DatePosted,
    ExperienceLevel,
    JobOffer,
    SearchCriteria,
    SortBy,
)
from jobscraper.scrapers.base import BaseScraper


class AdzunaScraper(BaseScraper):
    """
    Scraper pour Adzuna API.

    Adzuna agrège les offres de: Indeed, Monster, CareerBuilder, etc.
    API gratuite avec inscription: https://developer.adzuna.com/
    """

    name = "adzuna"
    base_url = "https://api.adzuna.com/v1/api/jobs"

    # Mapping des familles de filtres de contrat prises en charge par Adzuna
    CONTRACT_FILTER_MAPPING = {
        ContractType.CDI: "permanent",
        ContractType.CDD: "contract",
        ContractType.INTERIM: "contract",
        ContractType.FREELANCE: "contract",
    }

    # Mapping du tri
    SORT_MAPPING = {
        SortBy.RELEVANCE: "relevance",
        SortBy.DATE: "date",
    }

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialise le scraper Adzuna.

        Args:
            config: Configuration avec app_id et app_key
        """
        super().__init__(config)
        settings = config or {}
        self.app_id = settings.get("app_id") or os.getenv("ADZUNA_APP_ID")
        self.app_key = settings.get("app_key") or os.getenv("ADZUNA_APP_KEY")
        self.country = config.get("country", "fr") if config else "fr"

        if not self.app_id or not self.app_key:
            logger.warning(
                "Clés API Adzuna non configurées. "
                "Définir ADZUNA_APP_ID et ADZUNA_APP_KEY dans .env "
                "ou obtenir des clés sur https://developer.adzuna.com/"
            )

    def search(self, criteria: SearchCriteria) -> Iterator[JobOffer]:
        """
        Recherche des offres d'emploi via l'API Adzuna.

        Args:
            criteria: Critères de recherche

        Yields:
            JobOffer: Les offres d'emploi trouvées
        """
        self._begin_search()
        if not self.app_id or not self.app_key:
            logger.error("Clés API Adzuna manquantes")
            self._incomplete_search("Clés API Adzuna manquantes")
            return

        families = self._contract_filter_families(criteria)
        if not families:
            self._mark_search_complete()
            return

        jobs_found = 0
        max_results = criteria.max_results
        seen_ids: set[str] = set()
        results_per_page = 50  # Max autorisé par Adzuna

        if jobs_found >= max_results:
            self._mark_search_complete()
            return

        for contract_filter in families:
            page = 1
            family_seen_ids: set[str] = set()

            while jobs_found < max_results:
                url = self._build_search_url(
                    criteria,
                    page,
                    results_per_page,
                    contract_filter=contract_filter,
                )
                logger.debug(
                    "Requête Adzuna: page={}, filtre_contrat={}",
                    page,
                    contract_filter or "aucun",
                )

                try:
                    response = self._request_with_retry(
                        lambda: requests.get(url, timeout=self.timeout)
                    )
                    data = response.json()
                    if not isinstance(data, dict):
                        self._incomplete_search("Réponse Adzuna invalide")
                        return

                    results = data.get("results", [])
                    if not isinstance(results, list):
                        self._incomplete_search(
                            "Réponse Adzuna sans liste de résultats"
                        )
                        return
                    if not results:
                        total_count = data.get("count", 0)
                        if isinstance(total_count, (int, float)) and total_count > 0:
                            self._incomplete_search(
                                "Adzuna annonce des résultats mais renvoie une page vide"
                            )
                            return
                        logger.info("Plus d'offres trouvées")
                        break

                    new_jobs_on_page = 0
                    parsed_jobs_on_page = 0
                    for result in results:
                        job = self._parse_result(result)
                        if job:
                            parsed_jobs_on_page += 1
                            if job.id in family_seen_ids:
                                continue
                            family_seen_ids.add(job.id)
                            new_jobs_on_page += 1
                            if job.id in seen_ids:
                                continue
                            seen_ids.add(job.id)
                            jobs_found += 1
                            if jobs_found >= max_results:
                                self._mark_search_complete()
                                yield job
                                return
                            yield job

                    if parsed_jobs_on_page != len(results):
                        self._incomplete_search(
                            "Une partie des résultats Adzuna est inexploitable"
                        )

                    if new_jobs_on_page == 0:
                        logger.info("Plus de nouvelles offres")
                        self._incomplete_search(
                            "La page Adzuna ne contient que des doublons"
                        )
                        return

                    # Vérifier s'il y a plus de pages
                    total_count = data.get("count", 0)
                    if not isinstance(total_count, (int, float)) or total_count < 0:
                        self._incomplete_search("Pagination Adzuna invalide")
                        return
                    if page * results_per_page >= total_count:
                        break

                    page += 1

                except requests.RequestException as e:
                    logger.error("Erreur API Adzuna: {}", type(e).__name__)
                    if self.config.get("propagate_search_errors"):
                        raise
                    return
                except Exception as e:
                    logger.error("Erreur lors de la recherche: {}", type(e).__name__)
                    if self.config.get("propagate_search_errors"):
                        raise
                    return

        self._mark_search_complete()
        logger.info(f"Recherche terminée: {jobs_found} offres uniques trouvées")

    def get_job_details(self, job_id: str) -> Optional[JobOffer]:
        """
        Adzuna ne fournit pas de détails supplémentaires via l'API.
        Les détails sont déjà inclus dans les résultats de recherche.
        """
        return None

    def _contract_filter_families(
        self, criteria: SearchCriteria
    ) -> list[str | None]:
        if not criteria.contract_types:
            return [None]

        families: list[str | None] = []
        for contract_type in criteria.contract_types:
            family = self.CONTRACT_FILTER_MAPPING.get(contract_type)
            if family is not None and family not in families:
                families.append(family)
        return families

    def _build_search_url(
        self,
        criteria: SearchCriteria,
        page: int,
        results_per_page: int,
        contract_filter: str | None = None,
    ) -> str:
        """
        Construit l'URL de requête API Adzuna.

        Args:
            criteria: Critères de recherche
            page: Numéro de page
            results_per_page: Nombre de résultats par page

        Returns:
            URL de l'API formatée
        """
        base = f"{self.base_url}/{self.country}/search/{page}"

        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": min(results_per_page, 50),
            "content-type": "application/json",
        }

        # Mots-clés
        keywords_parts = []
        if criteria.title:
            keywords_parts.append(criteria.title)
        if criteria.keywords:
            keywords_parts.extend(criteria.keywords)
        if keywords_parts:
            params["what"] = " ".join(keywords_parts)

        # Localisation
        if criteria.location and criteria.location != "France":
            params["where"] = criteria.location

        # Rayon de recherche (en km)
        if criteria.radius_km:
            params["distance"] = criteria.radius_km

        # Type de contrat
        if contract_filter in {"permanent", "contract"}:
            params[contract_filter] = 1

        # Date de publication
        if criteria.date_posted:
            if criteria.date_posted == DatePosted.PAST_24H:
                params["max_days_old"] = 1
            elif criteria.date_posted == DatePosted.PAST_WEEK:
                params["max_days_old"] = 7
            elif criteria.date_posted == DatePosted.PAST_MONTH:
                params["max_days_old"] = 30

        # Tri
        if criteria.sort_by:
            params["sort_by"] = self.SORT_MAPPING.get(criteria.sort_by, "relevance")

        # Salaire minimum
        if criteria.salary_min:
            params["salary_min"] = int(criteria.salary_min)

        # Construire l'URL
        return f"{base}?{urlencode(params)}"

    def _parse_result(self, result: dict) -> Optional[JobOffer]:
        """
        Parse un résultat de l'API Adzuna.

        Args:
            result: Dictionnaire de résultat de l'API

        Returns:
            JobOffer ou None
        """
        try:
            job_id = result.get("id")
            if not job_id:
                return None

            title = result.get("title", "").strip()
            company = result.get("company", {}).get("display_name", "").strip()
            location = result.get("location", {}).get("display_name", "").strip()

            if not title or not company:
                return None

            # URL de l'offre
            url = result.get("redirect_url", "")

            # Description
            description = result.get("description", "")

            # Salaire
            salary_min = result.get("salary_min")
            salary_max = result.get("salary_max")

            # Date de publication
            created = result.get("created")
            posted_at = None
            if created:
                try:
                    posted_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except ValueError:
                    pass

            # Type de contrat
            contract_type = None
            contract_data = result.get("contract_type")
            if contract_data:
                if contract_data == "permanent":
                    contract_type = ContractType.CDI
                elif contract_data == "contract":
                    contract_type = ContractType.CDD

            # Catégorie
            category = result.get("category", {}).get("label", "")

            return JobOffer(
                id=f"adzuna_{job_id}",
                source=self.name,
                url=url,
                title=title,
                company=company,
                location=location or "France",
                description=description,
                salary_min=salary_min,
                salary_max=salary_max,
                contract_type=contract_type,
                posted_at=posted_at,
            )

        except Exception as e:
            logger.debug(f"Erreur parsing résultat Adzuna: {e}")
            return None
