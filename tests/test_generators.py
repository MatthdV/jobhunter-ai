"""Tests for CV and cover letter generators — Phase 3."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import ConfigurationError


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TEST_PROFILE = Path(__file__).parent / "fixtures" / "test_profile.yaml"

VALID_HIGHLIGHTS = '{"experience_ids": ["exp_acme_automation"], "skill_ids": ["n8n"], "hook": "Great fit."}'


def make_job(**kwargs: Any) -> MagicMock:
    job = MagicMock()
    job.title = kwargs.get("title", "Automation Engineer")
    job.description = kwargs.get("description", "Seeking an n8n expert with Python skills.")
    job.company = MagicMock()
    job.company.name = kwargs.get("company", "Acme Corp")
    return job


# ---------------------------------------------------------------------------
# CVGenerator tests
# ---------------------------------------------------------------------------


class TestCVGeneratorInit:
    def test_init_raises_configuration_error_without_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.generators.cv_generator.settings",
            MagicMock(anthropic_api_key="", anthropic_model="claude-opus-4-6"),
        )
        with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
            from src.generators.cv_generator import CVGenerator
            CVGenerator()
