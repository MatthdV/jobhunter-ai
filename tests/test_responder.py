"""Tests for RecruiterResponder — Phase 4C (slices 31-32)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import ConfigurationError
from src.communications.email_handler import EmailMessage
from src.storage.models import Application, ApplicationStatus


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
        received_at=datetime(2026, 3, 21, 10, 0, 0, tzinfo=timezone.utc),
    )


def make_application() -> Application:
    return Application(
        job_id=1,
        cv_path="/tmp/cv.pdf",
        cover_letter="Lettre.",
        status=ApplicationStatus.SUBMITTED,
    )


@pytest.fixture
def mock_responder_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.communications.recruiter_responder.settings",
        MagicMock(anthropic_api_key="test-key", anthropic_model="claude-opus-4-6"),
    )
    monkeypatch.setattr(
        "src.communications.recruiter_responder._PROFILE_PATH",
        __import__("pathlib").Path(__file__).parent / "fixtures" / "test_profile.yaml",
    )


@pytest.fixture
def mock_anthropic_client() -> AsyncMock:
    client = AsyncMock()
    msg = MagicMock()
    msg.content = [MagicMock(text="interview_invite")]
    client.messages.create = AsyncMock(return_value=msg)
    return client


@pytest.fixture
def responder(
    mock_responder_settings: None,
    mock_anthropic_client: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> "RecruiterResponder":
    with patch(
        "src.communications.recruiter_responder.anthropic.AsyncAnthropic",
        return_value=mock_anthropic_client,
    ):
        from src.communications.recruiter_responder import RecruiterResponder
        return RecruiterResponder()


# ---------------------------------------------------------------------------
# Slice 31 — __init__ + classify
# ---------------------------------------------------------------------------


class TestRecruiterResponderInit:
    def test_init_raises_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "src.communications.recruiter_responder.settings",
            MagicMock(anthropic_api_key="", anthropic_model="claude-opus-4-6"),
        )
        with pytest.raises(ConfigurationError):
            from src.communications.recruiter_responder import RecruiterResponder
            RecruiterResponder()

    async def test_classify_returns_intent_string(
        self, responder: "RecruiterResponder", mock_anthropic_client: AsyncMock
    ) -> None:
        msg = make_email_message("We'd like to invite you for an interview.")
        # mock returns "interview_invite"
        result = await responder.classify(msg)
        assert result == "interview_invite"
        mock_anthropic_client.messages.create.assert_called_once()

    async def test_classify_parses_from_response_text(
        self, responder: "RecruiterResponder", mock_anthropic_client: AsyncMock
    ) -> None:
        mock_anthropic_client.messages.create.return_value.content = [
            MagicMock(text="rejection")
        ]
        msg = make_email_message("We have decided to move forward with other candidates.")
        result = await responder.classify(msg)
        assert result == "rejection"


# ---------------------------------------------------------------------------
# Slice 32 — handle + draft_interview_reply + detect_scam
# ---------------------------------------------------------------------------


class TestHandleDispatch:
    async def test_handle_interview_invite_returns_draft(
        self, responder: "RecruiterResponder", mock_anthropic_client: AsyncMock
    ) -> None:
        # classify → interview_invite, then draft_interview_reply
        mock_anthropic_client.messages.create.side_effect = [
            MagicMock(content=[MagicMock(text="interview_invite")]),
            MagicMock(content=[MagicMock(text="Je suis disponible lundi ou mardi.")]),
        ]
        msg = make_email_message("We'd like to schedule an interview.")
        app = make_application()
        response = await responder.handle(msg, app)
        assert response is not None
        assert len(response) > 0

    async def test_handle_rejection_returns_none(
        self, responder: "RecruiterResponder", mock_anthropic_client: AsyncMock
    ) -> None:
        mock_anthropic_client.messages.create.return_value.content = [
            MagicMock(text="rejection")
        ]
        msg = make_email_message("Unfortunately we have chosen another candidate.")
        app = make_application()
        response = await responder.handle(msg, app)
        assert response is None

    async def test_handle_scam_returns_none(
        self, responder: "RecruiterResponder", mock_anthropic_client: AsyncMock
    ) -> None:
        mock_anthropic_client.messages.create.return_value.content = [
            MagicMock(text="scam")
        ]
        msg = make_email_message("Send €200 to unlock your application review.")
        app = make_application()
        response = await responder.handle(msg, app)
        assert response is None


class TestDetectScam:
    async def test_detect_scam_returns_true_for_suspicious(
        self, responder: "RecruiterResponder", mock_anthropic_client: AsyncMock
    ) -> None:
        mock_anthropic_client.messages.create.return_value.content = [
            MagicMock(text="true")
        ]
        msg = make_email_message("Pay €500 to process your application.")
        result = await responder.detect_scam(msg)
        assert result is True

    async def test_detect_scam_returns_false_for_legit(
        self, responder: "RecruiterResponder", mock_anthropic_client: AsyncMock
    ) -> None:
        mock_anthropic_client.messages.create.return_value.content = [
            MagicMock(text="false")
        ]
        msg = make_email_message("We'd like to schedule a 30-minute call.")
        result = await responder.detect_scam(msg)
        assert result is False
