"""Construction registry for the supported job-source adapters."""

from collections.abc import Mapping
from typing import Any

from jobscraper.config import Config, get_config
from jobscraper.scrapers.adzuna import AdzunaScraper
from jobscraper.scrapers.base import BaseScraper
from jobscraper.scrapers.francetravail import FranceTravailScraper
from jobscraper.scrapers.freework import FreeWorkScraper
from jobscraper.scrapers.hellowork import HelloWorkScraper
from jobscraper.scrapers.linkedin import LinkedInScraper
from jobscraper.scrapers.wttj import WTTJScraper


class ScraperRegistry:
    """Create a fresh scraper instance for each supported source."""

    scraper_types: Mapping[str, type[BaseScraper]] = {
        "linkedin": LinkedInScraper,
        "hellowork": HelloWorkScraper,
        "francetravail": FranceTravailScraper,
        "wttj": WTTJScraper,
        "adzuna": AdzunaScraper,
        "freework": FreeWorkScraper,
    }

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or get_config()

    def create(self, source: str) -> BaseScraper:
        """Return a configured scraper, rejecting unknown source identifiers."""

        scraper_type = self.scraper_types.get(source)
        if scraper_type is None:
            raise ValueError(f"Source de scraping inconnue: {source}")
        return scraper_type(self._source_config(source))

    def _source_config(self, source: str) -> dict[str, Any]:
        configured = getattr(self.config, source, None)
        if configured is None:
            values: dict[str, Any] = {}
        else:
            values = configured.model_dump()
            delay = values.pop("delay_between_requests", None)
            if delay is not None:
                values["delay"] = delay
        # Standalone CLI adapters remain backward compatible, while registry
        # instances surface operational failures to SyncService's source boundary.
        values["propagate_search_errors"] = True
        return values
