"""Automated responses to recruiter emails using Claude."""

import logging
from pathlib import Path
from typing import Any

import anthropic
import yaml

from src.communications.email_handler import EmailMessage
from src.config.settings import ConfigurationError, settings
from src.storage.models import Application

logger = logging.getLogger(__name__)

_PROFILE_PATH = Path(__file__).parent.parent / "config" / "profile.yaml"

_CLASSIFY_SYSTEM = (
    "You are classifying a recruiter email. "
    "Reply with EXACTLY ONE of these words (no punctuation, no explanation): "
    "interview_invite, info_request, rejection, scam, other"
)

_SCAM_SYSTEM = (
    "You are checking if a recruiter email is a scam. "
    "Reply with EXACTLY ONE word: true or false. "
    "Scam indicators: upfront payment, unrealistically high salary, urgency, "
    "requests for bank details or personal documents."
)


class RecruiterResponder:
    """Classify recruiter replies and generate appropriate responses.

    Handles the most common recruiter message types:
    - Interview invitation → propose availability slots
    - Request for more info → answer from profile data
    - Rejection → polite acknowledgement, no follow-up
    - Scam / spam detection → flag and skip

    All responses require human review before sending unless the user
    has explicitly enabled fully autonomous mode.

    Usage::

        responder = RecruiterResponder()
        response = await responder.handle(message, application)
    """

    def __init__(self) -> None:
        """Initialise Anthropic client and load profile.yaml."""
        if not settings.anthropic_api_key:
            raise ConfigurationError(
                "ANTHROPIC_API_KEY is not set — cannot initialise RecruiterResponder"
            )
        with open(_PROFILE_PATH) as f:
            self._profile: dict[str, Any] = yaml.safe_load(f)
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model

    # ------------------------------------------------------------------
    # Slice 31 — classify
    # ------------------------------------------------------------------

    async def classify(self, message: EmailMessage) -> str:
        """Classify the intent of a recruiter message.

        Returns one of: 'interview_invite', 'info_request', 'rejection',
        'scam', 'other'.
        """
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=20,
            system=_CLASSIFY_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Subject: {message.subject}\n\nBody:\n{message.body[:1000]}"
                    ),
                }
            ],
        )
        block = resp.content[0]
        text = block.text if hasattr(block, "text") else ""
        return text.strip().lower()

    # ------------------------------------------------------------------
    # Slice 32 — handle + draft_interview_reply + detect_scam
    # ------------------------------------------------------------------

    async def handle(self, message: EmailMessage, application: Application) -> str | None:
        """Classify a recruiter message and generate a draft response.

        Returns draft response text, or None for rejection/scam.
        """
        intent = await self.classify(message)

        if intent == "interview_invite":
            return await self.draft_interview_reply(message)
        if intent == "info_request":
            return await self._draft_info_reply(message)
        if intent in ("rejection", "scam"):
            if intent == "scam":
                logger.warning("Scam email detected from %s", message.sender)
            return None
        # "other" — return None (no automated response)
        return None

    async def draft_interview_reply(self, message: EmailMessage) -> str:
        """Generate an availability proposal in response to an interview invite."""
        profile_name = self._profile.get("candidate", {}).get("name", "Le candidat")
        prompt = (
            f"You are drafting a professional reply for {profile_name} to accept an "
            f"interview invitation. Write in the same language as the original email.\n\n"
            f"Original email:\nSubject: {message.subject}\n{message.body[:500]}\n\n"
            f"Propose 2-3 availability slots (Mon-Fri, 10h-18h). "
            f"Keep it concise (under 100 words)."
        )
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        block = resp.content[0]
        text = block.text if hasattr(block, "text") else ""
        return text.strip()

    async def detect_scam(self, message: EmailMessage) -> bool:
        """Return True if the message shows scam indicators."""
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=10,
            system=_SCAM_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Subject: {message.subject}\n\nBody:\n{message.body[:1000]}"
                    ),
                }
            ],
        )
        block = resp.content[0]
        text = block.text if hasattr(block, "text") else ""
        return text.strip().lower() == "true"

    async def _draft_info_reply(self, message: EmailMessage) -> str:
        """Generate a reply to an information request using profile data."""
        candidate = self._profile.get("candidate", {})
        skills = self._profile.get("skills", {}).get("top_3", [])
        prompt = (
            f"Draft a brief professional reply for {candidate.get('name', 'the candidate')} "
            f"responding to an information request. Write in the same language as the email.\n\n"
            f"Candidate skills: {', '.join(skills)}\n\n"
            f"Original email:\nSubject: {message.subject}\n{message.body[:500]}\n\n"
            f"Keep it under 80 words."
        )
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        block = resp.content[0]
        text = block.text if hasattr(block, "text") else ""
        return text.strip()
