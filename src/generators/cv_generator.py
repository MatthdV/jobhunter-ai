"""Personalised CV generation per job offer using Jinja2 + WeasyPrint."""

from pathlib import Path
from typing import Any

from src.storage.models import Job


class CVGenerator:
    """Generate a tailored PDF CV for a specific job offer.

    Flow:
    1. Load the base CV data from profile.yaml.
    2. Ask Claude to identify which skills and experiences to emphasise
       for this specific offer.
    3. Render the Jinja2 HTML template with personalised content.
    4. Convert HTML → PDF with WeasyPrint.

    Templates live in src/generators/templates/.

    Usage::

        generator = CVGenerator()
        pdf_path = await generator.generate(job, output_dir=Path("output/cvs"))
    """

    TEMPLATE_DIR = Path(__file__).parent / "templates"

    def __init__(self) -> None:
        """Load profile.yaml and initialise Jinja2 environment."""
        raise NotImplementedError

    async def generate(self, job: Job, output_dir: Path) -> Path:
        """Generate a personalised CV PDF for the given job.

        Args:
            job: Job offer to tailor the CV for.
            output_dir: Directory where the PDF will be written.

        Returns:
            Path to the generated PDF file.
        """
        raise NotImplementedError

    async def _select_highlights(self, job: Job) -> dict[str, Any]:
        """Use Claude to identify which experiences and skills to emphasise."""
        raise NotImplementedError

    def _render_html(self, context: dict[str, Any]) -> str:
        """Render the Jinja2 CV template with the given context."""
        raise NotImplementedError

    def _html_to_pdf(self, html: str, output_path: Path) -> Path:
        """Convert an HTML string to PDF using WeasyPrint."""
        raise NotImplementedError
