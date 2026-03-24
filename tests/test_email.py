"""Tests for EmailHandler — Phase 4C (slices 28-30)."""

import base64
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from src.config.settings import ConfigurationError

if TYPE_CHECKING:
    from src.communications.email_handler import EmailHandler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gmail_thread(thread_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a minimal Gmail thread dict for mocking."""
    return {"id": thread_id, "messages": messages}


def _make_gmail_message(
    message_id: str,
    thread_id: str,
    sender: str,
    subject: str,
    body: str,
    label_ids: list[str] | None = None,
) -> dict[str, Any]:
    body_b64 = base64.urlsafe_b64encode(body.encode()).decode()
    return {
        "id": message_id,
        "threadId": thread_id,
        "labelIds": label_ids or ["UNREAD", "INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": "Sat, 21 Mar 2026 10:00:00 +0000"},
            ],
            "body": {"data": body_b64},
        },
    }


@pytest.fixture
def mock_gmail_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.communications.email_handler.settings",
        MagicMock(
            gmail_client_id="client-id",
            gmail_client_secret="client-secret",
            gmail_refresh_token="refresh-token",
            gmail_user_email="test@gmail.com",
            is_gmail_configured=True,
        ),
    )


@pytest.fixture
def mock_gmail_service() -> MagicMock:
    """Mock Google API service object."""
    service = MagicMock()
    # messages().send()
    send_result = MagicMock()
    send_result.execute.return_value = {"id": "msg123", "threadId": "thread456"}
    service.users.return_value.messages.return_value.send.return_value = send_result
    # messages().modify()
    modify_result = MagicMock()
    modify_result.execute.return_value = {}
    service.users.return_value.messages.return_value.modify.return_value = modify_result
    # threads().get()
    service.users.return_value.threads.return_value.get.return_value = MagicMock()
    return service


@pytest.fixture
def email_handler(
    mock_gmail_settings: None,
    mock_gmail_service: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> "EmailHandler":
    with patch(
        "src.communications.email_handler.EmailHandler._build_service",
        return_value=mock_gmail_service,
    ):
        from src.communications.email_handler import EmailHandler
        return EmailHandler()


# ---------------------------------------------------------------------------
# Slice 28 — EmailHandler.__init__
# ---------------------------------------------------------------------------


class TestEmailHandlerInit:
    def test_init_raises_without_gmail_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "src.communications.email_handler.settings",
            MagicMock(is_gmail_configured=False),
        )
        with patch("src.communications.email_handler.EmailHandler._build_service"):
            from src.communications.email_handler import EmailHandler
            with pytest.raises(ConfigurationError):
                EmailHandler()

    def test_init_succeeds_with_valid_config(self, mock_gmail_settings: None) -> None:
        with patch(
            "src.communications.email_handler.EmailHandler._build_service",
            return_value=MagicMock(),
        ):
            from src.communications.email_handler import EmailHandler
            handler = EmailHandler()
            assert handler is not None


# ---------------------------------------------------------------------------
# Slice 29 — send
# ---------------------------------------------------------------------------


class TestEmailHandlerSend:
    async def test_send_returns_thread_id(
        self, email_handler: "EmailHandler", mock_gmail_service: MagicMock
    ) -> None:
        thread_id = await email_handler.send(
            to="recruiter@company.com",
            subject="Candidature — Automation Engineer",
            body="Bonjour, je vous contacte…",
        )
        assert thread_id == "thread456"
        mock_gmail_service.users.return_value.messages.return_value.send.assert_called_once()

    async def test_send_encodes_body_as_base64(
        self, email_handler: "EmailHandler", mock_gmail_service: MagicMock
    ) -> None:
        await email_handler.send(
            to="recruiter@company.com",
            subject="Test",
            body="Corps du message.",
        )
        call_args = (
            mock_gmail_service.users.return_value.messages.return_value.send.call_args
        )
        raw_msg = call_args.kwargs.get("body", {}).get("raw", "")
        assert raw_msg  # must be non-empty base64

    async def test_send_sets_thread_id_for_reply(
        self, email_handler: "EmailHandler", mock_gmail_service: MagicMock
    ) -> None:
        await email_handler.send(
            to="recruiter@company.com",
            subject="Re: Interview",
            body="Merci pour votre réponse.",
            reply_to_thread="thread_existing",
        )
        call_args = (
            mock_gmail_service.users.return_value.messages.return_value.send.call_args
        )
        body = call_args.kwargs.get("body", {})
        assert body.get("threadId") == "thread_existing"


# ---------------------------------------------------------------------------
# Slice 30 — get_unread_replies + mark_as_read
# ---------------------------------------------------------------------------


class TestGetUnreadReplies:
    async def test_get_unread_replies_returns_messages(
        self, email_handler: "EmailHandler", mock_gmail_service: MagicMock
    ) -> None:
        msg = _make_gmail_message(
            "msg001", "thread123", "alice@company.com", "Re: Application", "Bonjour!"
        )
        thread = _make_gmail_thread("thread123", [msg])
        mock_threads = mock_gmail_service.users.return_value.threads.return_value
        mock_threads.get.return_value.execute.return_value = thread

        from src.communications.email_handler import EmailMessage
        results = await email_handler.get_unread_replies(["thread123"])

        assert len(results) == 1
        assert isinstance(results[0], EmailMessage)
        assert results[0].sender == "alice@company.com"
        assert results[0].thread_id == "thread123"
        assert "Bonjour!" in results[0].body

    async def test_get_unread_replies_skips_read_messages(
        self, email_handler: "EmailHandler", mock_gmail_service: MagicMock
    ) -> None:
        msg = _make_gmail_message(
            "msg002", "thread456", "bob@company.com", "Re: Application", "No.",
            label_ids=["INBOX"],  # no UNREAD label
        )
        thread = _make_gmail_thread("thread456", [msg])
        mock_threads = mock_gmail_service.users.return_value.threads.return_value
        mock_threads.get.return_value.execute.return_value = thread

        results = await email_handler.get_unread_replies(["thread456"])
        assert len(results) == 0

    async def test_get_unread_replies_returns_empty_for_no_threads(
        self, email_handler: "EmailHandler"
    ) -> None:
        results = await email_handler.get_unread_replies([])
        assert results == []


class TestMarkAsRead:
    async def test_mark_as_read_removes_unread_label(
        self, email_handler: "EmailHandler", mock_gmail_service: MagicMock
    ) -> None:
        await email_handler.mark_as_read("msg123")
        modify = mock_gmail_service.users.return_value.messages.return_value.modify
        modify.assert_called_once_with(
            userId="me",
            id="msg123",
            body={"removeLabelIds": ["UNREAD"]},
        )
