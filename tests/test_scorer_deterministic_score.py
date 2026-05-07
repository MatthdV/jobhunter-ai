"""Tests for deterministic global_score computation from block scores."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.matching.scorer import (
    BLOCK_WEIGHTS,
    BlockScore,
    Scorer,
    ScoreResult,
    _compute_global_score,
)


# ---------------------------------------------------------------------------
# Unit tests for _compute_global_score
# ---------------------------------------------------------------------------


class TestComputeGlobalScore:
    def test_all_blocks_at_4(self):
        """6 blocs at 4.0 -> (4.0 - 1.0) / 4.0 * 100 = 75.0"""
        blocks = [BlockScore(name=n, score=4.0, details={}) for n in BLOCK_WEIGHTS]
        assert _compute_global_score(blocks) == 75.0

    def test_perfect_score(self):
        """6 blocs at 5.0 -> 100.0"""
        blocks = [BlockScore(name=n, score=5.0, details={}) for n in BLOCK_WEIGHTS]
        assert _compute_global_score(blocks) == 100.0

    def test_minimum_score(self):
        """6 blocs at 1.0 -> 0.0"""
        blocks = [BlockScore(name=n, score=1.0, details={}) for n in BLOCK_WEIGHTS]
        assert _compute_global_score(blocks) == 0.0

    def test_missing_block_uses_default(self):
        """5 blocs provided, 1 missing -> uses 3.0 for the missing one."""
        # All blocks except F_interview_prep, all at 4.0
        blocks = [
            BlockScore(name=n, score=4.0, details={})
            for n in BLOCK_WEIGHTS
            if n != "F_interview_prep"
        ]
        score = _compute_global_score(blocks)
        # F_interview_prep weight = 0.15, default 3.0
        # weighted = 0.85 * 4.0 + 0.15 * 3.0 = 3.4 + 0.45 = 3.85
        # score = ((3.85 - 1.0) / 4.0) * 100 = 71.25 -> 71.2 (rounded to 1 dp)
        assert score == 71.2

    def test_weights_matter(self):
        """B_cv_match (25%) at 5.0 with rest at 1.0 scores higher than
        A_role_summary (10%) at 5.0 with rest at 1.0."""
        # Scenario 1: B high, rest low
        blocks_b_high = [
            BlockScore(name=n, score=5.0 if n == "B_cv_match" else 1.0, details={})
            for n in BLOCK_WEIGHTS
        ]
        # Scenario 2: A high, rest low
        blocks_a_high = [
            BlockScore(name=n, score=5.0 if n == "A_role_summary" else 1.0, details={})
            for n in BLOCK_WEIGHTS
        ]
        score_b = _compute_global_score(blocks_b_high)
        score_a = _compute_global_score(blocks_a_high)
        assert score_b > score_a

    def test_empty_blocks_all_default(self):
        """No blocks at all -> all default to 3.0 -> ((3.0-1.0)/4.0)*100 = 50.0"""
        assert _compute_global_score([]) == 50.0

    def test_weights_sum_to_one(self):
        """Sanity check: weights must sum to 1.0."""
        assert abs(sum(BLOCK_WEIGHTS.values()) - 1.0) < 1e-9

    def test_clamps_above_100(self):
        """Scores above 5.0 (shouldn't happen, but defensive) clamp to 100."""
        blocks = [BlockScore(name=n, score=6.0, details={}) for n in BLOCK_WEIGHTS]
        assert _compute_global_score(blocks) == 100.0

    def test_clamps_below_0(self):
        """Scores below 1.0 (shouldn't happen) clamp to 0."""
        blocks = [BlockScore(name=n, score=0.0, details={}) for n in BLOCK_WEIGHTS]
        assert _compute_global_score(blocks) == 0.0


# ---------------------------------------------------------------------------
# Integration: _parse_response ignores LLM global_score
# ---------------------------------------------------------------------------


RESPONSE_WITH_BLOCKS = json.dumps({
    "archetype": "automation_engineer",
    "global_score": 99,  # LLM says 99 — should be IGNORED
    "blocks": {
        "A_role_summary": {"score": 2.0, "one_liner": "Test"},
        "B_cv_match": {"score": 2.0, "matched_requirements": [], "gaps": []},
        "C_level_strategy": {"score": 2.0, "detected_level": "mid",
                             "candidate_level": "senior",
                             "positioning_notes": "OK", "downlevel_contingency": None},
        "D_compensation": {"score": 2.0, "salary_assessment": "Low",
                           "market_context": "N/A", "ppp_analysis": "N/A"},
        "E_personalization": {"score": 2.0, "cv_changes": [],
                              "cover_letter_hooks": []},
        "F_interview_prep": {"score": 2.0, "stories": [],
                             "red_flag_questions": []},
    },
    "reasoning": "Below average match.",
    "strengths": ["Some Python"],
    "concerns": ["Weak fit"],
})

OLD_STYLE_RESPONSE = json.dumps({
    "score": 75,
    "reasoning": "Good fit overall.",
    "strengths": ["Python", "n8n"],
    "concerns": ["No K8s"],
})


@pytest.fixture
def scorer(monkeypatch):
    monkeypatch.setattr(
        "src.matching.scorer.settings",
        MagicMock(min_match_score=80, llm_provider="anthropic", llm_model="test"),
    )
    client = AsyncMock()
    return Scorer(client=client)


class TestParseResponseDeterministicScore:
    def test_ignores_llm_global_score(self, scorer):
        """LLM returns global_score: 99 but all blocks at 2.0.
        Computed score: ((2.0 - 1.0) / 4.0) * 100 = 25.0, NOT 99."""
        result = scorer._parse_response(RESPONSE_WITH_BLOCKS)
        assert result.score != 99.0
        assert result.score == 25.0

    def test_old_style_response_fallback(self, scorer):
        """Old-style response (no blocks) falls back to LLM score."""
        result = scorer._parse_response(OLD_STYLE_RESPONSE)
        assert result.score == 75.0
        assert result.blocks == []

    def test_no_global_score_key_with_blocks(self, scorer):
        """Response with blocks but no global_score key — computed from blocks."""
        data = json.loads(RESPONSE_WITH_BLOCKS)
        del data["global_score"]
        result = scorer._parse_response(json.dumps(data))
        assert result.score == 25.0
