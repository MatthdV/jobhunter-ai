#!/usr/bin/env python3
"""JobHunter AI — Semi-autonomous job search CLI."""


from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(
    name="jobhunter",
    help="Semi-autonomous job search automation for Matthieu de Villele.",
    add_completion=False,
)
console = Console()


@app.command()
def scan(
    sources: list[str] = typer.Option(  # noqa: B008
        ["linkedin", "indeed", "wttj"],
        "--source", "-s",
        help="Job boards to scrape.",
    ),
    limit: int = typer.Option(50, "--limit", "-l", help="Max offers per source."),
) -> None:
    """Scrape job boards across configured countries and store new offers."""
    import asyncio
    import importlib

    import yaml

    from src.config.settings import settings  # noqa: F401 — loads .env
    from src.scrapers.filters import ScraperFilters
    from src.storage.database import get_session
    from src.storage.models import Job
    from src.utils.salary_normalizer import get_supported_countries

    profile_path = Path(__file__).parent / "config" / "profile.yaml"
    with profile_path.open() as fh:
        profile = yaml.safe_load(fh)

    search_cfg = profile.get("search", {})
    countries = search_cfg.get("countries", ["FR"])
    location = search_cfg.get("location", "remote")
    keywords = profile.get("search_keywords", ["automation", "n8n", "RevOps"])

    console.print(
        f"[bold]Scanning[/bold] {sources} × {len(countries)} countries "
        f"(limit={limit} per source per country)…"
    )

    _scraper_map = {
        "wttj": "src.scrapers.wttj.WTTJScraper",
        "indeed": "src.scrapers.indeed.IndeedScraper",
        "indeed_api": "src.scrapers.indeed_api.IndeedApiScraper",
        "linkedin": "src.scrapers.linkedin.LinkedInScraper",
    }

    async def _run() -> int:
        with get_session() as session:
            existing_urls: set[str] = {u for (u,) in session.query(Job.url).all()}

        total = 0
        for source in sources:
            if source not in _scraper_map:
                console.print(f"[yellow]Unknown source: {source}[/yellow]")
                continue

            module_path, _, class_name = _scraper_map[source].rpartition(".")
            mod = importlib.import_module(module_path)
            scraper_cls = getattr(mod, class_name)
            supported = get_supported_countries(source)
            filters = ScraperFilters(remote_only=False)

            for country in countries:
                if supported and country not in supported:
                    console.print(
                        f"  [yellow]{source} doesn't support {country}, skipping[/yellow]"
                    )
                    continue
                try:
                    async with scraper_cls() as scraper:
                        jobs = await scraper.search(
                            keywords=keywords,
                            location=location,
                            filters=filters,
                            limit=limit,
                            seen_urls=existing_urls,
                            country_code=country,
                        )
                except Exception as exc:
                    console.print(f"[red]{source}/{country} error:[/red] {exc}")
                    continue

                fresh = [j for j in jobs if j.url not in existing_urls]
                if fresh:
                    with get_session() as session:
                        for job in fresh:
                            session.add(job)
                            existing_urls.add(job.url)
                    total += len(fresh)
                    console.print(
                        f"  [green]{source}/{country}[/green]: {len(fresh)} new jobs"
                    )
                else:
                    console.print(f"  {source}/{country}: 0 new (all duplicates)")
        return total

    total = asyncio.run(_run())
    console.print(
        f"[bold green]Done.[/bold green] {total} new job(s) across "
        f"{len(countries)} countries."
    )


@app.command()
def match(
    min_score: int = typer.Option(80, "--min-score", help="Minimum match score (0–100)."),
) -> None:
    """Score all NEW jobs against the candidate profile using Claude."""
    import asyncio

    from src.matching.scorer import Scorer
    from src.storage.database import get_session
    from src.storage.models import Job, JobStatus

    console.print(f"[bold]Matching[/bold] NEW jobs (min_score={min_score})…")

    async def _run() -> tuple[int, int]:
        scorer = Scorer()
        with get_session() as session:
            new_jobs = session.query(Job).filter(Job.status == JobStatus.NEW).all()
            if not new_jobs:
                return 0, 0
            console.print(f"  Scoring {len(new_jobs)} job(s)…")
            results = await scorer.score_batch(new_jobs, session)
            matched = sum(1 for j in new_jobs if j.status == JobStatus.MATCHED)
        return len(results), matched

    total, matched = asyncio.run(_run())
    console.print(
        f"[bold green]Done.[/bold green] {total} scored, {matched} matched (≥{min_score})."
    )


