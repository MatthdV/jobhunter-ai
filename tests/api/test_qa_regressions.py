"""Regression tests for bugs found by /qa on 2026-06-11.

Report: .gstack/qa-reports/qa-report-jobhunter-ai-production-2026-06-11.md
Reuses the fixtures/conventions of tests/api/test_api.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import app
from src.api.background import TaskStatus, tracker
from src.api.deps import get_current_user, require_user_redirect
from src.storage import database as _db_module
from src.storage.models import Base, User


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
    _test_user = User(id=_TEST_USER_ID, email="test@example.com", hashed_password="x")

    def _fake_user():
        return _test_user

    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[require_user_redirect] = _fake_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(require_user_redirect, None)


class TestSourceWhitelist:
    """Regression: ISSUE-001 — adzuna/france_travail rejected by source API.

    Found by /qa on 2026-06-11: the settings UI exposes 5 sources but
    AVAILABLE_SOURCES only listed 3, so toggling Adzuna or France Travail
    returned 422 'Unknown source'.
    """

    @pytest.mark.parametrize("source", ["wttj", "indeed", "linkedin", "adzuna", "france_travail"])
    def test_toggle_accepts_all_ui_sources(self, client: TestClient, source: str):
        resp = client.post("/api/profile/sources", json={"source": source, "enabled": True})
        assert resp.status_code == 200
        assert source in resp.json()["active_sources"]

    def test_toggle_rejects_unknown_source(self, client: TestClient):
        resp = client.post("/api/profile/sources", json={"source": "monster", "enabled": True})
        assert resp.status_code == 422

    @pytest.mark.parametrize("source", ["adzuna", "france_travail"])
    def test_source_config_accepts_api_sources(self, client: TestClient, source: str):
        resp = client.put(
            "/api/profile/source-config",
            json={"source": source, "keywords": ["python"], "location": "Paris", "work_modes": ["remote"]},
        )
        assert resp.status_code == 200


class TestPhaseNotStuckAfterConfig400:
    """Regression: ISSUE-002 — config 400 left the phase stuck in RUNNING.

    Found by /qa on 2026-06-11: trigger_respond marked the phase running
    before its Gmail config check; the 400 left the tracker in RUNNING
    forever, so every retry got 409 until app restart.
    """

    def _clear_ai_keys(self):
        from src.config.settings import settings
        keys = ("anthropic_api_key", "openai_api_key", "mistral_api_key",
                "deepseek_api_key", "openrouter_api_key")
        originals = {k: getattr(settings, k) for k in keys}
        for k in keys:
            setattr(settings, k, "")
        return originals

    def test_respond_400_releases_running_slot(self, client: TestClient):
        resp = client.post("/api/pipeline/respond")
        assert resp.status_code == 400
        # Phase must NOT be left running — a retry must reach the 400 again,
        # not a 409 'already running'.
        assert tracker.get("respond", user_id=_TEST_USER_ID)["status"] != TaskStatus.RUNNING
        retry = client.post("/api/pipeline/respond")
        assert retry.status_code == 400

    def test_match_400_releases_running_slot(self, client: TestClient):
        from src.config.settings import settings
        originals = self._clear_ai_keys()
        try:
            resp = client.post("/api/pipeline/match")
            assert resp.status_code == 400
            assert tracker.get("match", user_id=_TEST_USER_ID)["status"] != TaskStatus.RUNNING
            retry = client.post("/api/pipeline/match")
            assert retry.status_code == 400
        finally:
            for k, v in originals.items():
                setattr(settings, k, v)

    def test_apply_400_releases_running_slot(self, client: TestClient):
        from src.config.settings import settings
        originals = self._clear_ai_keys()
        try:
            resp = client.post("/api/pipeline/apply")
            assert resp.status_code == 400
            assert tracker.get("apply", user_id=_TEST_USER_ID)["status"] != TaskStatus.RUNNING
        finally:
            for k, v in originals.items():
                setattr(settings, k, v)

    def test_match_still_409_when_already_running(self, client: TestClient):
        # 409 priority is the existing contract — must survive the fix.
        tracker.start("match", user_id=_TEST_USER_ID)
        resp = client.post("/api/pipeline/match")
        assert resp.status_code == 409


class TestScanSurfacesSourceErrors:
    """Regression: ISSUE-003 — scan reported 'done, 0 jobs' on silent failure.

    Found by /qa on 2026-06-11: enabled sources without search_terms (the
    default onboarding state) were skipped silently and scan finished green
    with new_jobs=0 and no explanation.
    """

    def test_scan_with_keywordless_sources_reports_error(self, client: TestClient):
        import asyncio
        from src.api.routes.pipeline import _run_scan
        from src.storage.database import get_session

        # Enabled source without search_terms = the default onboarding state.
        with get_session() as session:
            user = session.get(User, _TEST_USER_ID)
            user.profile_yaml = (
                "job_sources:\n"
                "- name: adzuna\n"
                "  enabled: true\n"
                "  search_terms: []\n"
            )

        asyncio.run(_run_scan(_TEST_USER_ID))
        info = tracker.get("scan", user_id=_TEST_USER_ID)
        # All sources failed/skipped with 0 jobs → phase must be ERROR with a
        # message, not a green 'done' with new_jobs=0.
        assert info["status"] == TaskStatus.ERROR
        assert "mot-clé" in (info.get("error") or "")
