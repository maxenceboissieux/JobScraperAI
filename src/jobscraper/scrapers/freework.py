"""Scraper for public Free-Work job listings."""

import json
import re
import time
import unicodedata
from datetime import datetime, timedelta
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Dict, Iterator, Optional
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup
from loguru import logger

from jobscraper.models.job import ContractType, DatePosted, JobOffer, SearchCriteria
from jobscraper.scrapers.base import BaseScraper
from jobscraper.utils import geocoding


def slugify(value: str) -> str:
    """Convert a location label to the slug format used by Free-Work."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")


class FreeWorkScraper(BaseScraper):
    """Search public Free-Work listings."""

    name = "freework"
    base_url = "https://www.free-work.com"

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)
        self.delay_between_requests = float(self.config.get("delay", 2))
        self.page_size = max(1, int(self.config.get("page_size", 16)))
        self.max_pages = max(1, int(self.config.get("max_pages", 50)))
        self._canonical_urls: dict[str, str] = {}

    def search(self, criteria: SearchCriteria) -> Iterator[JobOffer]:
        """Yield unique matching jobs from consecutive full result pages."""
        page = 1
        yielded = 0
        seen_ids: set[str] = set()

        while yielded < criteria.max_results and page <= self.max_pages:
            url = self._build_search_url(criteria, page=page)
            logger.debug(f"Récupération Free-Work page {page}: {url}")
            try:
                soup = BeautifulSoup(self._fetch_page(url), "lxml")
            except Exception as exc:
                logger.error(f"Erreur lors de la recherche Free-Work: {exc}")
                break

            page_jobs: list[JobOffer] = []
            for extractor in (
                self._extract_nuxt_jobs,
                self._extract_json_ld_jobs,
                self._extract_job_cards,
            ):
                page_jobs = [
                    job
                    for candidate in extractor(soup)
                    if (job := self._parse_job_card(candidate)) is not None
                ]
                if page_jobs:
                    break
            if not page_jobs:
                break

            new_ids_on_page = 0
            for job in page_jobs:
                if yielded >= criteria.max_results:
                    break

                if job.id in seen_ids:
                    continue
                seen_ids.add(job.id)
                new_ids_on_page += 1

                if not self._matches_criteria(job, criteria):
                    continue

                yielded += 1
                yield job

            if (
                yielded >= criteria.max_results
                or len(page_jobs) < self.page_size
                or new_ids_on_page == 0
            ):
                break

            page += 1
            if self.delay_between_requests > 0:
                time.sleep(self.delay_between_requests)

    def get_job_details(self, job_id: str) -> Optional[JobOffer]:
        """Fetch and normalize a public Free-Work detail page."""
        target = self._resolve_detail_target(job_id)
        if target is None:
            return None

        external_id, url = target
        logger.debug(f"Récupération détails Free-Work: {url}")
        try:
            soup = BeautifulSoup(self._fetch_page(url), "lxml")
            return self._parse_job_details(soup, external_id, url)
        except Exception as exc:
            logger.error(f"Erreur récupération détails Free-Work {external_id}: {exc}")
            return None

    def _resolve_detail_target(self, value: str) -> Optional[tuple[str, str]]:
        """Resolve a cached ID or a canonical absolute Free-Work offer URL."""
        rendered = value.strip()
        parsed = urlparse(rendered)
        if parsed.scheme or parsed.netloc:
            external_id = self._canonical_external_id(rendered)
            if not external_id:
                return None
            self._canonical_urls[external_id] = rendered
            return external_id, rendered

        external_id = self._external_id(rendered, "")
        if not external_id:
            return None
        url = self._canonical_urls.get(external_id)
        return (external_id, url) if url else None

    @staticmethod
    def _canonical_external_id(value: str) -> Optional[str]:
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.hostname not in {
            "free-work.com",
            "www.free-work.com",
        }:
            return None
        match = re.fullmatch(r"/fr/tech-it/[^/]+/job-mission/([^/]+)/?", parsed.path)
        return match.group(1) if match else None

    def _parse_job_details(
        self, soup: BeautifulSoup, external_id: str, url: str
    ) -> Optional[JobOffer]:
        """Prefer JobPosting JSON-LD and fill missing fields from page HTML."""
        try:
            structured_jobs = self._extract_json_ld_jobs(soup)
            detail_container = soup.select_one(
                "[data-job-id], [data-testid='job-detail'], "
                "article.job-detail, main.job-detail"
            )
            if not structured_jobs and detail_container is None:
                return None

            structured = structured_jobs[0] if structured_jobs else {}
            structured_values = self._detail_structured_values(structured)
            html_values = self._detail_html_values(detail_container or soup)

            def prefer_structured(key: str) -> Any:
                value = structured_values.get(key)
                return value if value not in (None, "", []) else html_values.get(key)

            title = str(prefer_structured("title") or "").strip()
            if not title:
                return None

            salary_min = prefer_structured("salary_min")
            salary_max = prefer_structured("salary_max")
            salary_currency = str(prefer_structured("salary_currency") or "EUR")
            detail_url = urljoin(
                self.base_url, str(prefer_structured("url") or url).strip()
            )

            return JobOffer(
                id=f"freework_{external_id}",
                source=self.name,
                url=detail_url,
                title=title,
                company=str(prefer_structured("company") or "Non spécifié").strip(),
                location=str(prefer_structured("location") or "France").strip(),
                description=prefer_structured("description"),
                salary_min=salary_min,
                salary_max=salary_max,
                salary_currency=salary_currency,
                contract_type=self._map_contract_type(prefer_structured("contract")),
                posted_at=self._parse_posted_date(prefer_structured("posted_at")),
                skills=prefer_structured("skills") or [],
                benefits=prefer_structured("benefits") or [],
            )
        except (AttributeError, TypeError, ValueError) as exc:
            logger.debug(f"Détails Free-Work ignorés: {exc}")
            return None

    def _detail_structured_values(self, item: dict[str, Any]) -> dict[str, Any]:
        values = self._structured_values(item) if item else {}
        salary_min, salary_max, salary_currency = self._parse_salary(
            item.get("baseSalary") if item else None
        )
        values.update(
            {
                "description": self._clean_rich_text(item.get("description")),
                "salary_min": salary_min,
                "salary_max": salary_max,
                "salary_currency": salary_currency,
                "skills": self._normalize_list(
                    item.get("skills") or item.get("qualifications")
                ),
                "benefits": self._normalize_list(item.get("jobBenefits")),
            }
        )
        return values

    def _detail_html_values(self, soup: BeautifulSoup) -> dict[str, Any]:
        title = soup.select_one("h1")
        company = soup.select_one(
            "[itemprop='hiringOrganization'] [itemprop='name'], "
            "[itemprop='hiringOrganization'], .job-company, [data-company]"
        )
        location = soup.select_one(
            "[itemprop='jobLocation'], .job-location, [data-location]"
        )
        description = soup.select_one(
            "[itemprop='description'], .job-description, #job-description, "
            "[data-testid='job-description']"
        )
        contract = soup.select_one(
            "[itemprop='employmentType'], .job-contract, [data-contract]"
        )
        salary = soup.select_one("[itemprop='baseSalary'], .job-salary, [data-salary]")
        time_element = soup.select_one("time")
        salary_min, salary_max, salary_currency = self._parse_salary(
            salary.get_text(" ", strip=True) if salary else None
        )

        return {
            "title": title.get_text(" ", strip=True) if title else None,
            "company": self._element_value(company, "data-company"),
            "location": self._element_value(location, "data-location"),
            "description": (
                description.get_text(" ", strip=True) if description else None
            ),
            "contract": self._element_value(contract, "data-contract"),
            "posted_at": (
                time_element.get("datetime") or time_element.get_text(" ", strip=True)
                if time_element
                else None
            ),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": salary_currency,
            "skills": self._html_list(soup, ".job-skills, [data-skills]"),
            "benefits": self._html_list(soup, ".job-benefits, [data-benefits]"),
        }

    @staticmethod
    def _element_value(element: Any, attribute: str) -> Optional[str]:
        if element is None:
            return None
        return element.get(attribute) or element.get_text(" ", strip=True) or None

    @classmethod
    def _html_list(cls, soup: BeautifulSoup, selector: str) -> list[str]:
        container = soup.select_one(selector)
        if container is None:
            return []
        items = [item.get_text(" ", strip=True) for item in container.select("li")]
        if items:
            return [item for item in items if item]
        return cls._normalize_list(container.get_text(" ", strip=True))

    @staticmethod
    def _clean_rich_text(value: Any) -> Optional[str]:
        if not isinstance(value, str) or not value.strip():
            return None
        return BeautifulSoup(value, "lxml").get_text(" ", strip=True) or None

    @staticmethod
    def _normalize_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if not isinstance(value, str) or not value.strip():
            return []
        return [item.strip() for item in re.split(r"[,;\n]", value) if item.strip()]

    @classmethod
    def _parse_salary(
        cls, value: Any
    ) -> tuple[Optional[float], Optional[float], Optional[str]]:
        currency = None
        if isinstance(value, dict):
            currency = value.get("currency")
            amount = value.get("value", value)
            if isinstance(amount, dict):
                minimum = cls._as_float(amount.get("minValue") or amount.get("value"))
                maximum = cls._as_float(amount.get("maxValue"))
                return minimum, maximum, str(currency) if currency else None
            return cls._as_float(amount), None, str(currency) if currency else None

        if not isinstance(value, str):
            return None, None, None
        normalized = value.replace("\xa0", " ")
        amounts = re.findall(r"\d[\d ]*(?:[.,]\d+)?", normalized)
        parsed = [cls._as_float(amount) for amount in amounts]
        parsed = [amount for amount in parsed if amount is not None]
        currency_match = re.search(r"\b(EUR|USD|GBP)\b|€|\$|£", normalized, re.I)
        if currency_match:
            currency = {"€": "EUR", "$": "USD", "£": "GBP"}.get(
                currency_match.group(0), currency_match.group(0).upper()
            )
        return (
            parsed[0] if parsed else None,
            parsed[1] if len(parsed) > 1 else None,
            currency,
        )

    @staticmethod
    def _as_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(str(value).replace(" ", "").replace(",", "."))
        except ValueError:
            return None

    def _build_search_url(self, criteria: SearchCriteria, page: int = 1) -> str:
        path = "/fr/tech-it/jobs"
        if criteria.location and criteria.location.casefold() != "france":
            path += f"/{slugify(criteria.location)}"

        query = " ".join(filter(None, [criteria.title, *criteria.keywords]))
        params = {"query": query} if query else {}
        if page > 1:
            params["page"] = str(page)

        suffix = f"?{urlencode(params)}" if params else ""
        return f"{self.base_url}{path}{suffix}"

    def _extract_nuxt_jobs(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Extract concrete job dictionaries without decoding Nuxt devalue refs."""
        script = soup.select_one("script#__NUXT_DATA__")
        if script is None:
            return []

        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            return []

        jobs: list[dict[str, Any]] = []
        fingerprints: set[tuple[str, str, str]] = set()

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                title = value.get("title") or value.get("name")
                url = value.get("url") or value.get("href") or value.get("path")
                identifier = (
                    value.get("id") or value.get("jobId") or value.get("identifier")
                )
                if isinstance(title, str) and (
                    isinstance(url, str) or isinstance(identifier, (str, int))
                ):
                    fingerprint = (str(identifier or ""), title, str(url or ""))
                    if fingerprint not in fingerprints:
                        fingerprints.add(fingerprint)
                        jobs.append(value)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(payload)
        return jobs

    def _extract_json_ld_jobs(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Extract JobPosting nodes from JSON-LD graphs and item lists."""
        jobs: list[dict[str, Any]] = []
        fingerprints: set[tuple[str, str]] = set()

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                node_type = value.get("@type")
                types = node_type if isinstance(node_type, list) else [node_type]
                if "JobPosting" in types:
                    fingerprint = (
                        str(value.get("identifier") or value.get("@id") or ""),
                        str(value.get("url") or value.get("title") or ""),
                    )
                    if fingerprint not in fingerprints:
                        fingerprints.add(fingerprint)
                        jobs.append(value)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        for script in soup.select('script[type="application/ld+json"]'):
            try:
                walk(json.loads(script.string or script.get_text()))
            except (TypeError, json.JSONDecodeError):
                continue
        return jobs

    def _extract_job_cards(self, soup: BeautifulSoup) -> list[Any]:
        """Extract rendered cards, deduplicated across desktop/mobile markup."""
        cards = list(soup.select("[data-job-id]"))
        if cards:
            return cards

        cards = []
        seen_urls: set[str] = set()
        for link in soup.select('a[href*="/job-mission/"]'):
            href = str(link.get("href") or "")
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)

            card = link.find_parent(["article", "li"])
            if card is None:
                card = link.find_parent("div", class_="mb-4")
            if card is None:
                card = link.find_parent(
                    "div", class_=lambda classes: classes and "shadow" in classes
                )
            cards.append(card or link.parent)
        return cards

    def _parse_job_card(self, card: Any) -> Optional[JobOffer]:
        """Normalize a structured job object or rendered HTML job card."""
        try:
            if isinstance(card, dict):
                values = self._structured_values(card)
            else:
                values = self._html_values(card)

            raw_url = str(values.get("url") or "").strip()
            title = str(values.get("title") or "").strip()
            if not raw_url or not title:
                return None

            url = urljoin(self.base_url, raw_url)
            external_id = self._external_id(values.get("id"), url)
            if not external_id:
                return None

            company = str(values.get("company") or "").strip() or "Non spécifié"
            location = str(values.get("location") or "").strip() or "France"
            contract_type = self._map_contract_type(values.get("contract"))
            posted_at = self._parse_posted_date(values.get("posted_at"))

            job = JobOffer(
                id=f"freework_{external_id}",
                source=self.name,
                url=url,
                title=title,
                company=company,
                location=location,
                contract_type=contract_type,
                posted_at=posted_at,
            )
            if self._canonical_external_id(url) == external_id:
                self._canonical_urls[external_id] = url
            return job
        except (AttributeError, TypeError, ValueError) as exc:
            logger.debug(f"Carte Free-Work ignorée: {exc}")
            return None

    def _structured_values(self, item: dict[str, Any]) -> dict[str, Any]:
        identifier = item.get("id") or item.get("jobId") or item.get("identifier")
        if isinstance(identifier, dict):
            identifier = identifier.get("value") or identifier.get("@id")

        company = (
            item.get("company")
            or item.get("hiringOrganization")
            or item.get("organization")
        )
        if isinstance(company, dict):
            company = company.get("name") or company.get("label")

        location = item.get("location") or item.get("jobLocation")
        if isinstance(location, list):
            location = location[0] if location else None
        location = self._structured_location(location)

        return {
            "id": identifier or item.get("@id"),
            "url": item.get("url")
            or item.get("href")
            or item.get("path")
            or item.get("@id"),
            "title": item.get("title") or item.get("name"),
            "company": company,
            "location": location,
            "contract": (
                item.get("employmentType")
                or item.get("contractType")
                or item.get("contract")
                or item.get("type")
            ),
            "posted_at": (
                item.get("datePosted")
                or item.get("publishedAt")
                or item.get("publicationDate")
                or item.get("createdAt")
            ),
        }

    def _structured_location(self, location: Any) -> Optional[str]:
        if isinstance(location, str):
            return location
        if not isinstance(location, dict):
            return None

        for key in ("label", "shortLabel", "name", "addressLocality"):
            if location.get(key):
                return str(location[key])

        address = location.get("address")
        if isinstance(address, str):
            return address
        if isinstance(address, dict):
            parts = [
                address.get("postalCode"),
                address.get("addressLocality"),
                address.get("addressRegion"),
            ]
            rendered = ", ".join(str(part) for part in parts if part)
            return rendered or None
        return None

    def _html_values(self, card: Any) -> dict[str, Any]:
        link = card.select_one('a[href*="/job-mission/"]')
        title_element = link or card.select_one("h2, h3")
        company_element = card.select_one(
            "[data-company], .job-company, .company, .font-bold"
        )
        location_element = card.select_one("[data-location], .job-location, .location")
        time_element = card.select_one("time")
        contract_element = card.select_one(
            "[data-contract], .job-contract, .contract, span.tag"
        )

        external_id = card.get("data-job-id") or card.get("data-id")
        if not external_id:
            tagged = card.select_one('[id^="tags-"]')
            external_id = tagged.get("id") if tagged else None

        location = (
            location_element.get_text(" ", strip=True) if location_element else None
        )
        if not location:
            location = self._labelled_value(card, "lieu")

        contract = card.get("data-contract")
        if not contract and contract_element is not None:
            contract = contract_element.get_text(" ", strip=True)

        posted_at = None
        if time_element is not None:
            posted_at = time_element.get("datetime") or time_element.get_text(
                strip=True
            )

        return {
            "id": external_id,
            "url": link.get("href") if link else None,
            "title": title_element.get_text(" ", strip=True) if title_element else None,
            "company": (
                company_element.get("data-company")
                or company_element.get_text(" ", strip=True)
                if company_element
                else None
            ),
            "location": location,
            "contract": contract,
            "posted_at": posted_at,
        }

    @staticmethod
    def _labelled_value(card: Any, label: str) -> Optional[str]:
        for element in card.find_all(string=True):
            if element.strip().casefold() != label.casefold():
                continue
            container = element.parent.parent if element.parent else None
            if container is None:
                continue
            spans = container.find_all("span")
            if spans:
                value = spans[-1].get_text(" ", strip=True)
                if value and value.casefold() != label.casefold():
                    return value
        return None

    @staticmethod
    def _external_id(value: Any, url: str) -> Optional[str]:
        if value is not None:
            rendered = str(value).strip()
            tagged_match = re.fullmatch(r"tags-(.+)", rendered)
            if tagged_match:
                rendered = tagged_match.group(1)
            if rendered.startswith("freework_"):
                rendered = rendered.removeprefix("freework_")
            if "/" not in rendered and rendered:
                return rendered

        path = urlparse(url).path.rstrip("/")
        return path.rsplit("/", 1)[-1] if path else None

    def _parse_posted_date(self, value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not value.strip():
            return None

        rendered = value.strip()
        try:
            return datetime.fromisoformat(rendered.replace("Z", "+00:00"))
        except ValueError:
            pass

        for date_format in ("%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(rendered, date_format)
            except ValueError:
                continue
        return None

    def _map_contract_type(self, value: Any) -> Optional[ContractType]:
        if isinstance(value, list):
            value = " ".join(str(part) for part in value)
        if not value:
            return None

        normalized = slugify(str(value)).replace("-", " ")
        mappings = (
            (("freelance", "independant", "mission"), ContractType.FREELANCE),
            (("alternance", "apprentissage"), ContractType.ALTERNANCE),
            (("interim", "temporaire"), ContractType.INTERIM),
            (("stage", "internship"), ContractType.STAGE),
            (("cdd",), ContractType.CDD),
            (("cdi",), ContractType.CDI),
        )
        for labels, contract_type in mappings:
            if any(
                re.search(rf"\b{re.escape(label)}\b", normalized) for label in labels
            ):
                return contract_type
        return None

    def _matches_criteria(self, job: JobOffer, criteria: SearchCriteria) -> bool:
        """Apply criteria that the public Free-Work URL cannot represent."""
        if criteria.contract_types and job.contract_type not in criteria.contract_types:
            return False

        if (
            criteria.radius_km
            and criteria.location
            and criteria.location.casefold() != "france"
        ):
            origin = self._resolve_local_coordinates(criteria.location)
            destination = self._resolve_local_coordinates(job.location)
            if origin is None or destination is None:
                return False
            if self._haversine_km(origin, destination) > criteria.radius_km:
                return False

        maximum_age = {
            DatePosted.PAST_24H: timedelta(hours=24),
            DatePosted.PAST_WEEK: timedelta(days=7),
            DatePosted.PAST_MONTH: timedelta(days=30),
        }.get(criteria.date_posted)
        if maximum_age is None and criteria.posted_within_days:
            maximum_age = timedelta(days=criteria.posted_within_days)
        if maximum_age is not None:
            if job.posted_at is None:
                return False
            now = datetime.now(job.posted_at.tzinfo)
            if job.posted_at < now - maximum_age:
                return False

        return True

    @staticmethod
    def _resolve_local_coordinates(location: str) -> Optional[tuple[float, float]]:
        """Resolve a French city from the bounded local coordinate table."""
        normalized_location = slugify(location)
        if not normalized_location:
            return None
        for city, coordinates in geocoding.FRENCH_CITIES.items():
            normalized_city = slugify(city)
            if re.search(
                rf"(?<![a-z0-9]){re.escape(normalized_city)}(?![a-z0-9])",
                normalized_location,
            ):
                return coordinates
        return None

    @staticmethod
    def _haversine_km(
        origin: tuple[float, float], destination: tuple[float, float]
    ) -> float:
        """Return great-circle distance in kilometres between two coordinates."""
        origin_lat, origin_lon = (radians(value) for value in origin)
        destination_lat, destination_lon = (radians(value) for value in destination)
        latitude_delta = destination_lat - origin_lat
        longitude_delta = destination_lon - origin_lon
        haversine = sin(latitude_delta / 2) ** 2 + (
            cos(origin_lat) * cos(destination_lat) * sin(longitude_delta / 2) ** 2
        )
        return 2 * 6371.0088 * atan2(sqrt(haversine), sqrt(1 - haversine))
