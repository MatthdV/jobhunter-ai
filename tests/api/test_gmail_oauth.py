"""Tests for the in-app Gmail OAuth connect flow + per-user EmailHandler creds.

No network calls: the Google Flow and Gmail profile lookup are mocked at the
site of use (src.api.routes.pages). Follows the fixture conventions of
tests/api/test_followup.py — never touches the real jobhunter.db.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import app
from src.api.background import tracker
from src.api.deps import get_current_user, require_user_redirect
from src.api.security import create_oauth_state_token, decrypt_keys, encrypt_keys
from src.config.settings import settings
from src.storage import database as _db_module
from src.storage.database import _migrate_schema
from src.storage.models import Base, User

_TEST_USER_ID = 1
_JWT_SECRET = "test-secret-at-least-32-characters-long"
_FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def gmail_env(monkeypatch):
    """Configure the instance-wide OAuth client + crypto secrets."""
    monkeypatch.setattr(settings, "jwt_secret", _JWT_SECRET)
    monkeypatch.setattr(settings, "fernet_key", _FERNET_KEY)
    monkeypatch.setattr(settings, "gmail_oauth_client_id", "oauth-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "gmail_oauth_client_secret", "oauth-client-secret")
    yield


@pytest.fixture(autouse=True)
def setup_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    _db_module._engine = engine
    _db_module._SessionLocal = session_factory
    Base.metadata.create_all(bind=engine)
    with session_factory() as s:
        s.add(User(email="test@example.com", hashed_password="x"))
        s.commit()
    tracker.reset()
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    _db_module._engine = None
    _db_module._SessionLocal = None


def _load_test_user() -> User:
    with _db_module.get_session() as s:
        user = s.get(User, _TEST_USER_ID)
        s.expunge(user)
        return user


@pytest.fixture()
def client(setup_db):
    def _fake_user():
        return _load_test_user()

    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[require_user_redirect] = _fake_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# /settings/gmail/connect
# ---------------------------------------------------------------------------


class TestGmailConnect:
    def test_redirects_to_google_consent(self, client):
        resp = client.get("/settings/gmail/connect", follow_redirects=False)
        assert resp.status_code == 302
        loc = resp.headers["location"]
        assert loc.startswith("https://accounts.google.com/o/oauth2/auth")
        assert "state=" in loc
        assert "access_type=offline" in loc
        assert "prompt=consent" in loc
        assert "mail.google.com" in loc  # scope

    def test_503_when_oauth_client_missing(self, client, monkeypatch):
        monkeypatch.setattr(settings, "gmail_oauth_client_id", "")
        resp = client.get("/settings/gmail/connect", follow_redirects=False)
        assert resp.status_code == 503

    def test_503_when_fernet_missing(self, client, monkeypatch):
        monkeypatch.setattr(settings, "fernet_key", "")
        resp = client.get("/settings/gmail/connect", follow_redirects=False)
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# /settings/gmail/callback
# ---------------------------------------------------------------------------


def _mock_flow(refresh_token="rt-secret-123"):
    flow = MagicMock()
    flow.credentials = MagicMock(refresh_token=refresh_token)
    return flow


class TestGmailCallback:
    def test_invalid_state_rejected(self, client):
        resp = client.get(
            "/settings/gmail/callback?state=garbage&code=abc",
            follow_redirects=False,
        )
        assert resp.status_code == 400

    def test_state_for_other_user_rejected(self, client):
        state = create_oauth_state_token(999, _JWT_SECRET)
        resp = client.get(
            f"/settings/gmail/callback?state={state}&code=abc",
            follow_redirects=False,
        )
        assert resp.status_code == 400

    def test_access_token_not_valid_as_state(self, client):
        from src.api.security import create_access_token

        state = create_access_token(_TEST_USER_ID, _JWT_SECRET)
        resp = client.get(
            f"/settings/gmail/callback?state={state}&code=abc",
            follow_redirects=False,
        )
        assert resp.status_code == 400

    def test_denied_redirects_with_flag(self, client):
        resp = client.get(
            "/settings/gmail/callback?error=access_denied",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/settings?gmail=denied"

    def test_success_stores_encrypted_token_and_email(self, client):
        state = create_oauth_state_token(_TEST_USER_ID, _JWT_SECRET)
        with patch(
            "src.api.routes.pages._build_gmail_flow", return_value=_mock_flow()
        ) as build_flow, patch(
            "src.api.routes.pages._gmail_profile_email",
            return_value="moi@gmail.com",
        ):
            resp = client.get(
                f"/settings/gmail/callback?state={state}&code=auth-code",
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/settings?gmail=connected"
        build_flow.return_value.fetch_token.assert_called_once_with(code="auth-code")

        user = _load_test_user()
        keys = decrypt_keys(user.encrypted_keys, _FERNET_KEY)
        assert keys["gmail_refresh_token"] == "rt-secret-123"
        assert keys["gmail_user_email"] == "moi@gmail.com"
        assert user.gmail_connected_email == "moi@gmail.com"
        assert user.gmail_connected_at is not None

    def test_no_refresh_token_redirects_error(self, client):
        state = create_oauth_state_token(_TEST_USER_ID, _JWT_SECRET)
        with patch(
            "src.api.routes.pages._build_gmail_flow",
            return_value=_mock_flow(refresh_token=None),
        ):
            resp = client.get(
                f"/settings/gmail/callback?state={state}&code=auth-code",
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/settings?gmail=error"

    def test_preserves_existing_credentials(self, client):
        # User already has an OpenRouter key stored — connecting Gmail must keep it
        with _db_module.get_session() as s:
            user = s.get(User, _TEST_USER_ID)
            user.encrypted_keys = encrypt_keys(
                {"openrouter_api_key": "sk-or-keep-me"}, _FERNET_KEY
            )
        state = create_oauth_state_token(_TEST_USER_ID, _JWT_SECRET)
        with patch(
            "src.api.routes.pages._build_gmail_flow", return_value=_mock_flow()
        ), patch(
            "src.api.routes.pages._gmail_profile_email", return_value="moi@gmail.com"
        ):
            client.get(
                f"/settings/gmail/callback?state={state}&code=auth-code",
                follow_redirects=False,
            )
        keys = decrypt_keys(_load_test_user().encrypted_keys, _FERNET_KEY)
        assert keys["openrouter_api_key"] == "sk-or-keep-me"
        assert keys["gmail_refresh_token"] == "rt-secret-123"


# ---------------------------------------------------------------------------
# /settings/gmail/disconnect
# ---------------------------------------------------------------------------


class TestGmailDisconnect:
    def test_disconnect_clears_token_and_revokes(self, client):
        with _db_module.get_session() as s:
            user = s.get(User, _TEST_USER_ID)
            user.encrypted_keys = encrypt_keys(
                {"gmail_refresh_token": "rt-old", "gmail_user_email": "moi@gmail.com"},
                _FERNET_KEY,
            )
            user.gmail_connected_email = "moi@gmail.com"

        with patch("httpx.post") as revoke:
            resp = client.post("/settings/gmail/disconnect", follow_redirects=False)

        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings?gmail=disconnected"
        revoke.assert_called_once()
        assert revoke.call_args.kwargs["data"] == {"token": "rt-old"}

        user = _load_test_user()
        keys = decrypt_keys(user.encrypted_keys, _FERNET_KEY)
        assert "gmail_refresh_token" not in keys
        assert "gmail_user_email" not in keys
        assert user.gmail_connected_email is None
        assert user.gmail_connected_at is None

    def test_disconnect_survives_revoke_failure(self, client):
        with _db_module.get_session() as s:
            user = s.get(User, _TEST_USER_ID)
            user.encrypted_keys = encrypt_keys(
                {"gmail_refresh_token": "rt-old"}, _FERNET_KEY
            )
        with patch("httpx.post", side_effect=OSError("network down")):
            resp = client.post("/settings/gmail/disconnect", follow_redirects=False)
        assert resp.status_code == 303
        keys = decrypt_keys(_load_test_user().encrypted_keys, _FERNET_KEY)
        assert "gmail_refresh_token" not in keys


# ---------------------------------------------------------------------------
# Per-user settings merge + EmailHandler credentials
# ---------------------------------------------------------------------------


class TestPerUserGmailCreds:
    def test_global_oauth_client_merged_into_user_settings(self):
        from src.api.user_settings import get_settings_for_user

        user = _load_test_user()
        cfg = get_settings_for_user(user)
        assert cfg["gmail_client_id"] == settings.gmail_oauth_client_id
        assert cfg["gmail_client_secret"] == settings.gmail_oauth_client_secret
        assert cfg["gmail_refresh_token"] == ""  # not connected yet

    def test_user_refresh_token_merged(self):
        from src.api.user_settings import get_settings_for_user

        with _db_module.get_session() as s:
            user = s.get(User, _TEST_USER_ID)
            user.encrypted_keys = encrypt_keys(
                {"gmail_refresh_token": "rt-user", "gmail_user_email": "moi@gmail.com"},
                _FERNET_KEY,
            )
        cfg = get_settings_for_user(_load_test_user())
        assert cfg["gmail_refresh_token"] == "rt-user"
        assert cfg["gmail_user_email"] == "moi@gmail.com"
        assert cfg["gmail_client_id"] == settings.gmail_oauth_client_id

    def test_email_handler_uses_user_cfg(self):
        from src.communications.email_handler import EmailHandler

        with patch.object(EmailHandler, "_build_service", return_value=MagicMock()):
            handler = EmailHandler(
                {
                    "gmail_client_id": "cid",
                    "gmail_client_secret": "csec",
                    "gmail_refresh_token": "rt",
                    "gmail_user_email": "moi@gmail.com",
                }
            )
        assert handler._client_id == "cid"
        assert handler._client_secret == "csec"
        assert handler._refresh_token == "rt"
        assert handler._user == "moi@gmail.com"

    def test_email_handler_falls_back_to_global_settings(self, monkeypatch):
        from src.communications.email_handler import EmailHandler

        monkeypatch.setattr(settings, "gmail_client_id", "gcid")
        monkeypatch.setattr(settings, "gmail_client_secret", "gcsec")
        monkeypatch.setattr(settings, "gmail_refresh_token", "grt")
        monkeypatch.setattr(settings, "gmail_user_email", "global@gmail.com")
        with patch.object(EmailHandler, "_build_service", return_value=MagicMock()):
            handler = EmailHandler()  # legacy no-arg call sites keep working
        assert handler._client_id == "gcid"
        assert handler._refresh_token == "grt"
        assert handler._user == "global@gmail.com"

    def test_email_handler_raises_without_creds(self, monkeypatch):
        from src.communications.email_handler import EmailHandler
        from src.config.settings import ConfigurationError

        monkeypatch.setattr(settings, "gmail_client_id", "")
        monkeypatch.setattr(settings, "gmail_client_secret", "")
        monkeypatch.setattr(settings, "gmail_refresh_token", "")
        with pytest.raises(ConfigurationError):
            EmailHandler({})


# ---------------------------------------------------------------------------
# Pipeline respond phase uses per-user credentials
# ---------------------------------------------------------------------------


class TestRespondPhaseCreds:
    def test_run_respond_passes_user_cfg_to_email_handler(self):
        from src.api.routes.pipeline import _run_respond

        user_cfg = {
            "gmail_client_id": "cid",
            "gmail_client_secret": "csec",
            "gmail_refresh_token": "rt-user",
            "gmail_user_email": "moi@gmail.com",
        }
        handler = MagicMock()
        handler.get_unread_replies = AsyncMock(return_value=[])
        with patch(
            "src.api.routes.pipeline.get_settings_for_user", return_value=user_cfg
        ), patch(
            "src.communications.email_handler.EmailHandler", return_value=handler
        ) as handler_cls:
            asyncio.run(_run_respond(_TEST_USER_ID))
        handler_cls.assert_called_once_with(user_cfg)


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------


class TestGmailMigration:
    def test_migrate_adds_gmail_columns_to_legacy_table(self):
        from sqlalchemy import text

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE users (id INTEGER PRIMARY KEY, "
                    "email VARCHAR(255), hashed_password VARCHAR(255))"
                )
            )
            conn.commit()
        _migrate_schema(engine)
        cols = {c["name"] for c in inspect(engine).get_columns("users")}
        assert "gmail_connected_email" in cols
        assert "gmail_connected_at" in cols
        engine.dispose()
