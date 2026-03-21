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
    """Scrape job boards and store new offers in the database."""
    console.print(f"[bold]Scanning[/bold] {sources} (limit={limit} per source)…")
    raise NotImplementedError("Phase 2 — scraping not yet implemented")


@app.command()
def match(
    min_score: int = typer.Option(80, "--min-score", help="Minimum match score (0–100)."),
) -> None:
    """Score all NEW jobs against the candidate profile using Claude."""
    console.print(f"[bold]Matching[/bold] jobs with min_score={min_score}…")
    raise NotImplementedError("Phase 2 — matching not yet implemented")


@app.command()
def apply(
    job_id: int | None = typer.Argument(None, help="Job ID to apply to (omit = all MATCHED)."),
    dry_run: bool = typer.Option(True, "--dry-run/--live", help="Preview without submitting."),
) -> None:
    """Generate CV + cover letter and submit application after human validation.

    Always requires explicit human approval before submission.
    """
    import asyncio
    from datetime import date, datetime, time as _time

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

        for job, (cv_path, letter) in zip(eligible, generated):
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
    zip_path: Path = typer.Argument(..., help="Path to the LinkedIn data export ZIP."),
) -> None:
    """Bootstrap profile.yaml with experience data from a LinkedIn export ZIP."""
    from src.importers.linkedin_importer import LinkedInImporter
    from src.config.settings import settings  # noqa: F401 — ensures .env loaded

    profile_path = Path(__file__).parent / "config" / "profile.yaml"
    console.print(f"[bold]Importing[/bold] LinkedIn data from {zip_path}…")
    try:
        LinkedInImporter().import_zip(zip_path, profile_path)
        console.print("[green]Done.[/green] profile.yaml updated.")
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)


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
