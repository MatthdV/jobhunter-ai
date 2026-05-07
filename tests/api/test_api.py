"""Comprehensive tests for the JobHunter AI FastAPI dashboard.

Covers: stats, jobs CRUD, pipeline triggers, page routes, and edge cases.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import app
from src.api.background import TaskStatus, tracker
from src.storage import database as _db_module
from src.storage.database import configure, drop_all, get_session, init_db
from src.storage.models import (
    Application,
    ApplicationStatus,
    Base,
    Company,
    Job,
    JobStatus,
    Recruiter,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_db():
    """Fresh in-memory SQLite DB for each test using StaticPool.

    StaticPool ensures all sessions share the same in-memory connection, which
    is required for sqlite:///:memory: — otherwise each new connection gets an
    empty database (no tables).
    """
    # Build a single-connection pool engine
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Inject into the database module so get_session() uses this engine
    _db_module._engine = engine
    _db_module._SessionLocal = session_factory

    # Create tables on our engine
    Base.metadata.create_all(bind=engine)

    # Reset the singleton tracker so pipeline state doesn't bleed between tests
    tracker._tasks.clear()

    yield

    # Teardown
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    _db_module._engine = None
    _db_module._SessionLocal = None


@pytest.fixture()
def client(setup_db):  # explicit dependency ensures setup_db runs first
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(
    title: str = "Engineer",
    url: str = "https://example.com/job/1",
    source: str = "wttj",
    status: JobStatus = JobStatus.NEW,
    match_score: float | None = None,
    scraped_at: datetime | None = None,
    company: Company | None = None,
    salary_min: int | None = None,
    salary_max: int | None = None,
) -> Job:
    return Job(
        title=title,
        url=url,
        source=source,
        status=status,
        match_score=match_score,
        scraped_at=scraped_at or datetime.utcnow(),
        company=company,
        salary_min=salary_min,
        salary_max=salary_max,
    )


def _make_company(name: str = "Acme Corp") -> Company:
    return Company(name=name)


def _make_application(
    job: Job,
    status: ApplicationStatus = ApplicationStatus.DRAFT,
    submitted_at: datetime | None = None,
) -> Application:
    return Application(
        job=job,
        status=status,
        submitted_at=submitted_at,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


# ---------------------------------------------------------------------------
# Stats endpoint — GET /api/stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_empty_db_returns_all_zeros(self, client: TestClient):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["today"]["scanned"] == 0
        assert data["today"]["matched"] == 0
        assert data["today"]["applied"] == 0
        assert data["today"]["replied"] == 0
        assert data["total"]["scanned"] == 0
        assert data["total"]["matched"] == 0
        assert data["total"]["applied"] == 0
        assert data["total"]["replied"] == 0

    def test_total_scanned_includes_all_jobs(self, client: TestClient):
        with get_session() as session:
            session.add(_make_job(url="https://example.com/1"))
            session.add(_make_job(url="https://example.com/2"))
        resp = client.get("/api/stats")
        assert resp.json()["total"]["scanned"] == 2

    def test_today_scanned_only_counts_jobs_scraped_today(self, client: TestClient):
        yesterday = datetime.utcnow() - timedelta(days=1)
        with get_session() as session:
            session.add(_make_job(url="https://example.com/today", scraped_at=datetime.utcnow()))
            session.add(_make_job(url="https://example.com/yesterday", scraped_at=yesterday))
        resp = client.get("/api/stats")
        data = resp.json()
        assert data["today"]["scanned"] == 1
        assert data["total"]["scanned"] == 2

    def test_total_matched_counts_matched_pending_applied(self, client: TestClient):
        with get_session() as session:
            session.add(_make_job(url="https://example.com/1", status=JobStatus.MATCHED))
            session.add(_make_job(url="https://example.com/2", status=JobStatus.PENDING))
            session.add(_make_job(url="https://example.com/3", status=JobStatus.APPLIED))
            session.add(_make_job(url="https://example.com/4", status=JobStatus.NEW))
            session.add(_make_job(url="https://example.com/5", status=JobStatus.SKIPPED))
        resp = client.get("/api/stats")
        assert resp.json()["total"]["matched"] == 3

    def test_total_applied_counts_only_submitted_applications(self, client: TestClient):
        with get_session() as session:
            j1 = _make_job(url="https://example.com/1")
            j2 = _make_job(url="https://example.com/2")
            session.add(j1)
            session.add(j2)
            session.flush()
            session.add(Application(job_id=j1.id, status=ApplicationStatus.SUBMITTED,
                                    created_at=datetime.utcnow(), updated_at=datetime.utcnow()))
            session.add(Application(job_id=j2.id, status=ApplicationStatus.DRAFT,
                                    created_at=datetime.utcnow(), updated_at=datetime.utcnow()))
        resp = client.get("/api/stats")
        assert resp.json()["total"]["applied"] == 1

    def test_total_replied_counts_replied_interview_offer(self, client: TestClient):
        with get_session() as session:
            for i, st in enumerate([
                ApplicationStatus.REPLIED,
                ApplicationStatus.INTERVIEW,
                ApplicationStatus.OFFER,
                ApplicationStatus.DRAFT,
            ]):
                j = _make_job(url=f"https://example.com/{i}")
                session.add(j)
                session.flush()
                session.add(Application(job_id=j.id, status=st,
                                        created_at=datetime.utcnow(), updated_at=datetime.utcnow()))
        resp = client.get("/api/stats")
        assert resp.json()["total"]["replied"] == 3

    def test_pipeline_status_idle_by_default(self, client: TestClient):
        resp = client.get("/api/stats")
        phases = resp.json()["pipeline_status"]
        assert "scan" in phases
        assert phases["scan"]["status"] == "idle"
        assert phases["match"]["status"] == "idle"
        assert phases["apply"]["status"] == "idle"
        assert phases["respond"]["status"] == "idle"

    def test_pipeline_status_reflects_tracker_state(self, client: TestClient):
        tracker.start("scan")
        resp = client.get("/api/stats")
        assert resp.json()["pipeline_status"]["scan"]["status"] == "running"


# ---------------------------------------------------------------------------
# Jobs list — GET /api/jobs
# ---------------------------------------------------------------------------


class TestJobsList:
    def test_empty_db_returns_empty_list(self, client: TestClient):
        resp = client.get("/api/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_returns_jobs_with_correct_fields(self, client: TestClient):
        with get_session() as session:
            session.add(_make_job(title="SRE Role", url="https://example.com/sre"))
        resp = client.get("/api/jobs")
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["title"] == "SRE Role"
        assert item["url"] == "https://example.com/sre"
        assert "status" in item
        assert "scraped_at" in item

    def test_returns_jobs_sorted_by_scraped_at_desc(self, client: TestClient):
        now = datetime.utcnow()
        with get_session() as session:
            session.add(_make_job(url="https://example.com/old",
                                  scraped_at=now - timedelta(hours=2)))
            session.add(_make_job(url="https://example.com/new",
                                  scraped_at=now - timedelta(hours=1)))
            session.add(_make_job(url="https://example.com/newest",
                                  scraped_at=now))
        resp = client.get("/api/jobs")
        items = resp.json()["items"]
        times = [item["scraped_at"] for item in items]
        assert times == sorted(times, reverse=True)

    def test_filter_by_status_matched(self, client: TestClient):
        with get_session() as session:
            session.add(_make_job(url="https://example.com/1", status=JobStatus.MATCHED))
            session.add(_make_job(url="https://example.com/2", status=JobStatus.NEW))
            session.add(_make_job(url="https://example.com/3", status=JobStatus.SKIPPED))
        resp = client.get("/api/jobs?status=matched")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert all(item["status"] == "matched" for item in data["items"])

    def test_filter_by_status_new(self, client: TestClient):
        with get_session() as session:
            session.add(_make_job(url="https://example.com/1", status=JobStatus.NEW))
            session.add(_make_job(url="https://example.com/2", status=JobStatus.MATCHED))
        resp = client.get("/api/jobs?status=new")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["status"] == "new"

    def test_invalid_status_returns_422(self, client: TestClient):
        resp = client.get("/api/jobs?status=not_a_status")
        assert resp.status_code == 422

    def test_pagination_limit_and_offset(self, client: TestClient):
        with get_session() as session:
            for i in range(10):
                session.add(_make_job(url=f"https://example.com/{i}"))
        resp = client.get("/api/jobs?limit=3&offset=0")
        data = resp.json()
        assert len(data["items"]) == 3
        assert data["total"] == 10
        assert data["limit"] == 3
        assert data["offset"] == 0

    def test_pagination_offset_beyond_total_returns_empty(self, client: TestClient):
        with get_session() as session:
            session.add(_make_job(url="https://example.com/1"))
        resp = client.get("/api/jobs?offset=999999")
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 1

    def test_large_offset_does_not_error(self, client: TestClient):
        resp = client.get("/api/jobs?offset=999999")
        assert resp.status_code == 200

    def test_job_with_no_company_returns_null_company(self, client: TestClient):
        with get_session() as session:
            session.add(_make_job(url="https://example.com/1"))
        resp = client.get("/api/jobs")
        assert resp.json()["items"][0]["company"] is None

    def test_job_with_company_returns_company_name(self, client: TestClient):
        with get_session() as session:
            company = _make_company("Startup Inc")
            session.add(company)
            session.flush()
            session.add(_make_job(url="https://example.com/1", company=company))
        resp = client.get("/api/jobs")
        assert resp.json()["items"][0]["company"]["name"] == "Startup Inc"

    def test_job_with_no_application_returns_null_application(self, client: TestClient):
        with get_session() as session:
            session.add(_make_job(url="https://example.com/1"))
        resp = client.get("/api/jobs")
        assert resp.json()["items"][0]["application"] is None

    def test_job_with_application_returns_application_nested(self, client: TestClient):
        with get_session() as session:
            j = _make_job(url="https://example.com/1")
            session.add(j)
            session.flush()
            session.add(Application(job_id=j.id, status=ApplicationStatus.DRAFT,
                                    created_at=datetime.utcnow(), updated_at=datetime.utcnow()))
        resp = client.get("/api/jobs")
        app_data = resp.json()["items"][0]["application"]
        assert app_data is not None
        assert app_data["status"] == "draft"

    def test_match_score_none_serializes_as_null(self, client: TestClient):
        with get_session() as session:
            session.add(_make_job(url="https://example.com/1", match_score=None))
        resp = client.get("/api/jobs")
        assert resp.json()["items"][0]["match_score"] is None

    def test_null_salary_fields_serialize_as_null(self, client: TestClient):
        with get_session() as session:
            session.add(_make_job(url="https://example.com/1", salary_min=None, salary_max=None))
        resp = client.get("/api/jobs")
        item = resp.json()["items"][0]
        assert item["salary_min"] is None
        assert item["salary_max"] is None

    def test_invalid_limit_type_returns_422(self, client: TestClient):
        resp = client.get("/api/jobs?limit=abc")
        assert resp.status_code == 422

    def test_limit_zero_blocked_by_ge_constraint(self, client: TestClient):
        # limit has ge=1 constraint
        resp = client.get("/api/jobs?limit=0")
        assert resp.status_code == 422

    def test_special_chars_in_title_returned_safely(self, client: TestClient):
        with get_session() as session:
            session.add(_make_job(
                title='<script>alert(1)</script>',
                url="https://example.com/xss"
            ))
        resp = client.get("/api/jobs")
        assert resp.status_code == 200
        # Title is returned as-is in JSON (escaping is the browser's job for HTML)
        assert resp.json()["items"][0]["title"] == "<script>alert(1)</script>"

    def test_response_includes_limit_and_offset_echo(self, client: TestClient):
        resp = client.get("/api/jobs?limit=10&offset=5")
        data = resp.json()
        assert data["limit"] == 10
        assert data["offset"] == 5


# ---------------------------------------------------------------------------
# Job detail — GET /api/jobs/{id}
# ---------------------------------------------------------------------------


class TestJobDetail:
    def test_valid_id_returns_job(self, client: TestClient):
        with get_session() as session:
            j = _make_job(title="Backend Dev", url="https://example.com/1")
            session.add(j)
            session.flush()
            job_id = j.id

        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Backend Dev"
        assert data["id"] == job_id

    def test_nonexistent_id_returns_404(self, client: TestClient):
        resp = client.get("/api/jobs/99999")
        assert resp.status_code == 404

    def test_job_with_application_nested_in_detail(self, client: TestClient):
        with get_session() as session:
            j = _make_job(url="https://example.com/1")
            session.add(j)
            session.flush()
            session.add(Application(job_id=j.id, status=ApplicationStatus.PENDING_VALIDATION,
                                    created_at=datetime.utcnow(), updated_at=datetime.utcnow()))
            job_id = j.id

        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        app_data = resp.json()["application"]
        assert app_data is not None
        assert app_data["status"] == "pending_validation"

    def test_job_with_company_in_detail(self, client: TestClient):
        with get_session() as session:
            c = _make_company("BigCo")
            session.add(c)
            session.flush()
            j = _make_job(url="https://example.com/1", company=c)
            session.add(j)
            session.flush()
            job_id = j.id

        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["company"]["name"] == "BigCo"

    def test_job_with_no_company_returns_null_in_detail(self, client: TestClient):
        with get_session() as session:
            j = _make_job(url="https://example.com/1")
            session.add(j)
            session.flush()
            job_id = j.id

        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.json()["company"] is None

    def test_job_detail_no_application_returns_null(self, client: TestClient):
        with get_session() as session:
            j = _make_job(url="https://example.com/1")
            session.add(j)
            session.flush()
            job_id = j.id

        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.json()["application"] is None


# ---------------------------------------------------------------------------
# Job update — PATCH /api/jobs/{id}
# ---------------------------------------------------------------------------


class TestJobPatch:
    def _create_job(self) -> int:
        with get_session() as session:
            j = _make_job(url="https://example.com/1", status=JobStatus.NEW)
            session.add(j)
            session.flush()
            return j.id

    def test_update_status_to_valid_value_succeeds(self, client: TestClient):
        job_id = self._create_job()
        resp = client.patch(f"/api/jobs/{job_id}", json={"status": "matched"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "matched"

    def test_update_status_persisted_in_db(self, client: TestClient):
        job_id = self._create_job()
        client.patch(f"/api/jobs/{job_id}", json={"status": "skipped"})
        with get_session() as session:
            job = session.get(Job, job_id)
            assert job.status == JobStatus.SKIPPED

    def test_nonexistent_id_returns_404(self, client: TestClient):
        resp = client.patch("/api/jobs/99999", json={"status": "matched"})
        assert resp.status_code == 404

    def test_invalid_status_value_returns_422(self, client: TestClient):
        job_id = self._create_job()
        resp = client.patch(f"/api/jobs/{job_id}", json={"status": "nonexistent_status"})
        assert resp.status_code == 422

    def test_patch_with_null_status_is_noop(self, client: TestClient):
        job_id = self._create_job()
        resp = client.patch(f"/api/jobs/{job_id}", json={"status": None})
        assert resp.status_code == 200
        assert resp.json()["status"] == "new"

    def test_patch_all_valid_statuses(self, client: TestClient):
        for status in JobStatus:
            with get_session() as session:
                j = _make_job(url=f"https://example.com/{status.value}")
                session.add(j)
                session.flush()
                job_id = j.id
            resp = client.patch(f"/api/jobs/{job_id}", json={"status": status.value})
            assert resp.status_code == 200
            assert resp.json()["status"] == status.value


# ---------------------------------------------------------------------------
# Pipeline triggers
# ---------------------------------------------------------------------------


class TestPipelineScan:
    def test_post_scan_returns_started(self, client: TestClient):
        """Endpoint returns immediately with started status; background task is mocked."""
        from unittest.mock import AsyncMock
        with patch("src.api.routes.pipeline._run_scan", new_callable=AsyncMock):
            resp = client.post("/api/pipeline/scan")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert data["phase"] == "scan"

    def test_second_scan_while_running_returns_409(self, client: TestClient):
        tracker.start("scan")  # Manually mark as running
        resp = client.post("/api/pipeline/scan")
        assert resp.status_code == 409

    def test_scan_response_includes_message(self, client: TestClient):
        from unittest.mock import AsyncMock
        with patch("src.api.routes.pipeline._run_scan", new_callable=AsyncMock):
            resp = client.post("/api/pipeline/scan")
        assert resp.status_code == 200
        assert "message" in resp.json()

    def test_scan_no_longer_uses_ensure_future(self, client: TestClient):
        """Fixed: background_tasks.add_task(_run_scan) works without event loop tricks.

        Previously the route called asyncio.ensure_future which crashed outside an
        event loop. Now it delegates directly to FastAPI BackgroundTasks.
        """
        from unittest.mock import AsyncMock
        with patch("src.api.routes.pipeline._run_scan", new_callable=AsyncMock):
            resp = client.post("/api/pipeline/scan")
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"


class TestPipelineMatch:
    def test_match_returns_400_when_no_api_key(self, client: TestClient):
        from src.config.settings import settings
        original = settings.anthropic_api_key
        settings.anthropic_api_key = ""
        try:
            resp = client.post("/api/pipeline/match")
            assert resp.status_code == 400
            assert "AI provider" in resp.json()["detail"]
        finally:
            settings.anthropic_api_key = original

    def test_match_409_when_already_running(self, client: TestClient):
        tracker.start("match")
        resp = client.post("/api/pipeline/match")
        assert resp.status_code == 409

    def test_match_returns_started_when_configured(self, client: TestClient):
        from unittest.mock import AsyncMock
        from src.config.settings import settings
        settings.anthropic_api_key = "fake-key-for-testing"
        try:
            with patch("src.api.routes.pipeline._run_match", new_callable=AsyncMock):
                resp = client.post("/api/pipeline/match")
            assert resp.status_code == 200
            assert resp.json()["status"] == "started"
        finally:
            settings.anthropic_api_key = ""


class TestPipelineApply:
    def test_apply_returns_400_when_no_api_key(self, client: TestClient):
        from src.config.settings import settings
        original = settings.anthropic_api_key
        settings.anthropic_api_key = ""
        try:
            resp = client.post("/api/pipeline/apply")
            assert resp.status_code == 400
        finally:
            settings.anthropic_api_key = original

    def test_apply_dry_run_true_by_default(self, client: TestClient):
        from unittest.mock import AsyncMock
        from src.config.settings import settings
        settings.anthropic_api_key = "fake-key"
        try:
            with patch("src.api.routes.pipeline._run_apply", new_callable=AsyncMock):
                resp = client.post("/api/pipeline/apply")
            assert resp.status_code == 200
            assert "dry_run=True" in resp.json()["message"]
        finally:
            settings.anthropic_api_key = ""

    def test_apply_dry_run_false_reflected_in_message(self, client: TestClient):
        from unittest.mock import AsyncMock
        from src.config.settings import settings
        settings.anthropic_api_key = "fake-key"
        try:
            with patch("src.api.routes.pipeline._run_apply", new_callable=AsyncMock):
                resp = client.post("/api/pipeline/apply?dry_run=false")
            assert resp.status_code == 200
            assert "dry_run=False" in resp.json()["message"]
        finally:
            settings.anthropic_api_key = ""

    def test_apply_409_when_already_running(self, client: TestClient):
        tracker.start("apply")
        resp = client.post("/api/pipeline/apply")
        assert resp.status_code == 409


class TestPipelineRespond:
    def test_respond_returns_400_when_gmail_not_configured(self, client: TestClient):
        from src.config.settings import settings
        orig_id = settings.gmail_client_id
        orig_secret = settings.gmail_client_secret
        orig_token = settings.gmail_refresh_token
        settings.gmail_client_id = ""
        settings.gmail_client_secret = ""
        settings.gmail_refresh_token = ""
        try:
            resp = client.post("/api/pipeline/respond")
            assert resp.status_code == 400
            assert "Gmail" in resp.json()["detail"]
        finally:
            settings.gmail_client_id = orig_id
            settings.gmail_client_secret = orig_secret
            settings.gmail_refresh_token = orig_token

    def test_respond_409_when_already_running(self, client: TestClient):
        tracker.start("respond")
        resp = client.post("/api/pipeline/respond")
        assert resp.status_code == 409


class TestPipelineStatus:
    def test_status_returns_all_four_phases(self, client: TestClient):
        resp = client.get("/api/pipeline/status")
        assert resp.status_code == 200
        phases = resp.json()["phases"]
        assert set(phases.keys()) == {"scan", "match", "apply", "respond"}

    def test_all_phases_idle_by_default(self, client: TestClient):
        resp = client.get("/api/pipeline/status")
        phases = resp.json()["phases"]
        for phase in ["scan", "match", "apply", "respond"]:
            assert phases[phase]["status"] == "idle"

    def test_status_reflects_running_phase(self, client: TestClient):
        tracker.start("apply")
        resp = client.get("/api/pipeline/status")
        assert resp.json()["phases"]["apply"]["status"] == "running"

    def test_status_reflects_done_phase(self, client: TestClient):
        tracker.done("scan", result={"new_jobs": 5})
        resp = client.get("/api/pipeline/status")
        phases = resp.json()["phases"]
        assert phases["scan"]["status"] == "done"
        assert phases["scan"]["result"]["new_jobs"] == 5

    def test_status_reflects_error_phase(self, client: TestClient):
        tracker.error("match", "something went wrong")
        resp = client.get("/api/pipeline/status")
        phases = resp.json()["phases"]
        assert phases["match"]["status"] == "error"
        assert phases["match"]["error"] == "something went wrong"


# ---------------------------------------------------------------------------
# Task tracker — unit tests
# ---------------------------------------------------------------------------


class TestTaskTracker:
    def test_idle_by_default(self):
        tracker._tasks.clear()
        assert tracker.get("scan")["status"] == TaskStatus.IDLE

    def test_start_sets_running(self):
        tracker._tasks.clear()
        tracker.start("scan")
        assert tracker.is_running("scan")
        assert tracker.get("scan")["status"] == TaskStatus.RUNNING

    def test_done_sets_done(self):
        tracker._tasks.clear()
        tracker.start("scan")
        tracker.done("scan", result={"new_jobs": 3})
        assert tracker.get("scan")["status"] == TaskStatus.DONE
        assert tracker.get("scan")["result"]["new_jobs"] == 3
        assert not tracker.is_running("scan")

    def test_error_sets_error(self):
        tracker._tasks.clear()
        tracker.error("scan", "exploded")
        assert tracker.get("scan")["status"] == TaskStatus.ERROR
        assert tracker.get("scan")["error"] == "exploded"

    def test_all_returns_four_phases(self):
        tracker._tasks.clear()
        all_phases = tracker.all()
        assert set(all_phases.keys()) == {"scan", "match", "apply", "respond"}

    def test_done_without_prior_start_is_safe(self):
        tracker._tasks.clear()
        # Should not raise even if start() was never called
        tracker.done("scan", result=None)
        assert tracker.get("scan")["status"] == TaskStatus.DONE

    def test_error_without_prior_start_is_safe(self):
        tracker._tasks.clear()
        tracker.error("scan", "boom")
        assert tracker.get("scan")["status"] == TaskStatus.ERROR


# ---------------------------------------------------------------------------
# Page routes (HTML)
# ---------------------------------------------------------------------------


class TestPageRoutes:
    """Tests for HTML page routes.

    NOTE: There are two bugs in src/api/routes/pages.py:
    1. dashboard() — NameError: `class JobsNS: total = total` fails because Python
       class bodies cannot access enclosing function scope via closures when attribute
       name matches variable name.
    2. job_detail() — TypeError when Jinja2 template context contains unhashable types.
    """

    def test_root_returns_200(self, client: TestClient):
        """Dashboard renders without errors after NameError fix (SimpleNamespace)."""
        resp = client.get("/")
        assert resp.status_code == 200

    def test_jobs_list_page_returns_200(self, client: TestClient):
        """/jobs page delegates to dashboard() and renders correctly."""
        resp = client.get("/jobs")
        assert resp.status_code == 200

    def test_job_detail_page_invalid_id_returns_404(self, client: TestClient):
        resp = client.get("/jobs/99999")
        assert resp.status_code == 404

    def test_job_detail_page_renders_ok(self, client: TestClient):
        """Job detail page renders after TemplateResponse API fix."""
        with get_session() as session:
            j = _make_job(url="https://example.com/1")
            session.add(j)
            session.flush()
            job_id = j.id
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Concurrent pipeline requests
# ---------------------------------------------------------------------------


class TestConcurrentPipeline:
    def test_second_scan_while_first_running_gets_409(self, client: TestClient):
        """Two rapid POSTs to /api/pipeline/scan — second should get 409."""
        tracker.start("scan")  # Simulate a running task
        resp = client.post("/api/pipeline/scan")
        assert resp.status_code == 409

    def test_409_detail_mentions_phase(self, client: TestClient):
        tracker.start("match")
        resp = client.post("/api/pipeline/match")
        assert resp.status_code == 409
        assert "match" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Background task crash — tracker should set error state
# ---------------------------------------------------------------------------


class TestBackgroundTaskCrash:
    def test_tracker_error_state_on_exception(self):
        """If a phase raises, tracker.error() should be called."""
        tracker._tasks.clear()
        # Simulate _run_scan crashing: tracker.start + tracker.error
        tracker.start("scan")
        assert tracker.is_running("scan")
        tracker.error("scan", "Unexpected exception")
        state = tracker.get("scan")
        assert state["status"] == TaskStatus.ERROR
        assert not tracker.is_running("scan")

    def test_tracker_not_stuck_running_after_error(self):
        tracker._tasks.clear()
        tracker.start("apply")
        tracker.error("apply", "crash")
        assert not tracker.is_running("apply")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_negative_offset_returns_422(self, client: TestClient):
        resp = client.get("/api/jobs?offset=-1")
        assert resp.status_code == 422

    def test_limit_above_200_returns_422(self, client: TestClient):
        resp = client.get("/api/jobs?limit=201")
        assert resp.status_code == 422

    def test_limit_at_max_200_succeeds(self, client: TestClient):
        resp = client.get("/api/jobs?limit=200")
        assert resp.status_code == 200

    def test_multiple_jobs_pagination_consistency(self, client: TestClient):
        """First page + second page together should equal full list."""
        with get_session() as session:
            for i in range(7):
                session.add(_make_job(url=f"https://example.com/{i}"))

        page1 = client.get("/api/jobs?limit=4&offset=0").json()["items"]
        page2 = client.get("/api/jobs?limit=4&offset=4").json()["items"]
        all_ids = {item["id"] for item in page1 + page2}
        assert len(all_ids) == 7

    def test_job_salary_with_values_serialized_correctly(self, client: TestClient):
        with get_session() as session:
            session.add(_make_job(url="https://example.com/1",
                                  salary_min=50000, salary_max=80000))
        resp = client.get("/api/jobs")
        item = resp.json()["items"][0]
        assert item["salary_min"] == 50000
        assert item["salary_max"] == 80000

    def test_stats_today_matched_only_counts_todays_scraped_jobs(self, client: TestClient):
        yesterday = datetime.utcnow() - timedelta(days=1)
        with get_session() as session:
            session.add(_make_job(url="https://example.com/1",
                                  status=JobStatus.MATCHED,
                                  scraped_at=datetime.utcnow()))
            session.add(_make_job(url="https://example.com/2",
                                  status=JobStatus.MATCHED,
                                  scraped_at=yesterday))
        resp = client.get("/api/stats")
        data = resp.json()
        assert data["today"]["matched"] == 1
        assert data["total"]["matched"] == 2

    def test_pipeline_response_has_message_field(self, client: TestClient):
        from unittest.mock import AsyncMock
        with patch("src.api.routes.pipeline._run_scan", new_callable=AsyncMock):
            resp = client.post("/api/pipeline/scan")
        assert resp.status_code == 200
        assert "message" in resp.json()

    def test_job_patch_empty_body_is_noop(self, client: TestClient):
        with get_session() as session:
            j = _make_job(url="https://example.com/1", status=JobStatus.NEW)
            session.add(j)
            session.flush()
            job_id = j.id

        resp = client.patch(f"/api/jobs/{job_id}", json={})
        assert resp.status_code == 200
        assert resp.json()["status"] == "new"

    def test_application_with_recruiter_doesnt_crash(self, client: TestClient):
        """Job detail should not crash when application has a recruiter linked."""
        with get_session() as session:
            c = _make_company("Corp")
            session.add(c)
            session.flush()
            r = Recruiter(name="Alice", email="alice@corp.com", company_id=c.id)
            session.add(r)
            session.flush()
            j = _make_job(url="https://example.com/1", company=c)
            session.add(j)
            session.flush()
            app = Application(
                job_id=j.id,
                status=ApplicationStatus.SUBMITTED,
                recruiter_id=r.id,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(app)
            session.flush()
            job_id = j.id

        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["application"] is not None
