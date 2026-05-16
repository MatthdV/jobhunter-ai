"""Pytest configuration — custom marks and shared fixtures."""

import os
from pathlib import Path

import pytest

# Test fixture profile — contains archetypes + job_sources for unit tests.
# The real src/config/profile.yaml is gitignored (user-specific).
_TEST_PROFILE = Path(__file__).parent / "fixtures" / "test_profile.yaml"


@pytest.fixture(autouse=True, scope="session")
def set_test_profile_path() -> None:
    """Point PROFILE_PATH to the test fixture so no real profile.yaml is required.

    Uses setdefault so an explicit PROFILE_PATH env var (e.g. in CI with a
    real profile) still takes precedence over the fixture.
    """
    os.environ.setdefault("PROFILE_PATH", str(_TEST_PROFILE))


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    _weasyprint_ok = True
    try:
        from weasyprint import HTML  # noqa: F401
    except (OSError, ImportError):
        _weasyprint_ok = False

    skip_env = os.getenv("SKIP_WEASYPRINT")
    if not _weasyprint_ok or skip_env:
        reason = "WeasyPrint native libraries not installed" if not _weasyprint_ok else "SKIP_WEASYPRINT env var is set"
        skip = pytest.mark.skip(reason=reason)
        for item in items:
            if item.get_closest_marker("weasyprint"):
                item.add_marker(skip)
