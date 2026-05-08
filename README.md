# JobHunter AI

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-81%20passing-brightgreen.svg)](#tests)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A job search pipeline I built for my own search — and kept building because the problem turned out to have more depth than expected.

![Dashboard](docs/screenshots/dashboard.png)

*53 offers scanned, 2 matched above threshold — pipeline controls trigger each phase independently.*

It scrapes job boards, scores each offer with a 6-block LLM evaluation, generates a tailored CV and cover letter per application, then handles recruiter replies. The only human step is approving on Telegram before anything is sent.

Numbers I'm targeting: 50 offers analyzed per day, 5–10 applications, 15%+ reply rate.

## Why this exists

Manual job searching is mostly pattern matching — read 50 JDs, mentally score them against your CV, write a cover letter that sounds vaguely personalized. It's slow and the quality degrades after about 10.

This automates the mechanical parts. The LLM does the matching and personalization; I do the judgment calls on what to actually send.

## How it works

```
Gmail alerts ─┐
Career pages  ├──► score (A–F) ──► generate CV + letter ──► [Telegram gate] ──► submit
Indeed API    ┘         │
                  company research
```

Each offer gets scored across 6 blocks. The global score (0–100) comes from a weighted average of block scores — the LLM never outputs a number directly. That was a deliberate choice: asking a model to output "score: 82" produces drift and hallucinated confidence. Computing it server-side from structured data is stable.

| Block | Weight | What it evaluates |
|-------|--------|-------------------|
| A — Role summary | 10% | Archetype detection, seniority, work arrangement |
| B — CV match | 25% | Matched requirements with evidence + gaps with severity |
| C — Level strategy | 15% | Seniority positioning, whether to push up or anchor |
| D — Compensation | 15% | PPP-adjusted salary fit |
| E — Personalization | 20% | Specific CV edits + cover letter angles for this offer |
| F — Interview prep | 15% | STAR story mapping, likely hard questions |

Score formula: `((weighted_avg_1–5 − 1.0) / 4.0) × 100`. Missing blocks default to 3.0 with a warning logged. Threshold to proceed: ≥80.

![Job detail — 79% match](docs/screenshots/job-detail.png)

## Stack

Python 3.11+ · FastAPI · HTMX · SQLAlchemy 2 + Alembic · Playwright · Pydantic Settings · Typer · Jinja2 + WeasyPrint · Anthropic / OpenAI / Mistral / DeepSeek / OpenRouter

The LLM layer is provider-agnostic. Swap `LLM_PROVIDER` in `.env` and nothing else changes. I run scoring on Claude Sonnet and generation on a cheaper model — that's what `LLM_SCORING_PROVIDER` / `LLM_SCORING_MODEL` are for.

## Quick start

```bash
git clone https://github.com/MatthdV/jobhunter-ai.git
cd jobhunter-ai
pip install -e ".[dev]"

cp .env.example .env
# Add your LLM provider key, Gmail OAuth credentials, Telegram token

python -m src.main init-db
alembic upgrade head

# Run the pipeline
python -m src.main scan --source gmail_alerts --limit 50
python -m src.main match --min-score 80 --detailed

# Web dashboard
uvicorn src.api.app:app --reload   # http://localhost:8000
```

## What's implemented

| Component | Status |
|-----------|--------|
| Gmail job-alert scraper | ✅ |
| Career pages — Greenhouse REST + Ashby GraphQL | ✅ |
| Indeed via JSearch API | ✅ (requires RapidAPI subscription) |
| WTTJ scraper | ✅ |
| LinkedIn scraper | ⚠️ works, disabled by default (ToS risk) |
| MCP bridge — batch JSON importer | ✅ |
| 6-block A–F scorer with archetypes | ✅ |
| Company research — web enrichment | ✅ |
| STAR story bank | ✅ |
| CV generation — Jinja2 → WeasyPrint → PDF | ✅ |
| Cover letter generation | ✅ |
| Recruiter reply handling — classify + draft | ✅ |
| Telegram approval gate + daily summary | ✅ |
| FastAPI + HTMX web dashboard | ✅ |
| Phase 5 — Calendly + interview prep | 🔲 |

## Architecture

```
src/
├── main.py                      # Typer CLI — entry point
├── api/                         # FastAPI + HTMX dashboard
│   └── routes/                  # pages, jobs, stats, pipeline
├── config/
│   ├── settings.py              # Pydantic Settings, loads .env
│   ├── profile.yaml             # Candidate profile + search config — source of truth
│   ├── portals.yaml             # Career page portals (Greenhouse, Ashby)
│   └── stories.yaml             # STAR+R interview story bank
├── storage/
│   ├── models.py                # Job, Company, Application, MatchResult
│   └── database.py
├── scrapers/
│   ├── gmail_scraper.py         # Job-alert emails → stubs → JSearch enrichment
│   ├── indeed_scraper.py        # JSearch API + Playwright fallback
│   ├── career_pages.py          # Greenhouse REST + Ashby GraphQL
│   ├── wttj_scraper.py
│   └── linkedin_scraper.py      # playwright-stealth
├── importers/
│   └── mcp_bridge.py            # Drains data/mcp_inbox/ JSON batches
├── matching/
│   ├── scorer.py                # 6-block A–F evaluator
│   └── archetypes.py            # Role archetype detection
├── interview/
│   └── story_bank.py            # STAR+R library
├── analysis/
│   └── company_researcher.py    # Web-search enrichment → Company model
├── generators/
│   ├── cv_generator.py
│   └── cover_letter_generator.py
├── communications/
│   ├── email_handler.py         # Gmail API
│   ├── telegram_bot.py          # Approval gate + notifications
│   └── recruiter_responder.py   # Reply classifier + draft
├── scheduler/
│   └── job_scheduler.py         # Full cycle: import → scan → research → match → apply → respond
└── llm/
    ├── base.py                  # Abstract LLMClient
    ├── anthropic_client.py
    ├── openai_client.py
    ├── mistral_client.py
    ├── deepseek_client.py
    ├── openrouter_client.py
    └── factory.py
```

## CLI reference

```bash
# Scanning
python -m src.main scan --source gmail_alerts --limit 50
python -m src.main scan --source gmail_alerts --parse-only   # print stubs, skip DB
python -m src.main scan --source indeed_api --limit 20
python -m src.main scan --source wttj --limit 50
python -m src.main scan --source career_pages

# Scoring
python -m src.main match --min-score 80
python -m src.main match --min-score 80 --detailed           # full A–F breakdown

# Company research
python -m src.main research "Anthropic"

# Applications
python -m src.main apply --dry-run    # generate without sending
python -m src.main apply --live       # requires Telegram approval

# Recruiter replies
python -m src.main respond

# Full pipeline cycle
python -m src.main run-once
```

## Design notes

**Why the scorer never asks the LLM for a number.**
Early versions prompted the model with "rate this job 0–100." The outputs drifted — the same offer scored 71 one run and 84 the next, with confident-sounding reasoning in both cases. The fix was to decompose scoring into six binary classification prompts (matched requirement: yes/no, gap severity: low/medium/high, etc.) and compute the global score server-side from a fixed weighted formula. The LLM cannot hallucinate a number it is never asked to produce. Block scores missing from a response default to 3.0 with a logged warning rather than crashing the batch. This pattern — LLM as structured classifier, arithmetic server-side — is the core architectural decision in the codebase.

**Human-in-the-loop gate.** `TelegramBot.request_approval()` blocks before any submission. It cannot be bypassed — `apply --live` fails without a Telegram token, and dry-run is the default.

**Profile as source of truth.** `src/config/profile.yaml` drives scoring prompts, CV generation, keyword rotation, and country tiers. Changing it changes everything — there's no secondary config to keep in sync.

**Provider-agnostic LLM layer.** Swap `LLM_PROVIDER` in `.env` and nothing else changes. `LLM_SCORING_PROVIDER` and `LLM_SCORING_MODEL` allow running scoring on a capable model (Claude Sonnet) while generation uses a cheaper one — cost awareness baked into the config, not the code.

**Session hygiene.** The async SQLAlchemy session had some sharp edges — specifically, you can't hold a sync session open across an `await`. The scorer opens session 1 to load IDs, closes it, then opens session 2 for async scoring. The apply phase snapshots job data into a dict before closing the session to avoid `DetachedInstanceError`.

## Tests

```bash
pytest                                       # all 81 tests
pytest tests/test_scorer_multibloc.py -v    # A–F scorer
pytest tests/test_scorer_deterministic_score.py -v
pytest -k "test_score"
```

## LLM providers

| Provider | `LLM_PROVIDER` | Default model | Key |
|---|---|---|---|
| Anthropic | `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai` | `gpt-4o` | `OPENAI_API_KEY` |
| Mistral | `mistral` | `mistral-large-latest` | `MISTRAL_API_KEY` |
| DeepSeek | `deepseek` | `deepseek-chat` | `DEEPSEEK_API_KEY` |
| OpenRouter | `openrouter` | `openai/gpt-4o` | `OPENROUTER_API_KEY` |

## Author

**Matthieu de Villele** — Automation & AI Engineer

[LinkedIn](https://www.linkedin.com/in/matthieudevillele/) · [GitHub](https://github.com/MatthdV)
