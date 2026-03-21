# Phase 3 Generators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement LinkedIn importer, CVGenerator, and CoverLetterGenerator for Phase 3 of JobHunter AI — from ZIP export to personalised PDF CV and cover letter.

**Architecture:** `LinkedInImporter` bootstraps `profile.yaml` from a LinkedIn data export ZIP (pure CSV parsing, no Claude). `CVGenerator` asks Claude to rank experiences, renders a Jinja2 HTML template, and converts to PDF via WeasyPrint. `CoverLetterGenerator` calls Claude with a structured prompt to produce a natural-voice letter in the detected language (FR/EN).

**Tech Stack:** Python 3.11, anthropic SDK, Jinja2, WeasyPrint, PyYAML, csv, zipfile, pytest + AsyncMock

**Spec:** `docs/superpowers/specs/2026-03-21-phase3-generators-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/importers/__init__.py` | Create | Empty package marker |
| `src/importers/linkedin_importer.py` | Create | CSV → YAML bootstrapper |
| `src/generators/cv_generator.py` | Implement stub | PDF CV generation |
| `src/generators/cover_letter.py` | Implement stub | Cover letter generation |
| `src/generators/templates/cv.html.jinja2` | Create | Single-column CV template |
| `src/config/profile.yaml` | Extend | Add experiences/education/projects sections |
| `src/main.py` | Modify | Add `import-linkedin` CLI command |
| `tests/conftest.py` | Create or modify | `@pytest.mark.weasyprint` + skipif |
| `tests/test_importers.py` | Create | Slices 1–2 |
| `tests/test_generators.py` | Implement stubs | Slices 3–13 |
| `tests/fixtures/test_profile.yaml` | Create | Minimal profile for generator tests |
| `tests/fixtures/linkedin/Positions.csv` | Create | LinkedIn export fixture |
| `tests/fixtures/linkedin/Education.csv` | Create | LinkedIn export fixture |
| `tests/fixtures/linkedin/Skills.csv` | Create | LinkedIn export fixture |
| `tests/fixtures/linkedin/Projects.csv` | Create | LinkedIn export fixture |
| `pyproject.toml` | Modify | Add pytest `markers` entry |

---

## Task 1: Setup — fixtures, conftest, pyproject markers

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/fixtures/test_profile.yaml`
- Create: `tests/fixtures/linkedin/Positions.csv`
- Create: `tests/fixtures/linkedin/Education.csv`
- Create: `tests/fixtures/linkedin/Skills.csv`
- Create: `tests/fixtures/linkedin/Projects.csv`
- Modify: `pyproject.toml`

- [ ] **Step 1: Create CSV fixtures**

`tests/fixtures/linkedin/Positions.csv`:
```
Company Name,Title,Started On,Finished On,Location,Description
Qonto,RevOps Lead,Mar 2022,,Paris (Remote),"Automatisé le pipeline CRM avec n8n — -40% de saisie manuelle
Déployé 12 workflows Salesforce vers HubSpot en 3 mois"
Acme Corp,Automation Engineer,Jan 2020,Feb 2022,Full Remote,Deployed n8n automation workflows for 5 clients
```

`tests/fixtures/linkedin/Education.csv`:
```
School Name,Degree Name,Start Date,End Date
ESCP Business School,Master Management,2013,2015
```

`tests/fixtures/linkedin/Skills.csv`:
```
Name
n8n
Python
RevOps
AI Automation
LangChain
```

`tests/fixtures/linkedin/Projects.csv`:
```
Title,Description,URL
JobHunter AI,Semi-autonomous job search automation — Python + Claude API,https://github.com/mdevillele/jobhunter-ai
```

- [ ] **Step 2: Create test_profile.yaml**

`tests/fixtures/test_profile.yaml`:
```yaml
candidate:
  name: Test Candidate
  title: Automation Engineer
  location: Full Remote

skills:
  top_3: [n8n, Python, RevOps]
  additional: [LangChain, Docker]
  tech_stack: {}

experiences:
  - id: exp_acme_automation
    company: Acme Corp
    title: Automation Engineer
    start: "2022-01"
    end: null
    location: Remote
    bullets:
      - "Built n8n workflows saving 40% manual work"
      - "Integrated 5 APIs for CRM automation"
  - id: exp_beta_revops
    company: Beta Inc
    title: RevOps Consultant
    start: "2020-06"
    end: "2021-12"
    location: Remote
    bullets:
      - "Deployed HubSpot pipeline automation"
      - "Reduced sales cycle by 3 weeks"
  - id: exp_gamma_ai
    company: Gamma
    title: AI Engineer
    start: "2019-01"
    end: "2020-05"
    location: Remote
    bullets:
      - "Built RAG pipeline with LangChain"

education:
  - institution: Some University
    degree: Master Computer Science
    start: "2015"
    end: "2017"

projects:
  - id: proj_test
    name: Test Project
    description: "A test automation project"
    url: null
```

- [ ] **Step 3: Add pytest markers to pyproject.toml**

In `pyproject.toml`, extend `[tool.pytest.ini_options]`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "weasyprint: tests requiring native WeasyPrint dependencies (libpango, libcairo)",
]
```

- [ ] **Step 4: Create or update conftest.py**

Check if `tests/conftest.py` exists first: `ls tests/conftest.py 2>/dev/null || echo "missing"`

If it does not exist, create it. If it exists, append only the `pytest_collection_modifyitems` function if not already present.

`tests/conftest.py` (full content if new file):
```python
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
```

- [ ] **Step 5: Verify markers registered**

Run: `pytest --co -q 2>&1 | head -5`
Expected: no "PytestUnknownMarkWarning" about `weasyprint`

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/fixtures/test_profile.yaml tests/fixtures/linkedin/ pyproject.toml
git commit -m "test(phase3): add fixtures, conftest weasyprint marker, test_profile.yaml"
```

---

## Task 2: LinkedInImporter — package + parse_positions (Slice 1)

**Files:**
- Create: `src/importers/__init__.py`
- Create: `src/importers/linkedin_importer.py`
- Create: `tests/test_importers.py`

- [ ] **Step 1: Write the failing test**

`tests/test_importers.py`:
```python
"""Tests for LinkedInImporter — Phase 3."""

