"""Build a candidate profile dict from an exported LinkedIn profile PDF.

LinkedIn lets users export their profile as PDF ("More → Save to PDF"). This
module extracts the text and asks the user's configured LLM to map it onto the
rich profile schema consumed by the Scorer, CVGenerator and CoverLetterGenerator
(candidate / skills / experiences / education / projects).

The LLM output is best-effort: the route layer merges it into the existing
profile YAML and the user reviews it before it's used.
"""

from __future__ import annotations

import json
import logging
import re
from io import BytesIO
from typing import Any

from src.llm.base import LLMClient

logger = logging.getLogger(__name__)

_MAX_TOKENS = 2048
_MAX_TEXT_CHARS = 12000  # keep prompt bounded; LinkedIn PDFs are usually short

_SYSTEM_MESSAGE = (
    "You extract a structured candidate profile from the raw text of a LinkedIn "
    "profile PDF export. Return ONLY valid JSON (no markdown fence, no prose) "
    "matching exactly this schema:\n"
    "{\n"
    '  "candidate": {"name": str, "title": str, "location": str, '
    '"experience_years": int|null, "languages": [str]},\n'
    '  "skills": {"top_3": [str], "additional": [str]},\n'
    '  "experiences": [{"id": str, "company": str, "title": str, '
    '"start": "YYYY-MM"|null, "end": "YYYY-MM"|null, "location": str, "bullets": [str]}],\n'
    '  "education": [{"school": str, "degree": str, "years": str}],\n'
    '  "projects": []\n'
    "}\n"
    "Rules: id = slug of company (lowercase, underscores, prefix 'exp_'). "
    "top_3 = the 3 most prominent skills; additional = the rest. "
    "bullets = concise achievement lines from each role's description. "
    "Use null when a field is unknown. Do not invent facts not present in the text."
)


class LinkedInPdfError(RuntimeError):
    """Raised when the PDF can't be read or the LLM output can't be parsed."""


def extract_text(pdf_bytes: bytes) -> str:
    """Extract concatenated text from a PDF byte string."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
    except Exception as exc:  # corrupt / not a PDF
        raise LinkedInPdfError(f"Impossible de lire le PDF : {exc}") from exc

    parts = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(parts).strip()
    if not text:
        raise LinkedInPdfError(
            "Aucun texte extrait du PDF (PDF scanné/image ?). Exporte ton profil "
            "via LinkedIn « Plus → Enregistrer au format PDF »."
        )
    return text[:_MAX_TEXT_CHARS]


async def profile_from_pdf(text: str, llm_client: LLMClient) -> dict[str, Any]:
    """Ask the LLM to map extracted PDF text onto the profile schema."""
    raw = await llm_client.complete(
        prompt=f"## LinkedIn profile PDF text\n\n{text}",
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM_MESSAGE,
    )

    data = _parse_json(raw)
    if data is None:
        raise LinkedInPdfError("La réponse de l'IA n'était pas un JSON exploitable.")
    return data


def _parse_json(raw: str) -> dict[str, Any] | None:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
    return None
