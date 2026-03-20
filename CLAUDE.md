# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

JobHunter AI is a semi-autonomous job search automation system built for Matthieu de Villele (Automation & AI Engineer / RevOps Consultant). The system automates job discovery, application generation, recruiter communication, and interview preparation — with mandatory human validation before submitting applications.

**Target KPIs**: 50 offers analyzed/day → 5-10 applications/day → 15%+ response rate → 2-3 interviews/week.

## 5-Phase Architecture

```
Phase 1 — Préparation  : Profile analysis, LinkedIn optimization, adaptive CV generation
Phase 2 — Recherche    : Scraping (LinkedIn, Indeed, WTTJ, AngelList), IA matching (score > 80%)
Phase 3 — Candidature  : Personalized CV + cover letter per offer → human validation gate → submission
Phase 4 — Réponse      : Auto-responses, salary negotiation scripts, scam detection
Phase 5 — RDV          : Calendly integration, company briefings, Q&A prep, Telegram/email recap
```

Semi-autonomous model: the user only validates and passes interviews. Everything else is automated.

## Tech Stack

| Component       | Technology                              |
|-----------------|-----------------------------------------|
| Scraping        | Playwright + Python                     |
| IA Matching     | Claude API + Embeddings                 |
| CV Generation   | Jinja2 + WeasyPrint (HTML → PDF)        |
| Email           | Gmail API                               |
| Scheduling      | Calendly API                            |
| Notifications   | Telegram Bot + Email                    |
| Storage         | SQLite (dev) / PostgreSQL (prod)        |
| Automation      | n8n for workflow orchestration          |

## Commands

```bash
# Install dependencies (requires Python 3.11+)
pip install -e ".[dev]"

# Install Playwright browsers (first time only)
playwright install chromium

# Initialise the database
python -m src.main init-db

# Run the CLI
python -m src.main --help
python -m src.main scan --source linkedin --limit 20
python -m src.main match --min-score 80
python -m src.main apply --dry-run

# Tests
pytest
pytest tests/test_scrapers.py -v   # single file
pytest -k "test_score"             # single test

# Type checking & lint
mypy src/
ruff check src/ tests/
```

## Architecture

```
src/
├── main.py               # Typer CLI — entry point
├── config/
│   ├── settings.py       # Pydantic Settings (loads .env) — REAL
│   └── profile.yaml      # Candidate profile, target roles, companies — REAL
├── storage/
│   ├── models.py         # SQLAlchemy ORM: Job, Application, Company, Recruiter — REAL
│   └── database.py       # Engine, session factory, init_db(), health_check() — REAL
├── scrapers/             # Phase 2 — STUBS (BaseScraper + LinkedIn/Indeed/WTTJ)
├── matching/             # Phase 2 — STUBS (Scorer via Claude, EmbeddingMatcher)
├── generators/           # Phase 3 — STUBS (CVGenerator, CoverLetterGenerator)
├── communications/       # Phase 4 — STUBS (EmailHandler, TelegramBot, RecruiterResponder)
├── scheduler/            # Phase 4 — STUB (JobScheduler orchestrates all phases)
└── analysis/             # Profile analysis (migrated from analysis/)
```

## Key Design Decisions

- **Human-in-the-loop gate**: `TelegramBot.request_approval()` blocks before any application is submitted — never bypass this gate
- **Dry-run default**: `settings.dry_run = True` by default; must explicitly pass `--live` to submit
- **Daily cap**: `settings.max_applications_per_day` hard-limits submissions
- **Match threshold**: only jobs with `match_score >= settings.min_match_score` proceed to the apply phase
- **Profile source of truth**: `src/config/profile.yaml` drives scoring prompts, CV generation, and search keywords — edit here, not in code
- **Personalization over volume**: each CV and cover letter is tailored per offer via Claude; never blasted generically
- **ANTHROPIC_API_KEY**: optional at import time, enforced at runtime by `Scorer.__init__` / `CoverLetterGenerator.__init__` via `ConfigurationError`
