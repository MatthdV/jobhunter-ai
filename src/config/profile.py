"""Centralized profile.yaml path resolution.

All modules that need profile.yaml should import get_profile_path() from here
instead of hardcoding ``Path(__file__).parent.parent / "config" / "profile.yaml"``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from src.storage.models import User

logger = logging.getLogger(__name__)

_DEFAULT_PROFILE_PATH = Path(__file__).parent / "profile.yaml"


def get_profile_path() -> Path:
    """Return the profile YAML path.

    Resolution order:
    1. ``PROFILE_PATH`` environment variable (absolute or relative to cwd)
    2. ``src/config/profile.yaml`` (original default)
    """
    env = os.environ.get("PROFILE_PATH")
    if env:
        return Path(env).expanduser().resolve()
    return _DEFAULT_PROFILE_PATH


def get_profile_for_user(user: "User") -> dict[str, Any]:
    """Return parsed profile dict for a specific user.

    Resolution order:
    1. ``User.profile_yaml`` (DB field) — per-user profile stored at registration
    2. ``PROFILE_PATH`` env var / ``src/config/profile.yaml`` — instance-level default
    3. Empty dict — graceful fallback when nothing is configured

    This lets CLI mode (no User object) continue using the file-based flow,
    while web/multi-tenant mode uses per-user DB profiles.
    """
    if user.profile_yaml:
        try:
            return yaml.safe_load(user.profile_yaml) or {}
        except Exception as exc:
            logger.warning("Failed to parse profile_yaml for user %d: %s", user.id, exc)

    try:
        with get_profile_path().open() as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        logger.debug("No profile.yaml file found — using empty profile defaults")
        return {}
    except Exception as exc:
        logger.warning("Failed to load profile.yaml: %s", exc)
        return {}
