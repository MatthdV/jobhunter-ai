# Phase 3 — Generators Design

**Date**: 2026-03-21
**Scope**: LinkedIn importer, CV generator, cover letter generator
**Status**: Approved

---

## Context

Phase 3 automates the production of tailored application documents per job offer. It consists of three components:

1. **LinkedIn importer** — one-shot bootstrap that reads a LinkedIn data export ZIP and populates `profile.yaml` with work experience, education, and projects
2. **CVGenerator** — generates a personalised PDF CV per job offer using Jinja2 + WeasyPrint, with Claude selecting which experiences to highlight
3. **CoverLetterGenerator** — generates a plain-text cover letter per job offer using Claude, in the candidate's natural voice

---

## 1. LinkedIn Importer

### Location

`src/importers/linkedin_importer.py`

`src/importers/__init__.py` is an empty file (package marker only; the class is not re-exported from it — tests import directly from `src.importers.linkedin_importer`).

### Public interface

```python
class LinkedInImporter:
    def import_zip(self, zip_path: Path, profile_path: Path) -> None: ...
```

Usage:
```python
importer = LinkedInImporter()
importer.import_zip(zip_path, profile_path)
```

### Flow

1. Open the ZIP file. If `zip_path` does not exist or is not a valid ZIP archive, raise `ValueError(f"Not a valid ZIP file: {zip_path}")` immediately.
2. Locate the relevant LinkedIn CSV files: `Positions.csv`, `Education.csv`, `Skills.csv`, `Projects.csv`. If a CSV file is missing from the ZIP, log a warning and skip that section — the corresponding `profile.yaml` section is left unchanged.
3. Parse each present CSV into lightweight Python dataclasses.
4. Replace (not merge) the `experiences`, `education`, `skills.top_3`, and `projects` top-level sections in `profile.yaml`. The entire `skills` mapping is not replaced — only the `top_3` list within it is overwritten. `skills.additional` and `skills.tech_stack` are preserved.
5. Write the updated YAML back to disk.

### TDD coverage for CSV parsers

Slices 1–2 validate `Positions.csv` parsing and YAML writing. `Education.csv`, `Skills.csv`, and `Projects.csv` follow the same parsing pattern (CSV row → dict). They share the same code path and do not have dedicated slices — the integration is validated via the `import_zip` end-to-end test fixture which includes all four files.

### CLI command

```bash
python -m src.main import-linkedin <zip_path>
```

### Design notes

- No Claude call — pure CSV → YAML parsing, fast and deterministic
- Idempotent: re-running on the same ZIP produces the same result
- Only the four LinkedIn-sourced sections are overwritten; all other sections are preserved
- Pre-existing note: `Scorer._build_prompt` reads `skills.get("top", [])` (wrong key — should be `top_3`). This is a known bug, out of scope for Phase 3. Phase 3 generators always use `skills["top_3"]` — the two coexist until Phase 2 is revisited.

---

## 2. Extended `profile.yaml` schema

Three new top-level sections are added. The canonical key for the top skills list is `skills.top_3` (as declared in the existing `profile.yaml`). Note: `Scorer._build_prompt` currently reads `skills.get("top", [])` — this is a pre-existing key mismatch and out of scope for Phase 3.

```yaml
experiences:
  - id: exp_qonto_revops          # unique slug — referenced by _select_highlights
    company: Qonto
    title: RevOps Lead
    start: "2022-03"
    end: null                     # null = current role
    location: Paris (Remote)
    bullets:
      - "Automatisé le pipeline CRM avec n8n — -40% de saisie manuelle"
      - "Déployé 12 workflows Salesforce → HubSpot en 3 mois"

education:
  - institution: ESCP Business School
    degree: Master Management
    start: "2013"
    end: "2015"

projects:
  - id: proj_jobhunter
    name: JobHunter AI
    description: "Système d'automatisation de recherche d'emploi — Python, Claude API, n8n"
    url: https://github.com/mdevillele/jobhunter-ai
```

The `id` field on each experience and project is the key used by `_select_highlights` — Claude returns a list of ids rather than rewriting content.

**Skill identification**: `skill_ids` in the Claude response are matched **by string value** against the flat list produced by concatenating `skills["top_3"] + skills.get("additional", [])`. Values are short unique strings (e.g. `"n8n"`, `"Python"`) — no separate ID slugs needed.

