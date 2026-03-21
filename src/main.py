#!/usr/bin/env python3
"""JobHunter AI — Semi-autonomous job search CLI."""


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
    mode = "[yellow]DRY RUN[/yellow]" if dry_run else "[red]LIVE[/red]"
    target = f"job #{job_id}" if job_id else "all MATCHED jobs"
    console.print(f"[bold]Applying[/bold] to {target} ({mode})…")
    raise NotImplementedError("Phase 3 — application generation not yet implemented")


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


if __name__ == "__main__":
    app()