@app.command()
def apply(
    job_id: int | None = typer.Argument(None, help="Job ID to apply to (omit = all MATCHED)."),
    dry_run: bool = typer.Option(True, "--dry-run/--live", help="Preview without submitting."),
) -> None:
    """Generate CV + cover letter and submit application after human validation.

    Always requires explicit human approval before submission.
    """
    import asyncio
    from datetime import date, datetime
    from datetime import time as _time

    from src.config.settings import settings
    from src.generators.cover_letter import CoverLetterGenerator
    from src.generators.cv_generator import CVGenerator
    from src.storage.database import get_session
    from src.storage.models import Application, ApplicationStatus, Job, JobStatus

    mode = "[yellow]DRY RUN[/yellow]" if dry_run else "[red]LIVE[/red]"
    target = f"job #{job_id}" if job_id else "all MATCHED jobs"
    console.print(f"[bold]Applying[/bold] to {target} ({mode})…")

    cv_gen = CVGenerator()
    cl_gen = CoverLetterGenerator()

    output_dir = Path("data") / "cvs"
    output_dir.mkdir(parents=True, exist_ok=True)

    with get_session() as session:
        query = session.query(Job).filter(Job.status == JobStatus.MATCHED)
        if job_id is not None:
            query = query.filter(Job.id == job_id)
        jobs = query.all()

        # Slice 15 — daily cap: count today's submitted applications
        today_start = datetime.combine(date.today(), _time.min)
        today_count = (
            session.query(Application)
            .filter(
                Application.created_at >= today_start,
                Application.status == ApplicationStatus.SUBMITTED,
            )
            .count()
        )
        remaining = max(0, settings.max_applications_per_day - today_count)

        # Skip jobs that already have an application
        eligible = [j for j in jobs if j.application is None][:remaining]

        if not eligible:
            console.print("No eligible jobs to process.")
            return

        async def _run() -> list[tuple[Path, str]]:
            results: list[tuple[Path, str]] = []
            for job in eligible:
                cv_path = await cv_gen.generate(job, output_dir)
                letter = await cl_gen.generate(job)
                results.append((cv_path, letter))
            return results

        generated = asyncio.run(_run())

        for job, (cv_path, letter) in zip(eligible, generated, strict=False):
            app_record = Application(
                job_id=job.id,
                cv_path=str(cv_path),
                cover_letter=letter,
                status=ApplicationStatus.DRAFT,
            )
            session.add(app_record)

        count = len(generated)

    console.print(f"[green]Done.[/green] {count} application(s) created.")


@app.command()
def status() -> None:
    """Show pipeline summary: scraped / matched / applied / replied / interviews."""
    raise NotImplementedError("Phase 2 — status dashboard not yet implemented")


@app.command("init-db")
def init_db_cmd() -> None:
    """Initialise the database schema (run once on fresh install)."""
    from src.storage.database import health_check, init_db

    init_db()
    ok = health_check()
    if ok:
        console.print("[green]Database initialised and reachable.[/green]")
    else:
        console.print("[red]Database initialised but health check failed.[/red]")
        raise typer.Exit(code=1)


@app.command("import-linkedin")
def import_linkedin(
    zip_path: Path = typer.Argument(..., help="Path to the LinkedIn data export ZIP."),  # noqa: B008
) -> None:
    """Bootstrap profile.yaml with experience data from a LinkedIn export ZIP."""
    from src.config.settings import settings  # noqa: F401 — ensures .env loaded
    from src.importers.linkedin_importer import LinkedInImporter

    profile_path = Path(__file__).parent / "config" / "profile.yaml"
    console.print(f"[bold]Importing[/bold] LinkedIn data from {zip_path}…")
    try:
        LinkedInImporter().import_zip(zip_path, profile_path)
        console.print("[green]Done.[/green] profile.yaml updated.")
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc


@app.command("run-once")
def run_once_cmd() -> None:
    """Execute a single full pipeline cycle (scan → match → apply → respond)."""
    import asyncio

    from src.scheduler.job_scheduler import JobScheduler

    console.print("[bold]Running[/bold] pipeline (single cycle)…")
    scheduler = JobScheduler()
    asyncio.run(scheduler.run_once())
    console.print("[green]Done.[/green]")


@app.command("run-loop")
def run_loop_cmd(
    interval: int = typer.Option(3600, "--interval", "-i", help="Seconds between cycles."),
) -> None:
    """Run the pipeline on a recurring schedule (Ctrl+C to stop)."""
    import asyncio

    from src.scheduler.job_scheduler import JobScheduler

    console.print(f"[bold]Starting[/bold] pipeline loop (interval={interval}s)…")
    scheduler = JobScheduler()
    try:
        asyncio.run(scheduler.run_loop(interval=interval))
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/yellow]")


if __name__ == "__main__":
    app()
