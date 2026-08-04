"""Interface en ligne de commande pour JobScraper."""

import json
import os
import socket
import sys
import webbrowser
from datetime import datetime
from functools import partial
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from typing import List, Optional
from zoneinfo import ZoneInfo

import click
import uvicorn
from loguru import logger
from rich.console import Console
from rich.table import Table

from jobscraper.api.app import DEFAULT_FRONTEND_DIST, create_app
from jobscraper.automation.launchd import (
    AutomationError,
    get_launch_agent_status,
    install_launch_agent,
    installed_launch_agent_path,
    read_launch_agent_schedule,
    uninstall_launch_agent,
)
from jobscraper.config import get_config
from jobscraper.models.job import (
    ContractType,
    DatePosted,
    ExperienceLevel,
    SearchCriteria,
    SortBy,
    WorkplaceType,
)
from jobscraper.runtime import (
    DEFAULT_DATABASE_URL,
    RuntimeServices,
    SessionServices,
    build_runtime,
)
from jobscraper.scrapers.adzuna import AdzunaScraper
from jobscraper.scrapers.francetravail import FranceTravailScraper
from jobscraper.scrapers.freework import FreeWorkScraper
from jobscraper.scrapers.hellowork import HelloWorkScraper
from jobscraper.scrapers.linkedin import LinkedInScraper
from jobscraper.scrapers.wttj import WTTJScraper
from jobscraper.services.catchup import CatchupService, resolve_local_timezone

console = Console()

SUPPORTED_SOURCES = (
    "linkedin",
    "hellowork",
    "francetravail",
    "adzuna",
    "wttj",
    "freework",
)


def setup_logging(verbose: bool) -> None:
    """Configure le logging."""
    import sys

    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, level=level)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Mode verbose")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    """JobScraper - Outil de scraping d'offres d'emploi."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    setup_logging(verbose)


@main.group()
def automation() -> None:
    """Gère la synchronisation quotidienne avec launchd sur macOS."""


