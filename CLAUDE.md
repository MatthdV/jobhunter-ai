# JobHunter AI — Project Guidelines

## Overview

Semi-autonomous job search pipeline: scrape → match → apply → respond.
Multi-country search with salary normalization (PPP-adjusted EUR).

## Architecture

```
src/
├── config/          # profile.yaml (candidate profile + search config), settings.py
├── scrapers/        # BaseScraper + WTTJ, Indeed (API + Playwright), LinkedIn
├── utils/           # salary_normalizer.py (PPP conversion)
├── storage/         # SQLAlchemy models (Job, Company, Application, etc.) + Alembic
├── matching/        # LLM-based scorer (profile.yaml vs job)
├── generators/      # CV (Jinja2 + WeasyPrint) + cover letter (LLM)
├── communications/  # Telegram bot, Gmail handler, recruiter responder
├── scheduler/       # Pipeline orchestrator (scan → match → apply → respond)
├── llm/             # Multi-provider LLM clients (Anthropic, OpenAI, Mistral, etc.)
├── importers/       # LinkedIn export ZIP → profile.yaml
├── analysis/        # Profile analyzer
└── main.py          # Typer CLI
```

## Commands

```bash
# Dependencies
.venv/bin/pip install -e ".[dev]"

# Tests (ALWAYS use .venv/bin/python — system Python is 3.9, incompatible)
.venv/bin/python -m pytest tests/ --no-header -q
.venv/bin/python -m pytest tests/test_scrapers.py -x  # specific file

# CLI
.venv/bin/python -m src.main scan --source wttj --limit 10
.venv/bin/python -m src.main match --min-score 80
.venv/bin/python -m src.main apply --dry-run

# Migrations
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m alembic revision --autogenerate -m "description"
```

## Multi-Country Search

Configured in `src/config/profile.yaml` under `search:`:

```yaml
search:
  countries: ["FR", "US", "GB", "DE", "NL", "ES", "CH", "BE", "CA", "SE"]
  location: "remote"
  base_currency: "EUR"
```

### Scraper Support

| Scraper      | Countries supported |
|-------------|-------------------|
| WTTJ        | FR only           |
| Indeed API   | All 10            |
| Indeed (PW)  | All 10            |
| LinkedIn     | All 10 (geoId)    |

### Salary Normalization

`src/utils/salary_normalizer.py` converts salaries to EUR and applies purchasing power parity (PPP) coefficients. France is baseline (1.0). Job model stores both original (`salary_min`/`salary_max`) and normalized (`salary_normalized_min`/`salary_normalized_max`).

## Key Patterns

- **Scrapers**: All extend `BaseScraper` with `_fetch_raw()` + `_parse_raw()`. Country passed via `country_code` param (default "FR").
- **Rate limiting**: Token bucket per scraper with MIN_DELAY/MAX_DELAY/MAX_RPH.
- **Deduplication**: By URL, both in-batch and cross-session (seen_urls set).
- **LLM scoring**: Claude scores jobs 0-100 against profile.yaml. PPP-normalized salaries in prompt.
- **Database**: SQLAlchemy 2.0 + Alembic migrations. SQLite default, PostgreSQL for multi-tenant.

## Testing

- TDD vertical slices: test → impl → test → impl
- 250+ tests, pytest + pytest-asyncio
- Mock Playwright with fixture files in `tests/fixtures/`
- DB tests use `sqlite:///:memory:` with autouse fixture

## Multi-Tenant Backend (API)

FastAPI backend in `api/` for multi-user SaaS mode. Next.js frontend in `web/`.
