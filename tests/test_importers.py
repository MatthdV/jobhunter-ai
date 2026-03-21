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


class TestLinkedInImporterImportZip:
    def test_import_zip_writes_all_four_sections(self, tmp_path: Path) -> None:
        """import_zip writes experiences, education, skills.top_3, and projects."""
        files = {
            "Positions.csv": (FIXTURES / "Positions.csv").read_text(),
            "Education.csv": (FIXTURES / "Education.csv").read_text(),
            "Skills.csv": (FIXTURES / "Skills.csv").read_text(),
            "Projects.csv": (FIXTURES / "Projects.csv").read_text(),
        }
        zip_path = make_zip(tmp_path, files)
        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text("candidate:\n  name: Test\nskills:\n  tech_stack: {}\n")

        importer = LinkedInImporter()
        importer.import_zip(zip_path, profile_path)

        import yaml
        profile = yaml.safe_load(profile_path.read_text())

        assert "experiences" in profile
        assert len(profile["experiences"]) >= 1
        assert "education" in profile
        assert len(profile["education"]) >= 1
        assert profile["skills"]["top_3"]  # non-empty list
        assert "projects" in profile
        assert len(profile["projects"]) >= 1
        # tech_stack preserved
        assert "tech_stack" in profile["skills"]

    def test_import_zip_raises_on_invalid_path(self, tmp_path: Path) -> None:
        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text("candidate:\n  name: Test\n")
        with pytest.raises(ValueError, match="Not a valid ZIP"):
            LinkedInImporter().import_zip(tmp_path / "nonexistent.zip", profile_path)

    def test_import_zip_skips_missing_csv(self, tmp_path: Path) -> None:
        """A ZIP with only Positions.csv should not overwrite education/projects."""
        files = {"Positions.csv": (FIXTURES / "Positions.csv").read_text()}
        zip_path = make_zip(tmp_path, files)
        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text(
            "candidate:\n  name: Test\n"
            "education:\n  - institution: Existing\n    degree: BA\n"
        )
        LinkedInImporter().import_zip(zip_path, profile_path)

        import yaml
        profile = yaml.safe_load(profile_path.read_text())
        assert profile["education"][0]["institution"] == "Existing"
