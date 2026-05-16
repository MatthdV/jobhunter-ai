"""Archetype detection and configuration loader."""

from pathlib import Path
from typing import Any

import yaml

from src.config.profile import get_profile_path


def load_archetypes(profile_path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load archetype definitions from profile.yaml."""
    path = profile_path or get_profile_path()
    with path.open() as fh:
        profile = yaml.safe_load(fh)
    return profile.get("archetypes", {})


def detect_archetype(
    job_title: str,
    job_description: str,
    archetypes: dict[str, dict[str, Any]],
) -> str:
    """Detect the best-matching archetype for a job based on keyword overlap."""
    text = f"{job_title} {job_description}".lower()
    best_key = "generic"
    best_count = 0

    for key, config in archetypes.items():
        keywords = config.get("keywords", [])
        count = sum(1 for kw in keywords if kw.lower() in text)
        if count > best_count:
            best_count = count
            best_key = key

    return best_key if best_count > 0 else "generic"
