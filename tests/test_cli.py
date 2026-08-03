import pytest
from click.testing import CliRunner

import jobscraper.cli as cli_module
import jobscraper.scrapers as scrapers
from jobscraper.cli import main
from jobscraper.config import Config
from jobscraper.models.job import JobOffer
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
    assert result.exit_code == 0
    assert "Invalid value for '--source'" not in result.output


def test_cli_details_enriches_freework_from_stored_url(runner, monkeypatch):
    canonical_url = (
        "https://www.free-work.com/fr/tech-it/job-mission/"
        "developpeur-python/developpeur-python-exemple"
    )
    search_job = JobOffer(
        id="freework_659066",
        source="freework",
        url=canonical_url,
        title="Développeur Python",
        company="Entreprise Exemple",
        location="Paris",
    )
    detail_calls = []
    displayed_jobs = []

    monkeypatch.setattr(
        FreeWorkScraper,
        "search",
        lambda _scraper, _criteria: iter((search_job,)),
    )

    def get_job_details(_scraper, job_url):
        detail_calls.append(job_url)
        return search_job.model_copy(
            update={
                "id": "freework_developpeur-python-exemple",
                "description": "Détails complets",
            }
        )

    monkeypatch.setattr(FreeWorkScraper, "get_job_details", get_job_details)
    monkeypatch.setattr(
        cli_module,
        "display_jobs_table",
        lambda jobs: displayed_jobs.extend(jobs),
    )

    result = runner.invoke(
        main,
        ["search", "-k", "python", "-s", "freework", "-n", "1", "--details"],
    )

    assert result.exit_code == 0
    assert detail_calls == [canonical_url]
    assert [job.id for job in displayed_jobs] == ["freework_659066"]
    assert displayed_jobs[0].description == "Détails complets"


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
