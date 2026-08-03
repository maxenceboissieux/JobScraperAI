"""Scraper pour France Travail (ex Pôle Emploi)."""

import re
import time
from datetime import datetime, timedelta
from typing import Dict, Iterator, Optional
from urllib.parse import urlencode

from bs4 import BeautifulSoup, Tag
from loguru import logger

from jobscraper.models.job import (
    ContractType,
    DatePosted,
    ExperienceLevel,
    JobOffer,
    SearchCriteria,
)
from jobscraper.scrapers.base import BaseScraper


class FranceTravailScraper(BaseScraper):
    """Scraper pour les offres d'emploi France Travail."""

    name = "francetravail"
    base_url = "https://candidat.francetravail.fr"

    # Mapping des types de contrat
    CONTRACT_MAPPING = {
        ContractType.CDI: "CDI",
        ContractType.CDD: "CDD",
        ContractType.INTERIM: "MIS",
        ContractType.STAGE: "SAI",
        ContractType.ALTERNANCE: "CDS",
        ContractType.FREELANCE: "LIB",
    }

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialise le scraper France Travail.

        Args:
            config: Configuration optionnelle
        """
        super().__init__(config)
        self.delay_between_requests = config.get("delay", 2) if config else 2

    def _get_headers(self) -> dict:
        """Headers HTTP pour France Travail."""
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
        Recherche des offres d'emploi sur France Travail.

        Args:
            criteria: Critères de recherche

        Yields:
            JobOffer: Les offres d'emploi trouvées
        """
        url = self._build_search_url(criteria)
        logger.info(f"Recherche France Travail: {url}")

        page = 1
        jobs_found = 0
        max_results = criteria.max_results
        seen_ids: set = set()

        while jobs_found < max_results:
            page_url = f"{url}&page={page}" if page > 1 else url
            logger.debug(f"Récupération page {page}: {page_url}")

            try:
                html = self._fetch_page(page_url)
                soup = BeautifulSoup(html, "lxml")

                job_cards = self._extract_job_cards(soup)

                if not job_cards:
                    logger.info("Plus d'offres trouvées")
                    break

                new_jobs_on_page = 0
                for card in job_cards:
                    if jobs_found >= max_results:
                        break

                    job = self._parse_job_card(card)
                    if job:
                        if job.id in seen_ids:
                            logger.debug(f"Doublon ignoré: {job.id}")
                            continue
                        seen_ids.add(job.id)
                        jobs_found += 1
                        new_jobs_on_page += 1
                        yield job

                if new_jobs_on_page == 0:
                    logger.info("Plus de nouvelles offres")
                    break

                page += 1
                time.sleep(self.delay_between_requests)

            except Exception as e:
                logger.error(f"Erreur lors de la recherche: {e}")
                break

        logger.info(f"Recherche terminée: {jobs_found} offres uniques trouvées")

    def get_job_details(self, job_id: str) -> Optional[JobOffer]:
        """
        Récupère les détails complets d'une offre.

        Args:
            job_id: Identifiant de l'offre

        Returns:
            JobOffer avec tous les détails ou None
        """
        numeric_id = job_id.replace("francetravail_", "")
        url = f"{self.base_url}/offres/recherche/detail/{numeric_id}"
        logger.debug(f"Récupération détails: {url}")

        try:
            html = self._fetch_page(url)
            soup = BeautifulSoup(html, "lxml")
            return self._parse_job_details(soup, numeric_id, url)
        except Exception as e:
            logger.error(f"Erreur récupération détails job {job_id}: {e}")
            return None

    def _build_search_url(self, criteria: SearchCriteria) -> str:
        """
        Construit l'URL de recherche France Travail.

        Args:
            criteria: Critères de recherche

        Returns:
            URL de recherche formatée
        """
        base = f"{self.base_url}/offres/recherche"

        # Construire les mots-clés
        keywords_parts = []
        if criteria.title:
            keywords_parts.append(criteria.title)
        if criteria.keywords:
            keywords_parts.extend(criteria.keywords)

        params = {
            "offresPartenaires": "true",
            "tri": "0",  # Pertinence
        }

        # Ajouter la localisation aux mots-clés (le paramètre lieux nécessite un code commune)
        if criteria.location and criteria.location.lower() != "france":
            keywords_parts.append(criteria.location)

        if keywords_parts:
            params["motsCles"] = " ".join(keywords_parts)

        # Rayon de recherche
        if criteria.radius_km:
            params["rayon"] = str(criteria.radius_km)

        # Type de contrat
        if criteria.contract_types:
            contract_codes = [
                self.CONTRACT_MAPPING.get(ct)
                for ct in criteria.contract_types
                if ct in self.CONTRACT_MAPPING
            ]
            if contract_codes:
                params["typeContrat"] = ",".join(filter(None, contract_codes))

        # Date de publication
        if criteria.date_posted:
            if criteria.date_posted == DatePosted.PAST_24H:
                params["dureeCreation"] = "1"
            elif criteria.date_posted == DatePosted.PAST_WEEK:
                params["dureeCreation"] = "7"
            elif criteria.date_posted == DatePosted.PAST_MONTH:
                params["dureeCreation"] = "31"

        return f"{base}?{urlencode(params)}"

    def _extract_job_cards(self, soup: BeautifulSoup) -> list[Tag]:
        """
        Extrait les cartes d'offres d'emploi de la page.

        Args:
            soup: BeautifulSoup de la page

        Returns:
            Liste des éléments de carte d'offre
        """
        # Sélecteur principal
        cards = soup.select("li.result[data-id-offre]")
        if cards:
            logger.debug(f"{len(cards)} offres trouvées")
            return cards

        # Fallback
        cards = soup.select("li.result")
        if cards:
            logger.debug(f"Fallback: {len(cards)} offres trouvées")
            return cards

        return []

    def _parse_job_card(self, card: Tag) -> Optional[JobOffer]:
        """
        Parse une carte d'offre d'emploi France Travail.

        Args:
            card: Élément BeautifulSoup de la carte

        Returns:
            JobOffer ou None si parsing échoue
        """
        try:
            # ID depuis l'attribut data
            job_id = card.get("data-id-offre")
            if not job_id:
                # Essayer d'extraire de l'URL
                link = card.select_one("a[href*='/offres/recherche/detail/']")
                if link:
                    href_value = link.get("href", "")
                    href = href_value if isinstance(href_value, str) else ""
                    match = re.search(r"/detail/([A-Z0-9]+)", href)
                    if match:
                        job_id = match.group(1)

            if not job_id:
                return None

            # URL
            url = f"{self.base_url}/offres/recherche/detail/{job_id}"

            # Titre
            title_elem = card.select_one("h2.media-heading span.media-heading-title")
            if not title_elem:
                title_elem = card.select_one("h2.media-heading")
            title = title_elem.get_text(strip=True) if title_elem else None

            # Entreprise et localisation depuis p.subtext
            company = None
            location = None
            subtext = card.select_one("p.subtext")
            if subtext:
                subtext_content = subtext.get_text(strip=True)
                # Format: "ENTREPRISE - LOCALISATION"
                if " - " in subtext_content:
                    parts = subtext_content.split(" - ", 1)
                    company = parts[0].strip()
                    location = parts[1].strip() if len(parts) > 1 else None
                else:
                    # Essayer avec le span pour la localisation
                    loc_span = subtext.select_one("span")
                    if loc_span:
                        location = loc_span.get_text(strip=True)
                        company = subtext_content.replace(location, "").strip(" -")

            # Description
            description_elem = card.select_one("p.description")
            description = (
                description_elem.get_text(strip=True) if description_elem else None
            )

            # Type de contrat
            contract_type = None
            contract_elem = card.select_one("p.contrat, div.media-right p.contrat")
            if contract_elem:
                contract_text = contract_elem.get_text(strip=True).upper()
                if "CDI" in contract_text:
                    contract_type = ContractType.CDI
                elif "CDD" in contract_text:
                    contract_type = ContractType.CDD
                elif "INTÉRIM" in contract_text or "MIS" in contract_text:
                    contract_type = ContractType.INTERIM
                elif "ALTERNANCE" in contract_text:
                    contract_type = ContractType.ALTERNANCE

            # Date de publication
            posted_at = None
            date_elem = card.select_one("p.date")
            if date_elem:
                date_text = date_elem.get_text(strip=True)
                posted_at = self._parse_relative_date(date_text)

            # Validation minimale
            if not title:
                return None

            return JobOffer(
                id=f"francetravail_{job_id}",
                source=self.name,
                url=url,
                title=title,
                company=company or "Entreprise confidentielle",
                location=location or "France",
                description=description,
                contract_type=contract_type,
                posted_at=posted_at,
            )

        except Exception as e:
            logger.debug(f"Erreur parsing carte: {e}")
            return None

    def _parse_relative_date(self, text: str) -> Optional[datetime]:
        """
        Parse une date relative en français.

        Args:
            text: Texte contenant la date (ex: "Publié il y a 6 jours")

        Returns:
            datetime ou None
        """
        now = datetime.now()
        text_lower = text.lower()

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
            match = re.search(pattern, text_lower, re.IGNORECASE)
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
            title_elem = soup.select_one("h1, [itemprop='title']")
            title = title_elem.get_text(strip=True) if title_elem else "Unknown"

            # Entreprise
            company_elem = soup.select_one("[itemprop='hiringOrganization']")
            company = (
                company_elem.get_text(strip=True)
                if company_elem
                else "Entreprise confidentielle"
            )

            # Localisation
            location_elem = soup.select_one("[itemprop='jobLocation']")
            location = location_elem.get_text(strip=True) if location_elem else "France"

            # Description
            description_elem = soup.select_one("[itemprop='description'], .description")
            description = (
                description_elem.get_text(strip=True) if description_elem else None
            )

            return JobOffer(
                id=f"francetravail_{job_id}",
                source=self.name,
                url=url,
                title=title,
                company=company,
                location=location,
                description=description,
            )

        except Exception as e:
            logger.error(f"Erreur parsing détails: {e}")
            return None
