"""LinkedIn data export importer — populates profile.yaml from ZIP."""

import csv
import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _slug(value: str) -> str:
    """Slugify a string: lowercase, alphanumeric + underscores, max 40 chars."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:40]


class LinkedInImporter:
    """Import LinkedIn data export ZIP into profile.yaml."""

    def import_zip(self, zip_path: Path, profile_path: Path) -> None:
        """Parse LinkedIn export ZIP and update profile.yaml sections.

        Args:
            zip_path: Path to the LinkedIn data export ZIP file.
            profile_path: Path to the profile.yaml file to update.

        Raises:
            ValueError: If zip_path is not a valid ZIP archive.
        """
        if not zip_path.exists() or not zipfile.is_zipfile(zip_path):
            raise ValueError(f"Not a valid ZIP file: {zip_path}")

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            updates: dict[str, Any] = {}

            if "Positions.csv" in names:
                updates["experiences"] = self._parse_positions(
                    zf.read("Positions.csv").decode("utf-8")
                )
            else:
                logger.warning("Positions.csv not found in ZIP — experiences unchanged")

            if "Education.csv" in names:
                updates["education"] = self._parse_education(
                    zf.read("Education.csv").decode("utf-8")
                )
            else:
                logger.warning("Education.csv not found in ZIP — education unchanged")

            if "Skills.csv" in names:
                updates["skills_top_3"] = self._parse_skills(
                    zf.read("Skills.csv").decode("utf-8")
                )
            else:
                logger.warning("Skills.csv not found in ZIP — skills.top_3 unchanged")

            if "Projects.csv" in names:
                updates["projects"] = self._parse_projects(
                    zf.read("Projects.csv").decode("utf-8")
                )
            else:
                logger.warning("Projects.csv not found in ZIP — projects unchanged")

        with profile_path.open() as fh:
            profile: dict[str, Any] = yaml.safe_load(fh) or {}

        if "experiences" in updates:
            profile["experiences"] = updates["experiences"]
        if "education" in updates:
            profile["education"] = updates["education"]
        if "skills_top_3" in updates:
            if "skills" not in profile:
                profile["skills"] = {}
            profile["skills"]["top_3"] = updates["skills_top_3"]
        if "projects" in updates:
            profile["projects"] = updates["projects"]

        with profile_path.open("w") as fh:
            yaml.dump(profile, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def _parse_positions(self, csv_text: str) -> list[dict[str, Any]]:
        reader = csv.DictReader(io.StringIO(csv_text))
        experiences = []
        for row in reader:
            company = row.get("Company Name", "").strip()
            title = row.get("Title", "").strip()
            if not company or not title:
                continue
            description = row.get("Description", "").strip()
            bullets = [b.strip() for b in description.split("\n") if b.strip()][:3]
            experiences.append({
                "id": f"exp_{_slug(company)}_{_slug(title)}",
                "company": company,
                "title": title,
                "start": row.get("Started On", "").strip() or None,
                "end": row.get("Finished On", "").strip() or None,
                "location": row.get("Location", "").strip() or None,
                "bullets": bullets,
            })
        return experiences

    def _parse_education(self, csv_text: str) -> list[dict[str, Any]]:
        reader = csv.DictReader(io.StringIO(csv_text))
        return [
            {
                "institution": row.get("School Name", "").strip(),
                "degree": row.get("Degree Name", "").strip(),
                "start": row.get("Start Date", "").strip() or None,
                "end": row.get("End Date", "").strip() or None,
            }
            for row in reader
            if row.get("School Name", "").strip()
        ]

    def _parse_skills(self, csv_text: str) -> list[str]:
        reader = csv.DictReader(io.StringIO(csv_text))
        return [row["Name"].strip() for row in reader if row.get("Name", "").strip()][:10]

    def _parse_projects(self, csv_text: str) -> list[dict[str, Any]]:
        reader = csv.DictReader(io.StringIO(csv_text))
        return [
            {
                "id": f"proj_{_slug(row.get('Title', '').strip())}",
                "name": row.get("Title", "").strip(),
                "description": row.get("Description", "").strip(),
                "url": row.get("URL", "").strip() or None,
            }
            for row in reader
            if row.get("Title", "").strip()
        ]
