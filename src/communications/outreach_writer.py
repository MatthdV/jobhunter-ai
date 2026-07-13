"""Outreach writer — draft a personalized email to a recruiter for a job posting."""

from __future__ import annotations

import logging

from src.analysis.recruiter_finder import _parse_json_response
from src.llm.base import LLMClient

logger = logging.getLogger(__name__)

_SYSTEM_MESSAGE = (
    "You write short, direct outreach emails from a job candidate to a recruiter, "
    "in reference to a specific job posting. Goals: stand out from the portal pile, "
    "show 2-3 concrete matches between the candidate profile and the role, stay "
    "under 180 words, no flattery, no buzzwords. Write in the same language as the "
    "job description (French job → French email).\n"
    "Mention that the CV is attached and that the candidate also applied via the "
    "official posting.\n\n"
    "Return ONLY valid JSON with this exact schema:\n"
    "{\n"
    '  "subject": "<email subject line referencing the role>",\n'
    '  "body": "<plain-text email body, greeting to sign-off>"\n'
    "}\n"
    "Do not include any text outside the JSON object."
)

_MAX_DESCRIPTION_CHARS = 3000


async def draft_outreach(
    job_title: str,
    job_description: str | None,
    company_name: str,
    recruiter_name: str,
    recruiter_title: str | None,
    profile: dict,
    client: LLMClient,
) -> tuple[str, str]:
    """Return (subject, body) for a recruiter outreach email.

    Raises ValueError when the LLM response cannot be parsed.
    """
    candidate = profile.get("candidate", {}) or {}
    candidate_summary = "\n".join(
        f"- {k}: {v}"
        for k, v in candidate.items()
        if v and isinstance(v, (str, int, float))
    )
    description = (job_description or "")[:_MAX_DESCRIPTION_CHARS]

    prompt = (
        f"Job: {job_title} at {company_name}\n"
        f"Recruiter: {recruiter_name}"
        + (f" ({recruiter_title})" if recruiter_title else "")
        + f"\n\nCandidate profile:\n{candidate_summary or '- (no profile data)'}\n\n"
        f"Job description:\n{description or '(none)'}"
    )
    text = await client.complete(prompt=prompt, max_tokens=1024, system=_SYSTEM_MESSAGE)
    data = _parse_json_response(text)
    if not data or not data.get("subject") or not data.get("body"):
        logger.warning("Unparseable outreach draft: %r", text[:200])
        raise ValueError("Could not generate a valid email draft — try again")
    return str(data["subject"]).strip(), str(data["body"]).strip()
