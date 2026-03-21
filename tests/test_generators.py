"""Tests for CV and cover letter generators — Phase 3."""

from pathlib import Path

import pytest


class TestCVGenerator:
    def test_generate_creates_pdf_file(self, tmp_path: Path) -> None:
        pass  # Phase 3

    def test_generated_pdf_is_non_empty(self, tmp_path: Path) -> None:
        pass  # Phase 3

    def test_output_filename_includes_job_title(self, tmp_path: Path) -> None:
        pass  # Phase 3

    @pytest.mark.asyncio
    async def test_select_highlights_calls_claude(self) -> None:
        pass  # Phase 3

    def test_render_html_includes_candidate_name(self) -> None:
        pass  # Phase 3


class TestCoverLetterGenerator:
    @pytest.mark.asyncio
    async def test_generate_returns_non_empty_string(self) -> None:
        pass  # Phase 3

    def test_detect_language_french_job(self) -> None:
        pass  # Phase 3

    def test_detect_language_english_job(self) -> None:
        pass  # Phase 3

    @pytest.mark.asyncio
    async def test_refine_incorporates_feedback(self) -> None:
        pass  # Phase 3

    def test_prompt_excludes_forbidden_buzzwords(self) -> None:
        pass  # Phase 3
