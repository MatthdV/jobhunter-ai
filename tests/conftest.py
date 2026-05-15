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
    if not os.getenv("SKIP_WEASYPRINT"):
        return
    skip = pytest.mark.skip(reason="SKIP_WEASYPRINT env var is set")
    for item in items:
        if item.get_closest_marker("weasyprint"):
            item.add_marker(skip)
