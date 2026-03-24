# JobHunter AI

## Project

JobHunter AI is a semi-autonomous job search system with a Python CLI backend (FastAPI API) and a Next.js 14 web frontend. The backend core logic is in `src/`, shared by CLI and API. The frontend is in `web/`. The system supports multi-tenant usage with encrypted API keys and user-specific data.

## Commands

- Backend setup and usage:
  - `pip install -e ".[dev,all-llm]"`
  - `playwright install chromium`
  - `python -m src.main init-db`  # Initialize database
  - `python -m src.main scan --source wttj --limit 20`  # Scan jobs from WTTJ
  - `python -m src.main match --min-score 80`  # Match jobs with profile
  - `python -m src.main apply --dry-run`  # Dry-run job applications

- Backend testing and linting:
  - `pytest`  # Run all tests
  - `pytest tests/test_scrapers.py -v`  # Run scraper tests verbosely
  - `pytest -k "test_score"`  # Run tests matching "test_score"
  - `SKIP_WEASYPRINT=1 pytest`  # Skip WeasyPrint-dependent tests
  - `DYLD_LIBRARY_PATH=/opt/homebrew/lib pytest`  # Set env for macOS libs
  - `mypy src/`  # Run static type checks
  - `ruff check src/ tests/`  # Run linter

- Frontend commands (in `web/`):
  - `pnpm install`  # Install dependencies
  - `pnpm dev`  # Start dev server
  - `pnpm build`  # Build production bundle
  - `pnpm lint`  # Lint frontend code

- Docker:
  - `make build && make run`  # Build and run Docker container

## Verification

- Run `pytest` and confirm all tests pass without errors.
- Run `mypy src/` and ensure no type errors.
- Run `ruff check src/ tests/` and fix all lint warnings/errors.
- Start backend with `python -m src.main scan --source wttj --limit 1` and verify it fetches one job.
- Start frontend with `pnpm dev` and verify UI loads without errors.
- Run `python -m src.main apply --dry-run` and confirm no actual applications are sent.

## Architecture

- `src/`: Python core shared by CLI and API
  - `main.py`: Typer CLI entrypoint
  - `config/`: Pydantic settings and canonical candidate profile (`profile.yaml`)
  - `llm/`: Abstract LLM client interface and provider-specific clients
  - `scrapers/`: Job scrapers using Playwright and APIs
  - `matching/`: Scoring logic for job/profile matching
  - `generators/`: CV and cover letter generation (Jinja2, WeasyPrint, LLM)
  - `communications/`: Email, Telegram bot, recruiter response handlers
  - `scheduler/`: Pipeline orchestration (scan → match → apply → respond)
  - `storage/`: SQLAlchemy models and DB session management
  - `importers/`: LinkedIn profile importer

- `api/`: FastAPI wrapping `src/` for multi-tenant web access with JWT auth and encrypted API keys

- `web/`: Next.js 14 frontend with Tailwind CSS and shadcn/ui components

## Code Style

- Python:
  - Use type hints everywhere
  - Enforce `mypy --strict` and `ruff` linting
  - Write docstrings on all public functions and classes
- TypeScript:
  - Use strict mode and ES modules
  - Avoid `any` type unless explicitly documented
- Naming conventions:
  - Files and folders: kebab-case
  - React components: PascalCase
  - Variables and functions: camelCase
- Commits:
  - Write English commit messages using Conventional Commits format, e.g. `feat(scraper): add WTTJ pagination`
- Code and comments in English; UI and notifications in French

## Workflow

- Use feature branches named by feature or bugfix, e.g. `feature/scraper-wttj-pagination`
- Open pull requests for all changes; require at least one review approval before merging
- Run all tests and linters locally before pushing
- Use `git rebase` to keep history linear; avoid `git push --force` without team consent
- Deploy backend and frontend via CI/CD pipelines after merging to main branch
- Use environment variables for secrets; never commit credentials to repo

## Testing

- Use `pytest` for backend unit and integration tests
- Write tests covering public interfaces, not internal implementation details
- Follow vertical slice TDD: write one test, implement minimal code to pass, then repeat
- Avoid refactoring code until tests pass (GREEN)
- Use environment variables to skip or modify tests that require external dependencies (e.g., WeasyPrint)

## Gotchas

- Never bypass TelegramBot human approval gate before applying to jobs
- Scrapers must be read-only; do not persist data directly to DB in scraper code
- Always use `LLMClient.complete()` abstraction; do not import provider SDKs in business logic
- Profile in `profile.yaml` is the single source of truth for scoring and generation
- Enforce daily application caps and minimum match score thresholds strictly
- Encrypt API keys in DB with Fernet; CLI keys stored only in `.env`

## Error Handling

- Log all errors with `console.error` or Python `logging.error` including context
- Return HTTP 400 for client errors with user-friendly messages
- Retry transient failures with exponential backoff in scrapers and API calls
- Fail gracefully on missing or malformed profile data; prompt user to fix
- Use dry-run mode by default to prevent unintended job applications

## Constraints

- Use PostgreSQL in production; SQLite only for local development
- Support multi-tenant data isolation via `user_id` foreign keys on all tables
- Limit API rate per scraper using token bucket algorithm with configured delays
- Support multiple LLM providers switchable via `LLM_PROVIDER` environment variable

## Multi-tenant Web

- Each user has isolated data: API keys, profile, jobs, applications
- Frontend uses NextAuth.js for authentication; backend uses JWT tokens
- Encrypt API keys at rest in database using Fernet encryption

## LLM Providers

- Supported providers: `anthropic`, `openai`, `mistral`, `deepseek`, `openrouter`
- Switch provider by setting `LLM_PROVIDER` in `.env`
- OpenRouter supports 100+ models with a single API key

## Rate Limiting

- Enforce minimum and maximum delays per request per scraper:
  - WTTJ: 1.0s–2.5s delay, max 120 requests/hour
  - Indeed: 2.0s–4.0s delay, max 60 requests/hour
  - LinkedIn: 3.0s–7.0s delay, max 30 requests/hour
- Use token bucket algorithm per scraper instance to enforce limits