---

## 3. CVGenerator

### Public interface

```python
generator = CVGenerator()
pdf_path = await generator.generate(job: Job, output_dir: Path) -> Path
```

`output_dir` is a required positional argument (no default), matching the existing stub signature.

### Constants (module level)

```python
_CV_SYSTEM_MESSAGE = (
    "You are a CV personalisation assistant. Given a candidate profile and a job offer, "
    "identify which experiences and skills to highlight. "
    "Return ONLY valid JSON with this exact schema:\n"
    '{"experience_ids": ["<id>", ...], "skill_ids": ["<value>", ...], "hook": "<one sentence>"}\n'
    "experience_ids must be a subset of the IDs present in the profile. "
    "skill_ids must be string values from the candidate's skills list. "
    "Do not include any text outside the JSON object."
)
_CV_MAX_TOKENS = 256
```

### Method signatures

```python
async def generate(self, job: Job, output_dir: Path) -> Path: ...
async def _select_highlights(self, job: Job) -> dict[str, Any]: ...
def _render_html(self, context: dict[str, Any]) -> str: ...
def _html_to_pdf(self, html: str, output_path: Path) -> Path: ...
```

### Flow

1. `__init__` — loads `profile.yaml` using a module-level constant `_PROFILE_PATH = Path(__file__).parent.parent / "config" / "profile.yaml"` (same pattern as `Scorer`). Initialises Jinja2 environment from `src/generators/templates/`. Raises `ConfigurationError` if `ANTHROPIC_API_KEY` is not set. Uses `settings.anthropic_model` for all Claude calls.

2. `_select_highlights(job) -> dict[str, Any]` → single Claude call:
   - model: `settings.anthropic_model`, max_tokens: `_CV_MAX_TOKENS`, system: `_CV_SYSTEM_MESSAGE`
   - Response text extracted using the same pattern as `Scorer`: `next(block.text for block in response.content if hasattr(block, "text"))`
   - Parsed with `json.loads()`. Fallback regex extraction on `json.JSONDecodeError` (same pattern as `Scorer._parse_response`).
   - Returns `{"experience_ids": [...], "skill_ids": [...], "hook": "..."}` typed as `dict[str, Any]` — intentional use of `Any` per project convention (same as `Scorer._parse_response`), documented here as an exception to strict mypy.

3. `generate()` catches any exception from `_select_highlights` and applies the fallback:
   ```python
   fallback = {"experience_ids": [e["id"] for e in self._profile["experiences"]], "skill_ids": [], "hook": ""}
   ```
   `_select_highlights` itself does **not** catch exceptions — it propagates them to `generate()`. The fallback lives in `generate()`.

4. `generate()` truncates `experience_ids` to the **first 4 entries** after receiving the result (from highlights or fallback).

5. Experiences in `context["experiences"]` are ordered **in the order Claude returned them** in `experience_ids` (i.e. the Claude-ranked order is preserved). Experiences not in `experience_ids` are excluded.

6. Company name resolution: `job.company.name if job.company else "unknown"` — handles missing relationship gracefully.

7. Output filename: `cv_{slug(job.title)}_{slug(company_name)}_{YYYYMMDD}.pdf`
   Slugification: `re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:40]`

8. `_render_html(context)` → Jinja2 template `cv.html.jinja2`.

   **`context` schema** (exact keys):
   ```python
   {
       "candidate":    dict,        # profile["candidate"]
       "experiences":  list[dict],  # filtered, ordered per experience_ids, max 4
       "skills_all":   list[str],   # skills["top_3"] + skills.get("additional", [])
       "skill_ids":    list[str],   # highlighted skill values (subset of skills_all)
       "education":    list[dict],  # profile["education"]
       "projects":     list[dict],  # profile["projects"]
       "hook":         str,         # from _select_highlights (may be "")
   }
   ```

9. `_html_to_pdf(html, output_path)` → real WeasyPrint call, writes the PDF, returns `output_path`.

10. `generate()` orchestrates steps 2–9, returns the `Path` to the written PDF.

### Template (MVP)

Single-column HTML with inline CSS (required for WeasyPrint compatibility):

