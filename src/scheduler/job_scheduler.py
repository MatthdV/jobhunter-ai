"""Pipeline orchestrator — ties all phases together in the right order."""



class JobScheduler:
    """Orchestrate the full job search pipeline.

    Execution order per cycle:
    1. Scrape configured sources for new offers.
    2. Deduplicate against existing DB records.
    3. Pre-filter with EmbeddingMatcher (optional, saves LLM credits).
    4. Score surviving offers with Scorer.
    5. Persist results; update Job.status.
    6. For each MATCHED job, generate CV + cover letter draft.
    7. Send Telegram approval request to human.
    8. On approval, submit application via EmailHandler.
    9. Poll Gmail for recruiter replies; trigger RecruiterResponder.
    10. Send daily summary via Telegram.

    Usage::

        scheduler = JobScheduler()
        await scheduler.run_once()          # Single cycle
        await scheduler.run_loop(interval=3600)  # Every hour
    """

    def __init__(self) -> None:
        """Initialise all sub-components from settings."""
        raise NotImplementedError

    async def run_once(self) -> None:
        """Execute a full pipeline cycle (scan → match → apply → respond)."""
        raise NotImplementedError

    async def run_loop(self, interval: int = 3600) -> None:
        """Run the pipeline on a recurring schedule.

        Args:
            interval: Seconds between cycles. Default: 1 hour.
        """
        raise NotImplementedError

    async def _scan_phase(self) -> int:
        """Run all scrapers and persist new jobs. Returns count of new jobs."""
        raise NotImplementedError

    async def _match_phase(self) -> int:
        """Score all NEW jobs. Returns count of MATCHED jobs."""
        raise NotImplementedError

    async def _apply_phase(self) -> int:
        """Generate applications and trigger human approval flow.

        Respects settings.max_applications_per_day and settings.dry_run.
        Returns count of applications submitted.
        """
        raise NotImplementedError

    async def _respond_phase(self) -> int:
        """Check Gmail for recruiter replies and draft responses.

        Returns count of replies handled.
        """
        raise NotImplementedError