import io
import zipfile
from pathlib import Path

import pytest

from src.importers.linkedin_importer import LinkedInImporter

FIXTURES = Path(__file__).parent / "fixtures" / "linkedin"


def make_zip(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a ZIP file in tmp_path containing the given filename → content mapping."""
    zip_path = tmp_path / "linkedin_export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return zip_path


class TestLinkedInImporterParsePositions:
    def test_parse_positions_returns_experience_list(self, tmp_path: Path) -> None:
        csv_content = (FIXTURES / "Positions.csv").read_text()
        zip_path = make_zip(tmp_path, {"Positions.csv": csv_content})
        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text("candidate:\n  name: Test\n")

        importer = LinkedInImporter()
        importer.import_zip(zip_path, profile_path)

        import yaml
        profile = yaml.safe_load(profile_path.read_text())
        experiences = profile["experiences"]
        assert isinstance(experiences, list)
        assert len(experiences) >= 1
        first = experiences[0]
        assert "id" in first
        assert "company" in first
        assert "title" in first
        assert "bullets" in first
        assert first["id"].startswith("exp_")
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_importers.py::TestLinkedInImporterParsePositions -v
```
Expected: `ModuleNotFoundError: No module named 'src.importers'`

- [ ] **Step 3: Create package and importer skeleton**

`src/importers/__init__.py` — empty file.

`src/importers/linkedin_importer.py`:
```python
"""LinkedIn data export importer — populates profile.yaml from ZIP."""

import csv
import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _slug(value: str) -> str:
    """Slugify a string: lowercase, alphanumeric + underscores, max 40 chars."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:40]


class LinkedInImporter:
    """Import LinkedIn data export ZIP into profile.yaml."""

    def import_zip(self, zip_path: Path, profile_path: Path) -> None:
        """Parse LinkedIn export ZIP and update profile.yaml sections.

        Args:
            zip_path: Path to the LinkedIn data export ZIP file.
            profile_path: Path to the profile.yaml file to update.

        Raises:
            ValueError: If zip_path is not a valid ZIP archive.
        """
        if not zip_path.exists() or not zipfile.is_zipfile(zip_path):
            raise ValueError(f"Not a valid ZIP file: {zip_path}")

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            updates: dict[str, Any] = {}

            if "Positions.csv" in names:
                updates["experiences"] = self._parse_positions(
                    zf.read("Positions.csv").decode("utf-8")
                )
            else:
                logger.warning("Positions.csv not found in ZIP — experiences unchanged")

            if "Education.csv" in names:
                updates["education"] = self._parse_education(
                    zf.read("Education.csv").decode("utf-8")
                )
            else:
                logger.warning("Education.csv not found in ZIP — education unchanged")

            if "Skills.csv" in names:
                updates["skills_top_3"] = self._parse_skills(
                    zf.read("Skills.csv").decode("utf-8")
                )
            else:
                logger.warning("Skills.csv not found in ZIP — skills.top_3 unchanged")

            if "Projects.csv" in names:
                updates["projects"] = self._parse_projects(
                    zf.read("Projects.csv").decode("utf-8")
                )
            else:
                logger.warning("Projects.csv not found in ZIP — projects unchanged")

        with profile_path.open() as fh:
            profile: dict[str, Any] = yaml.safe_load(fh) or {}

        if "experiences" in updates:
            profile["experiences"] = updates["experiences"]
        if "education" in updates:
            profile["education"] = updates["education"]
        if "skills_top_3" in updates:
            if "skills" not in profile:
                profile["skills"] = {}
            profile["skills"]["top_3"] = updates["skills_top_3"]
        if "projects" in updates:
            profile["projects"] = updates["projects"]

        with profile_path.open("w") as fh:
            yaml.dump(profile, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def _parse_positions(self, csv_text: str) -> list[dict[str, Any]]:
        reader = csv.DictReader(io.StringIO(csv_text))
        experiences = []
        for row in reader:
            company = row.get("Company Name", "").strip()
            title = row.get("Title", "").strip()
            if not company or not title:
                continue
            description = row.get("Description", "").strip()
            bullets = [b.strip() for b in description.split("\n") if b.strip()][:3]
            experiences.append({
                "id": f"exp_{_slug(company)}_{_slug(title)}",
                "company": company,
                "title": title,
                "start": row.get("Started On", "").strip() or None,
                "end": row.get("Finished On", "").strip() or None,
                "location": row.get("Location", "").strip() or None,
                "bullets": bullets,
            })
        return experiences

    def _parse_education(self, csv_text: str) -> list[dict[str, Any]]:
        reader = csv.DictReader(io.StringIO(csv_text))
        return [
            {
                "institution": row.get("School Name", "").strip(),
                "degree": row.get("Degree Name", "").strip(),
                "start": row.get("Start Date", "").strip() or None,
                "end": row.get("End Date", "").strip() or None,
            }
            for row in reader
            if row.get("School Name", "").strip()
        ]

    def _parse_skills(self, csv_text: str) -> list[str]:
        reader = csv.DictReader(io.StringIO(csv_text))
        return [row["Name"].strip() for row in reader if row.get("Name", "").strip()][:10]

    def _parse_projects(self, csv_text: str) -> list[dict[str, Any]]:
        reader = csv.DictReader(io.StringIO(csv_text))
        return [
            {
                "id": f"proj_{_slug(row.get('Title', '').strip())}",
                "name": row.get("Title", "").strip(),
                "description": row.get("Description", "").strip(),
                "url": row.get("URL", "").strip() or None,
            }
            for row in reader
            if row.get("Title", "").strip()
        ]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_importers.py::TestLinkedInImporterParsePositions -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/importers/ tests/test_importers.py
git commit -m "feat(importers): add LinkedInImporter skeleton with CSV parsing (slice 1)"
```

---

## Task 3: LinkedInImporter — full import_zip tests + CLI (Slice 2)

> **Note:** `import_zip` was implemented in Task 2. These are integration tests written after the implementation — they validate end-to-end behaviour across all four CSV sections. Run them immediately after writing; they should pass green without additional code changes.

**Files:**
- Modify: `tests/test_importers.py`
- Modify: `src/main.py`

- [ ] **Step 1: Write the integration tests**

Add to `tests/test_importers.py`:
```python
class TestLinkedInImporterImportZip:
    def test_import_zip_writes_all_four_sections(self, tmp_path: Path) -> None:
        """import_zip writes experiences, education, skills.top_3, and projects."""
        files = {
            "Positions.csv": (FIXTURES / "Positions.csv").read_text(),
            "Education.csv": (FIXTURES / "Education.csv").read_text(),
            "Skills.csv": (FIXTURES / "Skills.csv").read_text(),
            "Projects.csv": (FIXTURES / "Projects.csv").read_text(),
        }
        zip_path = make_zip(tmp_path, files)
        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text("candidate:\n  name: Test\nskills:\n  tech_stack: {}\n")

        importer = LinkedInImporter()
        importer.import_zip(zip_path, profile_path)

        import yaml
        profile = yaml.safe_load(profile_path.read_text())

        assert "experiences" in profile
        assert len(profile["experiences"]) >= 1
        assert "education" in profile
        assert len(profile["education"]) >= 1
        assert profile["skills"]["top_3"]  # non-empty list
        assert "projects" in profile
        assert len(profile["projects"]) >= 1
        # tech_stack preserved
        assert "tech_stack" in profile["skills"]

    def test_import_zip_raises_on_invalid_path(self, tmp_path: Path) -> None:
        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text("candidate:\n  name: Test\n")
        with pytest.raises(ValueError, match="Not a valid ZIP"):
            LinkedInImporter().import_zip(tmp_path / "nonexistent.zip", profile_path)

    def test_import_zip_skips_missing_csv(self, tmp_path: Path) -> None:
        """A ZIP with only Positions.csv should not overwrite education/projects."""
        files = {"Positions.csv": (FIXTURES / "Positions.csv").read_text()}
        zip_path = make_zip(tmp_path, files)
        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text(
            "candidate:\n  name: Test\n"
            "education:\n  - institution: Existing\n    degree: BA\n"
        )
        LinkedInImporter().import_zip(zip_path, profile_path)

        import yaml
        profile = yaml.safe_load(profile_path.read_text())
        assert profile["education"][0]["institution"] == "Existing"
```

- [ ] **Step 2: Run to verify all pass (implementation already exists)**

```bash
pytest tests/test_importers.py::TestLinkedInImporterImportZip -v
```
Expected: PASS — implementation was written in Task 2

- [ ] **Step 3: Run full test suite to verify all pass**

```bash
pytest tests/test_importers.py -v
```
Expected: all PASS (the implementation from Task 2 already covers this)

- [ ] **Step 4: Add CLI command to main.py**

Add to `src/main.py`:
```python
@app.command("import-linkedin")
def import_linkedin(
    zip_path: Path = typer.Argument(..., help="Path to the LinkedIn data export ZIP."),
) -> None:
    """Bootstrap profile.yaml with experience data from a LinkedIn export ZIP."""
    from src.importers.linkedin_importer import LinkedInImporter
    from src.config.settings import settings  # noqa: F401 — ensures .env loaded

    profile_path = Path(__file__).parent / "config" / "profile.yaml"
    console.print(f"[bold]Importing[/bold] LinkedIn data from {zip_path}…")
    try:
        LinkedInImporter().import_zip(zip_path, profile_path)
        console.print("[green]Done.[/green] profile.yaml updated.")
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
```

- [ ] **Step 5: Smoke-test CLI (dry run — no real ZIP)**

```bash
python -m src.main import-linkedin --help
```
Expected: shows help text with `ZIP_PATH` argument

- [ ] **Step 6: Commit**

```bash
git add tests/test_importers.py src/main.py
git commit -m "feat(importers): full import_zip + CLI command (slice 2)"
```

---

## Task 4: Extend profile.yaml with experiences/education/projects schema

**Files:**
- Modify: `src/config/profile.yaml`

This is a data-only task — no new tests. The schema must be in place before CVGenerator reads it in production.

- [ ] **Step 1: Add three new sections to profile.yaml**

Append to `src/config/profile.yaml` (after the existing `filters:` section):

```yaml
# ---------------------------------------------------------------------------
# Work experience — source of truth for CV generation
# Populated by: python -m src.main import-linkedin <zip>
# ---------------------------------------------------------------------------
experiences:
  - id: exp_placeholder
    company: "À compléter via import-linkedin"
    title: "Automation & AI Engineer"
    start: "2020-01"
    end: null
    location: "Full Remote"
    bullets:
      - "Importer votre profil LinkedIn avec: python -m src.main import-linkedin <zip>"

# ---------------------------------------------------------------------------
# Education
# ---------------------------------------------------------------------------
education: []

# ---------------------------------------------------------------------------
# Side projects
# ---------------------------------------------------------------------------
projects: []
```

- [ ] **Step 2: Verify YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('src/config/profile.yaml'))"
```
Expected: no output (no error)

- [ ] **Step 3: Commit**

```bash
git add src/config/profile.yaml
git commit -m "feat(profile): add experiences/education/projects schema to profile.yaml"
```

---

## Task 5: CVGenerator __init__ — ConfigurationError (Slice 3)

**Files:**
- Modify: `src/generators/cv_generator.py`
- Modify: `tests/test_generators.py`

- [ ] **Step 1: Write the failing test**

Replace the stub `TestCVGenerator` class in `tests/test_generators.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_generators.py::TestCVGeneratorInit -v
```
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement CVGenerator __init__**

Replace `src/generators/cv_generator.py` with:
```python
"""Personalised CV generation per job offer using Jinja2 + WeasyPrint."""

import contextlib
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import anthropic
import yaml
from jinja2 import Environment, FileSystemLoader

from src.config.settings import ConfigurationError, settings
from src.storage.models import Job

logger = logging.getLogger(__name__)

_PROFILE_PATH = Path(__file__).parent.parent / "config" / "profile.yaml"

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


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:40]


class CVGenerator:
    """Generate a tailored PDF CV for a specific job offer."""

    TEMPLATE_DIR = Path(__file__).parent / "templates"

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise ConfigurationError("ANTHROPIC_API_KEY is required for CV generation")
        with _PROFILE_PATH.open() as fh:
            self._profile: dict[str, Any] = yaml.safe_load(fh)
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(self.TEMPLATE_DIR)),
            autoescape=False,
        )

    async def generate(self, job: Job, output_dir: Path) -> Path:
        raise NotImplementedError

    async def _select_highlights(self, job: Job) -> dict[str, Any]:
        raise NotImplementedError

    def _render_html(self, context: dict[str, Any]) -> str:
        raise NotImplementedError

    def _html_to_pdf(self, html: str, output_path: Path) -> Path:
        raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_generators.py::TestCVGeneratorInit -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/generators/cv_generator.py tests/test_generators.py
git commit -m "feat(cv_generator): implement __init__ with ConfigurationError guard (slice 3)"
```

---

## Task 6: CVGenerator _select_highlights — happy path (Slice 4)

**Files:**
- Modify: `src/generators/cv_generator.py`
- Modify: `tests/test_generators.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_generators.py`, before `TestCVGeneratorInit`:
```python
@pytest.fixture
def mock_cv_client() -> AsyncMock:
    client = AsyncMock()
    msg = MagicMock()
    msg.content = [MagicMock(text=VALID_HIGHLIGHTS)]
    client.messages.create = AsyncMock(return_value=msg)
    return client


@pytest.fixture
def cv_generator(monkeypatch: pytest.MonkeyPatch, mock_cv_client: AsyncMock) -> "CVGenerator":
    monkeypatch.setattr(
        "src.generators.cv_generator.settings",
        MagicMock(anthropic_api_key="test-key", anthropic_model="claude-opus-4-6"),
    )
    monkeypatch.setattr("src.generators.cv_generator._PROFILE_PATH", _TEST_PROFILE)
    with patch("src.generators.cv_generator.anthropic.AsyncAnthropic", return_value=mock_cv_client):
        from src.generators.cv_generator import CVGenerator
        return CVGenerator()
```

Then add `TestCVGeneratorSelectHighlights`:
```python
class TestCVGeneratorSelectHighlights:
    @pytest.mark.asyncio
    async def test_select_highlights_calls_claude_returns_dict(
        self, cv_generator: "CVGenerator", mock_cv_client: AsyncMock
    ) -> None:
        job = make_job()
        result = await cv_generator._select_highlights(job)

        assert isinstance(result, dict)
        assert "experience_ids" in result
        assert isinstance(result["experience_ids"], list)
        assert "skill_ids" in result
        assert isinstance(result["skill_ids"], list)
        assert "hook" in result
        assert isinstance(result["hook"], str)
        mock_cv_client.messages.create.assert_called_once()
        call_kwargs = mock_cv_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-opus-4-6"
        assert call_kwargs["max_tokens"] == 256
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_generators.py::TestCVGeneratorSelectHighlights -v
```
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement _select_highlights**

Replace `_select_highlights` in `cv_generator.py`:
```python
async def _select_highlights(self, job: Job) -> dict[str, Any]:
    """Use Claude to identify which experiences and skills to emphasise."""
    exp_ids = [e["id"] for e in self._profile.get("experiences", [])]
    skills = self._profile.get("skills", {})
    all_skills: list[str] = skills.get("top_3", []) + skills.get("additional", [])

    user_message = (
        "## Candidate Profile\n"
        f"Experience IDs available: {', '.join(exp_ids)}\n"
        f"Skills available: {', '.join(all_skills)}\n\n"
        "## Job Offer\n"
        f"Title: {job.title}\n"
        f"Company: {job.company.name if job.company else 'Unknown'}\n"
        f"Description:\n{(job.description or '')[:1500]}"
    )

    response = await self._client.messages.create(
        model=settings.anthropic_model,
        max_tokens=_CV_MAX_TOKENS,
        system=_CV_SYSTEM_MESSAGE,
        messages=[{"role": "user", "content": user_message}],
    )
    text = next(block.text for block in response.content if hasattr(block, "text"))

    data: dict[str, Any] | None = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            with contextlib.suppress(json.JSONDecodeError):
                data = json.loads(match.group())

    if data is None:
        raise ValueError(f"Could not parse JSON from _select_highlights: {text!r}")

    return data  # type: ignore[return-value]
```

- [ ] **Step 4: Run test**

```bash
pytest tests/test_generators.py::TestCVGeneratorSelectHighlights -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/generators/cv_generator.py tests/test_generators.py
git commit -m "feat(cv_generator): implement _select_highlights with Claude call (slice 4)"
```

---

## Task 7: CVGenerator generate() fallback (Slice 5)

**Files:**
- Modify: `src/generators/cv_generator.py`
- Modify: `tests/test_generators.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_generators.py`:
```python
class TestCVGeneratorFallback:
    @pytest.mark.asyncio
    async def test_generate_uses_fallback_when_select_highlights_raises(
        self, cv_generator: "CVGenerator", mock_cv_client: AsyncMock, tmp_path: Path
    ) -> None:
        mock_cv_client.messages.create = AsyncMock(side_effect=Exception("Claude down"))

        # _render_html and _html_to_pdf are still NotImplementedError at this slice.
        # Patch them directly on the instance to isolate the fallback logic.
        called_with: dict[str, Any] = {}

        def fake_render(context: dict[str, Any]) -> str:
            called_with.update(context)
            return "<html>fallback</html>"

        def fake_pdf(html: str, output_path: Path) -> Path:
            output_path.write_bytes(b"%PDF fallback")
            return output_path

        cv_generator._render_html = fake_render  # type: ignore[method-assign]
        cv_generator._html_to_pdf = fake_pdf  # type: ignore[method-assign]

        await cv_generator.generate(make_job(), tmp_path)

        assert "experiences" in called_with
        assert "skill_ids" in called_with
        assert called_with["skill_ids"] == []   # fallback: no highlights
        assert called_with["hook"] == ""
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_generators.py::TestCVGeneratorFallback -v
```
Expected: FAIL — `NotImplementedError` from `generate()`

- [ ] **Step 3: Implement generate() with fallback**

Replace `generate` in `cv_generator.py`:
```python
async def generate(self, job: Job, output_dir: Path) -> Path:
    """Generate a personalised CV PDF for the given job."""
    try:
        highlights = await self._select_highlights(job)
    except Exception:
        logger.warning("_select_highlights failed — using fallback (natural order)")
        highlights = {
            "experience_ids": [e["id"] for e in self._profile.get("experiences", [])],
            "skill_ids": [],
            "hook": "",
        }

    exp_ids: list[str] = highlights["experience_ids"][:4]
    exp_by_id = {e["id"]: e for e in self._profile.get("experiences", [])}
    experiences = [exp_by_id[eid] for eid in exp_ids if eid in exp_by_id]

    skills = self._profile.get("skills", {})
    skills_all: list[str] = skills.get("top_3", []) + skills.get("additional", [])

    context: dict[str, Any] = {
        "candidate": self._profile.get("candidate", {}),
        "experiences": experiences,
        "skills_all": skills_all,
        "skill_ids": highlights.get("skill_ids", []),
        "education": self._profile.get("education", []),
        "projects": self._profile.get("projects", []),
        "hook": highlights.get("hook", ""),
    }

    html = self._render_html(context)

    company_name = job.company.name if job.company else "unknown"
    filename = (
        f"cv_{_slug(job.title)}_{_slug(company_name)}_{date.today().strftime('%Y%m%d')}.pdf"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    return self._html_to_pdf(html, output_dir / filename)
```

- [ ] **Step 4: Run test**

```bash
pytest tests/test_generators.py::TestCVGeneratorFallback -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/generators/cv_generator.py tests/test_generators.py
git commit -m "feat(cv_generator): implement generate() with fallback on Claude error (slice 5)"
```

---

## Task 8: Jinja2 template + _render_html (Slice 6)

**Files:**
- Create: `src/generators/templates/cv.html.jinja2`
- Modify: `src/generators/cv_generator.py`
- Modify: `tests/test_generators.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_generators.py`:
```python
class TestCVGeneratorRenderHtml:
    def test_render_html_includes_candidate_name(self, cv_generator: "CVGenerator") -> None:
        import yaml
        profile = yaml.safe_load(_TEST_PROFILE.read_text())
        context: dict[str, Any] = {
            "candidate": profile["candidate"],
            "experiences": profile["experiences"][:2],
            "skills_all": ["n8n", "Python"],
            "skill_ids": ["n8n"],
            "education": profile.get("education", []),
            "projects": profile.get("projects", []),
            "hook": "Great fit for this role.",
        }
        html = cv_generator._render_html(context)
        assert "Test Candidate" in html
        assert "<strong>n8n</strong>" in html
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_generators.py::TestCVGeneratorRenderHtml -v
```
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Create the Jinja2 template**

`src/generators/templates/cv.html.jinja2`:
```html
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<style>
  body { font-family: Arial, sans-serif; font-size: 11pt; color: #111; margin: 0; padding: 24pt; }
  h1 { font-size: 20pt; margin: 0 0 4pt; }
  .subtitle { font-size: 12pt; color: #444; margin: 0 0 12pt; }
  h2 { font-size: 12pt; text-transform: uppercase; letter-spacing: 1pt;
       border-bottom: 1pt solid #ccc; margin: 16pt 0 6pt; padding-bottom: 2pt; }
  .exp-header { font-weight: bold; margin-top: 8pt; }
  .exp-meta { font-size: 10pt; color: #555; margin: 1pt 0 3pt; }
  ul { margin: 4pt 0; padding-left: 18pt; }
  li { margin: 2pt 0; }
  .skills { font-size: 10pt; line-height: 1.6; }
  .hook { font-style: italic; color: #333; margin-bottom: 10pt; border-left: 3pt solid #ccc; padding-left: 8pt; }
</style>
</head>
<body>

<h1>{{ candidate.name }}</h1>
<div class="subtitle">{{ candidate.title }}{% if candidate.location %} — {{ candidate.location }}{% endif %}</div>

{% if hook %}
<div class="hook">{{ hook }}</div>
{% endif %}

{% if experiences %}
<h2>Expériences</h2>
{% for exp in experiences %}
<div class="exp-header">{{ exp.title }} — {{ exp.company }}</div>
<div class="exp-meta">
  {{ exp.start or '' }}{% if exp.end %} → {{ exp.end }}{% else %} → présent{% endif %}
  {% if exp.location %} · {{ exp.location }}{% endif %}
</div>
{% if exp.bullets %}
<ul>{% for b in exp.bullets %}<li>{{ b }}</li>{% endfor %}</ul>
{% endif %}
{% endfor %}
{% endif %}

{% if skills_all %}
<h2>Compétences</h2>
<div class="skills">
{% for skill in skills_all %}{% if not loop.first %}, {% endif %}{% if skill in skill_ids %}<strong>{{ skill }}</strong>{% else %}{{ skill }}{% endif %}{% endfor %}
</div>
{% endif %}

{% if education %}
<h2>Formation</h2>
{% for edu in education %}
<div class="exp-header">{{ edu.degree }} — {{ edu.institution }}</div>
<div class="exp-meta">{{ edu.start or '' }}{% if edu.end %} → {{ edu.end }}{% endif %}</div>
{% endfor %}
{% endif %}

{% if projects %}
<h2>Projets</h2>
{% for proj in projects %}
<div class="exp-header">{{ proj.name }}</div>
<div>{{ proj.description }}</div>
{% if proj.url %}<div class="exp-meta">{{ proj.url }}</div>{% endif %}
{% endfor %}
{% endif %}

</body>
</html>
```

- [ ] **Step 4: Implement _render_html**

Replace `_render_html` in `cv_generator.py`:
```python
def _render_html(self, context: dict[str, Any]) -> str:
    """Render the Jinja2 CV template with the given context."""
    template = self._jinja_env.get_template("cv.html.jinja2")
    return template.render(**context)
```

- [ ] **Step 5: Run test**

```bash
pytest tests/test_generators.py::TestCVGeneratorRenderHtml -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/generators/cv_generator.py src/generators/templates/cv.html.jinja2 tests/test_generators.py
git commit -m "feat(cv_generator): implement _render_html + Jinja2 template (slice 6)"
```

---

## Task 9: CVGenerator _html_to_pdf (Slice 7)

**Files:**
- Modify: `src/generators/cv_generator.py`
- Modify: `tests/test_generators.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_generators.py`:
```python
class TestCVGeneratorHtmlToPdf:
    @pytest.mark.weasyprint
    def test_html_to_pdf_writes_nonempty_file(
        self, cv_generator: "CVGenerator", tmp_path: Path
    ) -> None:
        html = "<html><body><p>Test CV content</p></body></html>"
        output_path = tmp_path / "test.pdf"
        result = cv_generator._html_to_pdf(html, output_path)
        assert result == output_path
        assert output_path.exists()
        assert output_path.stat().st_size > 0
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_generators.py::TestCVGeneratorHtmlToPdf -v
```
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement _html_to_pdf**

Replace `_html_to_pdf` in `cv_generator.py`:
```python
def _html_to_pdf(self, html: str, output_path: Path) -> Path:
    """Convert an HTML string to PDF using WeasyPrint."""
    from weasyprint import HTML  # type: ignore[import-untyped]
    HTML(string=html).write_pdf(str(output_path))
    return output_path
```

- [ ] **Step 4: Run test**

```bash
pytest tests/test_generators.py::TestCVGeneratorHtmlToPdf -v
```
Expected: PASS (requires WeasyPrint + libpango/libcairo installed)
If WeasyPrint deps missing: `SKIP_WEASYPRINT=1 pytest tests/test_generators.py::TestCVGeneratorHtmlToPdf -v` → SKIP

- [ ] **Step 5: Commit**

```bash
git add src/generators/cv_generator.py tests/test_generators.py
git commit -m "feat(cv_generator): implement _html_to_pdf with WeasyPrint (slice 7)"
```

---

## Task 10: CVGenerator generate() end-to-end (Slice 8)

**Files:**
- Modify: `tests/test_generators.py`

`generate()` is already implemented (Task 7). This task adds the end-to-end test that exercises the full pipeline.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_generators.py`:
```python
class TestCVGeneratorGenerate:
    @pytest.mark.weasyprint
    @pytest.mark.asyncio
    async def test_generate_returns_existing_pdf_path(
        self, cv_generator: "CVGenerator", tmp_path: Path
    ) -> None:
        pdf_path = await cv_generator.generate(make_job(), tmp_path)
        assert pdf_path.exists()
        assert pdf_path.suffix == ".pdf"
        assert pdf_path.stat().st_size > 0
        assert "automation_engineer" in pdf_path.name
        assert "acme_corp" in pdf_path.name

    @pytest.mark.asyncio
    async def test_generate_output_filename_slugified(
        self, cv_generator: "CVGenerator", tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cv_generator._html_to_pdf = lambda html, path: (path.write_bytes(b"%PDF"), path)[1]  # type: ignore[method-assign]
        pdf_path = await cv_generator.generate(
            make_job(title="Lead RevOps / Data Engineer", company="Acme Corp"), tmp_path
        )
        assert " " not in pdf_path.name
        assert "/" not in pdf_path.name
```

- [ ] **Step 2: Run**

```bash
pytest tests/test_generators.py::TestCVGeneratorGenerate -v
```
Expected: both PASS (weasyprint test may skip if deps missing)

- [ ] **Step 3: Run full generator test suite so far**

```bash
pytest tests/test_generators.py -v -k "CVGenerator"
```
Expected: all PASS (or SKIP for weasyprint marks)

- [ ] **Step 4: Commit**

```bash
git add tests/test_generators.py
git commit -m "test(cv_generator): add end-to-end generate() tests (slice 8)"
```

---

## Task 11: CoverLetterGenerator __init__ (Slice 9)

**Files:**
- Modify: `src/generators/cover_letter.py`
- Modify: `tests/test_generators.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_generators.py`:
```python
# ---------------------------------------------------------------------------
# CoverLetterGenerator tests
# ---------------------------------------------------------------------------


class TestCoverLetterGeneratorInit:
    def test_init_raises_configuration_error_without_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.generators.cover_letter.settings",
            MagicMock(anthropic_api_key="", anthropic_model="claude-opus-4-6"),
        )
        with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
            from src.generators.cover_letter import CoverLetterGenerator
            CoverLetterGenerator()
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_generators.py::TestCoverLetterGeneratorInit -v
```
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement CoverLetterGenerator**

Replace `src/generators/cover_letter.py` entirely:
```python
"""Cover letter generation using Claude — human tone, no buzzwords."""

import logging
import re
from pathlib import Path
from typing import Any, Literal

import anthropic
import yaml

from src.config.settings import ConfigurationError, settings
from src.storage.models import Application, Job

logger = logging.getLogger(__name__)

_PROFILE_PATH = Path(__file__).parent.parent / "config" / "profile.yaml"

_CL_MAX_TOKENS = 1024

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
_ENGLISH_THRESHOLD: float = 0.25  # validated: FR max 0.23, EN min 0.36


class CoverLetterGenerator:
    """Generate a personalised cover letter for a specific job offer."""

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise ConfigurationError("ANTHROPIC_API_KEY is required for cover letter generation")
        with _PROFILE_PATH.open() as fh:
            self._profile: dict[str, Any] = yaml.safe_load(fh)
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def generate(self, job: Job) -> str:
        raise NotImplementedError

    async def refine(self, application: Application, feedback: str) -> str:
        raise NotImplementedError

    def _build_prompt(self, job: Job) -> str:
        raise NotImplementedError

    def _detect_language(self, job: Job) -> Literal["fr", "en"]:
        raise NotImplementedError
```

- [ ] **Step 4: Run test**

```bash
pytest tests/test_generators.py::TestCoverLetterGeneratorInit -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/generators/cover_letter.py tests/test_generators.py
git commit -m "feat(cover_letter): implement __init__ with ConfigurationError guard (slice 9)"
```

---

## Task 12: CoverLetterGenerator _detect_language (Slice 10)

**Files:**
- Modify: `src/generators/cover_letter.py`
- Modify: `tests/test_generators.py`

- [ ] **Step 1: Write the failing test**

Add fixture + test to `tests/test_generators.py`:
```python
@pytest.fixture
def cl_generator(monkeypatch: pytest.MonkeyPatch) -> "CoverLetterGenerator":
    monkeypatch.setattr(
        "src.generators.cover_letter.settings",
        MagicMock(anthropic_api_key="test-key", anthropic_model="claude-opus-4-6"),
    )
    monkeypatch.setattr("src.generators.cover_letter._PROFILE_PATH", _TEST_PROFILE)
    with patch("anthropic.AsyncAnthropic"):
        from src.generators.cover_letter import CoverLetterGenerator
        return CoverLetterGenerator()


class TestCoverLetterDetectLanguage:
    def test_detect_language_returns_fr_for_french_job(
        self, cl_generator: "CoverLetterGenerator"
    ) -> None:
        job = make_job(
            description=(
                "Nous recherchons un ingénieur en automatisation pour rejoindre notre équipe. "
                "Vous serez responsable de l'automatisation des processus CRM avec n8n et Python."
            )
        )
        assert cl_generator._detect_language(job) == "fr"

    def test_detect_language_returns_en_for_english_job(
        self, cl_generator: "CoverLetterGenerator"
    ) -> None:
        job = make_job(
            description=(
                "We are looking for a senior automation engineer to join our platform team. "
                "You will be responsible for building and maintaining our workflow automation systems."
            )
        )
        assert cl_generator._detect_language(job) == "en"

    def test_detect_language_defaults_to_fr_for_empty_description(
        self, cl_generator: "CoverLetterGenerator"
    ) -> None:
        job = make_job(description="")
        assert cl_generator._detect_language(job) == "fr"
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_generators.py::TestCoverLetterDetectLanguage -v
```
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement _detect_language**

Replace `_detect_language` in `cover_letter.py`:
```python
def _detect_language(self, job: Job) -> Literal["fr", "en"]:
    """Detect whether the job posting is in French or English."""
    description = job.description or ""
    if not description.strip():
        return "fr"
    tokens = [re.sub(r"[^a-z]", "", t) for t in description.lower().split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        return "fr"
    en_count = sum(1 for t in tokens if t in _ENGLISH_FUNCTION_WORDS)
    return "en" if (en_count / len(tokens)) > _ENGLISH_THRESHOLD else "fr"
```

- [ ] **Step 4: Run test**

```bash
pytest tests/test_generators.py::TestCoverLetterDetectLanguage -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/generators/cover_letter.py tests/test_generators.py
git commit -m "feat(cover_letter): implement _detect_language with 0.25 threshold (slice 10)"
```

---

## Task 13: CoverLetterGenerator _build_prompt (Slice 11)

**Files:**
- Modify: `src/generators/cover_letter.py`
- Modify: `tests/test_generators.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_generators.py`:
```python
class TestCoverLetterBuildPrompt:
    def test_build_prompt_contains_forbidden_words_instruction(
        self, cl_generator: "CoverLetterGenerator"
    ) -> None:
        """The forbidden-word list appears inside the 'Never use' instruction."""
        job = make_job()
        prompt = cl_generator._build_prompt(job)
        assert "holistique" in prompt
        assert "synergique" in prompt
        assert "Never use" in prompt or "never use" in prompt.lower()

    def test_build_prompt_includes_job_title_and_company(
        self, cl_generator: "CoverLetterGenerator"
    ) -> None:
        job = make_job(title="Senior RevOps Engineer", company="Qonto")
        prompt = cl_generator._build_prompt(job)
        assert "Senior RevOps Engineer" in prompt
        assert "Qonto" in prompt

    def test_build_prompt_contains_language_instruction_french(
        self, cl_generator: "CoverLetterGenerator"
    ) -> None:
        job = make_job(description="Nous recherchons un ingénieur pour rejoindre notre équipe.")
        prompt = cl_generator._build_prompt(job)
        assert "French" in prompt or "french" in prompt.lower()

    def test_build_prompt_contains_language_instruction_english(
        self, cl_generator: "CoverLetterGenerator"
    ) -> None:
        job = make_job(
            description="We are looking for an engineer to join our team and build automation workflows."
        )
        prompt = cl_generator._build_prompt(job)
        assert "English" in prompt or "english" in prompt.lower()
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_generators.py::TestCoverLetterBuildPrompt -v
```
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement _build_prompt**

Replace `_build_prompt` in `cover_letter.py`:
```python
def _build_prompt(self, job: Job) -> str:
    """Build the generation prompt from job data and candidate profile."""
    lang = self._detect_language(job)
    lang_str = "French" if lang == "fr" else "English"

    candidate = self._profile.get("candidate", {})
    experiences = self._profile.get("experiences", [])[:3]
    skills_top: list[str] = self._profile.get("skills", {}).get("top_3", [])

    exp_lines = ""
    for exp in experiences:
        bullets = exp.get("bullets", [])[:2]
        bullet_text = "\n".join(f"  - {b}" for b in bullets)
        exp_lines += f"- {exp['title']} @ {exp['company']}\n{bullet_text}\n"

    company_name = job.company.name if job.company else "unknown"
    description = (job.description or "")[:1500]
    forbidden = ", ".join(sorted(_FORBIDDEN_WORDS))

    return (
        f"## Candidate: {candidate.get('name', '')} — {candidate.get('title', '')}\n"
        f"Top skills: {', '.join(skills_top)}\n\n"
        "## Relevant experiences:\n"
        f"{exp_lines}\n"
        f"## Job: {job.title} at {company_name}\n"
        f"{description}\n\n"
        "---\n"
        f"Write entirely in {lang_str}.\n"
        "Open with a concrete hook tied to the company's product or challenge — no generic opener.\n"
        "Highlight 2–3 experiences with measurable outcomes.\n"
        "End with a direct call-to-action. No hollow enthusiasm.\n"
        f"Never use the following words: {forbidden}.\n"
        "Target length: 300–400 words."
    )
```

- [ ] **Step 4: Run test**

```bash
pytest tests/test_generators.py::TestCoverLetterBuildPrompt -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/generators/cover_letter.py tests/test_generators.py
git commit -m "feat(cover_letter): implement _build_prompt with tone rules + forbidden words (slice 11)"
```

---

## Task 14: CoverLetterGenerator generate() (Slice 12)

**Files:**
- Modify: `src/generators/cover_letter.py`
- Modify: `tests/test_generators.py`

- [ ] **Step 1: Write the failing test**

Add fixture and test:
```python
@pytest.fixture
def mock_cl_client() -> AsyncMock:
    client = AsyncMock()
    msg = MagicMock()
    msg.content = [MagicMock(text="Voici ma lettre de motivation rédigée avec soin.")]
    client.messages.create = AsyncMock(return_value=msg)
    return client


@pytest.fixture
def cl_generator_with_mock(
    monkeypatch: pytest.MonkeyPatch, mock_cl_client: AsyncMock
) -> "CoverLetterGenerator":
    monkeypatch.setattr(
        "src.generators.cover_letter.settings",
        MagicMock(anthropic_api_key="test-key", anthropic_model="claude-opus-4-6"),
    )
    monkeypatch.setattr("src.generators.cover_letter._PROFILE_PATH", _TEST_PROFILE)
    with patch("src.generators.cover_letter.anthropic.AsyncAnthropic", return_value=mock_cl_client):
        from src.generators.cover_letter import CoverLetterGenerator
        return CoverLetterGenerator()


class TestCoverLetterGenerate:
    @pytest.mark.asyncio
    async def test_generate_returns_nonempty_string(
        self, cl_generator_with_mock: "CoverLetterGenerator"
    ) -> None:
        result = await cl_generator_with_mock.generate(make_job())
        assert isinstance(result, str)
        assert len(result) > 0
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_generators.py::TestCoverLetterGenerate -v
```
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement generate()**

Replace `generate` in `cover_letter.py`:
```python
async def generate(self, job: Job) -> str:
    """Generate a cover letter text for the given job."""
    response = await self._client.messages.create(
        model=settings.anthropic_model,
        max_tokens=_CL_MAX_TOKENS,
        messages=[{"role": "user", "content": self._build_prompt(job)}],
    )
    return next(block.text for block in response.content if hasattr(block, "text"))
```

- [ ] **Step 4: Run test**

```bash
pytest tests/test_generators.py::TestCoverLetterGenerate -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/generators/cover_letter.py tests/test_generators.py
git commit -m "feat(cover_letter): implement generate() (slice 12)"
```

---

## Task 15: CoverLetterGenerator refine() (Slice 13)

**Files:**
- Modify: `src/generators/cover_letter.py`
- Modify: `tests/test_generators.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_generators.py`:
```python
class TestCoverLetterRefine:
    @pytest.mark.asyncio
    async def test_refine_prompt_includes_letter_and_feedback(
        self, cl_generator_with_mock: "CoverLetterGenerator", mock_cl_client: AsyncMock
    ) -> None:
        application = MagicMock()
        application.cover_letter = "Ma lettre originale."
        application.job = make_job()
        feedback = "Rends le ton plus direct et mentionne n8n dès la première phrase."

        result = await cl_generator_with_mock.refine(application, feedback)

        assert isinstance(result, str)
        assert len(result) > 0
        call_args = mock_cl_client.messages.create.call_args
        prompt_content = call_args.kwargs["messages"][0]["content"]
        assert "Ma lettre originale." in prompt_content
        assert feedback in prompt_content

    @pytest.mark.asyncio
    async def test_refine_raises_if_cover_letter_is_none(
        self, cl_generator_with_mock: "CoverLetterGenerator"
    ) -> None:
        application = MagicMock()
        application.cover_letter = None
        application.job = make_job()
        with pytest.raises(ValueError, match="cover_letter is None"):
            await cl_generator_with_mock.refine(application, "Some feedback")
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_generators.py::TestCoverLetterRefine -v
```
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement refine()**

Replace `refine` in `cover_letter.py`:
```python
async def refine(self, application: Application, feedback: str) -> str:
    """Refine an existing cover letter based on human feedback."""
    if application.cover_letter is None:
        raise ValueError("application.cover_letter is None — generate a letter first")

    prompt = (
        f"{self._build_prompt(application.job)}\n\n"
        "---\n"
        "EXISTING LETTER:\n"
        f"{application.cover_letter}\n\n"
        "---\n"
        "FEEDBACK:\n"
        f"{feedback}\n\n"
        "---\n"
        "Revise the letter above according to the feedback. "
        "Keep the same language, length, and tone constraints."
    )
    response = await self._client.messages.create(
        model=settings.anthropic_model,
        max_tokens=_CL_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return next(block.text for block in response.content if hasattr(block, "text"))
```

- [ ] **Step 4: Run test**

```bash
pytest tests/test_generators.py::TestCoverLetterRefine -v
```
Expected: PASS

- [ ] **Step 5: Run full test suite to confirm nothing broken**

```bash
pytest tests/ -v --tb=short
```
Expected: all PASS (weasyprint tests skip if `SKIP_WEASYPRINT` set)

- [ ] **Step 6: Final commit**

```bash
git add src/generators/cover_letter.py tests/test_generators.py
git commit -m "feat(cover_letter): implement refine() with feedback prompt (slice 13)"
```

---

## Verification

After all tasks complete, run:

```bash
# Full test suite
pytest tests/ -v

# Type checking
mypy src/generators/cv_generator.py src/generators/cover_letter.py src/importers/linkedin_importer.py

# Linter
ruff check src/generators/ src/importers/

# Smoke-test CLI
python -m src.main --help
python -m src.main import-linkedin --help
```

Expected: all tests green, no mypy errors, no ruff errors.
