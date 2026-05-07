"""Tests for MCPBridgeImporter — JSON inbox → DB import pipeline."""

import json
from collections.abc import Generator
from pathlib import Path

import pytest

from src.importers.mcp_bridge import MCPBridgeImporter
from src.storage.database import configure, drop_all, get_session, init_db
from src.storage.models import Company, Job


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_db() -> Generator[None, None, None]:
    configure("sqlite:///:memory:")
    init_db()
    yield
    drop_all()


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    d = tmp_path / "mcp_inbox"
    d.mkdir()
    return d


@pytest.fixture
def processed(tmp_path: Path) -> Path:
    d = tmp_path / "mcp_inbox" / "processed"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def importer(inbox: Path, processed: Path) -> MCPBridgeImporter:
    return MCPBridgeImporter(inbox_dir=inbox, processed_dir=processed)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_JOB_PAYLOAD = {
    "schema_version": "1",
    "jobs": [
        {
            "title": "ML Engineer",
            "url": "https://example.com/jobs/42",
            "description": "Build models",
            "location": "Remote — Paris",
            "compensation": "70k-90k EUR",
            "job_type": "CDI",
            "country_code": "FR",
        },
    ],
}


def _write_json(path: Path, name: str, payload: dict) -> Path:
    f = path / name
    f.write_text(json.dumps(payload), encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# Tests — import valid JSON
# ---------------------------------------------------------------------------


class TestImportPending:
    def test_imports_single_job(self, importer: MCPBridgeImporter, inbox: Path) -> None:
        _write_json(inbox, "batch1.json", VALID_JOB_PAYLOAD)

        with get_session() as session:
            count = importer.import_pending(session)

        assert count == 1
        with get_session() as session:
            job = session.query(Job).first()
            assert job is not None
            assert job.title == "ML Engineer"
            assert job.url == "https://example.com/jobs/42"
            assert job.source == "mcp_indeed"
            assert job.is_remote is True  # "Remote" in location
            assert job.country_code == "FR"

    def test_imports_multiple_jobs_in_one_file(
        self, importer: MCPBridgeImporter, inbox: Path
    ) -> None:
        payload = {
            "schema_version": "1",
            "jobs": [
                {"title": "Job A", "url": "https://a.com/1", "country_code": "US"},
                {"title": "Job B", "url": "https://b.com/2", "country_code": "GB"},
            ],
        }
        _write_json(inbox, "multi.json", payload)

        with get_session() as session:
            count = importer.import_pending(session)

        assert count == 2

    def test_empty_inbox_returns_zero(self, importer: MCPBridgeImporter) -> None:
        with get_session() as session:
            assert importer.import_pending(session) == 0


# ---------------------------------------------------------------------------
# Tests — deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_same_url_imported_once(
        self, importer: MCPBridgeImporter, inbox: Path
    ) -> None:
        """Same URL in two files → only the first is persisted."""
        _write_json(inbox, "a.json", VALID_JOB_PAYLOAD)
        _write_json(
            inbox,
            "b.json",
            {
                "schema_version": "1",
                "jobs": [
                    {
                        "title": "ML Engineer (duplicate)",
                        "url": "https://example.com/jobs/42",
                    },
                ],
            },
        )

        with get_session() as session:
            count = importer.import_pending(session)

        assert count == 1
        with get_session() as session:
            assert session.query(Job).count() == 1

    def test_dedup_across_runs(
        self, importer: MCPBridgeImporter, inbox: Path
    ) -> None:
        """Import same URL twice in successive calls → second returns 0."""
        _write_json(inbox, "first.json", VALID_JOB_PAYLOAD)
        with get_session() as session:
            importer.import_pending(session)

        # Write same URL again
        _write_json(inbox, "second.json", VALID_JOB_PAYLOAD)
        with get_session() as session:
            count = importer.import_pending(session)

        assert count == 0
        with get_session() as session:
            assert session.query(Job).count() == 1


# ---------------------------------------------------------------------------
# Tests — company enrichment
# ---------------------------------------------------------------------------


class TestCompanyEnrichment:
    def test_creates_company_from_payload(
        self, importer: MCPBridgeImporter, inbox: Path
    ) -> None:
        payload = {
            "schema_version": "1",
            "jobs": [],
            "company": {
                "name": "Anthropic",
                "sector": "AI safety",
                "size": "200-500",
                "glassdoor_rating": 4.6,
            },
        }
        _write_json(inbox, "company.json", payload)

        with get_session() as session:
            importer.import_pending(session)

        with get_session() as session:
            co = session.query(Company).filter_by(name="Anthropic").first()
            assert co is not None
            assert co.sector == "AI safety"
            assert co.size == "200-500"
            assert co.glassdoor_rating == pytest.approx(4.6)
            assert co.researched_at is not None

    def test_enriches_existing_company(
        self, importer: MCPBridgeImporter, inbox: Path
    ) -> None:
        # Pre-create company with partial data
        with get_session() as session:
            session.add(Company(name="Anthropic", sector="AI"))
            session.commit()

        payload = {
            "schema_version": "1",
            "jobs": [],
            "company": {
                "name": "Anthropic",
                "size": "200-500",
                "glassdoor_rating": 4.6,
            },
        }
        _write_json(inbox, "enrich.json", payload)

        with get_session() as session:
            importer.import_pending(session)

        with get_session() as session:
            co = session.query(Company).filter_by(name="Anthropic").first()
            assert co is not None
            assert co.sector == "AI"  # not overwritten
            assert co.size == "200-500"  # filled in
            assert co.glassdoor_rating == pytest.approx(4.6)


# ---------------------------------------------------------------------------
# Tests — file moved to processed/
# ---------------------------------------------------------------------------


class TestFileMovedAfterImport:
    def test_file_moved_to_processed(
        self,
        importer: MCPBridgeImporter,
        inbox: Path,
        processed: Path,
    ) -> None:
        _write_json(inbox, "batch.json", VALID_JOB_PAYLOAD)

        with get_session() as session:
            importer.import_pending(session)

        assert not (inbox / "batch.json").exists()
        assert (processed / "batch.json").exists()


# ---------------------------------------------------------------------------
# Tests — invalid / malformed JSON
# ---------------------------------------------------------------------------


class TestInvalidJsonGracefulSkip:
    def test_invalid_json_skipped(
        self, importer: MCPBridgeImporter, inbox: Path
    ) -> None:
        """Malformed JSON should be skipped (not moved) without crashing."""
        (inbox / "bad.json").write_text("{not valid json!!!", encoding="utf-8")
        # Add a valid file too
        _write_json(inbox, "good.json", VALID_JOB_PAYLOAD)

        with get_session() as session:
            count = importer.import_pending(session)

        # Valid file still imported
        assert count == 1
        # Bad file stays in inbox (not moved)
        assert (inbox / "bad.json").exists()

    def test_missing_url_skipped(
        self, importer: MCPBridgeImporter, inbox: Path
    ) -> None:
        payload = {
            "schema_version": "1",
            "jobs": [{"title": "No URL job"}],
        }
        _write_json(inbox, "no_url.json", payload)

        with get_session() as session:
            count = importer.import_pending(session)

        assert count == 0