@automation.command("install")
@click.option("--hour", type=click.IntRange(0, 23), default=8, show_default=True)
@click.option("--minute", type=click.IntRange(0, 59), default=0, show_default=True)
def automation_install(hour: int, minute: int) -> None:
    """Installe ou met à jour l’automatisation quotidienne."""

    try:
        install_launch_agent(Path.cwd(), Path(sys.executable), hour=hour, minute=minute)
    except (AutomationError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Automatisation quotidienne installée à {hour:02d}:{minute:02d}.")


@automation.command("status")
def automation_status() -> None:
    """Affiche l’état de l’automatisation quotidienne."""

    try:
        status = get_launch_agent_status()
    except AutomationError as exc:
        raise click.ClickException(str(exc)) from exc
    schedule = (
        f" Planification : {status.schedule[0]:02d}:{status.schedule[1]:02d}."
        if status.schedule is not None
        else ""
    )
    if status.loaded:
        state = f" (état launchd : {status.state})" if status.state else ""
        click.echo(f"Automatisation active{state}.{schedule}")
    elif status.plist_exists:
        click.echo(f"Automatisation installée mais inactive.{schedule}")
    else:
        click.echo("Automatisation non installée.")


@automation.command("uninstall")
def automation_uninstall() -> None:
    """Désactive puis supprime l’automatisation quotidienne."""

    try:
        removed = uninstall_launch_agent()
    except AutomationError as exc:
        raise click.ClickException(str(exc)) from exc
    if removed:
        click.echo("Automatisation désinstallée.")
    else:
        click.echo("Automatisation déjà absente.")


def _read_launch_agent_schedule(plist_path: Path | None = None) -> tuple[int, int]:
    """Read the installed schedule, defaulting only when no plist exists."""

    try:
        resolved_path = plist_path or installed_launch_agent_path()
    except AutomationError as exc:
        raise click.ClickException(
            "Impossible de valider le plist launchd utilisateur. Réinstallez-le avec "
            "`jobscraper automation install --hour 8 --minute 0`."
        ) from exc
    try:
        resolved_path.stat()
    except FileNotFoundError:
        return 8, 0
    except OSError as exc:
        raise click.ClickException(
            "Impossible d’accéder au plist launchd. Vérifiez ses permissions ou "
            "réinstallez-le avec `jobscraper automation install --hour 8 --minute 0`."
        ) from exc
    try:
        return read_launch_agent_schedule(resolved_path)
    except (OSError, ValueError) as exc:
        raise click.ClickException(
            "Le plist launchd est illisible ou corrompu. Réinstallez-le avec "
            "`jobscraper automation install --hour 8 --minute 0`."
        ) from exc


def _validate_frontend_build(frontend_dist: Path) -> Path:
    """Require the Vite index and at least one generated asset."""

    resolved_dist = frontend_dist.resolve()
    try:
        index_valid = (resolved_dist / "index.html").is_file()
        assets = resolved_dist / "assets"
        assets_valid = assets.is_dir() and any(
            candidate.is_file() for candidate in assets.rglob("*")
        )
    except OSError:
        index_valid = False
        assets_valid = False
    if not index_valid or not assets_valid:
        raise click.ClickException(
            "Le build frontend est absent ou incomplet. Lancez "
            "`cd frontend && pnpm build`, puis relancez `jobscraper serve`."
        )
    return resolved_dist


def _local_now(local_timezone: ZoneInfo) -> datetime:
    return datetime.now(local_timezone)


def _run_startup_catchup(
    runtime: RuntimeServices,
    local_timezone: ZoneInfo,
    scheduled_hour: int,
    scheduled_minute: int,
) -> bool:
    """Evaluate and run catch-up inside the application-owned executor."""

    service = CatchupService()
    now = _local_now(local_timezone)
    if not service.is_due(
        now,
        None,
        scheduled_hour=scheduled_hour,
        scheduled_minute=scheduled_minute,
    ):
        return False
    return service.run_if_due(
        runtime,
        now=now,
        scheduled_hour=scheduled_hour,
        scheduled_minute=scheduled_minute,
    )


def _wait_until_reachable(host: str, port: int, cancelled: Event) -> bool:
    """Wait a bounded amount of time for the local HTTP socket."""

    deadline = monotonic() + 30.0
    while not cancelled.is_set() and monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return not cancelled.is_set()
        except OSError:
            cancelled.wait(0.1)
    return False


def _open_browser_when_ready(url: str, host: str, port: int, cancelled: Event) -> None:
    try:
        if _wait_until_reachable(host, port, cancelled):
            webbrowser.open(url)
    except Exception:
        logger.exception("Impossible d’ouvrir automatiquement le navigateur")


def _browser_host(bind_host: str) -> str:
    if bind_host == "0.0.0.0":
        return "127.0.0.1"
    if bind_host == "::":
        return "::1"
    return bind_host


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", type=click.IntRange(1, 65535), default=8000, show_default=True)
@click.option("--no-open", is_flag=True, help="Ne pas ouvrir le navigateur.")
@click.pass_context
def serve(ctx: click.Context, host: str, port: int, no_open: bool) -> None:
    """Prépare la base puis démarre l’interface web locale."""

    frontend_dist = _validate_frontend_build(DEFAULT_FRONTEND_DIST)
    scheduled_hour, scheduled_minute = _read_launch_agent_schedule()
    try:
        local_timezone = resolve_local_timezone()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    injected_runtime = ctx.obj.get("runtime") if ctx.obj else None
    runtime = injected_runtime or build_runtime(
        os.getenv("JOBSCRAPER_DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    browser_cancelled = Event()
    browser_thread: Thread | None = None
    primary_error: BaseException | None = None
    try:
        try:
            runtime.migrate()
        except Exception as exc:
            raise click.ClickException(
                "La migration de la base a échoué. Vérifiez la configuration puis "
                "lancez `alembic upgrade head` avant de réessayer."
            ) from exc

        startup_task = partial(
            _run_startup_catchup,
            runtime,
            local_timezone,
            scheduled_hour,
            scheduled_minute,
        )
        app = create_app(
            frontend_dist=frontend_dist,
            runtime=runtime,
            startup_task=startup_task,
        )

        if not no_open:
            browser_host = _browser_host(host)
            rendered_host = f"[{browser_host}]" if ":" in browser_host else browser_host
            url = f"http://{rendered_host}:{port}"
            browser_thread = Thread(
                target=_open_browser_when_ready,
                args=(url, browser_host, port, browser_cancelled),
                name="jobscraper-browser",
                daemon=True,
            )
            browser_thread.start()

        uvicorn.run(app, host=host, port=port)
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        browser_cancelled.set()
        if browser_thread is not None:
            browser_thread.join(timeout=1.0)
        try:
            runtime.close()
        except Exception as exc:
            if primary_error is not None:
                logger.error(
                    "Échec secondaire pendant la fermeture des ressources JobScraper"
                )
            else:
                raise click.ClickException(
                    "Impossible de fermer correctement les ressources JobScraper. "
                    "Redémarrez l’application avant de réessayer."
                ) from exc


@main.command()
@click.option("--keywords", "-k", multiple=True, help="Mots-clés de recherche")
@click.option("--title", "-t", help="Titre de poste exact (recherche précise)")
@click.option(
    "--location", "-l", default="France", help="Localisation (ville, région, pays)"
)
@click.option(
    "--radius",
    "-r",
    type=click.Choice(["5", "10", "25", "50", "100"]),
    help="Rayon de recherche en km",
)
@click.option(
    "--contract",
    "-c",
    multiple=True,
    type=click.Choice(["cdi", "cdd", "stage", "alternance", "interim", "freelance"]),
    help="Type de contrat",
)
@click.option(
    "--experience",
    "-e",
    multiple=True,
    type=click.Choice(["internship", "junior", "mid", "senior", "lead", "director"]),
    help="Niveau d'expérience",
)
@click.option(
    "--workplace",
    "-w",
    multiple=True,
    type=click.Choice(["on_site", "remote", "hybrid"]),
    help="Type de lieu de travail",
)
@click.option(
    "--date",
    type=click.Choice(["past_24h", "past_week", "past_month", "any_time"]),
    default="any_time",
    help="Date de publication",
)
@click.option(
    "--sort",
    type=click.Choice(["relevance", "date"]),
    default="relevance",
    help="Tri des résultats",
)
@click.option("--company", multiple=True, help="Entreprises spécifiques")
@click.option("--max-results", "-n", default=50, help="Nombre maximum de résultats")
@click.option("--output", "-o", type=click.Path(), help="Fichier de sortie")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "csv", "table"]),
    default="table",
)
@click.option("--details", "-d", is_flag=True, help="Récupérer les détails complets")
@click.option(
    "--source",
    "-s",
    multiple=True,
    type=click.Choice(
        ["linkedin", "hellowork", "francetravail", "adzuna", "wttj", "freework", "all"]
    ),
    default=["linkedin", "hellowork", "francetravail", "adzuna", "wttj", "freework"],
    help="Sources: linkedin, hellowork, francetravail, adzuna (Indeed+Monster), wttj, freework, all",
)
@click.pass_context
def search(
    ctx: click.Context,
    keywords: tuple,
    title: Optional[str],
    location: str,
    radius: Optional[str],
    contract: tuple,
    experience: tuple,
    workplace: tuple,
    date: str,
    sort: str,
    company: tuple,
    max_results: int,
    output: Optional[str],
    output_format: str,
    details: bool,
    source: tuple,
) -> None:
    """
    Recherche des offres d'emploi sur plusieurs sources.

    Exemples:

      # Recherche LinkedIn (défaut)
      jobscraper search -k python -l Paris

      # Recherche WTTJ uniquement
      jobscraper search -k python -l Paris -s wttj

      # Recherche sur toutes les sources
      jobscraper search -k python -l Paris -s all

      # Recherche CDI senior en remote
      jobscraper search -k "data engineer" -c cdi -e senior -w remote

      # Export JSON avec détails
      jobscraper search -k python -n 100 --details -o jobs.json
    """
    config = get_config()

    # Construire les critères de recherche
    criteria = SearchCriteria(
        keywords=list(keywords) if keywords else [],
        title=title,
        location=location,
        radius_km=int(radius) if radius else None,
        contract_types=[ContractType(c) for c in contract] if contract else [],
        experience_levels=(
            [ExperienceLevel(e) for e in experience] if experience else []
        ),
        workplace_types=[WorkplaceType(w) for w in workplace] if workplace else [],
        date_posted=DatePosted(date) if date else None,
        sort_by=SortBy(sort),
        companies=list(company) if company else [],
        max_results=max_results,
    )

    # Affichage des critères
    console.print(f"[bold blue]Recherche d'offres d'emploi...[/bold blue]")
    if criteria.title:
        console.print(f'Titre: "{criteria.title}"')
    if criteria.keywords:
        console.print(f"Mots-clés: {', '.join(criteria.keywords)}")
    console.print(f"Localisation: {criteria.location}")
    if criteria.radius_km:
        console.print(f"Rayon: {criteria.radius_km} km")
    if criteria.contract_types:
        console.print(f"Contrat: {', '.join(c.value for c in criteria.contract_types)}")
    if criteria.experience_levels:
        console.print(
            f"Expérience: {', '.join(e.value for e in criteria.experience_levels)}"
        )
    if criteria.workplace_types:
        console.print(f"Lieu: {', '.join(w.value for w in criteria.workplace_types)}")
    if criteria.date_posted and criteria.date_posted != DatePosted.ANY_TIME:
        console.print(f"Date: {criteria.date_posted.value}")
    if criteria.sort_by == SortBy.DATE:
        console.print("Tri: Plus récent")
    if details:
        console.print("[dim]Mode détaillé activé[/dim]")

    # Déterminer les sources à utiliser
    sources_to_use = set(source)
    if "all" in sources_to_use:
        sources_to_use = {
            "linkedin",
            "hellowork",
            "francetravail",
            "adzuna",
            "wttj",
            "freework",
        }
    console.print(f"Sources: {', '.join(sources_to_use)}")

    jobs = []

    # Scraping LinkedIn
    if "linkedin" in sources_to_use:
        with LinkedInScraper(
            {"delay": config.linkedin.delay_between_requests}
        ) as scraper:
            with console.status("[bold green]Scraping LinkedIn...") as status:
                for job in scraper.search(criteria):
                    jobs.append(job)
                    status.update(
                        f"[bold green]LinkedIn... {len(jobs)} offres trouvées"
                    )

            if details and jobs:
                linkedin_jobs = [j for j in jobs if j.source == "linkedin"]
                enriched = []
                with console.status("[bold cyan]Détails LinkedIn...") as status:
                    for i, job in enumerate(linkedin_jobs, 1):
                        status.update(
                            f"[bold cyan]Détails LinkedIn... {i}/{len(linkedin_jobs)}"
                        )
                        job_id = job.id.replace("linkedin_", "")
                        detailed = scraper.get_job_details(job_id)
                        enriched.append(detailed if detailed else job)
                # Remplacer les jobs LinkedIn par les enrichis
                jobs = [j for j in jobs if j.source != "linkedin"] + enriched

    # Scraping HelloWork
    if "hellowork" in sources_to_use:
        with HelloWorkScraper(
            {"delay": config.hellowork.delay_between_requests}
        ) as scraper:
            with console.status("[bold magenta]Scraping HelloWork...") as status:
                initial_count = len(jobs)
                for job in scraper.search(criteria):
                    jobs.append(job)
                    status.update(
                        f"[bold magenta]HelloWork... {len(jobs) - initial_count} offres trouvées"
                    )

    # Scraping France Travail (ex Pôle Emploi)
    if "francetravail" in sources_to_use:
        with FranceTravailScraper(
            {"delay": config.francetravail.delay_between_requests}
        ) as scraper:
            with console.status("[bold blue]Scraping France Travail...") as status:
                initial_count = len(jobs)
                for job in scraper.search(criteria):
                    jobs.append(job)
                    status.update(
                        f"[bold blue]France Travail... {len(jobs) - initial_count} offres trouvées"
                    )

    # Scraping Adzuna (agrégateur: Indeed, Monster, etc.)
    if "adzuna" in sources_to_use:
        import os

        adzuna_config = {
            "app_id": os.getenv("ADZUNA_APP_ID"),
            "app_key": os.getenv("ADZUNA_APP_KEY"),
        }
        with AdzunaScraper(adzuna_config) as scraper:
            with console.status(
                "[bold yellow]Scraping Adzuna (Indeed, Monster...)..."
            ) as status:
                initial_count = len(jobs)
                for job in scraper.search(criteria):
                    jobs.append(job)
                    status.update(
                        f"[bold yellow]Adzuna... {len(jobs) - initial_count} offres trouvées"
                    )

    # Scraping Welcome to the Jungle (WTTJ)
    if "wttj" in sources_to_use:
        with WTTJScraper({"delay": config.wttj.delay_between_requests}) as scraper:
            with console.status(
                "[bold red]Scraping Welcome to the Jungle..."
            ) as status:
                initial_count = len(jobs)
                for job in scraper.search(criteria):
                    jobs.append(job)
                    status.update(
                        f"[bold red]WTTJ... {len(jobs) - initial_count} offres trouvées"
                    )

    # Scraping Free-Work
    if "freework" in sources_to_use:
        with FreeWorkScraper(
            {"delay": config.freework.delay_between_requests}
        ) as scraper:
            with console.status("[bold cyan]Scraping Free-Work...") as status:
                initial_count = len(jobs)
                for job in scraper.search(criteria):
                    jobs.append(job)
                    status.update(
                        f"[bold cyan]Free-Work... {len(jobs) - initial_count} "
                        "offres trouvées"
                    )

            if details:
                freework_jobs = [job for job in jobs if job.source == "freework"]
                enriched = []
                with console.status("[bold cyan]Détails Free-Work...") as status:
                    for index, job in enumerate(freework_jobs, 1):
                        status.update(
                            f"[bold cyan]Détails Free-Work... "
                            f"{index}/{len(freework_jobs)}"
                        )
                        detailed = scraper.get_job_details(str(job.url))
                        enriched.append(
                            detailed.model_copy(update={"id": job.id})
                            if detailed
                            else job
                        )
                jobs = [job for job in jobs if job.source != "freework"] + enriched

    if not jobs:
        console.print("[yellow]Aucune offre trouvée.[/yellow]")
        return

    console.print(f"\n[bold green]{len(jobs)} offres trouvées![/bold green]\n")

    # Affichage selon le format demandé
    if output_format == "table" and not output:
        display_jobs_table(jobs)
    elif output_format == "json" or (output and output.endswith(".json")):
        save_jobs_json(jobs, output)
    elif output_format == "csv" or (output and output.endswith(".csv")):
        save_jobs_csv(jobs, output)
    else:
        display_jobs_table(jobs)


