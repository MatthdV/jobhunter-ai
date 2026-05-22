#!/usr/bin/env python3
"""JobHunter AI — Semi-autonomous job search CLI."""


from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(
    name="jobhunter",
    help="Semi-autonomous job search pipeline — scan, score, apply, respond.",
    add_completion=False,
)
console = Console()


@app.command()
def scan(
    sources: list[str] = typer.Option(  # noqa: B008
        ["gmail_alerts", "indeed_api", "wttj"],
        "--source", "-s",
        help="Job boards to scan. linkedin available but disabled by default (ToS risk).",
    ),
    limit: int = typer.Option(50, "--limit", "-l", help="Max offers per source."),
    parse_only: bool = typer.Option(
        False, "--parse-only", help="gmail_alerts: print extracted stubs, skip JSearch + DB."
    ),
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

    from src.config.profile import get_profile_path

    with get_profile_path().open() as fh:
        profile = yaml.safe_load(fh)

    search_cfg = profile.get("search", {})
    countries = search_cfg.get("countries", ["FR"])
    location = search_cfg.get("location", "remote")
    keywords = profile.get("search_keywords", ["automation", "n8n", "RevOps"])

    console.print(
        f"[bold]Scanning[/bold] {sources} × {len(keywords)} keywords "
        f"× {len(countries)} countries (limit={limit})…"
    )

    _scraper_map = {
        "wttj": "src.scrapers.wttj.WTTJScraper",
        "indeed": "src.scrapers.indeed.IndeedScraper",
        "indeed_api": "src.scrapers.indeed_api.IndeedApiScraper",
        "linkedin": "src.scrapers.linkedin.LinkedInScraper",
        "adzuna": "src.scrapers.adzuna.AdzunaScraper",
        "france_travail": "src.scrapers.france_travail.FranceTravailScraper",
    }

    async def _run() -> int:
        with get_session() as session:
            existing_urls: set[str] = {u for (u,) in session.query(Job.url).all()}

        total = 0

        # Gmail job-alert scraper — separate flow (no keywords, reads emails)
        if "gmail_alerts" in sources:
            from src.scrapers.gmail_scraper import GmailJobAlertScraper

            try:
                async with GmailJobAlertScraper() as gmail_scraper:
                    if parse_only:
                        stubs = await gmail_scraper._fetch_stubs(max_emails=limit)
                        console.print(
                            f"[bold]gmail_alerts parse-only:[/bold] "
                            f"{len(stubs)} stub(s) extracted\n"
                        )
                        for i, s in enumerate(stubs, 1):
                            console.print(
                                f"  [{i}] [cyan]{s['title']}[/cyan] "
                                f"@ [yellow]{s.get('company') or '?'}[/yellow] "
                                f"— {s.get('location') or '?'}\n"
                                f"      {s['url']}"
                            )
                    else:
                        jobs = await gmail_scraper.scan_alerts(
                            max_emails=limit,
                            seen_urls=existing_urls,
                            country_code=countries[0] if countries else "FR",
                        )
                        fresh = [j for j in jobs if j.url not in existing_urls]
                        if fresh:
                            with get_session() as session:
                                for job in fresh:
                                    session.add(job)
                                    existing_urls.add(job.url)
                            total += len(fresh)
                        console.print(
                            f"  gmail_alerts: [green]{len(fresh)}[/green] new, "
                            f"{len(jobs) - len(fresh)} dupes"
                        )
            except Exception as exc:
                console.print(f"[red]gmail_alerts init error:[/red] {exc}")

        # Career pages scanner — separate flow (no keywords, iterates portals)
        if "career_pages" in sources:
            from src.scrapers.career_pages import CareerPageScraper

            try:
                async with CareerPageScraper() as cp_scraper:
                    jobs = await cp_scraper.scan_all_portals(seen_urls=existing_urls)
                    fresh = [j for j in jobs if j.url not in existing_urls]
                    if fresh:
                        with get_session() as session:
                            for job in fresh:
                                session.add(job)
                                existing_urls.add(job.url)
                        total += len(fresh)
                    console.print(
                        f"  career_pages: [green]{len(fresh)}[/green] new, "
                        f"{len(jobs) - len(fresh)} dupes"
                    )
            except Exception as exc:
                console.print(f"[red]career_pages init error:[/red] {exc}")

        # Standard keyword-based scrapers
        for source in sources:
            if source == "career_pages":
                continue
            if source not in _scraper_map:
                console.print(f"[yellow]Unknown source: {source}[/yellow]")
                continue

            module_path, _, class_name = _scraper_map[source].rpartition(".")
            mod = importlib.import_module(module_path)
            scraper_cls = getattr(mod, class_name)
            supported = get_supported_countries(source)
            filters = ScraperFilters(remote_only=False)

            try:
                async with scraper_cls() as scraper:
                    for country in countries:
                        if supported and country not in supported:
                            continue
                        for kw in keywords:
                            try:
                                jobs = await scraper.search(
                                    keywords=[kw],
                                    location=location,
                                    filters=filters,
                                    limit=limit,
                                    seen_urls=existing_urls,
                                    country_code=country,
                                )
                            except Exception as exc:
                                console.print(
                                    f"  [red]{source}/{country}/{kw}:[/red] {exc}"
                                )
                                continue

                            fresh = [j for j in jobs if j.url not in existing_urls]
                            if fresh:
                                with get_session() as session:
                                    for job in fresh:
                                        session.add(job)
                                        existing_urls.add(job.url)
                                total += len(fresh)
                            safe_kw = kw.replace("[", "\\[")
                            console.print(
                                f"  {source}/{country} \\[{safe_kw}]: "
                                f"[green]{len(fresh)}[/green] new, "
                                f"{len(jobs) - len(fresh)} dupes"
                            )
            except Exception as exc:
                console.print(f"[red]{source} init error:[/red] {exc}")
                continue
        return total

    total = asyncio.run(_run())
    console.print(
        f"[bold green]Done.[/bold green] {total} new job(s) across "
        f"{len(keywords)} keywords × {len(countries)} countries."
    )


@app.command()
def match(
    min_score: int = typer.Option(80, "--min-score", help="Minimum match score (0–100)."),
    detailed: bool = typer.Option(False, "--detailed", help="Print full A-F evaluation."),
) -> None:
    """Score all NEW jobs against the candidate profile using Claude."""
    import asyncio
    import json as _json

    from src.matching.scorer import Scorer
    from src.storage.database import get_session
    from src.storage.models import Job, JobStatus, MatchResult

    console.print(f"[bold]Matching[/bold] NEW jobs (min_score={min_score})…")

    async def _run() -> tuple[int, int, list[dict]]:
        scorer = Scorer()
        with get_session() as session:
            new_jobs = session.query(Job).filter(Job.status == JobStatus.NEW).all()
            if not new_jobs:
                return 0, 0, []
            console.print(f"  Scoring {len(new_jobs)} job(s)…")
            results = await scorer.score_batch(new_jobs, session)
            matched = sum(1 for j in new_jobs if j.status == JobStatus.MATCHED)
            # Collect display data while session is still open
            display = []
            for mr in results:
                display.append({
                    "title": mr.job.title,
                    "score": mr.score,
                    "evaluation_json": mr.evaluation_json,
                    "archetype": mr.archetype,
                })
        return len(results), matched, display

    total, matched, display = asyncio.run(_run())

    if detailed and display:
        for d in display:
            console.print(f"\n[bold]{d['title']}[/bold] — score={d['score']}")
            if d["evaluation_json"]:
                eval_data = _json.loads(d["evaluation_json"])
                for block_name, block_data in eval_data.get("blocks", {}).items():
                    block_score = block_data.get("score", "?")
                    console.print(f"  {block_name}: {block_score}/5.0")
            if d["archetype"]:
                console.print(f"  Archetype: {d['archetype']}")

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
def respond() -> None:
    """Poll Gmail for recruiter replies and draft auto-responses (Phase 4).

    Checks all SUBMITTED applications with a tracked Gmail thread, classifies
    recruiter messages, and drafts replies via the configured LLM provider.
    Sends a Telegram notification for each reply received.
    """
    import asyncio

    from src.communications.email_handler import EmailHandler
    from src.communications.recruiter_responder import RecruiterResponder
    from src.config.settings import settings
    from src.storage.database import get_session
    from src.storage.models import Application, ApplicationStatus

    console.print("[bold]Responding[/bold] — polling Gmail for recruiter replies…")

    telegram = None
    if settings.is_telegram_configured:
        from src.communications.telegram_bot import TelegramBot
        telegram = TelegramBot()

    email_handler = EmailHandler()
    responder = RecruiterResponder()

    async def _run() -> int:
        if telegram:
            await telegram.start_polling()
        try:
            with get_session() as session:
                submitted = (
                    session.query(Application)
                    .filter(
                        Application.status == ApplicationStatus.SUBMITTED,
                        Application.gmail_thread_id.isnot(None),
                    )
                    .all()
                )
                thread_ids = [a.gmail_thread_id for a in submitted if a.gmail_thread_id]
                app_by_thread = {
                    a.gmail_thread_id: a.id for a in submitted if a.gmail_thread_id
                }

            if not thread_ids:
                return 0

            replies = await email_handler.get_unread_replies(thread_ids)
            handled = 0
            for msg in replies:
                app_id = app_by_thread.get(msg.thread_id)
                if app_id is None:
                    continue
                with get_session() as session:
                    app = session.get(Application, app_id)
                    if app is None:
                        continue
                    draft = await responder.handle(msg, app)
                    if draft is not None:
                        app.status = ApplicationStatus.REPLIED  # type: ignore[assignment]
                    if telegram:
                        job = app.job
                        await telegram.notify_reply_received(
                            job, msg.sender, msg.body[:200]
                        )
                await email_handler.mark_as_read(msg.message_id)
                handled += 1
            return handled
        finally:
            if telegram:
                await telegram.stop_polling()

    handled = asyncio.run(_run())
    console.print(f"[bold green]Done.[/bold green] {handled} reply/replies handled.")


@app.command()
def research(
    company: str = typer.Argument(..., help="Company name to research."),
) -> None:
    """Deep research a company. Outputs structured insight."""
    import asyncio

    from src.analysis.company_researcher import CompanyResearcher

    console.print(f"[bold]Researching[/bold] {company}…")

    async def _run() -> None:
        researcher = CompanyResearcher()
        insight = await researcher.research(company)
        console.print(f"  Sector: {insight.sector or 'Unknown'}")
        console.print(f"  Size: {insight.size_estimate or 'Unknown'}")
        console.print(f"  Funding: {insight.funding_stage or 'Unknown'}")
        console.print(f"  Tech stack: {', '.join(insight.tech_stack_signals) or 'Unknown'}")
        console.print(f"  Culture: {', '.join(insight.culture_signals) or 'Unknown'}")
        console.print(f"  Glassdoor: {insight.glassdoor_rating if insight.glassdoor_rating is not None else 'N/A'}")
        console.print(f"  Growth: {', '.join(insight.growth_signals) or 'None'}")
        if insight.red_flags:
            console.print(f"  [red]Red flags: {', '.join(insight.red_flags)}[/red]")
        else:
            console.print("  Red flags: None")

    asyncio.run(_run())
    console.print("[bold green]Done.[/bold green]")


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

    from src.config.profile import get_profile_path

    profile_path = get_profile_path()
    console.print(f"[bold]Importing[/bold] LinkedIn data from {zip_path}…")
    try:
        LinkedInImporter().import_zip(zip_path, profile_path)
        console.print("[green]Done.[/green] profile.yaml updated.")
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc


@app.command("import-mcp")
def import_mcp_cmd() -> None:
    """Import jobs from MCP bridge inbox (data/mcp_inbox/*.json)."""
    from src.importers.mcp_bridge import MCPBridgeImporter
    from src.storage.database import get_session

    console.print("[bold]Importing[/bold] MCP bridge data…")
    importer = MCPBridgeImporter()
    with get_session() as session:
        count = importer.import_pending(session)
    console.print(f"[bold green]Done.[/bold green] {count} new job(s) imported from MCP.")


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
