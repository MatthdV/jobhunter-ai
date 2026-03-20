# Phase 1 — Scraping Design Spec

**Date:** 2026-03-20
**Status:** Approved
**Scope:** Job board scrapers — WTTJ, Indeed, LinkedIn

---

## Context

Phase 0 laid the scaffolding. Phase 1 implements the first real pipeline stage: discovering job offers. Three sources are targeted in order of complexity: Welcome to the Jungle (no auth), Indeed (no auth), LinkedIn (authenticated, stealth required).

The output of every scraper is a list of normalised `Job` ORM instances, ready to be persisted and passed to the Phase 2 scoring pipeline.

---

## Architectural Approach

**Fat base class (Option A).** `BaseScraper` implements all shared infrastructure — rate limiting, retry, deduplication, Playwright lifecycle, normalisation. Concrete scrapers override only `_fetch_raw()` and `_parse_raw()`. No separate service layer (that role belongs to `JobScheduler` in Phase 4).

---

## Interface

### Public API

```python
async def search(
    keywords: list[str],
    location: str = "remote",
    filters: ScraperFilters | None = None,
    limit: int = 50,
) -> list[Job]:
    """Search for job offers. Returns normalised, deduplicated Job instances."""
```

### Filter Dataclass

```python
@dataclass
class ScraperFilters:
    remote_only: bool = True
    contract_types: list[str] = field(default_factory=lambda: ["CDI", "Freelance"])
    min_salary: int | None = None
```

### Exceptions — `src/scrapers/exceptions.py`

| Exception | Trigger | Behaviour |
|---|---|---|
| `ScraperError` | Base class | — |
| `RateLimitError` | HTTP 429 detected | Retry × 3, then log WARNING + skip |
| `AuthenticationError` | LinkedIn cookies expired, no credentials | Raise immediately, abort scraper |
| `ParseError` | Markup changed / unexpected structure | Log WARNING + skip offer, continue |

---

## Rate Limiting & Retry

### Per-source delays (constants on the class)

| Source | MIN_DELAY | MAX_DELAY | MAX_RPH |
|---|---|---|---|
| WTTJ | 1.0s | 2.5s | 120 |
| Indeed | 2.0s | 4.0s | 60 |
| LinkedIn | 3.0s | 7.0s | 30 |

`BaseScraper._wait()` draws a uniform random delay in [MIN_DELAY, MAX_DELAY]. A token bucket enforces MAX_RPH across the session.

### Retry strategy — `BaseScraper._with_retry(coro, max_attempts=3)`

- Backoff: 1s → 2s → 4s (exponential)
- Retry on: `RateLimitError`, network errors, HTTP 429/503
- No retry on: HTTP 403 (blocked), 404 (offer deleted) → raise `ParseError` immediately
- After 3 failures: log `WARNING`, skip offer, continue to next

---

## Scraper Implementations

### WTTJ — XHR Intercept

```
Playwright loads: welcometothejungle.com/jobs?query={keyword}&remote=true
page.on("response") filters URLs matching /api/*jobs*
→ response.json() → list of offer dicts
→ _parse_raw() maps WTTJ fields → normalised Job
```

No authentication required. JSON response is stable compared to DOM parsing.

### Indeed — HTML + BeautifulSoup

```
Playwright loads: fr.indeed.com/jobs?q={keyword}&remotejob=032b
page.content() → BeautifulSoup → CSS selectors on job cards
→ _parse_raw() → Job
Pagination: &start=0, &start=10, ... until limit reached
```

No authentication required.

### LinkedIn — Stealth + Persistent Cookies

**Setup flow:**
1. Apply `playwright-stealth` to patch browser fingerprints
2. Load cookies from `data/linkedin_cookies.json` (if file exists)
3. Navigate to `linkedin.com` → check authenticated state
4. If not authenticated:
   - If `LINKEDIN_EMAIL` + `LINKEDIN_PASSWORD` set → run login flow → save cookies
   - If credentials missing → raise `AuthenticationError` immediately
5. Cookies saved back to `data/linkedin_cookies.json` after each successful session

**Search flow:**
```
Navigate: linkedin.com/jobs/search/?keywords={kw}&f_WT=2 (remote filter)
→ parse job cards (title, company, location, url)
→ for each card: navigate to detail page → parse full description
```

Cookie file path: `data/linkedin_cookies.json` — already in `.gitignore`.

---

## Normalisation

`BaseScraper._normalize(job: Job) -> Job` runs on every parsed job:

- `title`: stripped, title case
- `salary_min` / `salary_max`: extracted via `_parse_salary()`, in EUR/year
  - Daily rate format (`700€/jour`) → multiply by 220 working days
- `is_remote`: `True` if "remote", "télétravail", "distanciel" in title/location/description
- `scraped_at`: `datetime.utcnow()`
- `source`: set from `self.source` class attribute

### Salary parsing patterns

| Input | Output |
|---|---|
| `"80 000 € - 100 000 €/an"` | `(80000, 100000)` |
| `"700€/jour"` | `(154000, 154000)` |
| `"Selon profil"` | `(None, None)` |
| `""` / missing | `(None, None)` |

---

## Deduplication

`BaseScraper` maintains a `_seen_urls: set[str]` per search call. Jobs with a URL already in the database (`Job.url` unique constraint) or already seen in the current batch are silently skipped.

---

## File Changes

```
src/scrapers/
├── base.py          # Beef up: rate limiter, retry, dedup, normalize, Playwright lifecycle
├── exceptions.py    # NEW: ScraperError, RateLimitError, AuthenticationError, ParseError
├── filters.py       # NEW: ScraperFilters dataclass
├── wttj.py          # Implement: XHR intercept
├── indeed.py        # Implement: BS4 HTML parsing
└── linkedin.py      # Implement: stealth + cookies + login flow

data/
└── linkedin_cookies.json   # gitignored, created at runtime

tests/
├── fixtures/
│   ├── wttj/
│   │   ├── search_results.json
│   │   ├── job_no_salary.json
│   │   └── job_expired.json
│   ├── indeed/
│   │   ├── search_results.html
│   │   ├── job_daily_rate.html
│   │   └── job_no_location.html
│   └── linkedin/
│       ├── search_results.html
│       └── job_detail.html
└── test_scrapers.py   # Full implementation (replaces stubs)
```

---

## Test Cases

Each scraper implements the following cases against hand-written fixtures:

| Test | All 3 scrapers | LinkedIn only |
|---|---|---|
| `test_parse_complete_job` | ✓ | |
| `test_parse_missing_salary` | ✓ | |
| `test_parse_salary_annual` | ✓ | |
| `test_parse_salary_daily_rate` | ✓ | |
| `test_parse_remote_detection` | ✓ | |
| `test_deduplication` | ✓ | |
| `test_rate_limit_retry` | ✓ | |
| `test_parse_error_skipped` | ✓ | |
| `test_cookie_load_skips_login` | | ✓ |
| `test_missing_credentials_raises` | | ✓ |

All tests: `pytest-asyncio` + `AsyncMock` for Playwright. Zero network calls.

---

## Constraints

- `dry_run` from `settings` has no effect on scraping (read-only operation)
- Scrapers never persist to DB directly — callers (Phase 4 `JobScheduler`) handle persistence
- LinkedIn credentials never logged, never stored outside `data/linkedin_cookies.json`