def _sync_status_label(status: str) -> str:
    """Return a compact French label for a durable synchronization status."""

    return {
        "succeeded": "Réussie",
        "partial": "Partielle",
        "failed": "Échouée",
    }.get(status, status)


def _display_sync_results(
    services: SessionServices, search_name: str, run_id: str
) -> str:
    """Render one run's durable per-source results and return its status."""

    run = services.sync_runs.get(run_id)
    if run is None:
        raise RuntimeError("La synchronisation terminée est introuvable.")
    table = Table(title=f"Synchronisation — {search_name}")
    table.add_column("Source", style="cyan")
    table.add_column("Statut")
    table.add_column("Trouvées", justify="right")
    table.add_column("Enregistrées", justify="right")
    table.add_column("Erreur")
    for result in services.sync_runs.source_results(run_id):
        table.add_row(
            result.source,
            _sync_status_label(result.status),
            str(result.offers_seen),
            str(result.offers_persisted),
            result.error_message or "",
        )
    console.print(table)
    return str(run.status)


@main.command("sync-saved-searches")
@click.option(
    "--search-id",
    type=click.UUID,
    help="Identifiant précis d'une recherche enregistrée.",
)
@click.option(
    "--source",
    type=click.Choice(SUPPORTED_SOURCES),
    help="Limiter la synchronisation à une source.",
)
@click.pass_context
def sync_saved_searches(
    ctx: click.Context, search_id: object | None, source: str | None
) -> None:
    """Synchronise les recherches enregistrées sans démarrer l'API."""

    injected_runtime = ctx.obj.get("runtime") if ctx.obj else None
    runtime = injected_runtime or build_runtime(
        os.getenv("JOBSCRAPER_DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    try:
        runtime.migrate()
        with runtime.session_services() as services:
            if search_id is None:
                searches = services.saved_searches.list(active=True)
            else:
                selected = services.saved_searches.get(str(search_id))
                if selected is None:
                    raise click.ClickException(
                        "La recherche enregistrée demandée n’existe pas."
                    )
                if source is not None and source not in selected.sources:
                    raise click.ClickException(
                        f"La source {source} ne fait pas partie de cette recherche."
                    )
                searches = [selected]

            if not searches:
                console.print(
                    "[yellow]Aucune recherche active. "
                    "Activez-en une dans l’interface avant de relancer.[/yellow]"
                )
                return

            if source is not None and search_id is None:
                searches = [search for search in searches if source in search.sources]
                if not searches:
                    raise click.ClickException(
                        f"Aucune recherche active ne configure la source {source}."
                    )

            statuses: list[str] = []
            only_sources = None if source is None else {source}
            for saved_search in searches:
                run_id = services.sync_service.run(
                    saved_search.id, only_sources=only_sources
                )
                statuses.append(
                    _display_sync_results(services, saved_search.name, run_id)
                )

        if all(status == "succeeded" for status in statuses):
            console.print("[bold green]Synchronisation terminée.[/bold green]")
            return
        if all(status == "failed" for status in statuses):
            console.print("[bold red]La synchronisation a échoué.[/bold red]")
            raise click.exceptions.Exit(1)
        console.print(
            "[bold yellow]Synchronisation terminée, mais partielle.[/bold yellow]"
        )
        raise click.exceptions.Exit(2)
    finally:
        runtime.close()


def display_jobs_table(jobs: List) -> None:
    """Affiche les offres dans un tableau."""
    table = Table(title="Offres d'emploi")
    table.add_column("Titre", style="cyan", no_wrap=True)
    table.add_column("Entreprise", style="magenta")
    table.add_column("Localisation", style="green")
    table.add_column("Source")

    for job in jobs[:20]:  # Limiter l'affichage
        table.add_row(
            job.title[:40] + "..." if len(job.title) > 40 else job.title,
            job.company[:25] + "..." if len(job.company) > 25 else job.company,
            job.location[:20] + "..." if len(job.location) > 20 else job.location,
            job.source,
        )

    console.print(table)

    if len(jobs) > 20:
        console.print(f"\n[dim]... et {len(jobs) - 20} autres offres[/dim]")


def save_jobs_json(jobs: List, output: Optional[str]) -> None:
    """Sauvegarde les offres en JSON."""
    data = [job.model_dump(mode="json") for job in jobs]

    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        console.print(f"[green]Offres sauvegardées dans {output}[/green]")
    else:
        console.print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def save_jobs_csv(jobs: List, output: Optional[str]) -> None:
    """Sauvegarde les offres en CSV."""
    import csv
    from io import StringIO

    fieldnames = [
        "id",
        "source",
        "title",
        "company",
        "location",
        "url",
        "contract_type",
        "experience_level",
        "remote",
        "posted_at",
        "description",
    ]

    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for job in jobs:
                writer.writerow({k: getattr(job, k, "") for k in fieldnames})
        console.print(f"[green]Offres sauvegardées dans {output}[/green]")
    else:
        output_buffer = StringIO()
        writer = csv.DictWriter(output_buffer, fieldnames=fieldnames)
        writer.writeheader()
        for job in jobs:
            writer.writerow({k: str(getattr(job, k, "")) for k in fieldnames})
        console.print(output_buffer.getvalue())


@main.command()
def sources() -> None:
    """Liste les sources disponibles."""
    table = Table(title="Sources disponibles")
    table.add_column("Source", style="cyan")
    table.add_column("Statut", style="green")
    table.add_column("Description")

    sources_info = [
        ("LinkedIn", "Actif", "Offres d'emploi LinkedIn"),
        ("HelloWork", "Actif", "Offres d'emploi HelloWork"),
        ("France Travail", "Actif", "Ex Pôle Emploi"),
        ("Adzuna", "Actif*", "Agrégateur (Indeed, Monster) - nécessite clés API"),
        ("Welcome to the Jungle", "Actif", "Startups et scale-ups (via Algolia)"),
        ("Free-Work", "Actif", "Missions freelance et emplois dans la tech"),
        ("Apec", "À venir", "Cadres et jeunes diplômés"),
    ]

    for source, status, description in sources_info:
        table.add_row(source, status, description)

    console.print(table)


if __name__ == "__main__":
    main()
