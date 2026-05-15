"""LLM-based job offer scorer with multi-bloc A-F evaluation."""

import asyncio
import contextlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.llm.base import LLMClient
from src.llm.factory import get_client
from src.interview.story_bank import StoryBank
from src.matching.archetypes import detect_archetype, load_archetypes
from src.storage.models import Job, JobStatus, MatchResult

logger = logging.getLogger(__name__)

from src.config.profile import get_profile_path

_EXPECTED_BLOCKS = frozenset(
    ["A_role_summary", "B_cv_match", "C_level_strategy",
     "D_compensation", "E_personalization", "F_interview_prep"]
)

BLOCK_WEIGHTS: dict[str, float] = {
    "A_role_summary": 0.10,      # 10% — role categorization
    "B_cv_match": 0.25,          # 25% — CV/offer fit (most important)
    "C_level_strategy": 0.15,    # 15% — seniority alignment
    "D_compensation": 0.15,      # 15% — salary/compensation
    "E_personalization": 0.20,   # 20% — CV + cover letter personalization
    "F_interview_prep": 0.15,    # 15% — interview preparation
}


def _compute_global_score(blocks: list["BlockScore"]) -> float:
    """Compute a deterministic 0-100 score from block scores (1.0-5.0).

    Missing blocks default to 3.0 (neutral midpoint).
    Formula: ((weighted_avg - 1.0) / 4.0) * 100
    """
    scores = {b.name: b.score for b in blocks}
    for name in BLOCK_WEIGHTS:
        if name not in scores:
            logger.warning("Block %s missing — using default 3.0", name)

    weighted_sum = sum(
        scores.get(name, 3.0) * weight
        for name, weight in BLOCK_WEIGHTS.items()
    )
    global_score = round(((weighted_sum - 1.0) / 4.0) * 100, 1)
    return max(0.0, min(100.0, global_score))

_SYSTEM_MESSAGE = (
    "You are a job matching expert. Evaluate the fit between the candidate profile "
    "and the job offer using a structured multi-block evaluation (A through F).\n"
    "Salary has been normalized to EUR with purchasing power parity (PPP). "
    "Compare directly against the candidate's EUR salary target.\n\n"
    "Return ONLY valid JSON with this exact schema:\n"
    "{\n"
    '  "archetype": "<detected archetype key>",\n'
    '  "blocks": {\n'
    '    "A_role_summary": {\n'
    '      "score": <float 1.0-5.0>,\n'
    '      "archetype_detected": "<archetype key>",\n'
    '      "domain": "<domain>",\n'
    '      "function": "<function>",\n'
    '      "seniority": "<level>",\n'
    '      "work_arrangement": "<arrangement>",\n'
    '      "one_liner": "<one line summary>"\n'
    "    },\n"
    '    "B_cv_match": {\n'
    '      "score": <float 1.0-5.0>,\n'
    '      "matched_requirements": [{"requirement": "...", "cv_proof": "...", "strength": "..."}],\n'
    '      "gaps": [{"requirement": "...", "severity": "...", "mitigation": "..."}]\n'
    "    },\n"
    '    "C_level_strategy": {\n'
    '      "score": <float 1.0-5.0>,\n'
    '      "detected_level": "...", "candidate_level": "...",\n'
    '      "positioning_notes": "...", "downlevel_contingency": null\n'
    "    },\n"
    '    "D_compensation": {\n'
    '      "score": <float 1.0-5.0>,\n'
    '      "salary_assessment": "...", "market_context": "...", "ppp_analysis": "..."\n'
    "    },\n"
    '    "E_personalization": {\n'
    '      "score": <float 1.0-5.0>,\n'
    '      "cv_changes": [{"current": "...", "proposed": "...", "reason": "..."}],\n'
    '      "cover_letter_hooks": ["..."]\n'
    "    },\n"
    '    "F_interview_prep": {\n'
    '      "score": <float 1.0-5.0>,\n'
    '      "stories": [{"requirement": "...", "star_prompt": "...", "suggested_story_id": "..."}],\n'
    '      "red_flag_questions": ["..."]\n'
    "    }\n"
    "  },\n"
    '  "reasoning": "<2-3 sentences>",\n'
    '  "strengths": ["<strength>", ...],\n'
    '  "concerns": ["<concern>", ...]\n'
    "}\n"
    "Note: global_score is computed server-side from block scores — do not include it.\n"
    "Do not include any text outside the JSON object."
)