- **Header**: name, title, location, contact links
- **Experiences**: `experiences` list (already sorted and capped), each with company, title, dates, bullets
- **Skills**: `skills_all` comma-separated; values in `skill_ids` wrapped in `<strong>`
- **Education**: institution, degree, dates
- **Projects**: name, description, URL (if any)

### WeasyPrint in tests

`_html_to_pdf` and the end-to-end `generate()` are tested with **real WeasyPrint calls** (slices 7–8). This requires the native WeasyPrint dependencies (libpango, libcairo) to be installed. Mark these tests with `@pytest.mark.weasyprint` and add a `conftest.py` `skipif` that skips the mark when the `SKIP_WEASYPRINT` environment variable is set — allows CI to opt out. Document installation in `README`.

---

## 4. CoverLetterGenerator

### Public interface

```python
generator = CoverLetterGenerator()
text: str = await generator.generate(job: Job) -> str
text: str = await generator.refine(application: Application, feedback: str) -> str
```

`application.job` is a valid SQLAlchemy relationship on the `Application` model (`job = relationship("Job", back_populates="application")` in `src/storage/models.py`).

### Constants (module level)

```python
_CL_MAX_TOKENS = 1024   # ~750 words headroom for a 300-400 word letter

_FORBIDDEN_WORDS: frozenset[str] = frozenset([
    "holistique", "synergique", "écosystème", "paradigme",
    "booster", "disruptif", "levier",
])

_ENGLISH_FUNCTION_WORDS: frozenset[str] = frozenset([
    "the", "and", "for", "with", "you", "our", "are", "this", "that", "will",
    "have", "from", "they", "your", "been", "has", "its", "can", "we", "their",
    "an", "be", "at", "by", "as", "is", "it", "in", "of", "to", "a",
    "who", "what", "which", "but", "not", "or", "if", "on", "so", "all",
    "more", "also", "when", "than", "then", "into", "about", "up", "out",
])
_ENGLISH_THRESHOLD: float = 0.25   # validated: FR max 0.23 (bilingual), EN min 0.36 — safe gap
```

### Method signatures

```python
def _detect_language(self, job: Job) -> Literal["fr", "en"]: ...
def _build_prompt(self, job: Job) -> str: ...
async def generate(self, job: Job) -> str: ...
async def refine(self, application: Application, feedback: str) -> str: ...
```

### Flow

1. `__init__` — loads `profile.yaml`, initialises `anthropic.AsyncAnthropic`, raises `ConfigurationError` if `ANTHROPIC_API_KEY` is not set. Uses `settings.anthropic_model` for all Claude calls.

2. `_detect_language(job) -> Literal["fr", "en"]` — tokenise `job.description` by whitespace, lowercase, strip non-alpha. Compute the fraction of tokens present in `_ENGLISH_FUNCTION_WORDS`. If fraction > `_ENGLISH_THRESHOLD` (0.25) → `'en'`; else `'fr'`. If `job.description` is `None` or empty, default to `'fr'`. Empirically validated: French jobs (even bilingual) top at 0.23; English jobs start at 0.36.

3. `_build_prompt(job) -> str` — calls `_detect_language(job)` internally to determine language. Constructs the prompt with:
   - Candidate: name, title, first 3 experiences by YAML order (title + company + first 2 bullets each), `skills["top_3"]`
   - Job: title, company name (`job.company.name if job.company else "unknown"`), description truncated to 1500 chars
   - Language instruction: `"Write entirely in {'French' if lang == 'fr' else 'English'}."`
   - Tone rules (open with concrete hook, 2–3 measurable outcomes, direct CTA)
   - Forbidden words instruction: `"Never use the following words: holistique, synergique, écosystème, paradigme, booster, disruptif, levier."`
   - Length instruction: `"Target length: 300–400 words."`

4. `generate(job) -> str` → single Claude call:
   - model: `settings.anthropic_model`, max_tokens: `_CL_MAX_TOKENS`
   - messages: `[{"role": "user", "content": self._build_prompt(job)}]`
   - Response text extracted with same pattern as `Scorer`
   - Returns the raw text response

5. `refine(application, feedback) -> str` → constructs a refinement prompt:
   ```
   {self._build_prompt(application.job)}

   ---
   EXISTING LETTER:
   {application.cover_letter}

   ---
   FEEDBACK:
   {feedback}

   ---
   Revise the letter above according to the feedback. Keep the same language, length, and tone constraints.
   ```
   Claude call: same model and max_tokens as `generate()`. Returns the revised plain text.

   **Precondition**: `application.cover_letter` must not be `None`. Callers are responsible for ensuring an existing letter exists before calling `refine()`. If `None`, `refine()` raises `ValueError("application.cover_letter is None — generate a letter first")`.

