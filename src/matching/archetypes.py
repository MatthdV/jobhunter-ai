"""Archetype detection and configuration loader."""

from pathlib import Path
from typing import Any

import yaml

from src.config.profile import get_profile_path

_DEFAULT_PROFILE_PATH = get_profile_path()


def load_archetypes(profile_path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load archetype definitions from profile.yaml.

    Args:
        profile_path: Optional path to a custom profile YAML file.
            Defaults to src/config/profile.yaml.

    Returns:
        Dict mapping archetype keys to their configuration.
    """
    path = profile_path or _DEFAULT_PROFILE_PATH
    with path.open() as fh:
        profile = yaml.safe_load(fh)
    return profile.get("archetypes", {})


def detect_archetype(
    job_title: str,
    job_description: str,
    archetypes: dict[str, dict[str, Any]],
) -> str:
    """Detect the best-matching archetype for a job based on keyword overlap.

    Concatenates title and description, then counts how many of each archetype's
    keywords appear in the text. The archetype with the highest count wins.

    Args:
        job_title: The job title.
        job_description: The full job description text.
        archetypes: Dict of archetype definitions (from load_archetypes).

    Returns:
        The archetype key (e.g. 'automation_engineer') or 'generic' if no match.
    """
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
