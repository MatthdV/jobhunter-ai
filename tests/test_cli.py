"""Tests for the CLI apply command — Phase 3 completion."""

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from src.main import app
from src.storage.database import configure, drop_all, get_session, init_db
from src.storage.models import Application, ApplicationStatus, Job, JobStatus

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_matched_job(url: str = "https://example.com/job/1") -> Job:
    return Job(
        title="Automation Engineer",
        url=url,
        source="wttj",
        description="Python automation expert needed.",
        is_remote=True,
        contract_type="CDI",
        status=JobStatus.MATCHED,
        match_score=85.0,
    )


# ---------------------------------------------------------------------------
# DB fixture — autouse resets to in-memory SQLite for every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_db() -> Generator[None, None, None]:
    configure("sqlite:///:memory:")
    init_db()
    yield
    drop_all()


# ---------------------------------------------------------------------------
# Generator mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_generators(monkeypatch: pytest.MonkeyPatch) -> None:
    cv_instance = MagicMock()
    cv_instance.generate = AsyncMock(return_value=Path("/tmp/cv_test.pdf"))

    cl_instance = MagicMock()
    cl_instance.generate = AsyncMock(return_value="Lettre de motivation test.")

    monkeypatch.setattr(
        "src.generators.cv_generator.CVGenerator",
        MagicMock(return_value=cv_instance),
    )
    monkeypatch.setattr(
        "src.generators.cover_letter.CoverLetterGenerator",
        MagicMock(return_value=cl_instance),
    )
    monkeypatch.setattr(
        "src.config.settings.settings",
        MagicMock(anthropic_api_key="test-key", max_applications_per_day=10),
    )


# ---------------------------------------------------------------------------
# Slice 14 — apply command wired to generators + DB
# ---------------------------------------------------------------------------


class TestApplyCommand:
    def test_apply_creates_application_for_matched_job(
        self, patched_generators: None
    ) -> None:
        with get_session() as session:
            job = make_matched_job()
            session.add(job)

        result = runner.invoke(app, ["apply"])

        assert result.exit_code == 0, result.output
        with get_session() as session:
            apps = session.query(Application).all()
            assert len(apps) == 1
            assert apps[0].cv_path == "/tmp/cv_test.pdf"
            assert apps[0].cover_letter == "Lettre de motivation test."
            assert apps[0].status == ApplicationStatus.DRAFT

    def test_apply_skips_jobs_with_existing_application(
        self, patched_generators: None
    ) -> None:
        with get_session() as session:
            job = make_matched_job()
            session.add(job)
            session.flush()
            existing = Application(
                job_id=job.id,
                cv_path="/tmp/old.pdf",
                cover_letter="old letter",
                status=ApplicationStatus.DRAFT,
            )
            session.add(existing)

        result = runner.invoke(app, ["apply"])

        assert result.exit_code == 0, result.output
        with get_session() as session:
            count = session.query(Application).count()
        assert count == 1  # still only the original

    def test_apply_targets_single_job_id(
        self, patched_generators: None
    ) -> None:
        with get_session() as session:
            job1 = make_matched_job(url="https://example.com/job/1")
            job2 = make_matched_job(url="https://example.com/job/2")
            session.add(job1)
            session.add(job2)
            session.flush()
            target_id = job1.id

        result = runner.invoke(app, ["apply", str(target_id)])

        assert result.exit_code == 0, result.output
        with get_session() as session:
            apps = session.query(Application).all()
            assert len(apps) == 1
            assert apps[0].job_id == target_id


# ---------------------------------------------------------------------------
# Slice 15 — daily cap
# ---------------------------------------------------------------------------


class TestApplyDailyCap:
    def test_apply_respects_max_applications_per_day(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cv_instance = MagicMock()
        cv_instance.generate = AsyncMock(return_value=Path("/tmp/cv_test.pdf"))
        cl_instance = MagicMock()
        cl_instance.generate = AsyncMock(return_value="Lettre.")

        monkeypatch.setattr(
            "src.generators.cv_generator.CVGenerator",
            MagicMock(return_value=cv_instance),
        )
        monkeypatch.setattr(
            "src.generators.cover_letter.CoverLetterGenerator",
            MagicMock(return_value=cl_instance),
        )
        monkeypatch.setattr(
            "src.config.settings.settings",
            MagicMock(anthropic_api_key="test-key", max_applications_per_day=2),
        )

        with get_session() as session:
            for i in range(5):
                session.add(make_matched_job(url=f"https://example.com/job/{i}"))

        result = runner.invoke(app, ["apply"])

        assert result.exit_code == 0, result.output
        with get_session() as session:
            count = session.query(Application).count()
        assert count == 2