### Slice 11 — what `_build_prompt` test asserts

The test asserts that the forbidden-words **instruction** is present in the prompt string:
```python
assert "holistique" in prompt   # word appears inside the "Never use" instruction
```
This is a positive assertion: the forbidden-word list is expected to appear in the prompt text as part of the constraint instruction to Claude.

### Slice 13 — `refine()` verification

The test for slice 13:
- Mocks the Anthropic client (same `AsyncMock` pattern as other tests)
- Calls `refine(application, feedback)` where `application.cover_letter` is a known string
- Asserts that the string passed to `client.messages.create` includes both the existing letter text and the feedback string
- Asserts that `refine()` returns a non-empty string (the mocked response)

### Output

Plain text stored in `Application.cover_letter` (TEXT column). No PDF. Language matches the job posting.

---

## 5. Error handling

| Situation | Behaviour |
|-----------|-----------|
| Missing API key | `ConfigurationError` at `__init__` (both generators) |
| `zip_path` does not exist or is not a valid ZIP | `ValueError` raised immediately in `import_zip` |
| LinkedIn CSV missing from ZIP | Log warning, skip that section |
| Claude returns unparseable JSON in `_select_highlights` | `generate()` catches, uses fallback dict (all experiences capped at 4, no skill highlights, empty hook), logs warning |
| Claude API error in `generate()` / `refine()` | Propagate exception — caller handles |
| WeasyPrint fails | Propagate exception — caller handles |

---

## 6. TDD plan — 13 vertical slices

| # | Test | Implementation |
|---|------|----------------|
| 1 | `LinkedInImporter` parses `Positions.csv` → list of experience dicts | `import_zip` + CSV parsing |
| 2 | `import_zip` writes all 4 sections (`experiences`, `education`, `skills.top_3`, `projects`) to `profile.yaml`; fixture includes all 4 CSVs; test asserts each section is present in output YAML | YAML merge + write |
| 3 | `CVGenerator.__init__` raises `ConfigurationError` without API key | `__init__` |
| 4 | `_select_highlights` calls Claude with `settings.anthropic_model` + `_CV_MAX_TOKENS`; returns dict with keys `experience_ids` (list[str]), `skill_ids` (list[str]), `hook` (str) | `_select_highlights` |
| 5 | `generate()` uses fallback dict when `_select_highlights` raises | fallback in `generate()` |
| 6 | `_render_html` includes `context["candidate"]["name"]` in the output HTML | `_render_html` + `cv.html.jinja2` |
| 7 | `_html_to_pdf` writes a non-empty file (`tmp_path`, real WeasyPrint) | `_html_to_pdf` |
| 8 | `generate()` returns an existing PDF Path (`tmp_path`, real WeasyPrint) | `generate()` end-to-end |
| 9 | `CoverLetterGenerator.__init__` raises `ConfigurationError` | `__init__` |
| 10 | `_detect_language` returns `'fr'` for French description, `'en'` for English | `_detect_language` |
| 11 | `_build_prompt` contains the forbidden-words instruction (asserts `"holistique" in prompt`) | `_build_prompt` |
| 12 | `generate()` returns a non-empty string (mocked Claude client) | `generate()` |
| 13 | `refine()` prompt includes existing letter text and feedback; returns non-empty string (mocked) | `refine()` |

---

## 7. File map

```
src/
├── importers/
│   ├── __init__.py               # NEW (empty — package marker only)
│   └── linkedin_importer.py      # NEW
├── generators/
│   ├── cv_generator.py           # IMPL (was stub)
│   ├── cover_letter.py           # IMPL (was stub)
│   └── templates/
│       └── cv.html.jinja2        # NEW
tests/
├── test_generators.py            # EXTEND (stubs → real tests)
├── test_importers.py             # NEW
└── fixtures/
    └── linkedin/
        ├── Positions.csv         # NEW (test fixture)
        ├── Education.csv         # NEW (test fixture)
        ├── Skills.csv            # NEW (test fixture)
        └── Projects.csv          # NEW (test fixture)
```
