"""Tests for TelegramBot — Phase 4A (slices 16-21)."""

import asyncio
from collections.abc import Generator
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import ConfigurationError
from src.storage.database import configure, drop_all, get_session, init_db
from src.storage.models import Application, ApplicationStatus, Job, JobStatus

if TYPE_CHECKING:
    from src.communications.telegram_bot import TelegramBot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_job(**kwargs: object) -> Job:
    defaults: dict[str, object] = {
        "title": "Automation Engineer",
        "url": "https://example.com/job/1",
        "source": "wttj",
        "description": "Python automation expert.",
        "is_remote": True,
        "contract_type": "CDI",
        "status": JobStatus.MATCHED,
        "match_score": 87.0,
        "salary_min": 90000,
        "salary_max": 120000,
    }
    defaults.update(kwargs)
    return Job(**defaults)


def make_application(job_id: int = 1) -> Application:
    return Application(
        job_id=job_id,
        cv_path="/tmp/cv.pdf",
        cover_letter="Lettre de motivation.",
        status=ApplicationStatus.DRAFT,
    )


@pytest.fixture(autouse=True)
def setup_db() -> Generator[None, None, None]:
    configure("sqlite:///:memory:")
    init_db()
    yield
    drop_all()


@pytest.fixture
def mock_telegram_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.communications.telegram_bot.settings",
        MagicMock(telegram_bot_token="test-token", telegram_chat_id="123456"),
    )


@pytest.fixture
def mock_bot() -> MagicMock:
    bot = MagicMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def telegram_bot(
    mock_telegram_settings: None, mock_bot: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> "TelegramBot":
    with patch("src.communications.telegram_bot.telegram.Bot", return_value=mock_bot):
        from src.communications.telegram_bot import TelegramBot
        return TelegramBot()


# ---------------------------------------------------------------------------
# Slice 16 — __init__ + ConfigurationError
# ---------------------------------------------------------------------------


class TestTelegramBotInit:
    def test_init_raises_without_bot_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "src.communications.telegram_bot.settings",
            MagicMock(telegram_bot_token="", telegram_chat_id="123456"),
        )
        with patch("src.communications.telegram_bot.telegram.Bot"):
            from src.communications.telegram_bot import TelegramBot
            with pytest.raises(ConfigurationError):
                TelegramBot()

    def test_init_raises_without_chat_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "src.communications.telegram_bot.settings",
            MagicMock(telegram_bot_token="test-token", telegram_chat_id=""),
        )
        with patch("src.communications.telegram_bot.telegram.Bot"):
            from src.communications.telegram_bot import TelegramBot
            with pytest.raises(ConfigurationError):
                TelegramBot()

    def test_init_succeeds_with_valid_config(self, mock_telegram_settings: None) -> None:
        with patch("src.communications.telegram_bot.telegram.Bot"):
            from src.communications.telegram_bot import TelegramBot
            bot = TelegramBot()
            assert bot is not None


# ---------------------------------------------------------------------------
# Slice 17 — _send_message helper
# ---------------------------------------------------------------------------


class TestSendMessage:
    async def test_send_message_calls_bot_with_chat_id_and_html(
        self, telegram_bot: "TelegramBot", mock_bot: MagicMock
    ) -> None:
        await telegram_bot._send_message("Hello <b>world</b>")
        mock_bot.send_message.assert_called_once_with(
            chat_id="123456",
            text="Hello <b>world</b>",
            parse_mode="HTML",
            reply_markup=None,
        )


# ---------------------------------------------------------------------------
# Slice 18 — notify_new_match
# ---------------------------------------------------------------------------


class TestNotifyNewMatch:
    async def test_notify_new_match_sends_message(
        self, telegram_bot: "TelegramBot", mock_bot: MagicMock
    ) -> None:
        with get_session() as session:
            job = make_job()
            session.add(job)
            session.flush()
            job_id = job.id

        with get_session() as session:
            job = session.get(Job, job_id)
            await telegram_bot.notify_new_match(job)

        mock_bot.send_message.assert_called_once()

    async def test_notify_new_match_card_contains_title_company_score(
        self, telegram_bot: "TelegramBot", mock_bot: MagicMock
    ) -> None:
        with get_session() as session:
            job = make_job()
            session.add(job)
            session.flush()
            job_id = job.id

        with get_session() as session:
            job = session.get(Job, job_id)
            await telegram_bot.notify_new_match(job)

        call_kwargs = mock_bot.send_message.call_args
        text = (
            call_kwargs.kwargs.get("text") or call_kwargs.args[0]
            if call_kwargs.args
            else call_kwargs.kwargs["text"]
        )
        assert "Automation Engineer" in text
        assert "87" in text  # score


