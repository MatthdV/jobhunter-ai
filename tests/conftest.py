"""Pytest configuration — custom marks and shared fixtures."""

import os

import pytest


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if not os.getenv("SKIP_WEASYPRINT"):
        return
    skip = pytest.mark.skip(reason="SKIP_WEASYPRINT env var is set")
    for item in items:
        if item.get_closest_marker("weasyprint"):
            item.add_marker(skip)
