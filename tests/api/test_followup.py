"""Tests for the follow-up (relance) feature: phase, routes, settings, migration.

Reuses the fixtures/conventions of tests/api/test_recruiter_routes.py.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import app
from src.api.background import tracker
from src.api.deps import get_current_user, require_user_redirect
from src.storage import database as _db_module
from src.storage.database import _migrate_schema
from src.storage.models import (
    Application,
    ApplicationStatus,
    Base,
    Company,
    Job,
    JobStatus,
    Recruiter,
    User,
)

_TEST_USER_ID = 1


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


@pytest.fixture()
def client(setup_db):
    _test_user = User(
        id=_TEST_USER_ID, email="test@example.com", hashed_password="x", dry_run=True
    )

    def _fake_user():
        return _test_user

    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[require_user_redirect] = _fake_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _seed_submitted_app(
    days_ago: int = 6,
    status: ApplicationStatus = ApplicationStatus.SUBMITTED,
    gmail_thread_id: str | None = "thread-1",
    followup_draft: bool = False,
    url: str = "https://x/1",
) -> int:
    """Create company + recruiter + job + application; return job id."""
    with _db_module.get_session() as s:
        company = Company(name=f"Acme-{url[-1]}", user_id=_TEST_USER_ID)
        s.add(company)
        s.flush()
        recruiter = Recruiter(
            name="Jane Doe", email=f"jane{url[-1]}@acme.io", source="hunter",
            confidence=0.9, user_id=_TEST_USER_ID, company_id=company.id,
            draft_subject="Original subject", draft_body="Original body",
        )
        s.add(recruiter)
        s.flush()
        job = Job(title="AI Engineer", url=url, source="wttj",
                  user_id=_TEST_USER_ID, company_id=company.id,
                  status=JobStatus.APPLIED)
        s.add(job)
        s.flush()
        app_row = Application(
            job_id=job.id, user_id=_TEST_USER_ID, status=status,
            submitted_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            gmail_thread_id=gmail_thread_id, recruiter_id=recruiter.id,
        )
        if followup_draft:
            app_row.followup_draft_subject = "Re: Original subject"
            app_row.followup_draft_body = "Polite follow-up"
            app_row.followup_generated_at = datetime.now(timezone.utc)
        s.add(app_row)
        return job.id


_GMAIL_CFG = {
    "gmail_client_id": "a", "gmail_client_secret": "b", "gmail_refresh_token": "c",
    "openrouter_api_key": "ok", "llm_provider": "openrouter",
}


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_migration_adds_followup_columns():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE applications (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.commit()
    _migrate_schema(engine)
    insp = inspect(engine)
    app_cols = {c["name"] for c in insp.get_columns("applications")}
    assert {
        "followup_draft_subject", "followup_draft_body",
        "followup_generated_at", "followup_sent_at",
    } <= app_cols
    user_cols = {c["name"] for c in insp.get_columns("users")}
    assert "followup_delay_days" in user_cols


# ---------------------------------------------------------------------------
# Pipeline phase _run_followup
# ---------------------------------------------------------------------------


def _run_phase(user_cfg: dict | None = None):
    from src.api.routes.pipeline import _run_followup

    with patch("src.api.routes.pipeline.get_settings_for_user",
               return_value=user_cfg or {}), \
         patch("src.api.routes.pipeline.get_profile_for_user", return_value={}), \
         patch("src.analysis.recruiter_finder._build_llm_client",
               return_value=MagicMock()), \
         patch("src.communications.followup_writer.draft_followup",
               new_callable=AsyncMock,
               return_value=("Re: Original subject", "Polite follow-up")) as mock_draft:
        asyncio.run(_run_followup(_TEST_USER_ID))
    return mock_draft


def test_run_followup_generates_draft(setup_db):
    job_id = _seed_submitted_app(days_ago=6)
    mock_draft = _run_phase()
    mock_draft.assert_awaited_once()
    with _db_module.get_session() as s:
        app_row = s.query(Application).one()
        assert app_row.followup_draft_subject == "Re: Original subject"
        assert app_row.followup_draft_body == "Polite follow-up"
        assert app_row.followup_generated_at is not None
        assert app_row.followup_sent_at is None


def test_run_followup_skips_recent_and_replied(setup_db):
    _seed_submitted_app(days_ago=2, url="https://x/1")
    _seed_submitted_app(days_ago=10, status=ApplicationStatus.REPLIED, url="https://x/2")
    mock_draft = _run_phase()
    mock_draft.assert_not_awaited()
    with _db_module.get_session() as s:
        assert all(
            a.followup_draft_subject is None for a in s.query(Application).all()
        )


def test_run_followup_respects_user_delay(setup_db):
    _seed_submitted_app(days_ago=6)
    mock_draft = _run_phase(user_cfg={"followup_delay_days": 10})
    mock_draft.assert_not_awaited()


def test_run_followup_skips_already_drafted(setup_db):
    _seed_submitted_app(days_ago=6, followup_draft=True)
    mock_draft = _run_phase()
    mock_draft.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /jobs/{id}/draft-followup
# ---------------------------------------------------------------------------


def test_draft_followup_route_generates(client):
    job_id = _seed_submitted_app(days_ago=6)
    with patch("src.api.user_settings.get_settings_for_user", return_value=_GMAIL_CFG), \
         patch("src.analysis.recruiter_finder._build_llm_client",
               return_value=MagicMock()), \
         patch("src.communications.followup_writer.draft_followup",
               new_callable=AsyncMock,
               return_value=("Re: S", "Follow-up body")):
        r = client.post(f"/jobs/{job_id}/draft-followup")
    assert r.status_code == 200, r.text
    assert "Follow-up body" in r.text
    with _db_module.get_session() as s:
        app_row = s.query(Application).one()
        assert app_row.followup_draft_subject == "Re: S"


def test_draft_followup_422_without_thread(client):
    job_id = _seed_submitted_app(gmail_thread_id=None)
    r = client.post(f"/jobs/{job_id}/draft-followup")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /jobs/{id}/send-followup
# ---------------------------------------------------------------------------


def test_send_followup_dry_run_saves_draft(client):
    job_id = _seed_submitted_app(days_ago=6, followup_draft=True)
    with patch("src.api.user_settings.get_settings_for_user", return_value=_GMAIL_CFG):
        r = client.post(f"/jobs/{job_id}/send-followup",
                        data={"subject": "Edited S", "body": "Edited B"})
    assert r.status_code == 422
    assert "dry-run" in r.json()["detail"].lower()
    with _db_module.get_session() as s:
        app_row = s.query(Application).one()
        assert app_row.followup_draft_subject == "Edited S"
        assert app_row.followup_sent_at is None


def test_send_followup_sends_in_thread(client):
    job_id = _seed_submitted_app(days_ago=6, followup_draft=True)
    with _db_module.get_session() as s:
        s.get(User, _TEST_USER_ID).dry_run = False

    _test_user = User(id=_TEST_USER_ID, email="test@example.com",
                      hashed_password="x", dry_run=False)
    app.dependency_overrides[get_current_user] = lambda: _test_user
    app.dependency_overrides[require_user_redirect] = lambda: _test_user

    fake_handler = AsyncMock()
    fake_handler.send = AsyncMock(return_value="thread-1")
    with patch("src.api.user_settings.get_settings_for_user", return_value=_GMAIL_CFG), \
         patch("src.communications.email_handler.EmailHandler",
               return_value=fake_handler):
        r = client.post(f"/jobs/{job_id}/send-followup",
                        data={"subject": "S", "body": "B"})
    assert r.status_code == 200, r.text
    fake_handler.send.assert_awaited_once()
    assert fake_handler.send.await_args.kwargs["reply_to_thread"] == "thread-1"
    with _db_module.get_session() as s:
        app_row = s.query(Application).one()
        assert app_row.followup_sent_at is not None
    # Sent state rendered
    assert "followup-section" in r.text


def test_send_followup_422_when_already_sent(client):
    job_id = _seed_submitted_app(days_ago=6, followup_draft=True)
    with _db_module.get_session() as s:
        s.query(Application).one().followup_sent_at = datetime.now(timezone.utc)
    with patch("src.api.user_settings.get_settings_for_user", return_value=_GMAIL_CFG):
        r = client.post(f"/jobs/{job_id}/send-followup",
                        data={"subject": "S", "body": "B"})
    assert r.status_code == 422
    assert "already sent" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Job detail + settings
# ---------------------------------------------------------------------------


def test_job_detail_shows_followup_section(client):
    job_id = _seed_submitted_app(days_ago=6, followup_draft=True)
    r = client.get(f"/jobs/{job_id}")
    assert r.status_code == 200
    assert "followup-section" in r.text
    assert "Polite follow-up" in r.text


def test_settings_update_followup_delay(client):
    r = client.post("/settings/search",
                    data={"max_days_old": "30", "followup_delay_days": "9"})
    assert r.status_code == 200
    with _db_module.get_session() as s:
        assert s.get(User, _TEST_USER_ID).followup_delay_days == 9
