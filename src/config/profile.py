"""Centralized profile.yaml path resolution.

All modules that need profile.yaml should import get_profile_path() from here
instead of hardcoding ``Path(__file__).parent.parent / "config" / "profile.yaml"``.
"""

import os
from pathlib import Path

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
