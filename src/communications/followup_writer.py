"""Follow-up writer — draft a polite relance email for a submitted application."""

from __future__ import annotations

import logging

from src.analysis.recruiter_finder import _parse_json_response
from src.llm.base import LLMClient

logger = logging.getLogger(__name__)

_SYSTEM_MESSAGE = (
    "You write short, polite follow-up emails from a job candidate to a recruiter, "
    "as a reply in an existing email thread about a job application. Goals: gently "
    "re-surface the application without pressure, add ONE new element of value "
    "(availability, a relevant result, or a concrete question about the process), "
    "stay under 120 words, no guilt-tripping, no flattery. Write in the same "
    "language as the original email (French original → French follow-up).\n\n"
    "Return ONLY valid JSON with this exact schema:\n"
    "{\n"
    '  "subject": "<reply subject, usually Re: <original subject>>",\n'
    '  "body": "<plain-text email body, greeting to sign-off>"\n'
    "}\n"
    "Do not include any text outside the JSON object."
)

_MAX_BODY_CHARS = 2000


async def draft_followup(
    job_title: str,
    company_name: str,
    original_subject: str | None,
    original_body: str | None,
    days_since: int,
    profile: dict,
    client: LLMClient,
) -> tuple[str, str]:
    """Return (subject, body) for a follow-up email in an existing thread.

    Raises ValueError when the LLM response cannot be parsed.
    """
    candidate = profile.get("candidate", {}) or {}
    candidate_summary = "\n".join(
        f"- {k}: {v}"
        for k, v in candidate.items()
        if v and isinstance(v, (str, int, float))
    )

    prompt = (
        f"Job: {job_title} at {company_name}\n"
        f"The candidate sent the original email {days_since} days ago and got no reply.\n\n"
        f"Original subject: {original_subject or '(unknown)'}\n"
        f"Original email:\n{(original_body or '(unknown)')[:_MAX_BODY_CHARS]}\n\n"
        f"Candidate profile:\n{candidate_summary or '- (no profile data)'}"
    )
    text = await client.complete(prompt=prompt, max_tokens=1024, system=_SYSTEM_MESSAGE)
    data = _parse_json_response(text)
    if not data or not data.get("subject") or not data.get("body"):
        logger.warning("Unparseable follow-up draft: %r", text[:200])
        raise ValueError("Could not generate a valid follow-up draft — try again")
    return str(data["subject"]).strip(), str(data["body"]).strip()
