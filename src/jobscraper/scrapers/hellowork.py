"""Scraper pour HelloWork."""

import re
import time
from datetime import datetime, timedelta
from typing import Dict, Iterator, Optional
from urllib.parse import quote_plus, urlencode

from bs4 import BeautifulSoup, Tag
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


class HelloWorkScraper(BaseScraper):
    """Scraper pour les offres d'emploi HelloWork."""

    name = "hellowork"
    base_url = "https://www.hellowork.com"

    # Mapping des types de contrat HelloWork
    CONTRACT_MAPPING = {
        ContractType.CDI: "CDI",
        ContractType.CDD: "CDD",
        ContractType.INTERIM: "interim",
        ContractType.STAGE: "stage",
        ContractType.ALTERNANCE: "alternance",
        ContractType.FREELANCE: "freelance",
    }

    # Mapping des dates de publication
    DATE_POSTED_MAPPING = {
        DatePosted.PAST_24H: "1",
        DatePosted.PAST_WEEK: "7",
        DatePosted.PAST_MONTH: "30",
        DatePosted.ANY_TIME: "",
    }

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialise le scraper HelloWork.

        Args:
            config: Configuration optionnelle
        """
        super().__init__(config)
        self.delay_between_requests = config.get("delay", 2) if config else 2

    def _get_headers(self) -> dict:
        """
        Retourne les headers HTTP pour HelloWork.
        Note: On évite brotli (br) car requests ne le supporte pas nativement.
        """
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }

    def search(self, criteria: SearchCriteria) -> Iterator[JobOffer]:
        """
        Recherche des offres d'emploi sur HelloWork.

        Args:
            criteria: Critères de recherche

        Yields:
            JobOffer: Les offres d'emploi trouvées
        """
        self._begin_search()
        jobs_found = 0
        max_results = criteria.max_results
        if jobs_found >= max_results:
            return

        seen_ids: set[str] = set()
        search_incomplete = False

        queries = self._search_queries(criteria)
        for query_index, query in enumerate(queries):
            url = self._build_search_url(criteria, query=query)
            logger.info(f"Recherche HelloWork: {url}")

            page = 1
            seen_ids_in_query: set[str] = set()
            while jobs_found < max_results:
                page_url = f"{url}&p={page}" if page > 1 else url
                logger.debug(f"Récupération page {page}: {page_url}")

                try:
                    html = self._fetch_page(page_url)
                    soup = BeautifulSoup(html, "lxml")
                    job_cards = self._extract_job_cards(soup)

                    if not job_cards:
                        logger.info("Plus d'offres trouvées")
                        break

                    new_jobs_on_page = 0
                    new_ids_in_query = 0
                    parsed_jobs_on_page = 0
                    for card in job_cards:
                        job = self._parse_job_card(card)
                        if job:
                            parsed_jobs_on_page += 1
                            if job.id not in seen_ids_in_query:
                                seen_ids_in_query.add(job.id)
                                new_ids_in_query += 1

                            if job.id in seen_ids:
                                logger.debug(f"Doublon ignoré: {job.id}")
                                continue

                            seen_ids.add(job.id)
                            jobs_found += 1
                            new_jobs_on_page += 1
                            yield job

                            if jobs_found >= max_results:
                                return

                    if parsed_jobs_on_page != len(job_cards):
                        search_incomplete = True
                        self._incomplete_search(
                            "Une partie des résultats HelloWork est inexploitable"
                        )
                        break

                    if query_index > 0 and page == 1 and new_jobs_on_page == 0:
                        logger.info(
                            "La requête HelloWork recouvre les résultats précédents"
                        )
                        break

                    if page > 1 and new_ids_in_query == 0:
                        logger.info("Plus de nouvelles offres")
                        search_incomplete = True
                        self._incomplete_search(
                            "La pagination HelloWork ne contient que des doublons"
                        )
                        break

                    page += 1
                    if self.delay_between_requests > 0:
                        time.sleep(self.delay_between_requests)

                except Exception as e:
                    logger.error(f"Erreur lors de la recherche: {e}")
                    if self.config.get("propagate_search_errors"):
                        raise
                    search_incomplete = True
                    break

            if search_incomplete:
                break
            if query_index < len(queries) - 1 and self.delay_between_requests > 0:
                time.sleep(self.delay_between_requests)

        logger.info(f"Recherche terminée: {jobs_found} offres uniques trouvées")
        if not search_incomplete:
            self._mark_search_complete()

    def get_job_details(self, job_id: str) -> Optional[JobOffer]:
        """
        Récupère les détails complets d'une offre HelloWork.

        Args:
            job_id: Identifiant de l'offre HelloWork

        Returns:
            JobOffer avec tous les détails ou None
        """
        # Extraire l'ID numérique si préfixé
        numeric_id = job_id.replace("hellowork_", "")
        url = f"{self.base_url}/fr-fr/emplois/{numeric_id}.html"
        logger.debug(f"Récupération détails: {url}")

        try:
            html = self._fetch_page(url)
            soup = BeautifulSoup(html, "lxml")
            return self._parse_job_details(soup, numeric_id, url)
        except Exception as e:
            logger.error(f"Erreur récupération détails job {job_id}: {e}")
            return None

    @staticmethod
    def _search_queries(criteria: SearchCriteria) -> list[str]:
        title = (criteria.title or "").strip()
        keywords = [keyword.strip() for keyword in criteria.keywords if keyword.strip()]
        candidates = ([title] if title else []) + [
            " ".join(filter(None, [title, keyword])) for keyword in keywords
        ]
        if not candidates:
            return [""]

        queries: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = " ".join(candidate.split()).casefold()
            if normalized and normalized not in seen:
                seen.add(normalized)
                queries.append(" ".join(candidate.split()))
        return queries or [""]

    def _build_search_url(
        self, criteria: SearchCriteria, *, query: str | None = None
    ) -> str:
        """
        Construit l'URL de recherche HelloWork.

        Args:
            criteria: Critères de recherche

        Returns:
            URL de recherche formatée
        """
        base = f"{self.base_url}/fr-fr/emploi/recherche.html"

        params = {}

        if query is None:
            query = self._search_queries(criteria)[0]
        if query:
            params["k"] = query

        if criteria.location:
            params["l"] = criteria.location

        # Type de contrat
        if criteria.contract_types:
            contract_codes = [
                self.CONTRACT_MAPPING.get(ct)
                for ct in criteria.contract_types
                if ct in self.CONTRACT_MAPPING
            ]
            if contract_codes:
                params["c"] = ",".join(filter(None, contract_codes))

        # Date de publication
        if criteria.date_posted and criteria.date_posted != DatePosted.ANY_TIME:
            date_code = self.DATE_POSTED_MAPPING.get(criteria.date_posted)
            if date_code:
                params["d"] = date_code

        # Rayon de recherche (en km)
        if criteria.radius_km:
            params["ray"] = str(criteria.radius_km)

        return f"{base}?{urlencode(params)}" if params else base

    def _extract_job_cards(self, soup: BeautifulSoup) -> list[Tag]:
        """
        Extrait les cartes d'offres d'emploi de la page.

        Args:
            soup: BeautifulSoup de la page

        Returns:
            Liste des éléments de carte d'offre
        """
        # Sélecteur principal pour HelloWork (structure 2024-2025)
        cards = list(soup.select("li[data-id-storage-item-id]"))
        if cards:
            logger.debug(f"{len(cards)} offres trouvées")
            return cards

        # Fallback: chercher via les liens d'offres
        offer_links = soup.select("a[href*='/fr-fr/emplois/']")
        if offer_links:
            cards = []
            seen_hrefs = set()
            for link in offer_links:
                href = link.get("href", "")
                if href in seen_hrefs:
                    continue
                seen_hrefs.add(href)
                parent = link.find_parent("li")
                if parent and parent not in cards:
                    cards.append(parent)
            if cards:
                logger.debug(f"Fallback: {len(cards)} offres trouvées via liens")
                return cards

        return []

    def _parse_job_card(self, card: Tag) -> Optional[JobOffer]:
        """
        Parse une carte d'offre d'emploi HelloWork.

        Args:
            card: Élément BeautifulSoup de la carte (li[data-id-storage-item-id])

        Returns:
            JobOffer ou None si parsing échoue
        """
        try:
            # ID depuis l'attribut data
            job_id = card.get("data-id-storage-item-id")
            if not job_id:
                return None

            # URL
            link = card.select_one("a[href*='/emplois/']")
            href = link.get("href", "") if link else None
            url = (
                href
                if isinstance(href, str) and href
                else f"/fr-fr/emplois/{job_id}.html"
            )
            if url.startswith("/"):
                url = f"{self.base_url}{url}"

            # Titre depuis l'input hidden (plus fiable)
            title_input = card.select_one('input[name="title"]')
            if title_input:
                title_value = title_input.get("value", "")
                title = title_value.strip() if isinstance(title_value, str) else None
            else:
                # Fallback: depuis le paragraphe
                title_elem = card.select_one("p.tw-typo-l, h3, h2")
                title = title_elem.get_text(strip=True) if title_elem else None

            # Entreprise depuis l'input hidden
            company_input = card.select_one('input[name="company"]')
            if company_input:
                company_value = company_input.get("value", "")
                company = (
                    company_value.strip() if isinstance(company_value, str) else None
                )
            else:
                # Fallback
                company_elem = card.select_one("p.tw-typo-s.tw-inline")
                company = company_elem.get_text(strip=True) if company_elem else None

            # Métadonnées actuelles, exposées via des attributs stables.
            location_elem = card.select_one('[data-cy="localisationCard"]')
            contract_elem = card.select_one('[data-cy="contractCard"]')
            location = (
                location_elem.get_text(" ", strip=True) if location_elem else None
            )
            contract_type = (
                self._map_contract_type(contract_elem.get_text(" ", strip=True))
                if contract_elem
                else None
            )
            salary_text = None

            # Balises historiques : elles restent utiles pour les anciennes cartes
            # et pour les métadonnées non encore couvertes par data-cy (salaire).
            tags = card.select(
                "div.tw-tag-secondary-s, div.tw-readonly.tw-tag-secondary-s"
            )
            for tag in tags:
                text = tag.get_text(" ", strip=True)

                # Localisation (contient un code postal ou arrondissement)
                if re.search(r"\d{2,5}$|^\d{5}", text) and not location:
                    location = text
                # Type de contrat
                elif not contract_type and text.upper() in [
                    "CDI",
                    "CDD",
                    "STAGE",
                    "ALTERNANCE",
                    "INTÉRIM",
                    "INTERIM",
                    "FREELANCE",
                ]:
                    contract_type = self._map_contract_type(text)
                # Salaire
                elif "€" in text and not salary_text:
                    salary_text = text

            # Date de publication
            posted_at = self._parse_posted_date(card)

            # Validation minimale
            if not title:
                return None

            return JobOffer(
                id=f"hellowork_{job_id}",
                source=self.name,
                url=url,
                title=title,
                company=company or "Non spécifié",
                location=location or "France",
                contract_type=contract_type,
                posted_at=posted_at,
            )

        except Exception as e:
            logger.debug(f"Erreur parsing carte: {e}")
            return None

    def _map_contract_type(self, text: str) -> Optional[ContractType]:
        """
        Convertit le texte du type de contrat en ContractType.
        """
        text_upper = text.upper().strip()
        mapping = {
            "CDI": ContractType.CDI,
            "CDD": ContractType.CDD,
            "STAGE": ContractType.STAGE,
            "ALTERNANCE": ContractType.ALTERNANCE,
            "INTÉRIM": ContractType.INTERIM,
            "INTERIM": ContractType.INTERIM,
            "FREELANCE": ContractType.FREELANCE,
        }
        return mapping.get(text_upper)

    def _parse_posted_date(self, card: Tag) -> Optional[datetime]:
        """
        Parse la date de publication depuis la carte.

        Args:
            card: Élément BeautifulSoup

        Returns:
            datetime ou None
        """
        # Chercher un élément time
        time_elem = card.select_one("time")
        if time_elem:
            datetime_attr = time_elem.get("datetime")
            if isinstance(datetime_attr, str):
                try:
                    return datetime.fromisoformat(datetime_attr.replace("Z", "+00:00"))
                except ValueError:
                    pass

        # Parser le texte relatif
        text = card.get_text().lower()
        return self._parse_relative_date(text)

    def _parse_relative_date(self, text: str) -> Optional[datetime]:
        """
        Parse une date relative en français.

        Args:
            text: Texte contenant la date

        Returns:
            datetime ou None
        """
        now = datetime.now()

        patterns = [
            (
                r"il y a (\d+)\s*minute",
                lambda m: now - timedelta(minutes=int(m.group(1))),
            ),
            (r"il y a (\d+)\s*heure", lambda m: now - timedelta(hours=int(m.group(1)))),
            (r"il y a (\d+)\s*jour", lambda m: now - timedelta(days=int(m.group(1)))),
            (
                r"il y a (\d+)\s*semaine",
                lambda m: now - timedelta(weeks=int(m.group(1))),
            ),
            (
                r"il y a (\d+)\s*mois",
                lambda m: now - timedelta(days=int(m.group(1)) * 30),
            ),
            (r"aujourd'hui", lambda m: now),
            (r"hier", lambda m: now - timedelta(days=1)),
        ]

        for pattern, handler in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return handler(match)

        return None

    def _parse_job_details(
        self, soup: BeautifulSoup, job_id: str, url: str
    ) -> Optional[JobOffer]:
        """
        Parse les détails complets d'une offre.

        Args:
            soup: BeautifulSoup de la page de détails
            job_id: ID de l'offre
            url: URL de l'offre

        Returns:
            JobOffer avec détails complets
        """
        try:
            # Titre
            title_elem = soup.select_one("h1, [class*='job-title']")
            title = title_elem.get_text(strip=True) if title_elem else "Unknown"

            # Entreprise
            company_elem = soup.select_one(
                "[class*='company'], [class*='entreprise'], "
                "[itemprop='hiringOrganization']"
            )
            company = (
                company_elem.get_text(strip=True) if company_elem else "Non spécifié"
            )

            # Localisation
            location_elem = soup.select_one(
                "[class*='location'], [class*='lieu'], " "[itemprop='jobLocation']"
            )
            location = location_elem.get_text(strip=True) if location_elem else "France"

            # Description
            description_elem = soup.select_one(
                "[class*='description'], [itemprop='description'], "
                ".job-description, #job-description"
            )
            description = (
                description_elem.get_text(strip=True) if description_elem else None
            )

            # Type de contrat
            contract_type = None
            contract_elem = soup.select_one("[itemprop='employmentType']")
            if contract_elem:
                contract_text = contract_elem.get_text().lower()
                if "cdi" in contract_text:
                    contract_type = ContractType.CDI
                elif "cdd" in contract_text:
                    contract_type = ContractType.CDD
                elif "stage" in contract_text:
                    contract_type = ContractType.STAGE
                elif "alternance" in contract_text:
                    contract_type = ContractType.ALTERNANCE

            # Salaire
            salary_min = None
            salary_max = None
            salary_elem = soup.select_one("[itemprop='baseSalary'], [class*='salary']")
            if salary_elem:
                salary_text = salary_elem.get_text()
                salary_match = re.search(r"(\d[\d\s]*)\s*(?:€|EUR)", salary_text)
                if salary_match:
                    salary_min = float(salary_match.group(1).replace(" ", ""))

            return JobOffer(
                id=f"hellowork_{job_id}",
                source=self.name,
                url=url,
                title=title,
                company=company,
                location=location,
                description=description,
                contract_type=contract_type,
                salary_min=salary_min,
                salary_max=salary_max,
            )

        except Exception as e:
            logger.error(f"Erreur parsing détails: {e}")
            return None
