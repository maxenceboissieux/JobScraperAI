"""Configuration de l'application."""

import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Charger les variables d'environnement
load_dotenv()


class ScraperConfig(BaseModel):
    """Configuration pour un scraper spécifique."""

    enabled: bool = True
    delay_between_requests: float = Field(default=2.0, ge=0.5)
    max_retries: int = Field(default=3, ge=1)
    timeout: int = Field(default=30, ge=5)


class LinkedInConfig(ScraperConfig):
    """Configuration spécifique à LinkedIn."""

    use_selenium: bool = False
    headless: bool = True


class HelloWorkConfig(ScraperConfig):
    """Configuration spécifique à HelloWork."""

    pass  # Utilise les paramètres par défaut de ScraperConfig


class FranceTravailConfig(ScraperConfig):
    """Configuration spécifique à France Travail."""

    pass  # Utilise les paramètres par défaut de ScraperConfig (scraping sans API)


class WTTJConfig(ScraperConfig):
    """Configuration spécifique à Welcome to the Jungle."""

    pass  # Utilise Algolia API publique, pas de config spéciale


class FreeWorkConfig(ScraperConfig):
    """Configuration spécifique à Free-Work."""

    pass


class AdzunaConfig(ScraperConfig):
    """Configuration spécifique à Adzuna."""

    pass


class Config(BaseModel):
    """Configuration globale de l'application."""

    # Répertoire de données
    data_dir: Path = Field(default=Path("./data"))

    # Configuration des scrapers
    linkedin: LinkedInConfig = Field(default_factory=LinkedInConfig)
    hellowork: HelloWorkConfig = Field(default_factory=HelloWorkConfig)
    francetravail: FranceTravailConfig = Field(default_factory=FranceTravailConfig)
    wttj: WTTJConfig = Field(default_factory=WTTJConfig)
    freework: FreeWorkConfig = Field(default_factory=FreeWorkConfig)
    adzuna: AdzunaConfig = Field(default_factory=AdzunaConfig)

    # Configuration globale
    log_level: str = "INFO"
    output_format: str = "json"  # json, csv, sqlite

    # Proxy (optionnel)
    proxy_url: Optional[str] = None

    @classmethod
    def from_env(cls) -> "Config":
        """
        Crée une configuration à partir des variables d'environnement.

        Returns:
            Instance de Config
        """
        return cls(
            data_dir=Path(os.getenv("JOBSCRAPER_DATA_DIR", "./data")),
            log_level=os.getenv("JOBSCRAPER_LOG_LEVEL", "INFO"),
            output_format=os.getenv("JOBSCRAPER_OUTPUT_FORMAT", "json"),
            proxy_url=os.getenv("JOBSCRAPER_PROXY_URL"),
            linkedin=LinkedInConfig(
                enabled=os.getenv("LINKEDIN_ENABLED", "true").lower() == "true",
                delay_between_requests=float(os.getenv("LINKEDIN_DELAY", "2.0")),
                use_selenium=os.getenv("LINKEDIN_USE_SELENIUM", "false").lower()
                == "true",
                headless=os.getenv("LINKEDIN_HEADLESS", "true").lower() == "true",
            ),
            hellowork=HelloWorkConfig(
                enabled=os.getenv("HELLOWORK_ENABLED", "true").lower() == "true",
                delay_between_requests=float(os.getenv("HELLOWORK_DELAY", "2.0")),
            ),
            francetravail=FranceTravailConfig(
                enabled=os.getenv("FRANCE_TRAVAIL_ENABLED", "true").lower() == "true",
                delay_between_requests=float(os.getenv("FRANCE_TRAVAIL_DELAY", "2.0")),
            ),
            wttj=WTTJConfig(
                enabled=os.getenv("WTTJ_ENABLED", "true").lower() == "true",
                delay_between_requests=float(os.getenv("WTTJ_DELAY", "1.0")),
            ),
            freework=FreeWorkConfig(
                enabled=os.getenv("FREEWORK_ENABLED", "true").lower() == "true",
                delay_between_requests=float(os.getenv("FREEWORK_DELAY", "2.0")),
            ),
            adzuna=AdzunaConfig(
                enabled=os.getenv("ADZUNA_ENABLED", "true").lower() == "true",
                delay_between_requests=float(os.getenv("ADZUNA_DELAY", "2.0")),
            ),
        )


# Instance globale de configuration
_config: Optional[Config] = None


def get_config() -> Config:
    """
    Récupère la configuration globale.

    Returns:
        Instance de Config
    """
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config


def set_config(config: Config) -> None:
    """
    Définit la configuration globale.

    Args:
        config: Instance de Config
    """
    global _config
    _config = config
