import pytest
from click.testing import CliRunner

import jobscraper.cli as cli_module
import jobscraper.scrapers as scrapers
from jobscraper.cli import main
from jobscraper.config import Config
from jobscraper.scrapers.freework import FreeWorkScraper


@pytest.fixture
def runner(monkeypatch):
    def empty_search(_scraper, _criteria):
        return iter(())

    for scraper_class in (
        "LinkedInScraper",
        "HelloWorkScraper",
        "FranceTravailScraper",
        "AdzunaScraper",
        "WTTJScraper",
    ):
        monkeypatch.setattr(getattr(cli_module, scraper_class), "search", empty_search)
    monkeypatch.setattr(FreeWorkScraper, "search", empty_search)
    return CliRunner()


def test_cli_accepts_freework_source(runner):
    result = runner.invoke(
        main, ["search", "-k", "python", "-s", "freework", "-n", "1"]
    )
    assert "Invalid value for '--source'" not in result.output


def test_cli_default_and_all_sources_include_freework(runner):
    default_result = runner.invoke(main, ["search", "-k", "python", "-n", "1"])
    all_result = runner.invoke(main, ["search", "-k", "python", "-s", "all", "-n", "1"])

    assert "freework" in default_result.output
    assert "freework" in all_result.output


def test_sources_command_lists_freework(runner):
    result = runner.invoke(main, ["sources"])

    assert "Free-Work" in result.output


def test_config_reads_freework_environment(monkeypatch):
    monkeypatch.setenv("FREEWORK_ENABLED", "false")
    monkeypatch.setenv("FREEWORK_DELAY", "1.25")

    config = Config.from_env()

    assert config.freework.enabled is False
    assert config.freework.delay_between_requests == 1.25


def test_scraper_package_exports_freework():
    assert scrapers.FreeWorkScraper is FreeWorkScraper
