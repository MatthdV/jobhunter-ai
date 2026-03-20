"""Automated responses to recruiter emails using Claude."""

from src.communications.email_handler import EmailMessage
from src.storage.models import Application


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
        raise NotImplementedError

    async def handle(self, message: EmailMessage, application: Application) -> str | None:
        """Classify a recruiter message and generate a draft response.

        Args:
            message: Incoming email from the recruiter.
            application: The application this message belongs to.

        Returns:
            Draft response text, or None if no response is appropriate
            (e.g. rejection, spam).
        """
        raise NotImplementedError

    async def classify(self, message: EmailMessage) -> str:
        """Classify the intent of a recruiter message.

        Returns one of: 'interview_invite', 'info_request', 'rejection',
        'scam', 'other'.
        """
        raise NotImplementedError

    async def draft_interview_reply(self, message: EmailMessage) -> str:
        """Generate an availability proposal in response to an interview invite."""
        raise NotImplementedError

    async def detect_scam(self, message: EmailMessage) -> bool:
        """Return True if the message shows scam indicators."""
        raise NotImplementedError
