"""Cover letter generation using Claude — human tone, no buzzwords."""

from src.storage.models import Application, Job


class CoverLetterGenerator:
    """Generate a personalised cover letter for a specific job offer.

    Principles:
    - First-person, natural French (or English if job is in English).
    - Opens with a concrete hook tied to the company's product or challenge.
    - Highlights 2–3 relevant experiences with measurable outcomes.
    - Ends with a clear call-to-action, not generic enthusiasm.
    - Explicitly forbidden: "holistique", "synergique", "écosystème",
      "paradigme", hollow superlatives.

    Usage::

        generator = CoverLetterGenerator()
        letter = await generator.generate(job)
    """

    def __init__(self) -> None:
        """Load profile.yaml and initialise Anthropic client."""
        raise NotImplementedError

    async def generate(self, job: Job) -> str:
        """Generate a cover letter text for the given job.

        Args:
            job: Job offer including title, company, and description.

        Returns:
            Plain text cover letter (ready to paste or attach as PDF).
        """
        raise NotImplementedError

    async def refine(self, application: Application, feedback: str) -> str:
        """Refine an existing cover letter based on human feedback.

        Args:
            application: Existing application whose cover_letter will be refined.
            feedback: Free-text instructions from the human reviewer.

        Returns:
            Revised cover letter text.
        """
        raise NotImplementedError

    def _build_prompt(self, job: Job) -> str:
        """Build the generation prompt from job data and candidate profile."""
        raise NotImplementedError

    def _detect_language(self, job: Job) -> str:
        """Detect whether the job posting is in French or English.

        Returns:
            'fr' or 'en'.
        """
        raise NotImplementedError
