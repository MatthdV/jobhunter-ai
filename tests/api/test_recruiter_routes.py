"""Tests for the recruiter contact routes (find / section / draft / send).

Reuses the fixtures/conventions of tests/api/test_qa_regressions.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import app
from src.api.deps import get_current_user, require_user_redirect
from src.storage import database as _db_module
from src.storage.models import (
    Application,
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


def _seed_job(with_recruiter: bool = False, recruiter_email: str | None = None,
              search_status: str | None = None) -> int:
    with _db_module.get_session() as s:
        company = Company(name="Acme", user_id=_TEST_USER_ID,
                          recruiter_search_status=search_status)
        s.add(company)
        s.flush()
        job = Job(title="AI Engineer", url="https://x/1", source="wttj",
                  user_id=_TEST_USER_ID, company_id=company.id,
                  status=JobStatus.MATCHED)
        s.add(job)
        s.flush()
        if with_recruiter:
            s.add(Recruiter(name="Jane Doe", title="TA Manager",
                            email=recruiter_email,
                            linkedin_url="https://linkedin.com/in/jane",
                            source="hunter", confidence=0.9,
                            user_id=_TEST_USER_ID, company_id=company.id))
        return job.id


_KEYS_OK = {"hunter_api_key": "hk", "brave_api_key": "", "llm_provider": "openrouter",
            "openrouter_api_key": "ok", "gmail_client_id": "", "gmail_client_secret": "",
            "gmail_refresh_token": ""}
_NO_KEYS = {"hunter_api_key": "", "brave_api_key": ""}


# ---------------------------------------------------------------------------
# GET /jobs/{id}/recruiter-section
# ---------------------------------------------------------------------------


def test_section_not_searched_state(client):
    job_id = _seed_job()
    with patch("src.api.user_settings.get_settings_for_user", return_value=_KEYS_OK) as _:
        with patch("src.api.routes.pages._recruiter_keys_configured", return_value=True):
            r = client.get(f"/jobs/{job_id}/recruiter-section")
    assert r.status_code == 200
    assert "Trouver le recruteur" in r.text


def test_section_found_state_shows_contact(client):
    job_id = _seed_job(with_recruiter=True, recruiter_email="jane@acme.io",
                       search_status="found")
    with patch("src.api.routes.pages._recruiter_keys_configured", return_value=True):
        r = client.get(f"/jobs/{job_id}/recruiter-section")
    assert r.status_code == 200
    assert "Jane Doe" in r.text
    assert "linkedin.com/in/jane" in r.text
    assert "jane@acme.io" in r.text


def test_section_searching_state_polls(client):
    job_id = _seed_job(search_status="searching")
    with patch("src.api.routes.pages._recruiter_keys_configured", return_value=True):
        r = client.get(f"/jobs/{job_id}/recruiter-section")
    assert "hx-trigger" in r.text and "every 2s" in r.text


def test_section_not_found_state(client):
    job_id = _seed_job(search_status="not_found")
    with patch("src.api.routes.pages._recruiter_keys_configured", return_value=True):
        r = client.get(f"/jobs/{job_id}/recruiter-section")
    assert "Réessayer" in r.text


def test_section_404_for_other_users_job(client):
    with _db_module.get_session() as s:
        s.add(User(id=2, email="other@example.com", hashed_password="x"))
        job = Job(title="X", url="https://x/2", source="wttj", user_id=2)
        s.add(job)
        s.flush()
        other_job_id = job.id
    r = client.get(f"/jobs/{other_job_id}/recruiter-section")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /jobs/{id}/find-recruiter
# ---------------------------------------------------------------------------


def test_find_recruiter_schedules_task_and_returns_searching(client):
    job_id = _seed_job()
    with patch("src.api.routes.pages._recruiter_keys_configured", return_value=True), \
         patch("src.analysis.recruiter_finder.find_and_persist_recruiter",
               new_callable=AsyncMock) as task:
        r = client.post(f"/jobs/{job_id}/find-recruiter")
    assert r.status_code == 200
    assert "every 2s" in r.text  # searching partial
    task.assert_called_once_with(job_id, _TEST_USER_ID)
    with _db_module.get_session() as s:
        job = s.get(Job, job_id)
        assert job.company.recruiter_search_status == "searching"


def test_find_recruiter_422_without_keys(client):
    job_id = _seed_job()
    with patch("src.api.routes.pages._recruiter_keys_configured", return_value=False):
        r = client.post(f"/jobs/{job_id}/find-recruiter")
    assert r.status_code == 422


def test_find_recruiter_idempotent_while_searching(client):
    job_id = _seed_job(search_status="searching")
    with patch("src.api.routes.pages._recruiter_keys_configured", return_value=True), \
         patch("src.analysis.recruiter_finder.find_and_persist_recruiter",
               new_callable=AsyncMock) as task:
        r = client.post(f"/jobs/{job_id}/find-recruiter")
    assert r.status_code == 200
    task.assert_not_called()


def test_find_recruiter_422_without_company(client):
    with _db_module.get_session() as s:
        job = Job(title="X", url="https://x/3", source="wttj", user_id=_TEST_USER_ID)
        s.add(job)
        s.flush()
        job_id = job.id
    with patch("src.api.routes.pages._recruiter_keys_configured", return_value=True):
        r = client.post(f"/jobs/{job_id}/find-recruiter")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /jobs/{id}/draft-email
# ---------------------------------------------------------------------------


def test_draft_email_persists_draft(client):
    job_id = _seed_job(with_recruiter=True, recruiter_email="jane@acme.io",
                       search_status="found")
    fake_client = object()
    with patch("src.analysis.recruiter_finder._build_llm_client",
               return_value=fake_client), \
         patch("src.api.user_settings.get_settings_for_user", return_value=_KEYS_OK), \
         patch("src.config.profile.get_profile_for_user", return_value={"candidate": {}}), \
         patch("src.communications.outreach_writer.draft_outreach",
               new_callable=AsyncMock, return_value=("Sujet", "Corps du mail")):
        r = client.post(f"/jobs/{job_id}/draft-email")
    assert r.status_code == 200
    assert "Sujet" in r.text and "Corps du mail" in r.text
    with _db_module.get_session() as s:
        rec = s.query(Recruiter).one()
        assert rec.draft_subject == "Sujet"
        assert rec.draft_body == "Corps du mail"


def test_draft_email_422_without_recruiter(client):
    job_id = _seed_job()
    r = client.post(f"/jobs/{job_id}/draft-email")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /jobs/{id}/send-recruiter-email
# ---------------------------------------------------------------------------


def test_send_respects_dry_run(client):
    job_id = _seed_job(with_recruiter=True, recruiter_email="jane@acme.io",
                       search_status="found")
    gmail_cfg = dict(_KEYS_OK, gmail_client_id="a", gmail_client_secret="b",
                     gmail_refresh_token="c")
    with patch("src.api.user_settings.get_settings_for_user", return_value=gmail_cfg):
        r = client.post(f"/jobs/{job_id}/send-recruiter-email",
                        data={"subject": "S", "body": "B"})
    assert r.status_code == 422
    assert "dry-run" in r.json()["detail"].lower()
    # Draft edits are persisted even when nothing is sent
    with _db_module.get_session() as s:
        rec = s.query(Recruiter).one()
        assert rec.draft_subject == "S"


def test_send_422_without_recruiter_email(client):
    job_id = _seed_job(with_recruiter=True, recruiter_email=None,
                       search_status="found")
    r = client.post(f"/jobs/{job_id}/send-recruiter-email",
                    data={"subject": "S", "body": "B"})
    assert r.status_code == 422


def test_send_creates_application_and_thread(client):
    job_id = _seed_job(with_recruiter=True, recruiter_email="jane@acme.io",
                       search_status="found")
    with _db_module.get_session() as s:
        user = s.get(User, _TEST_USER_ID)
        user.dry_run = False

    _test_user = User(id=_TEST_USER_ID, email="test@example.com",
                      hashed_password="x", dry_run=False)
    app.dependency_overrides[get_current_user] = lambda: _test_user
    app.dependency_overrides[require_user_redirect] = lambda: _test_user

    gmail_cfg = dict(_KEYS_OK, gmail_client_id="a", gmail_client_secret="b",
                     gmail_refresh_token="c")
    fake_handler = AsyncMock()
    fake_handler.send = AsyncMock(return_value="thread-42")
    with patch("src.api.user_settings.get_settings_for_user", return_value=gmail_cfg), \
         patch("src.communications.email_handler.EmailHandler",
               return_value=fake_handler):
        r = client.post(f"/jobs/{job_id}/send-recruiter-email",
                        data={"subject": "S", "body": "B"})
    assert r.status_code == 200, r.text
    fake_handler.send.assert_awaited_once()
    with _db_module.get_session() as s:
        job = s.get(Job, job_id)
        assert str(job.status) == "applied"
        app_row = s.query(Application).one()
        assert app_row.gmail_thread_id == "thread-42"
        assert app_row.recruiter_id is not None
