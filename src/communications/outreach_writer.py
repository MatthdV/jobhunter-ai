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


_DM_SYSTEM_MESSAGE = (
    "You write LinkedIn outreach for a job candidate contacting a recruiter about "
    "a specific job posting. The candidate sends these manually from their own "
    "LinkedIn account. Write in the same language as the job description "
    "(French job → French message). No flattery, no buzzwords, no emoji.\n\n"
    "Produce TWO texts:\n"
    "1. invite_note — the note attached to a connection request. HARD LIMIT "
    "280 characters. One concrete hook linking the candidate to the role, then "
    "a low-pressure ask.\n"
    "2. message — the direct message sent once connected (or as InMail). Max "
    "600 characters. 2-3 concrete matches between profile and role, mention the "
    "candidate applied via the official posting, end with a simple question.\n\n"
    "Return ONLY valid JSON with this exact schema:\n"
    "{\n"
    '  "invite_note": "<connection request note, max 280 chars>",\n'
    '  "message": "<direct message, max 600 chars>"\n'
    "}\n"
    "Do not include any text outside the JSON object."
)

_DM_INVITE_HARD_LIMIT = 300  # LinkedIn truncates connection notes at 300 chars


async def draft_linkedin_dm(
    job_title: str,
    job_description: str | None,
    company_name: str,
    recruiter_name: str,
    recruiter_title: str | None,
    profile: dict,
    client: LLMClient,
) -> tuple[str, str]:
    """Return (invite_note, message) for a semi-manual LinkedIn DM.

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
    text = await client.complete(prompt=prompt, max_tokens=1024, system=_DM_SYSTEM_MESSAGE)
    data = _parse_json_response(text)
    if not data or not data.get("invite_note") or not data.get("message"):
        logger.warning("Unparseable LinkedIn DM draft: %r", text[:200])
        raise ValueError("Could not generate a valid LinkedIn DM draft — try again")
    invite_note = str(data["invite_note"]).strip()[:_DM_INVITE_HARD_LIMIT]
    return invite_note, str(data["message"]).strip()
