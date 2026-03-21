# Scorer — Design Spec
**Date**: 2026-03-21
**Phase**: 2 — Matching IA
**File**: `src/matching/scorer.py`

---

## Goal

For each `Job` with `status=NEW` in the database, call the Claude API with a structured prompt that evaluates fit between the job offer and the candidate profile (`profile.yaml`). Return a `ScoreResult` (score 0–100 + structured reasoning). Persist results to a `MatchResult` DB table and update the `Job` status (`MATCHED` if score ≥ threshold, `SKIPPED` otherwise).

---

## Data Model

### New: `MatchResult` ORM table

```python
class MatchResult(Base):
    __tablename__ = "match_results"

    id             = Column(Integer, primary_key=True)
    job_id         = Column(Integer, ForeignKey("jobs.id"), unique=True, nullable=False)
    score          = Column(Float, nullable=False)        # 0–100
    reasoning      = Column(Text, nullable=False)         # 2–3 sentence explanation
    strengths_json = Column(Text, nullable=True)          # JSON array of strings
    concerns_json  = Column(Text, nullable=True)          # JSON array of strings
    model_used     = Column(String(100), nullable=False)  # e.g. "claude-opus-4-6"
    scored_at      = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job", back_populates="match_result")
```

### Modifications to `Job`

- Add `relationship("MatchResult", back_populates="job", uselist=False)` to `Job`.
- Existing `match_score` (Float) and `match_reasoning` (Text) columns remain and are updated on scoring (backward-compatible with downstream phases).

---

## In-Memory Result Type

`ScoreResult` dataclass (already defined in stub — no changes):

```python
@dataclass
class ScoreResult:
    score: float
    reasoning: str
    strengths: list[str]
    concerns: list[str]
```

---

## `Scorer` Class — Public API

### `__init__(self) -> None`
- Loads `src/config/profile.yaml` via `pathlib.Path` relative to the package root.
- Validates `settings.anthropic_api_key`; raises `ConfigurationError` if missing.
- Instantiates `anthropic.AsyncAnthropic(api_key=...)`.

### `async score(self, job: Job) -> ScoreResult`
- Calls `_build_prompt(job)` → sends to Claude → calls `_parse_response()`.
- Pure: does **not** touch the database.
- Raises `ScoringError` if parsing fails after retries.

### `async score_and_persist(self, job: Job, session: AsyncSession) -> MatchResult`
- Calls `score(job)`.
- Writes/upserts a `MatchResult` row.
- Updates `job.match_score`, `job.match_reasoning`, `job.status` (`MATCHED` or `SKIPPED`).
- Commits via the provided session.
- Returns the persisted `MatchResult`.

### `async score_batch(self, jobs: list[Job], session: AsyncSession) -> list[ScoreResult]`
- Runs `score_and_persist` concurrently with `asyncio.Semaphore(5)`.
- Retries on `anthropic.RateLimitError` with exponential backoff: delays 2s → 4s → 8s (max 3 attempts).
- Returns results in the same order as input.

### `_build_prompt(self, job: Job) -> str`
- Injects the candidate profile (title, experience_years, top_3 skills, full tech_stack, salary targets, remote_only, preferred_contract_types) and the job offer (title, company name, description truncated to 2000 chars, salary_raw/min/max, is_remote, contract_type, location).
- Explicitly instructs Claude to evaluate 5 dimensions (see Prompt Design).

### `_parse_response(self, response_text: str) -> ScoreResult`
1. Attempt `json.loads(response_text)`.
2. On failure, apply regex to extract the first `{...}` JSON block.
3. On second failure, raise `ScoringError(raw=response_text)`.
4. Validates required keys (`score`, `reasoning`, `strengths`, `concerns`); coerces `score` to float clamped to [0, 100].

---

## Prompt Design

### System message
```
You are a job matching expert. Evaluate the fit between the candidate profile and
the job offer across 5 dimensions: role alignment, tech stack overlap, salary match,
remote/location, and company type. Return ONLY valid JSON with this exact schema:
{
  "score": <integer 0-100>,
  "reasoning": "<2-3 sentences summarising the overall fit>",
  "strengths": ["<strength>", ...],
  "concerns": ["<concern or gap>", ...]
}
Do not include any text outside the JSON object.
```

### User message (template)
```
## Candidate Profile
- Title: {candidate.title}
- Experience: {candidate.experience_years} years
- Top skills: {skills.top_3}
- Full stack: {tech_stack summary}
- Salary target: {salary.min_annual}–{salary.max_annual} EUR/year (or {salary.min_daily_rate}–{salary.max_daily_rate} EUR/day)
- Remote only: {filters.remote_only}
- Contract types: {filters.preferred_contract_types}

## Job Offer
- Title: {job.title}
- Company: {job.company.name if available}
- Contract: {job.contract_type}
- Remote: {job.is_remote}
- Location: {job.location}
- Salary: {job.salary_raw} ({job.salary_min}–{job.salary_max} EUR)
- Description:
{job.description[:2000]}
```

---

## Error Handling

| Error | Behaviour |
|---|---|
| `ANTHROPIC_API_KEY` missing | `ConfigurationError` raised in `__init__` |
| `anthropic.RateLimitError` | Retry ×3 with exponential backoff (2s/4s/8s), then propagate |
| `anthropic.APIError` | Propagate immediately (not retried) |
| Malformed JSON from Claude | Regex fallback; if still invalid → `ScoringError` |
| Missing JSON keys | `ScoringError` with field name |

`ScoringError` is a new exception defined in `src/matching/scorer.py`.

---

## Threshold & Status Logic

```python
threshold = settings.min_match_score  # default 80

if result.score >= threshold:
    job.status = JobStatus.MATCHED
else:
    job.status = JobStatus.SKIPPED
```

---

## TDD Plan — Vertical Slices

| Slice | Test → Implementation |
|---|---|
| 1 | `test_init_raises_configuration_error_without_api_key` → `__init__` guard |
| 2 | `test_build_prompt_includes_job_title` → `_build_prompt` basic |
| 3 | `test_build_prompt_includes_salary_range` → `_build_prompt` salary injection |
| 4 | `test_parse_response_valid_json` → `_parse_response` happy path |
| 5 | `test_parse_response_handles_malformed_json` → regex fallback |
| 6 | `test_parse_response_raises_scoring_error_on_garbage` → `ScoringError` |
| 7 | `test_score_calls_claude_returns_score_result` → `score()` with `AsyncMock` |
| 8 | `test_score_and_persist_above_threshold_sets_matched` → `score_and_persist` |
| 9 | `test_score_and_persist_below_threshold_sets_skipped` → `score_and_persist` |
| 10 | `test_score_batch_respects_semaphore` → `score_batch` concurrency |
| 11 | `test_score_batch_retries_on_rate_limit` → retry backoff |

**Test infrastructure**:
- Mock: `unittest.mock.AsyncMock` on `anthropic.AsyncAnthropic.messages.create`
- DB: `aiosqlite` in-memory engine via `create_async_engine("sqlite+aiosqlite:///:memory:")`
- Factory: `make_job()` helper that returns an unsaved `Job` with sensible defaults

---

## Files Changed

| File | Change |
|---|---|
| `src/storage/models.py` | Add `MatchResult` model; add relationship to `Job` |
| `src/matching/scorer.py` | Full implementation (replaces stub) |
| `tests/test_matching.py` | Replace pass-stubs with real TDD tests |
