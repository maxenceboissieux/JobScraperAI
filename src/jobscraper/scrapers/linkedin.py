"""Scraper pour LinkedIn Jobs."""

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
    WorkplaceType,
)
from jobscraper.scrapers.base import BaseScraper


class LinkedInScraper(BaseScraper):
    """Scraper pour les offres d'emploi LinkedIn."""

    name = "linkedin"
    base_url = "https://www.linkedin.com"
    can_deactivate_unseen = False

    # Mapping des niveaux d'expérience LinkedIn
    EXPERIENCE_MAPPING = {
        ExperienceLevel.INTERNSHIP: "1",  # Internship
        ExperienceLevel.JUNIOR: "2",  # Entry level
        ExperienceLevel.MID: "3",  # Associate
        ExperienceLevel.SENIOR: "4",  # Mid-Senior level
        ExperienceLevel.LEAD: "5",  # Director
        ExperienceLevel.DIRECTOR: "6",  # Executive
    }

    # Mapping des types de contrat LinkedIn
    CONTRACT_MAPPING = {
        ContractType.CDI: "F",  # Full-time
        ContractType.CDD: "C",  # Contract
        ContractType.INTERIM: "T",  # Temporary
        ContractType.STAGE: "I",  # Internship
        ContractType.ALTERNANCE: "I",  # Internship (closest match)
        ContractType.FREELANCE: "C",  # Contract
        ContractType.OTHER: "O",  # Other
    }

    # Mapping des types de lieu de travail
    WORKPLACE_MAPPING = {
        WorkplaceType.ON_SITE: "1",  # On-site
        WorkplaceType.REMOTE: "2",  # Remote
        WorkplaceType.HYBRID: "3",  # Hybrid
    }

    # Mapping des dates de publication
    DATE_POSTED_MAPPING = {
        DatePosted.PAST_24H: "r86400",  # Past 24 hours
        DatePosted.PAST_WEEK: "r604800",  # Past week
        DatePosted.PAST_MONTH: "r2592000",  # Past month
        DatePosted.ANY_TIME: "",  # Any time (no filter)
    }

    # Mapping du tri
    SORT_MAPPING = {
        SortBy.RELEVANCE: "R",  # Most relevant
        SortBy.DATE: "DD",  # Most recent
    }

    # Rayons de recherche disponibles (en miles pour LinkedIn)
    RADIUS_MAPPING = {
        5: "5",
        10: "10",
        25: "25",
        50: "50",
        100: "100",
    }

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialise le scraper LinkedIn.

        Args:
            config: Configuration optionnelle
        """
        super().__init__(config)
        self.delay_between_requests = config.get("delay", 2) if config else 2

    def search(self, criteria: SearchCriteria) -> Iterator[JobOffer]:
        """
        Recherche des offres d'emploi sur LinkedIn.

        Args:
            criteria: Critères de recherche

        Yields:
            JobOffer: Les offres d'emploi trouvées
        """
        self._begin_search()
        initial_url = self._build_search_url(criteria)
        guest_url = self._build_search_url(criteria, guest=True)
        logger.info(f"Recherche LinkedIn: {initial_url}")

        start = 0
        jobs_found = 0
        max_results = criteria.max_results
        seen_ids: set = set()  # Pour la déduplication
        initial_page = True
        empty_page_seen = False

        while jobs_found < max_results:
            page_url = f"{initial_url if initial_page else guest_url}&start={start}"
            logger.debug(f"Récupération page: {page_url}")

            try:
                html = self._fetch_page(page_url)
                soup = BeautifulSoup(html, "lxml")

                job_cards = self._extract_job_cards(soup)

                if not job_cards:
                    if empty_page_seen:
                        logger.info("Plus d'offres trouvées")
                        self._mark_search_complete()
                        break
                    empty_page_seen = True
                    time.sleep(self.delay_between_requests)
                    continue

                empty_page_seen = False

                new_jobs_on_page = 0
                parsed_jobs_on_page = 0
                for card in job_cards:
                    if jobs_found >= max_results:
                        break

                    job = self._parse_job_card(card)
                    if job:
                        parsed_jobs_on_page += 1
                        # Déduplication par ID
                        if job.id in seen_ids:
                            logger.debug(f"Doublon ignoré: {job.id}")
                            continue
                        seen_ids.add(job.id)
                        jobs_found += 1
                        new_jobs_on_page += 1
                        yield job

                if jobs_found >= max_results:
                    break

                if parsed_jobs_on_page != len(job_cards):
                    self._incomplete_search(
                        "Une partie des résultats LinkedIn est inexploitables"
                    )

                # Si aucune nouvelle offre sur cette page, on arrête
                if new_jobs_on_page == 0:
                    logger.info("Plus de nouvelles offres")
                    self._incomplete_search(
                        "La pagination LinkedIn ne contient que des doublons"
                    )
                    break

                start += len(job_cards)
                initial_page = False
                time.sleep(self.delay_between_requests)

            except Exception as e:
                logger.error(f"Erreur lors de la recherche: {e}")
                if self.config.get("propagate_search_errors"):
                    raise
                break

        logger.info(f"Recherche terminée: {jobs_found} offres uniques trouvées")

    def get_job_details(self, job_id: str) -> Optional[JobOffer]:
        """
        Récupère les détails complets d'une offre LinkedIn.

        Args:
            job_id: Identifiant de l'offre LinkedIn

        Returns:
            JobOffer avec tous les détails ou None
        """
        url = f"{self.base_url}/jobs/view/{job_id}"
        logger.debug(f"Récupération détails: {url}")

        try:
            html = self._fetch_page(url)
            soup = BeautifulSoup(html, "lxml")
            return self._parse_job_details(soup, job_id, url)
        except Exception as e:
            logger.error(f"Erreur récupération détails job {job_id}: {e}")
            return None

    def _build_search_url(
        self, criteria: SearchCriteria, *, guest: bool = False
    ) -> str:
        """
        Construit l'URL de recherche LinkedIn avec tous les filtres disponibles.

        Args:
            criteria: Critères de recherche

        Returns:
            URL de recherche formatée
        """
        if guest:
            base = f"{self.base_url}/jobs-guest/jobs/api/seeMoreJobPostings/search"
        else:
            base = f"{self.base_url}/jobs/search"

        # Construire les mots-clés avec le titre si spécifié
        keywords_parts = []
        if criteria.title:
            keywords_parts.append(f'"{criteria.title}"')  # Recherche exacte
        if criteria.keywords:
            keywords_parts.extend(criteria.keywords)

        params = {
            "keywords": " ".join(keywords_parts),
            "location": criteria.location,
            "trk": "public_jobs_jobs-search-bar_search-submit",
        }
        if not guest:
            params.update({"position": "1", "pageNum": "0"})

        # Tri des résultats
        if criteria.sort_by:
            params["sortBy"] = self.SORT_MAPPING.get(criteria.sort_by, "R")

        # Filtre par niveau d'expérience
        if criteria.experience_levels:
            exp_codes = [
                self.EXPERIENCE_MAPPING.get(exp)
                for exp in criteria.experience_levels
                if exp in self.EXPERIENCE_MAPPING
            ]
            if exp_codes:
                params["f_E"] = ",".join(filter(None, exp_codes))

        # Filtre par type de contrat
        if criteria.contract_types:
            contract_codes = [
                self.CONTRACT_MAPPING.get(ct)
                for ct in criteria.contract_types
                if ct in self.CONTRACT_MAPPING
            ]
            if contract_codes:
                params["f_JT"] = ",".join(filter(None, contract_codes))

        # Filtre par type de lieu de travail (remote, hybrid, on-site)
        if criteria.workplace_types:
            workplace_codes = [
                self.WORKPLACE_MAPPING.get(wt)
                for wt in criteria.workplace_types
                if wt in self.WORKPLACE_MAPPING
            ]
            if workplace_codes:
                params["f_WT"] = ",".join(filter(None, workplace_codes))

        # Filtre par date de publication
        if criteria.date_posted and criteria.date_posted != DatePosted.ANY_TIME:
            date_code = self.DATE_POSTED_MAPPING.get(criteria.date_posted)
            if date_code:
                params["f_TPR"] = date_code
        elif criteria.date_posted is None and criteria.posted_within_days:
            # Compatibilité: ne consulter l'ancien filtre qu'en l'absence du nouveau.
            if criteria.posted_within_days <= 1:
                params["f_TPR"] = "r86400"
            elif criteria.posted_within_days <= 7:
                params["f_TPR"] = "r604800"
            elif criteria.posted_within_days <= 30:
                params["f_TPR"] = "r2592000"

        # Distance / Rayon de recherche
        radius_km = criteria.radius_km
        if radius_km is not None:
            # Trouver le rayon le plus proche disponible
            available_radii = sorted(self.RADIUS_MAPPING.keys())
            closest = min(available_radii, key=lambda value: abs(value - radius_km))
            params["distance"] = self.RADIUS_MAPPING[closest]

        # Filtre par entreprises spécifiques
        if criteria.companies:
            # LinkedIn utilise les IDs d'entreprise, mais on peut chercher par nom
            params["f_C"] = ",".join(criteria.companies)

        return f"{base}?{urlencode(params)}"

    def _extract_job_cards(self, soup: BeautifulSoup) -> list[Tag]:
        """
        Extrait les cartes d'offres d'emploi de la page.

        Args:
            soup: BeautifulSoup de la page

        Returns:
            Liste des éléments de carte d'offre
        """
        # Sélecteurs pour les pages publiques LinkedIn
        selectors = [
            "div.base-card",
            "li.jobs-search-results__list-item",
            "div.job-search-card",
        ]

        for selector in selectors:
            cards = soup.select(selector)
            if cards:
                return cards

        return []

    def _is_masked(self, text: Optional[str]) -> bool:
        """
        Vérifie si un texte est masqué par LinkedIn (contient trop d'astérisques).

        Args:
            text: Texte à vérifier

        Returns:
            True si le texte est masqué
        """
        if not text:
            return True
        # Compter les astérisques
        asterisk_count = text.count("*")
        # Si plus de 30% du texte sont des astérisques, c'est masqué
        if len(text) > 0 and asterisk_count / len(text) > 0.3:
            return True
        return False

    def _parse_job_card(self, card: Tag) -> Optional[JobOffer]:
        """
        Parse une carte d'offre d'emploi.

        Args:
            card: Élément BeautifulSoup de la carte

        Returns:
            JobOffer ou None si parsing échoue ou offre masquée
        """
        try:
            # Titre
            title_elem = card.select_one(
                "h3.base-search-card__title, "
                "a.job-card-list__title, "
                "h3.job-card-title"
            )
            title = title_elem.get_text(strip=True) if title_elem else None

            # Entreprise
            company_elem = card.select_one(
                "h4.base-search-card__subtitle, "
                "a.job-card-container__company-name, "
                "h4.job-card-subtitle"
            )
            company = company_elem.get_text(strip=True) if company_elem else None

            # Filtrer les offres masquées par LinkedIn
            if self._is_masked(title) or self._is_masked(company):
                logger.debug(f"Offre masquée ignorée: {title} @ {company}")
                return None

            # Localisation
            location_elem = card.select_one(
                "span.job-search-card__location, "
                "li.job-card-container__metadata-item, "
                "span.job-card-location"
            )
            location = location_elem.get_text(strip=True) if location_elem else None

            # URL et ID
            link_elem = card.select_one(
                "a.base-card__full-link, a.job-card-list__title"
            )
            href = link_elem.get("href") if link_elem else None
            url = str(href) if isinstance(href, str) else None

            # Extraire l'ID de l'URL (format: /jobs/view/titre-slug-123456)
            job_id = None
            if url:
                # L'ID est le dernier nombre dans l'URL avant les paramètres
                match = re.search(r"-(\d+)(?:\?|$)", url)
                if not match:
                    # Fallback: chercher dans data-entity-urn
                    urn_value = card.get("data-entity-urn", "")
                    urn = urn_value if isinstance(urn_value, str) else ""
                    match = re.search(r"jobPosting:(\d+)", urn)
                if match:
                    job_id = match.group(1)

            if not all([title, company, job_id]):
                return None

            # Date de publication
            posted_at = self._parse_posted_date(card)

            # Type de contrat quand il est exposé dans la carte publique
            contract_type = None
            contract_elem = card.select_one(
                "span.job-search-card__employment-type, "
                "span.job-card-container__employment-type"
            )
            if contract_elem:
                contract_text = contract_elem.get_text(strip=True).upper()
                contract_type = {
                    "CDI": ContractType.CDI,
                    "CDD": ContractType.CDD,
                    "INTÉRIM": ContractType.INTERIM,
                    "INTERIM": ContractType.INTERIM,
                    "STAGE": ContractType.STAGE,
                    "ALTERNANCE": ContractType.ALTERNANCE,
                    "FREELANCE": ContractType.FREELANCE,
                }.get(contract_text)

            return JobOffer(
                id=f"linkedin_{job_id}",
                source=self.name,
                url=url or f"{self.base_url}/jobs/view/{job_id}",
                title=title,
                company=company,
                location=location or "France",
                contract_type=contract_type,
                posted_at=posted_at,
            )

        except Exception as e:
            logger.debug(f"Erreur parsing carte: {e}")
            return None

    def _parse_posted_date(self, card: Tag) -> Optional[datetime]:
        """
        Parse la date de publication depuis la carte.

        Args:
            card: Élément BeautifulSoup

        Returns:
            datetime ou None
        """
        date_elem = card.select_one(
            "time.job-search-card__listdate, " "time.job-card-container__listed-date"
        )

        if date_elem:
            datetime_attr = date_elem.get("datetime")
            if isinstance(datetime_attr, str):
                try:
                    return datetime.fromisoformat(datetime_attr.replace("Z", "+00:00"))
                except ValueError:
                    pass

            # Parse le texte relatif (ex: "il y a 2 jours")
            text = date_elem.get_text(strip=True).lower()
            return self._parse_relative_date(text)

        return None

    def _parse_relative_date(self, text: str) -> Optional[datetime]:
        """
        Parse une date relative en français ou anglais.

        Args:
            text: Texte de la date (ex: "il y a 2 jours")

        Returns:
            datetime ou None
        """
        now = datetime.now()

        patterns = [
            (
                r"(\d+)\s*(minute|min)",
                lambda m: now - timedelta(minutes=int(m.group(1))),
            ),
            (
                r"(\d+)\s*(heure|hour|hr)",
                lambda m: now - timedelta(hours=int(m.group(1))),
            ),
            (r"(\d+)\s*(jour|day)", lambda m: now - timedelta(days=int(m.group(1)))),
            (
                r"(\d+)\s*(semaine|week)",
                lambda m: now - timedelta(weeks=int(m.group(1))),
            ),
            (
                r"(\d+)\s*(mois|month)",
                lambda m: now - timedelta(days=int(m.group(1)) * 30),
            ),
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
            title_element = soup.select_one(
                "h1.top-card-layout__title, " "h1.jobs-unified-top-card__job-title"
            )
            title = title_element.get_text(strip=True) if title_element else "Unknown"

            # Entreprise
            company_element = soup.select_one(
                "a.topcard__org-name-link, " "span.jobs-unified-top-card__company-name"
            )
            company = (
                company_element.get_text(strip=True) if company_element else "Unknown"
            )

            # Localisation
            location_element = soup.select_one(
                "span.topcard__flavor--bullet, " "span.jobs-unified-top-card__bullet"
            )
            location = (
                location_element.get_text(strip=True) if location_element else "France"
            )

            # Description
            description = soup.select_one(
                "div.description__text, " "div.jobs-description__content"
            )
            description_text = self._extract_description_text(description)

            # Critères (type de contrat, niveau d'expérience, etc.)
            criteria_items = soup.select(
                "li.description__job-criteria-item, "
                "li.jobs-unified-top-card__job-insight"
            )

            contract_type = None
            experience_level = None

            for item in criteria_items:
                text = item.get_text(strip=True).lower()
                if "cdi" in text or "full-time" in text or "temps plein" in text:
                    contract_type = ContractType.CDI
                elif "cdd" in text or "contract" in text:
                    contract_type = ContractType.CDD
                elif "stage" in text or "internship" in text:
                    contract_type = ContractType.STAGE
                elif "alternance" in text or "apprenticeship" in text:
                    contract_type = ContractType.ALTERNANCE

                if "entry" in text or "junior" in text or "débutant" in text:
                    experience_level = ExperienceLevel.JUNIOR
                elif "senior" in text or "confirmé" in text:
                    experience_level = ExperienceLevel.SENIOR
                elif "mid" in text or "intermédiaire" in text:
                    experience_level = ExperienceLevel.MID

            # Compétences
            skills = []
            skills_section = soup.select(
                "span.job-details-skill-match-status-list__skill-name"
            )
            for skill in skills_section:
                skills.append(skill.get_text(strip=True))

            return JobOffer(
                id=f"linkedin_{job_id}",
                source=self.name,
                url=url,
                title=title,
                company=company,
                location=location,
                description=description_text,
                contract_type=contract_type,
                experience_level=experience_level,
                skills=skills,
            )

        except Exception as e:
            logger.error(f"Erreur parsing détails: {e}")
            return None

    @staticmethod
    def _extract_description_text(element: Tag | None) -> str | None:
        """Extract readable detail text while preserving HTML block separators."""
        if element is None:
            return None
        lines = [
            re.sub(r"\s+", " ", line).strip()
            for line in element.get_text("\n", strip=True).splitlines()
        ]
        text = "\n".join(line for line in lines if line)
        return text or None
