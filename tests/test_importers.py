"""Tests for LinkedInImporter — Phase 3."""

import io
import zipfile
from pathlib import Path

import pytest

from src.importers.linkedin_importer import LinkedInImporter

FIXTURES = Path(__file__).parent / "fixtures" / "linkedin"


def make_zip(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a ZIP file in tmp_path containing the given filename → content mapping."""
    zip_path = tmp_path / "linkedin_export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return zip_path


class TestLinkedInImporterParsePositions:
    def test_parse_positions_returns_experience_list(self, tmp_path: Path) -> None:
        csv_content = (FIXTURES / "Positions.csv").read_text()
        zip_path = make_zip(tmp_path, {"Positions.csv": csv_content})
        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text("candidate:\n  name: Test\n")

        importer = LinkedInImporter()
        importer.import_zip(zip_path, profile_path)

        import yaml
        profile = yaml.safe_load(profile_path.read_text())
        experiences = profile["experiences"]
        assert isinstance(experiences, list)
        assert len(experiences) >= 1
        first = experiences[0]
        assert "id" in first
        assert "company" in first
        assert "title" in first
        assert "bullets" in first
        assert first["id"].startswith("exp_")
