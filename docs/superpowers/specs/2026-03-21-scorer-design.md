# Scorer — Design Spec
**Date**: 2026-03-21
**Phase**: 2 — Matching IA
**File**: `src/matching/scorer.py`

---

## Goal

For each `Job` with `status=NEW` in the database, call the Claude API with a structured prompt that evaluates fit between the job offer and the candidate profile (`profile.yaml`). Return a `ScoreResult` (score 0–100 + structured reasoning). Persist results to a `MatchResult` DB table and update the `Job` status (`MATCHED` if score ≥ threshold, `SKIPPED` otherwise).

---

## Session strategy — sync DB, async Claude calls

`src/storage/database.py` uses a synchronous SQLAlchemy stack (`create_engine`, `Session`, `sessionmaker`). **We keep it synchronous.** The `Scorer` methods are `async` because they `await` the Anthropic client, but all DB writes happen synchronously after the `await` resolves within the same coroutine. This is idiomatic: the async surface is only the network call; SQLite/PostgreSQL writes are fast and non-blocking at this scale.

No changes to `database.py`. No `AsyncSession`, no `aiosqlite`.

---

## Data Model

### `MatchResult` — added to `src/storage/models.py`

`MatchResult` is added directly to the existing `models.py` file so it inherits the module-level `Base` class (no import needed — `Base` is already defined at the top of the file). The snippet below shows only the new class; the imports it needs (`Integer`, `Float`, `Text`, `String`, `DateTime`, `ForeignKey`, `Column`, `relationship`, `datetime`) are already present in `models.py`.

```python
class MatchResult(Base):
    __tablename__ = "match_results"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    job_id         = Column(Integer, ForeignKey("jobs.id"), unique=True, nullable=False)
    # unique=True creates an implicit index on job_id (both SQLite and PostgreSQL
    # create an index as a side-effect of the unique constraint — intentional).
    score          = Column(Float, nullable=False)        # 0–100
    reasoning      = Column(Text, nullable=False)         # 2–3 sentence explanation
    strengths_json = Column(Text, nullable=True)          # JSON-encoded list[str]
    concerns_json  = Column(Text, nullable=True)          # JSON-encoded list[str]
    model_used     = Column(String(100), nullable=False)  # taken from settings.anthropic_model at score time
    scored_at      = Column(DateTime, default=datetime.utcnow)
    # datetime.utcnow is used as a callable reference (not called), same as existing models.
    # Ruff UP017 only flags datetime.utcnow() calls, not references — no lint issue.

    job = relationship("Job", back_populates="match_result")
```

### Modification to `Job` class (in `src/storage/models.py`)

Add the following line to the `Job` class, after the existing `application` relationship (line 97 in current file):

```python
match_result = relationship("MatchResult", back_populates="job", uselist=False)
```

Existing `match_score` (Float) and `match_reasoning` (Text) columns remain and are updated on scoring (backward-compatible with downstream phases 3–5).

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

## Custom Exceptions

```python
class ScoringError(Exception):
    """Raised when Claude's response cannot be parsed into a ScoreResult."""
    def __init__(self, message: str, raw: str = "") -> None: ...
```

Defined in `src/matching/scorer.py`.

---

## `Scorer` Class — Public API

### `__init__(self) -> None`
- Loads `src/config/profile.yaml` via `pathlib.Path` relative to the package root.
- Validates `settings.anthropic_api_key`; raises `ConfigurationError` if missing.
- Instantiates `anthropic.AsyncAnthropic(api_key=...)`.

### `async score(self, job: Job) -> ScoreResult`
- Calls `_build_prompt(job)` → sends to Claude → calls `_parse_response()`.
- Pure: does **not** touch the database.
- The retry logic (for `RateLimitError`) lives here, wrapping only the Anthropic API call, **not** the DB write. This prevents double-persist on retry.
- Raises `ScoringError` if parsing fails after retries.

### `async score_and_persist(self, job: Job, session: Session) -> MatchResult`
- Calls `score(job)` (async).
- **Upsert strategy**: query for an existing `MatchResult` with `job_id == job.id` using `session.execute(select(MatchResult).where(...)).scalar_one_or_none()`. If found, update fields in-place; if not, create a new instance and `session.add()` it.
- Updates `job.match_score`, `job.match_reasoning`, `job.status` (`MATCHED` or `SKIPPED`).
- Commits via the provided session.
- Returns the persisted `MatchResult`.
- Accepts a plain `sqlalchemy.orm.Session` (sync) — not `AsyncSession`.

