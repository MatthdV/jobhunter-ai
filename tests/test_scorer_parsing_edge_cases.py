"""Tests for scorer JSON parsing edge cases — reproducing the ScoringError bug.

These tests target _parse_response() and _strip_markdown_fences() with
realistic failure modes observed in production:
- Truncated LLM responses (max_tokens too small)
- Extra text around JSON
- Markdown fence variants
- Nested braces in values

NOTE: We inline the parsing logic to avoid importing src.storage.models
(which requires Python 3.11+ for StrEnum). This lets us test parsing
on any Python version.
"""

import contextlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Inlined scoring types and parsing logic (from src/matching/scorer.py)
# ---------------------------------------------------------------------------

_EXPECTED_BLOCKS = frozenset(
    ["A_role_summary", "B_cv_match", "C_level_strategy",
     "D_compensation", "E_personalization", "F_interview_prep"]
)


@dataclass
class BlockScore:
    name: str
    score: float
    details: dict[str, Any]


@dataclass
class ScoreResult:
    score: float
    reasoning: str
    strengths: list[str]
    concerns: list[str]
    archetype: str = "generic"
    blocks: list[BlockScore] = field(default_factory=list)


class ScoringError(Exception):
    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


def strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` wrappers.

    Handles: ```json, ```JSON, ```, preamble text before fences,
    trailing whitespace around fences.
    """
    stripped = text.strip()
    fence_match = re.search(r"```(?:\w+)?[ \t]*\n", stripped)
    if fence_match:
        stripped = stripped[fence_match.end():]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3].rstrip()
    return stripped


def extract_json_object(text: str) -> str | None:
    """Extract the first balanced JSON object using brace counting."""
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            if in_string:
                escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None


def parse_response(response_text: str) -> ScoreResult:
    """Parse LLM response into ScoreResult (matches Scorer._parse_response)."""
    data: dict[str, Any] | None = None
    cleaned = strip_markdown_fences(response_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        json_str = extract_json_object(cleaned)
        if json_str:
            with contextlib.suppress(json.JSONDecodeError):
                data = json.loads(json_str)

    if data is None:
        raise ScoringError("Could not parse JSON from response", raw=response_text)

    if "global_score" in data:
        score = max(0.0, min(100.0, float(data["global_score"])))
    elif "score" in data:
        score = max(0.0, min(100.0, float(data["score"])))
    else:
        raise ScoringError("Missing required key: score", raw=response_text)

    reasoning = data.get("reasoning")
    if reasoning is None:
        raise ScoringError("Missing required key: reasoning", raw=response_text)

    strengths = list(data.get("strengths", []))
    concerns = list(data.get("concerns", []))
    archetype = data.get("archetype", "generic")

    blocks: list[BlockScore] = []
    raw_blocks = data.get("blocks", {})
    if isinstance(raw_blocks, dict):
        for block_name in _EXPECTED_BLOCKS:
            if block_name in raw_blocks:
                block_data = raw_blocks[block_name]
                block_score = float(block_data.get("score", 0))
                details = {k: v for k, v in block_data.items() if k != "score"}
                blocks.append(BlockScore(
                    name=block_name, score=block_score, details=details,
                ))

    return ScoreResult(
        score=score, reasoning=reasoning, strengths=strengths,
        concerns=concerns, archetype=archetype, blocks=blocks,
    )


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

MINIMAL_VALID = json.dumps({
    "global_score": 82,
    "archetype": "automation_engineer",
    "blocks": {
        "A_role_summary": {"score": 4.0, "one_liner": "Test role"},
        "B_cv_match": {"score": 4.2, "matched_requirements": [], "gaps": []},
        "C_level_strategy": {"score": 3.5, "detected_level": "senior",
                             "candidate_level": "senior",
                             "positioning_notes": "OK", "downlevel_contingency": None},
        "D_compensation": {"score": 3.8, "salary_assessment": "OK",
                           "market_context": "N/A", "ppp_analysis": "N/A"},
        "E_personalization": {"score": 4.0, "cv_changes": [],
                              "cover_letter_hooks": ["Hook"]},
        "F_interview_prep": {"score": 3.5, "stories": [],
                             "red_flag_questions": ["Why?"]},
    },
    "reasoning": "Good match overall.",
    "strengths": ["Python", "automation"],
    "concerns": ["Salary on lower end"],
})


# ---------------------------------------------------------------------------
# Tests: Truncated responses (THE MAIN BUG)
# ---------------------------------------------------------------------------


class TestTruncatedResponse:
    """Bug scenario: LLM response cut off mid-JSON due to max_tokens."""

    def test_truncated_json_raises_scoring_error(self):
        truncated = MINIMAL_VALID[:200]
        with pytest.raises(ScoringError, match="Could not parse JSON"):
            parse_response(truncated)

    def test_truncated_json_missing_closing_brace(self):
        """JSON missing final } — greedy regex won't match properly."""
        almost_complete = MINIMAL_VALID[:-1]
        # This SHOULD fail (incomplete JSON), but the greedy regex might
        # grab from first { to some earlier }, producing garbage.
        # Let's see what actually happens:
        try:
            result = parse_response(almost_complete)
            # If it somehow parsed, it should still have correct top-level data
            # But it probably won't — the regex will grab a malformed subset
            pytest.fail(
                f"Expected ScoringError but got score={result.score}. "
                f"This means the greedy regex grabbed a subset of the JSON — "
                f"which is a silent data corruption bug!"
            )
        except ScoringError:
            pass  # Expected

    def test_truncated_after_blocks_missing_reasoning(self):
        """JSON truncated after blocks — missing reasoning field."""
        partial = json.loads(MINIMAL_VALID)
        del partial["reasoning"]
        del partial["strengths"]
        del partial["concerns"]
        with pytest.raises(ScoringError, match="reasoning"):
            parse_response(json.dumps(partial))


