"""Scrapers pour les différents sites d'emploi."""

from jobscraper.scrapers.base import AsyncBaseScraper, BaseScraper
from jobscraper.scrapers.francetravail import FranceTravailScraper
from jobscraper.scrapers.hellowork import HelloWorkScraper
from jobscraper.scrapers.linkedin import LinkedInScraper
from jobscraper.scrapers.wttj import WTTJScraper

__all__ = [
    "AsyncBaseScraper",
    "BaseScraper",
    "FranceTravailScraper",
    "HelloWorkScraper",
    "LinkedInScraper",
    "WTTJScraper",
]
