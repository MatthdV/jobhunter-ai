"""Tests for RecruiterResponder — Phase 4C (slices 31-32)."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.communications.email_handler import EmailMessage
from src.storage.models import Application, ApplicationStatus

if TYPE_CHECKING:
    from src.communications.recruiter_responder import RecruiterResponder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_email_message(body: str = "Bonjour, interview demain?") -> EmailMessage:
    return EmailMessage(
        thread_id="thread123",
        message_id="msg001",
        sender="alice@company.com",
        subject="Re: Application",
        body=body,
        received_at=datetime(2026, 3, 21, 10, 0, 0, tzinfo=UTC),
    )


def make_application() -> Application:
    return Application(
        job_id=1,
        cv_path="/tmp/cv.pdf",
        cover_letter="Lettre.",
        status=ApplicationStatus.SUBMITTED,
    )


@pytest.fixture(autouse=True)
def patch_profile_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.communications.recruiter_responder._PROFILE_PATH",
        __import__("pathlib").Path(__file__).parent / "fixtures" / "test_profile.yaml",
    )


@pytest.fixture
def mock_llm_client() -> AsyncMock:
    """Mock LLMClient.complete returns a plain string (matches the abstract interface)."""
    client = AsyncMock()
    client.complete = AsyncMock(return_value="interview_invite")
    return client


@pytest.fixture
def responder(mock_llm_client: AsyncMock) -> "RecruiterResponder":
    """Inject mock LLM client directly — no factory or Anthropic patching needed."""
    from src.communications.recruiter_responder import RecruiterResponder
    return RecruiterResponder(client=mock_llm_client)


# ---------------------------------------------------------------------------
# Slice 31 — __init__ + classify
# ---------------------------------------------------------------------------


class TestRecruiterResponderInit:
    async def test_classify_returns_intent_string(
        self, responder: "RecruiterResponder", mock_llm_client: AsyncMock
    ) -> None:
        msg = make_email_message("We'd like to invite you for an interview.")
        result = await responder.classify(msg)
        assert result == "interview_invite"
        mock_llm_client.complete.assert_called_once()

    async def test_classify_parses_from_response_text(
        self, responder: "RecruiterResponder", mock_llm_client: AsyncMock
    ) -> None:
        mock_llm_client.complete.return_value = "rejection"
        msg = make_email_message("We have decided to move forward with other candidates.")
        result = await responder.classify(msg)
        assert result == "rejection"


# ---------------------------------------------------------------------------
# Slice 32 — handle + draft_interview_reply + detect_scam
# ---------------------------------------------------------------------------


class TestHandleDispatch:
    async def test_handle_interview_invite_returns_draft(
        self, responder: "RecruiterResponder", mock_llm_client: AsyncMock
    ) -> None:
        mock_llm_client.complete.side_effect = [
            "interview_invite",
            "Je suis disponible lundi ou mardi.",
        ]
        msg = make_email_message("We'd like to schedule an interview.")
        app = make_application()
        response = await responder.handle(msg, app)
        assert response is not None
        assert len(response) > 0

    async def test_handle_rejection_returns_none(
        self, responder: "RecruiterResponder", mock_llm_client: AsyncMock
    ) -> None:
        mock_llm_client.complete.return_value = "rejection"
        msg = make_email_message("Unfortunately we have chosen another candidate.")
        app = make_application()
        response = await responder.handle(msg, app)
        assert response is None

    async def test_handle_scam_returns_none(
        self, responder: "RecruiterResponder", mock_llm_client: AsyncMock
    ) -> None:
        mock_llm_client.complete.return_value = "scam"
        msg = make_email_message("Send €200 to unlock your application review.")
        app = make_application()
        response = await responder.handle(msg, app)
        assert response is None


class TestDetectScam:
    async def test_detect_scam_returns_true_for_suspicious(
        self, responder: "RecruiterResponder", mock_llm_client: AsyncMock
    ) -> None:
        mock_llm_client.complete.return_value = "true"
        msg = make_email_message("Pay €500 to process your application.")
        result = await responder.detect_scam(msg)
        assert result is True

    async def test_detect_scam_returns_false_for_legit(
        self, responder: "RecruiterResponder", mock_llm_client: AsyncMock
    ) -> None:
        mock_llm_client.complete.return_value = "false"
        msg = make_email_message("We'd like to schedule a 30-minute call.")
        result = await responder.detect_scam(msg)
        assert result is False
