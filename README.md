# JobHunter AI

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Semi-autonomous job search pipeline driven by LLM scoring. Scrapes job boards, scores each offer against your profile using a 6-block A–F evaluation, generates a tailored CV and cover letter per application, and handles recruiter replies — with a mandatory human validation gate before anything is sent.

**You only show up for interviews.**

## Pipeline

```
Gmail alerts ──┐
Career pages   ├──► MCP bridge ──► Scorer A–F ──► CV + cover letter ──► [Telegram gate] ──► Submit
Indeed API     │                       │
WTTJ           ┘              Company research
```

| Phase | What it does | Status |
|-------|-------------|--------|
| 2 — Recherche | Gmail alerts, Indeed API, WTTJ, career pages (Greenhouse/Ashby), MCP bridge | ✅ |
| 2 — Scoring | Multi-bloc A–F evaluator + archetypes + company research | ✅ |
| 3 — Candidature | CV (Jinja2 → WeasyPrint) + cover letter, per-offer via LLM | ✅ |
| 4 — Réponse | Gmail polling, recruiter reply classifier, Telegram notifications | ✅ |
| Dashboard | FastAPI + HTMX web UI — pipeline control + job review | ✅ |
| LinkedIn scraper | Available, disabled by default (ToS risk) | ⚠️ |
| Phase 5 — RDV | Calendly integration, interview prep | 🔲 |

## Quick Start

```bash
git clone https://github.com/MatthdV/jobhunter-ai.git
cd jobhunter-ai
pip install -e ".[dev]"

cp .env.example .env
# Fill in LLM_PROVIDER + API key, Gmail credentials, Telegram token

python -m src.main init-db
alembic upgrade head

# Scan + score
python -m src.main scan --source gmail_alerts --limit 50
python -m src.main match --min-score 80 --detailed

# Web dashboard
uvicorn src.api.app:app --reload   # http://localhost:8000
```

## Scoring — 6-block A–F evaluation

Each offer is scored by an LLM across 6 structured blocks. The global score (0–100) is computed deterministically from block scores; the LLM never outputs the final number.

| Block | Weight | What it evaluates |
|-------|--------|-------------------|
| A — Role summary | 10% | Archetype detection, seniority, work arrangement |
| B — CV match | 25% | Matched requirements + gaps with severity |
| C — Level strategy | 15% | Seniority fit and positioning notes |
| D — Compensation | 15% | PPP-adjusted salary vs target |
| E — Personalization | 20% | CV edits + cover letter hooks per offer |
| F — Interview prep | 15% | STAR story mapping, red-flag questions |

Score formula: `((weighted_avg_1–5 − 1.0) / 4.0) × 100`. Missing blocks default to 3.0.

## Architecture

```
src/
├── main.py                     # Typer CLI
├── api/                        # FastAPI + HTMX dashboard
│   ├── app.py
│   └── routes/                 # pages, jobs, stats, pipeline
├── config/
│   ├── settings.py             # Pydantic Settings — loads .env
│   ├── profile.yaml            # Candidate profile + search config ← source of truth
│   ├── portals.yaml            # Career page portals (Greenhouse/Ashby)
│   └── stories.yaml            # STAR+R interview story bank
├── storage/
│   ├── models.py               # SQLAlchemy: Job, Company, Application, MatchResult
│   └── database.py
├── scrapers/
│   ├── gmail_scraper.py        # Gmail job-alert emails → Job stubs → JSearch enrich
│   ├── indeed_scraper.py       # JSearch API + Playwright fallback
│   ├── career_pages.py         # Greenhouse REST + Ashby GraphQL
│   ├── wttj_scraper.py
│   └── linkedin_scraper.py     # playwright-stealth (ToS risk — disabled by default)
├── importers/
│   └── mcp_bridge.py           # Drains data/mcp_inbox/ JSON batches
├── matching/
│   ├── scorer.py               # Multi-bloc A–F evaluator
│   └── archetypes.py           # Role archetype detection from profile.yaml
├── interview/
│   └── story_bank.py           # STAR+R story library (stories.yaml)
├── analysis/
│   └── company_researcher.py   # Web-search enrichment → Company model
├── generators/
│   ├── cv_generator.py         # Jinja2 → WeasyPrint → PDF
│   └── cover_letter_generator.py
├── communications/
│   ├── email_handler.py        # Gmail API send + thread tracking
│   ├── telegram_bot.py         # Approval gate + daily summary
│   └── recruiter_responder.py  # Reply classifier + draft generation
├── scheduler/
│   └── job_scheduler.py        # Orchestrates: import_mcp → scan → research → match → apply → respond
└── llm/
    ├── base.py                 # Abstract LLMClient
    ├── anthropic_client.py
    ├── openai_client.py
    ├── mistral_client.py
    ├── deepseek_client.py
    ├── openrouter_client.py
    └── factory.py
```

## LLM Providers

Set `LLM_PROVIDER` in `.env`. Optionally set `LLM_SCORING_PROVIDER` to use a different model for scoring vs generation.

| Provider | `LLM_PROVIDER` | Default model | Key |
|---|---|---|---|
| Anthropic | `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai` | `gpt-4o` | `OPENAI_API_KEY` |
| Mistral | `mistral` | `mistral-large-latest` | `MISTRAL_API_KEY` |
| DeepSeek | `deepseek` | `deepseek-chat` | `DEEPSEEK_API_KEY` |
| OpenRouter | `openrouter` | `openai/gpt-4o` | `OPENROUTER_API_KEY` |

## CLI Reference

```bash
python -m src.main init-db

# Scraping
python -m src.main scan --source gmail_alerts --limit 50
python -m src.main scan --source gmail_alerts --parse-only   # dry run: print stubs only
python -m src.main scan --source indeed_api  --limit 20
python -m src.main scan --source wttj        --limit 50
python -m src.main scan --source career_pages

# Scoring
python -m src.main match --min-score 80
python -m src.main match --min-score 80 --detailed           # print full A–F breakdown

# Company research
python -m src.main research "Anthropic"

# Applications
python -m src.main apply --dry-run   # generate CV + letter, no send
python -m src.main apply --live      # requires Telegram approval

# Recruiter replies
python -m src.main respond

# Full pipeline (one cycle)
python -m src.main run-once
```

## Key Design Decisions

- **Human-in-the-loop gate** — `TelegramBot.request_approval()` blocks before any submission; cannot be bypassed
- **Dry-run default** — `settings.dry_run = True`; `--live` required to submit
- **Daily cap** — `MAX_APPLICATIONS_PER_DAY` hard-limits sends to avoid platform bans
- **Profile as source of truth** — `src/config/profile.yaml` drives scoring prompts, CV generation, keyword rotation, and country tiers; edit there, not in code
- **Deterministic scoring** — global score computed server-side from block scores; LLM never outputs a final number (avoids hallucination drift)
- **Provider-agnostic LLM** — swap in one env var; separate `LLM_SCORING_PROVIDER` / `LLM_SCORING_MODEL` for cost optimisation

## Tests

```bash
pytest                                      # all tests
pytest tests/test_scorer_multibloc.py -v   # A–F scorer
pytest -k "test_score"                      # pattern match
```

## Author

**Matthieu de Villele** — Automation & AI Engineer / RevOps Consultant

[LinkedIn](https://www.linkedin.com/in/matthieudevillele/) · [GitHub](https://github.com/MatthdV)