### `async score_batch(self, jobs: list[Job], session: Session) -> list[MatchResult]`
- **Breaking change from stub**: adds `session: Session` param; return type changes from `list[ScoreResult]` to `list[MatchResult]`.
- Runs `score_and_persist` concurrently with `asyncio.Semaphore(5)`.
- Uses `asyncio.gather(*tasks)` with default `return_exceptions=False` — **fail-fast**: if any job raises an exception (e.g. `ScoringError`, `RateLimitError` exhausted), the batch raises immediately and no further jobs are scored. Callers are responsible for catching and handling partial results.
  - Rationale: a network or parsing error likely affects all concurrent requests; failing fast is more useful than silently returning partial results.
- Results are returned in the same order as input.

### `_build_prompt(self, job: Job) -> str`
- Injects the candidate profile and the job offer (see Prompt Design).
- Guards: `(job.description or "")[:2000]` — description is nullable.

### `_parse_response(self, response_text: str) -> ScoreResult`
1. Attempt `json.loads(response_text)`.
2. On failure, apply regex to extract the first `{...}` JSON block from the text.
3. On second failure, raise `ScoringError(message="…", raw=response_text)`.
4. Validates required keys (`score`, `reasoning`, `strengths`, `concerns`); coerces `score` to `float`, clamps to [0, 100].

---

## Retry Logic (inside `score()`)

Wraps **only the `client.messages.create(...)` call**. The DB write in `score_and_persist` is outside the retry boundary — a successfully persisted result is never re-written on retry.

| Attempt | Delay before retry |
|---|---|
| 1 | (immediate) |
| 2 | 2 s |
| 3 | 4 s |
| 4 (final) | raise `anthropic.RateLimitError` |

Retried exceptions: `anthropic.RateLimitError` only. `anthropic.APIError` propagates immediately.

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
- Salary target: {salary.min_annual}–{salary.max_annual} EUR/year
  (or {salary.min_daily_rate}–{salary.max_daily_rate} EUR/day freelance)
- Remote only: {filters.remote_only}
- Contract types: {filters.preferred_contract_types}

## Job Offer
- Title: {job.title}
- Company: {job.company.name if available else "Unknown"}
- Contract: {job.contract_type or "Unknown"}
- Remote: {job.is_remote}
- Location: {job.location or "Unknown"}
- Salary: {job.salary_raw or "Not specified"} ({job.salary_min}–{job.salary_max} EUR)
- Description:
{(job.description or "")[:2000]}
```

---

## Error Handling

| Error | Behaviour |
|---|---|
| `ANTHROPIC_API_KEY` missing | `ConfigurationError` raised in `__init__` |
| `anthropic.RateLimitError` | Retry ×3 with exponential backoff (2s/4s), then propagate |
| `anthropic.APIError` | Propagate immediately (not retried) |
| Malformed JSON from Claude | Regex fallback; if still invalid → `ScoringError` |
| Missing JSON keys | `ScoringError` with field name |
| `job.description` is `None` | Guarded: `(job.description or "")[:2000]` |
| Any exception in `score_batch` | Fail-fast: batch raises, partial results not returned |

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
| 3 | `test_build_prompt_includes_salary_range` → salary injection |
| 4 | `test_build_prompt_handles_none_description` → None guard |
| 5 | `test_parse_response_valid_json` → `_parse_response` happy path |
| 6 | `test_parse_response_handles_malformed_json` → regex fallback |
| 7 | `test_parse_response_raises_scoring_error_on_garbage` → `ScoringError` |
| 8 | `test_score_calls_claude_returns_score_result` → `score()` with `AsyncMock` |
| 9 | `test_score_retries_on_rate_limit` → retry backoff (mock raises then succeeds) |
| 10 | `test_score_and_persist_above_threshold_sets_matched` → `score_and_persist` insert |
| 11 | `test_score_and_persist_below_threshold_sets_skipped` → `score_and_persist` insert |
| 12 | `test_score_and_persist_upserts_existing_match_result` → upsert path |
| 13 | `test_score_batch_respects_semaphore` → `score_batch` concurrency |
| 14 | `test_score_batch_raises_on_any_scoring_error` → fail-fast behavior |

**Test infrastructure**:
- Mock: `unittest.mock.AsyncMock` on `anthropic.AsyncAnthropic.messages.create`
- DB: sync in-memory SQLite via `configure("sqlite:///:memory:")` + `init_db()`
- Factory: `make_job()` helper returning an unsaved `Job` with sensible defaults

---

## Files Changed

| File | Change |
|---|---|
| `src/storage/models.py` | Add `MatchResult` class; add `match_result` relationship to `Job` |
| `src/matching/scorer.py` | Full implementation (replaces stub) |
| `tests/test_matching.py` | Replace pass-stubs with real TDD tests (14 slices) |
| `pyproject.toml` | No new dependencies needed (anthropic + sqlalchemy already listed) |