# ---------------------------------------------------------------------------
# Slice 19 — request_approval (human gate)
# ---------------------------------------------------------------------------


class TestRequestApproval:
    async def test_request_approval_sends_message_with_inline_keyboard(
        self, telegram_bot: "TelegramBot", mock_bot: MagicMock
    ) -> None:
        with get_session() as session:
            job = make_job()
            session.add(job)
            session.flush()
            app = make_application(job_id=job.id)
            session.add(app)
            session.flush()
            job_id = job.id
            app_id = app.id

        async def _run() -> bool:
            with get_session() as session:
                job = session.get(Job, job_id)
                app = session.get(Application, app_id)
                # Simulate immediate approval by resolving the future
                async def _approve() -> None:
                    await asyncio.sleep(0.01)
                    telegram_bot._pending[app.id].set_result(True)

                asyncio.create_task(_approve())
                return await telegram_bot.request_approval(job, app)

        result = await _run()
        assert result is True
        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args
        reply_markup = call_kwargs.kwargs.get("reply_markup")
        assert reply_markup is not None

    async def test_request_approval_returns_false_on_reject(
        self, telegram_bot: "TelegramBot", mock_bot: MagicMock
    ) -> None:
        with get_session() as session:
            job = make_job()
            session.add(job)
            session.flush()
            app = make_application(job_id=job.id)
            session.add(app)
            session.flush()
            job_id = job.id
            app_id = app.id

        async def _run() -> bool:
            with get_session() as session:
                job = session.get(Job, job_id)
                app = session.get(Application, app_id)

                async def _reject() -> None:
                    await asyncio.sleep(0.01)
                    telegram_bot._pending[app.id].set_result(False)

                asyncio.create_task(_reject())
                return await telegram_bot.request_approval(job, app)

        result = await _run()
        assert result is False

    async def test_request_approval_returns_false_on_timeout(
        self, telegram_bot: "TelegramBot", mock_bot: MagicMock
    ) -> None:
        with get_session() as session:
            job = make_job()
            session.add(job)
            session.flush()
            app = make_application(job_id=job.id)
            session.add(app)
            session.flush()
            job_id = job.id
            app_id = app.id

        with get_session() as session:
            job = session.get(Job, job_id)
            app = session.get(Application, app_id)
            result = await telegram_bot.request_approval(job, app, timeout=0.05)

        assert result is False


# ---------------------------------------------------------------------------
# Slice 20 — notify_reply_received
# ---------------------------------------------------------------------------


class TestNotifyReplyReceived:
    async def test_notify_reply_received_includes_sender_and_snippet(
        self, telegram_bot: "TelegramBot", mock_bot: MagicMock
    ) -> None:
        with get_session() as session:
            job = make_job()
            session.add(job)
            session.flush()
            job_id = job.id

        with get_session() as session:
            job = session.get(Job, job_id)
            await telegram_bot.notify_reply_received(
                job, "Alice Recruteur", "Bonjour, nous aimerions vous rencontrer."
            )

        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args
        text = call_kwargs.kwargs.get("text", "")
        assert "Alice Recruteur" in text
        assert "Automation Engineer" in text


# ---------------------------------------------------------------------------
# Slice 21 — send_daily_summary
# ---------------------------------------------------------------------------


class TestSendDailySummary:
    async def test_send_daily_summary_sends_counts(
        self, telegram_bot: "TelegramBot", mock_bot: MagicMock
    ) -> None:
        with get_session() as session:
            job = make_job()
            session.add(job)
            session.flush()
            app = Application(
                job_id=job.id,
                cv_path="/tmp/cv.pdf",
                cover_letter="letter",
                status=ApplicationStatus.SUBMITTED,
            )
            session.add(app)

        await telegram_bot.send_daily_summary()

        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args
        text = call_kwargs.kwargs.get("text", "")
        assert len(text) > 0