@dataclass
class BlockScore:
    """Score for a single evaluation block (A-F)."""

    name: str
    score: float
    details: dict[str, Any]


@dataclass
class ScoreResult:
    """Result of scoring a single job offer."""

    score: float
    reasoning: str
    strengths: list[str]
    concerns: list[str]
    archetype: str = "generic"
    blocks: list[BlockScore] = field(default_factory=list)


class ScoringError(Exception):
    """Raised when the LLM response cannot be parsed into a ScoreResult."""

    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


class Scorer:
    """Score job offers against the candidate profile using an LLM."""

    def __init__(self, client: LLMClient | None = None, story_bank: StoryBank | None = None) -> None:
        if client is None:
            provider = settings.llm_scoring_provider or settings.llm_provider
            model = settings.llm_scoring_model or settings.llm_model or None
            client = get_client(provider, model=model)
        self._client = client
        # Resolve profile path at construction time, not at module import.
        # This ensures PROFILE_PATH env var changes (e.g. between test runs
        # or multi-tenant Docker restarts) are picked up without re-importing.
        profile_path = get_profile_path()
        with profile_path.open() as fh:
            self._profile: dict[str, Any] = yaml.safe_load(fh)
        self._archetypes = self._profile.get("archetypes", {})
        try:
            self._story_bank = story_bank or StoryBank()
        except FileNotFoundError:
            logger.warning("stories.yaml not found — Block F will have no stories")
            self._story_bank = None

    async def score(self, job: Job) -> ScoreResult:
        text = await self._client.complete(
            prompt=self._build_prompt(job),
            max_tokens=4096,
            system=_SYSTEM_MESSAGE,
        )
        return self._parse_response(text)

    async def score_and_persist(self, job: Job, session: Session) -> MatchResult:
        result = await self.score(job)

        existing = session.execute(
            select(MatchResult).where(MatchResult.job_id == job.id)
        ).scalar_one_or_none()

        scoring_model = settings.llm_scoring_model or settings.llm_model
        scoring_provider = settings.llm_scoring_provider or settings.llm_provider
        model_label = scoring_model or f"{scoring_provider}/default"

        # Serialize blocks to JSON for DB storage
        evaluation_data = {
            "archetype": result.archetype,
            "global_score": result.score,
            "blocks": {
                b.name: {"score": b.score, **b.details}
                for b in result.blocks
            },
        }
        eval_json = json.dumps(evaluation_data)

        if existing:
            existing.score = result.score  # type: ignore[assignment]
            existing.reasoning = result.reasoning  # type: ignore[assignment]
            existing.strengths_json = json.dumps(result.strengths)  # type: ignore[assignment]
            existing.concerns_json = json.dumps(result.concerns)  # type: ignore[assignment]
            existing.model_used = model_label  # type: ignore[assignment]
            existing.evaluation_json = eval_json  # type: ignore[assignment]
            existing.archetype = result.archetype  # type: ignore[assignment]
            match_result = existing
        else:
            match_result = MatchResult(
                job_id=job.id,
                score=result.score,
                reasoning=result.reasoning,
                strengths_json=json.dumps(result.strengths),
                concerns_json=json.dumps(result.concerns),
                model_used=model_label,
                evaluation_json=eval_json,
                archetype=result.archetype,
            )
            session.add(match_result)

        job.match_score = result.score  # type: ignore[assignment]
        job.match_reasoning = result.reasoning  # type: ignore[assignment]
        threshold = settings.min_match_score
        job.status = (
            JobStatus.MATCHED if result.score >= threshold else JobStatus.SKIPPED  # type: ignore[assignment]
        )

        session.commit()
        return match_result

    async def score_batch(self, jobs: list[Job], session: Session) -> list[MatchResult]:
        # Each coroutine gets its own session to avoid concurrent commit races.
        # SQLAlchemy Session is NOT coroutine-safe — sharing one session across
        # asyncio.gather() tasks causes identity_map corruption and overlapping
        # commits. We only use the incoming `session` to read job IDs; each
        # _score_one opens its own get_session() for the write path.
        from src.storage.database import get_session as _get_session

        semaphore = asyncio.Semaphore(5)

        async def _score_one(job_id: int) -> MatchResult:
            async with semaphore:
                with _get_session() as own_session:
                    job_obj = own_session.get(Job, job_id)
                    if job_obj is None:
                        raise ValueError(f"Job {job_id} not found")
                    return await self.score_and_persist(job_obj, own_session)

        job_ids = [j.id for j in jobs]
        tasks = [_score_one(jid) for jid in job_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: list[MatchResult] = []
        for job_id, res in zip(job_ids, results):
            if isinstance(res, Exception):
                logger.warning("Scoring failed for job_id=%s: %s", job_id, res)
            else:
                out.append(res)
        return out

    def _build_prompt(self, job: Job) -> str:
        p = self._profile
        candidate = p.get("candidate", {})
        skills = p.get("skills", {})
        salary = p.get("salary", {})
        filters = p.get("filters", {})
        experiences = p.get("experiences", [])

        top_skills = skills.get("top_3", [])[:3]
        tech_stack = skills.get("tech_stack", {})
        # Flatten tech_stack dict into a list
        if isinstance(tech_stack, dict):
            flat_stack = []
            for category_items in tech_stack.values():
                if isinstance(category_items, list):
                    flat_stack.extend(category_items)
            tech_stack_str = ", ".join(flat_stack)
        else:
            tech_stack_str = ", ".join(tech_stack)

        # Detect archetype for this job
        archetype_key = detect_archetype(
            job.title, job.description or "", self._archetypes,
        )
        archetype_cfg = self._archetypes.get(archetype_key, {})

        # Build experiences section
        exp_lines = []
        for exp in experiences[:5]:
            exp_lines.append(
                f"  - {exp.get('title', '')} @ {exp.get('company', '')} "
                f"({exp.get('start', '')}–{exp.get('end') or 'present'})"
            )
            for bullet in exp.get("bullets", [])[:3]:
                exp_lines.append(f"    • {bullet}")
        experiences_text = "\n".join(exp_lines) if exp_lines else "Not provided"

        # Build archetype section
        archetype_text = ""
        if archetype_key != "generic" and archetype_cfg:
            proof = ", ".join(archetype_cfg.get("proof_priorities", []))
            cv_emph = ", ".join(archetype_cfg.get("cv_emphasis", []))
            archetype_text = (
                f"\n## Archetype Detected: {archetype_cfg.get('label', archetype_key)}\n"
                f"- Key: {archetype_key}\n"
                f"- Proof priorities: {proof}\n"
                f"- CV emphasis: {cv_emph}\n"
            )

        prompt = (
            "## Candidate Profile\n"
            f"- Title: {candidate.get('title', 'Unknown')}\n"
            f"- Experience: {candidate.get('experience_years', 'Unknown')} years\n"
            f"- Top skills: {', '.join(top_skills)}\n"
            f"- Full stack: {tech_stack_str}\n"
            f"- Salary target: {salary.get('min_annual', '')}–{salary.get('max_annual', '')} EUR/year"
            f" (or {salary.get('min_daily_rate', '')}–{salary.get('max_daily_rate', '')} EUR/day freelance)\n"
            f"- Remote only: {filters.get('remote_only', False)}\n"
            f"- Contract types: {', '.join(filters.get('preferred_contract_types', []))}\n"
            f"\n## Key Experiences\n{experiences_text}\n"
            f"{archetype_text}"
            "\n## Job Offer\n"
            f"- Title: {job.title}\n"
            f"- Company: {job.company.name if job.company else 'Unknown'}\n"
            f"- Contract: {job.contract_type or 'Unknown'}\n"
            f"- Remote: {job.is_remote}\n"
            f"- Location: {job.location or 'Unknown'}\n"
            f"- Country: {getattr(job, 'country_code', 'FR') or 'FR'}\n"
            f"- Salary (original): {job.salary_raw or 'Not specified'}"
            f" ({job.salary_min}–{job.salary_max} {getattr(job, 'salary_currency', None) or 'EUR'})\n"
        )

        if getattr(job, "salary_normalized_min", None) or getattr(job, "salary_normalized_max", None):
            prompt += f"- Salary (PPP-normalized EUR): {job.salary_normalized_min}–{job.salary_normalized_max}\n"

        prompt += f"- Description:\n{(job.description or '')[:4000]}"

        # Company Intelligence enrichment (from CompanyInsight research)
        company = job.company
        if company and company.researched_at:
            lines = ["\n\n## Company Intelligence"]
            if company.funding_stage:
                lines.append(f"- Funding stage: {company.funding_stage}")
            if company.glassdoor_rating:
                lines.append(f"- Glassdoor rating: {company.glassdoor_rating}")
            for label, attr in [
                ("Tech stack signals", "tech_stack_signals"),
                ("Culture signals", "culture_signals"),
                ("Growth signals", "growth_signals"),
                ("Red flags", "red_flags"),
            ]:
                raw = getattr(company, attr, None)
                if raw:
                    try:
                        items = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        items = [raw]
                    if items:
                        lines.append(f"- {label}: {', '.join(str(i) for i in items)}")
            if len(lines) > 1:  # more than just the header
                prompt += "\n".join(lines)

        # Block F enrichment: inject matching stories for interview prep
        if self._story_bank is not None:
            stories = self._story_bank.get_stories_for_job(
                job_title=job.title,
                job_description=job.description or "",
                archetype=archetype_key,
            )
            stories_text = self._story_bank.format_for_evaluation(stories)
            if stories_text:
                prompt += (
                    "\n\n## Candidate Interview Stories (STAR+R)\n"
                    "Use these stories in Block F to map to job requirements.\n\n"
                    f"{stories_text}"
                )

        return prompt

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        """Remove ```json ... ``` or ``` ... ``` wrappers that LLMs love to add.

        Handles: ```json, ```JSON, ```, preamble text before fences,
        trailing whitespace around fences.
        """
        stripped = text.strip()
        # Find the fence even if there's preamble text before it
        fence_match = re.search(r"```(?:\w+)?[ \t]*\n", stripped)
        if fence_match:
            stripped = stripped[fence_match.end():]
            # Remove closing fence
            if stripped.rstrip().endswith("```"):
                stripped = stripped.rstrip()[:-3].rstrip()
        return stripped

    @staticmethod
    def _extract_json_object(text: str) -> str | None:
        """Extract the first balanced JSON object from text using brace counting.

        Unlike a greedy regex, this correctly handles:
        - Braces inside JSON string values
        - Extra text after the JSON (postamble with {braces})
        - Truncated JSON (returns None)
        """
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

        # Braces never balanced — truncated response
        return None

    def _parse_response(self, response_text: str) -> ScoreResult:
        data: dict[str, Any] | None = None
        # Step 1: strip markdown fences (LLMs almost always add them)
        cleaned = self._strip_markdown_fences(response_text)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Step 2: fallback — extract first balanced JSON object
            json_str = self._extract_json_object(cleaned)
            if json_str:
                with contextlib.suppress(json.JSONDecodeError):
                    data = json.loads(json_str)

        if data is None:
            logger.error(
                "LLM response (first 500 chars): %s | length=%d",
                response_text[:500], len(response_text),
            )
            raise ScoringError("Could not parse JSON from response", raw=response_text)

        reasoning = data.get("reasoning")
        if reasoning is None:
            raise ScoringError("Missing required key: reasoning", raw=response_text)

        strengths = list(data.get("strengths", []))
        concerns = list(data.get("concerns", []))
        archetype = data.get("archetype", "generic")

        # Parse blocks
        blocks: list[BlockScore] = []
        raw_blocks = data.get("blocks", {})
        if isinstance(raw_blocks, dict):
            for block_name in _EXPECTED_BLOCKS:
                if block_name in raw_blocks:
                    block_data = raw_blocks[block_name]
                    block_score = float(block_data.get("score", 0))
                    details = {k: v for k, v in block_data.items() if k != "score"}
                    blocks.append(BlockScore(
                        name=block_name,
                        score=block_score,
                        details=details,
                    ))
                else:
                    logger.warning("Missing block %s in LLM response", block_name)

        # Deterministic score: compute from blocks when available,
        # fallback to LLM score for old-style responses (no blocks).
        if blocks:
            llm_score = data.get("global_score")
            score = _compute_global_score(blocks)
            if llm_score is not None:
                logger.debug(
                    "LLM global_score=%s, computed=%s (using computed)",
                    llm_score, score,
                )
        elif "global_score" in data:
            score = max(0.0, min(100.0, float(data["global_score"])))
        elif "score" in data:
            score = max(0.0, min(100.0, float(data["score"])))
        else:
            raise ScoringError("Missing required key: score", raw=response_text)

        return ScoreResult(
            score=score,
            reasoning=reasoning,
            strengths=strengths,
            concerns=concerns,
            archetype=archetype,
            blocks=blocks,
        )