# ---------------------------------------------------------------------------
# Tests: Extra text around JSON
# ---------------------------------------------------------------------------


class TestExtraTextAroundJSON:

    def test_preamble_before_json(self):
        text = "Here is my evaluation:\n\n" + MINIMAL_VALID
        result = parse_response(text)
        assert result.score == 82.0

    def test_postamble_after_json(self):
        text = MINIMAL_VALID + "\n\nNote: I assumed the role is senior level."
        result = parse_response(text)
        assert result.score == 82.0

    def test_preamble_and_postamble(self):
        text = (
            "Based on my analysis:\n\n"
            + MINIMAL_VALID
            + "\n\nLet me know if you need more detail."
        )
        result = parse_response(text)
        assert result.score == 82.0

    def test_postamble_with_braces(self):
        """Postamble contains {} that could confuse greedy regex."""
        text = MINIMAL_VALID + '\n\nNote: the {salary} field was estimated.'
        result = parse_response(text)
        assert result.score == 82.0


# ---------------------------------------------------------------------------
# Tests: Markdown fence variants
# ---------------------------------------------------------------------------


class TestMarkdownFenceVariants:

    def test_json_fence_uppercase(self):
        text = "```JSON\n" + MINIMAL_VALID + "\n```"
        result = parse_response(text)
        assert result.score == 82.0

    def test_fence_with_trailing_spaces(self):
        text = "```json  \n" + MINIMAL_VALID + "\n```  "
        result = parse_response(text)
        assert result.score == 82.0

    def test_fence_with_preamble(self):
        """LLM says something, then opens a fence."""
        text = "Here is the result:\n\n```json\n" + MINIMAL_VALID + "\n```"
        result = parse_response(text)
        assert result.score == 82.0

    def test_plain_fence_no_lang(self):
        text = "```\n" + MINIMAL_VALID + "\n```"
        result = parse_response(text)
        assert result.score == 82.0


# ---------------------------------------------------------------------------
# Tests: Nested braces & edge cases
# ---------------------------------------------------------------------------


class TestNestedBracesInValues:

    def test_reasoning_with_braces(self):
        data = json.loads(MINIMAL_VALID)
        data["reasoning"] = "The role {automation engineer} is a strong match."
        result = parse_response(json.dumps(data))
        assert result.score == 82.0
        assert "{automation engineer}" in result.reasoning


class TestStripMarkdownFences:

    def test_no_fences(self):
        assert strip_markdown_fences('{"a": 1}') == '{"a": 1}'

    def test_json_fence(self):
        assert strip_markdown_fences('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_json_fence_uppercase(self):
        result = strip_markdown_fences('```JSON\n{"a": 1}\n```')
        assert '{"a": 1}' in result

    def test_fence_with_extra_whitespace(self):
        result = strip_markdown_fences('  ```json\n{"a": 1}\n```  ')
        assert '{"a": 1}' in result
