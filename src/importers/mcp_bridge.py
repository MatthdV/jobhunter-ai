"""MCP Bridge — imports job data collected by Cowork scheduled tasks.

Architecture:
    Cowork task → MCP Indeed search_jobs / get_company_data
    → writes JSON to data/mcp_inbox/*.json
    → this module reads, deduplicates, and persists to DB

The bridge decouples the MCP (only available inside Cowork sessions)
from the bot's Python runtime.  Files are consumed (moved to processed/)
after successful import.

Usage in scheduler::

    from src.importers.mcp_bridge import MCPBridgeImporter
    importer = MCPBridgeImporter()
    new_count = importer.import_pending(session)

Usage in CLI::

    python -m src.main import-mcp
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from src.storage.models import Company, Job, JobStatus

logger = logging.getLogger(__name__)

# Default paths — relative to project root
_INBOX_DIR = Path("data") / "mcp_inbox"
_PROCESSED_DIR = Path("data") / "mcp_inbox" / "processed"

# Expected JSON schema version (for forward-compat)
SCHEMA_VERSION = "1"


class MCPBridgeImporter:
    """Import jobs and company data from MCP bridge JSON files."""

    def __init__(
        self,
        inbox_dir: Path | None = None,
        processed_dir: Path | None = None,
    ) -> None:
        self._inbox = inbox_dir or _INBOX_DIR
        self._processed = processed_dir or _PROCESSED_DIR

    def import_pending(self, session: Session, user_id: int | None = None) -> int:
        """Import all pending JSON files from the inbox.

        Args:
            session: DB session for persistence.
            user_id: If provided, imported Job objects are tagged with this user_id.
                     Leave None for CLI/single-user mode.

        Returns count of new jobs imported.
        """
        self._inbox.mkdir(parents=True, exist_ok=True)
        self._processed.mkdir(parents=True, exist_ok=True)

        json_files = sorted(self._inbox.glob("*.json"))
        if not json_files:
            logger.debug("MCP inbox empty — nothing to import")
            return 0

        self._user_id = user_id  # stash for _build_job()
        existing_urls: set[str] = {
            url for (url,) in session.query(Job.url).all()
        }

        total_imported = 0

        for path in json_files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                count = self._process_file(data, session, existing_urls)
                total_imported += count
                # Move to processed
                shutil.move(str(path), str(self._processed / path.name))
                logger.info("Imported %d jobs from %s", count, path.name)
            except Exception:
                logger.exception("Failed to import %s — skipping", path.name)

        return total_imported

    def _process_file(
        self,
        data: dict[str, Any],
        session: Session,
        existing_urls: set[str],
    ) -> int:
        """Process a single MCP bridge JSON file.

        Supports two entry types:
        - "jobs": list of job search results
        - "company": company research data (enriches existing Company)
        """
        version = data.get("schema_version", SCHEMA_VERSION)
        if version != SCHEMA_VERSION:
            logger.warning(
                "Unknown schema version %s (expected %s) — attempting anyway",
                version, SCHEMA_VERSION,
            )

        imported = 0

        # Process job entries
        for job_data in data.get("jobs", []):
            url = job_data.get("url", "")
            if not url or url in existing_urls:
                continue
            job = self._build_job(job_data)
            session.add(job)
            existing_urls.add(url)
            imported += 1

        # Process company data (enrichment, not job creation)
        company_data = data.get("company")
        if company_data:
            self._enrich_company(company_data, session)

        session.commit()
        return imported

    def _build_job(self, data: dict[str, Any]) -> Job:
        """Build a Job instance from MCP bridge job data."""
        user_id = getattr(self, "_user_id", None)
        return Job(
            title=data.get("title", "Unknown"),
            url=data["url"],
            source="mcp_indeed",
            description=data.get("description"),
            salary_raw=data.get("compensation"),
            location=data.get("location"),
            contract_type=data.get("job_type"),
            country_code=data.get("country_code", "FR"),
            is_remote="remote" in (data.get("location") or "").lower()
            or "télétravail" in (data.get("location") or "").lower(),
            status=JobStatus.NEW,
            scraped_at=datetime.now(UTC),
            user_id=user_id,
        )

    def _enrich_company(
        self,
        data: dict[str, Any],
        session: Session,
    ) -> None:
        """Enrich a Company from MCP Indeed company data."""
        name = data.get("name")
        if not name:
            return

        company = (
            session.query(Company)
            .filter(Company.name == name)
            .first()
        )
        if not company:
            company = Company(name=name)
            session.add(company)

        # Only update fields that are not already set or that MCP provides better data for
        if data.get("size") and not company.size:
            company.size = data["size"]  # type: ignore[assignment]
        if data.get("sector") and not company.sector:
            company.sector = data["sector"]  # type: ignore[assignment]
        if data.get("description"):
            company.notes = data["description"]  # type: ignore[assignment]
        if data.get("glassdoor_rating") is not None:
            company.glassdoor_rating = data["glassdoor_rating"]  # type: ignore[assignment]
        if data.get("salary_data"):
            # Store salary intel in notes or a dedicated field
            existing_notes = company.notes or ""
            salary_info = json.dumps(data["salary_data"])
            if salary_info not in existing_notes:
                company.notes = f"{existing_notes}\n\nIndeed salary data: {salary_info}".strip()  # type: ignore[assignment]
        if data.get("ceo"):
            existing_notes = company.notes or ""
            if data["ceo"] not in existing_notes:
                company.notes = f"{existing_notes}\nCEO: {data['ceo']}".strip()  # type: ignore[assignment]

        company.researched_at = datetime.now(UTC)  # type: ignore[assignment]
        session.commit()
