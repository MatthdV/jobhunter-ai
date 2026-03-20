# Phase 1 — Scraping Design Spec

**Date:** 2026-03-20
**Status:** Approved (rev 2)
**Scope:** Job board scrapers — WTTJ, Indeed, LinkedIn

---

## Context

Phase 0 laid the scaffolding. Phase 1 implements the first real pipeline stage: discovering job offers. Three sources are targeted in order of complexity: Welcome to the Jungle (no auth), Indeed (no auth), LinkedIn (authenticated, stealth required).

The output of every scraper is a list of normalised `Job` ORM instances, ready to be persisted and passed to the Phase 2 scoring pipeline.

---

## Architectural Approach

**Fat base class (Option A).** `BaseScraper` implements all shared infrastructure — rate limiting, retry, deduplication, Playwright lifecycle, normalisation. Concrete scrapers override only `_fetch_raw()` and the source-specific parse logic. No separate service layer (that role belongs to `JobScheduler` in Phase 4).

### Method naming — renaming `scrape()` to `search()`

The Phase 0 stub declared `scrape(keywords, limit)`. Phase 1 renames this to `search(keywords, location, filters, limit)`. All three concrete stub files (`wttj.py`, `indeed.py`, `linkedin.py`) are updated accordingly. The stub docstrings referencing `scrape` are also removed.

---

## Interface

### Public API

```python
async def search(
    keywords: list[str],
    location: str = "remote",           # "remote" only in Phase 1; city support deferred
    filters: ScraperFilters | None = None,
    limit: int = 50,
    seen_urls: set[str] | None = None,  # URLs already in DB, passed by caller
) -> list[Job]:
    """Search for job offers. Returns normalised, deduplicated Job instances.

    Scrapers never access the database. The caller (JobScheduler) passes
    seen_urls to enable deduplication against existing DB records.
    """
```

**`location` scope:** Only `"remote"` is supported in Phase 1. Each scraper maps it to its hardcoded remote filter parameter. City-based location filtering is deferred to a future phase.

### Filter Dataclass — `src/scrapers/filters.py`

```python
@dataclass
class ScraperFilters:
    remote_only: bool = True
    contract_types: list[str] = field(
        default_factory=lambda: ["CDI", "Freelance", "Contract"]  # synced with profile.yaml
    )
    min_salary: int | None = None
    excluded_keywords: list[str] = field(
        default_factory=lambda: ["junior", "stage", "internship", "stagiaire", "alternance"]
    )
```

`excluded_keywords` is applied as a **post-parse filter** in `BaseScraper._normalize()` — if any excluded keyword appears (case-insensitive) in `job.title` or `job.description`, the job is silently dropped. This mirrors the `profile.yaml` `filters.excluded_keywords` list.

Callers should always construct `ScraperFilters` from `profile.yaml` via a helper. Phase 4 `JobScheduler` is responsible for that construction.

### Exceptions — `src/scrapers/exceptions.py`

| Exception | Trigger | Behaviour |
|---|---|---|
| `ScraperError` | Base class | — |
| `RateLimitError` | HTTP 429 detected | Retry × 3, then log WARNING + skip |
| `AuthenticationError` | LinkedIn: cookies expired + no credentials, or 2FA/CAPTCHA challenge | Raise immediately, abort scraper |
| `ParseError` | Markup changed / unexpected structure | Log WARNING + skip offer, continue |

---

## Rate Limiting & Retry

### Per-source delays (class-level constants)

| Source | MIN_DELAY | MAX_DELAY | MAX_RPH |
|---|---|---|---|
| WTTJ | 1.0s | 2.5s | 120 |
| Indeed | 2.0s | 4.0s | 60 |
| LinkedIn | 3.0s | 7.0s | 30 |

`BaseScraper._wait()` draws a uniform random delay in [MIN_DELAY, MAX_DELAY].

**Token bucket:** per-scraper-instance, sliding window, refills at `MAX_RPH / 3600` tokens/second, initial capacity = `MAX_RPH`. If the bucket is empty, `_wait()` blocks until a token is available.

### Retry strategy — `BaseScraper._with_retry(coro, max_attempts=3)`

- Backoff: 1s → 2s → 4s (exponential)
- Retry on: `RateLimitError`, network errors, HTTP 429/503
- No retry on: HTTP 403 (blocked), 404 (offer deleted) → raise `ParseError` immediately
- After 3 failures: log `WARNING`, skip offer, continue to next

---

## Scraper Implementations

### WTTJ — Playwright XHR Intercept

**Transport:** Playwright (not HTTPX). The existing stub's `_BASE_URL` and `_setup`/`_teardown` HTTPX references are replaced.

```
_setup(): launch Playwright browser (headless)
search():
  page.on("response", _handle_response)  # register intercept before navigation
  page.goto("welcometothejungle.com/jobs?query={keyword}&remote=true")
  await page.wait_for_load_state("networkidle")
  → _handle_response collects JSON from responses matching */api/*jobs*
  → parse collected dicts via _parse_raw()
  → paginate: click "next page" or increment offset param until limit reached
_teardown(): close browser
```

`_parse_raw(raw: dict[str, Any]) -> Job` — receives the WTTJ API dict directly.

### Indeed — Playwright + BeautifulSoup

**Parse strategy:** `page.content()` → `BeautifulSoup` → CSS selectors on job cards. `_parse_raw` receives a `BeautifulSoup` `Tag` (not a dict). The abstract signature in `BaseScraper` is widened to `_parse_raw(self, raw: Any) -> Job` to accommodate this.

```
search():
  page.goto("fr.indeed.com/jobs?q={keyword}&remotejob=032b")
  soup = BeautifulSoup(await page.content(), "lxml")
  cards = soup.select(".job_seen_beacon")  # selector TBD — confirm during implementation
  for card in cards: yield _parse_raw(card)
  Pagination: &start=0, &start=10, ... until limit reached
```

No authentication required.

### LinkedIn — Stealth + Persistent Cookies

**Transport:** Playwright + `playwright-stealth`.

**`data/` directory:** created at runtime by `_setup()` via `Path("data").mkdir(exist_ok=True)` before writing the cookie file.

**Setup flow:**
1. Apply `playwright-stealth` to browser context
2. Load cookies from `data/linkedin_cookies.json` (if file exists)
3. Navigate to `linkedin.com` → check for authenticated state (presence of nav element)
4. If not authenticated:
   - If `LINKEDIN_EMAIL` + `LINKEDIN_PASSWORD` set → run login flow → save cookies to file
   - If credentials missing → raise `AuthenticationError` immediately
5. If login flow encounters a 2FA prompt or CAPTCHA challenge → raise `AuthenticationError` immediately (2FA and CAPTCHA handling are **out of scope for Phase 1**; user must resolve manually and re-run)
6. Cookies saved back to `data/linkedin_cookies.json` after each successful session

**Search flow:**
```
page.goto("linkedin.com/jobs/search/?keywords={kw}&f_WT=2")  # f_WT=2 = remote
→ parse job cards (title, company, location, url)
→ for each card: page.goto(job_url) → parse full description
```

Cookie file: `data/linkedin_cookies.json` — already in `.gitignore`.

---

## Normalisation

`BaseScraper._normalize(job: Job) -> Job` runs on every parsed job:

- `title`: stripped, title case
- `salary_min` / `salary_max`: extracted via `_parse_salary()`, in EUR/year
  - Daily rate → multiply by `WORKING_DAYS_PER_YEAR = 220` (French standard: 365 − 104 weekends − 11 bank holidays − ~30 leave)
- `is_remote`: `True` if "remote", "télétravail", "distanciel" in title / location / description (case-insensitive)
- `scraped_at`: `datetime.now(timezone.utc)` (not `utcnow()`, deprecated in 3.12)
- `source`: set from `self.source` class attribute
- **Excluded keyword filter:** if any `filters.excluded_keywords` term matches title or description → return `None`; caller discards `None` results

### Salary parsing patterns

| Input | Output |
|---|---|
| `"80 000 € - 100 000 €/an"` | `(80000, 100000)` |
| `"700€/jour"` | `(154000, 154000)` |
| `"Selon profil"` | `(None, None)` |
| `""` / missing | `(None, None)` |

---

## Deduplication

Two layers, both in `BaseScraper.search()`:

1. **In-batch dedup:** `_seen_urls: set[str]` built during the current search call. Same URL twice in one batch → second entry silently dropped.
2. **DB dedup:** `seen_urls` parameter passed by the caller (contains URLs already persisted). Scrapers never query the DB themselves.

---

## File Changes

```
src/scrapers/
├── base.py          # Rename scrape()→search(); add rate limiter, retry, dedup,
│                    # normalize, Playwright lifecycle; widen _parse_raw to Any
├── exceptions.py    # NEW: ScraperError, RateLimitError, AuthenticationError, ParseError
├── filters.py       # NEW: ScraperFilters dataclass (synced with profile.yaml)
├── wttj.py          # Implement: XHR intercept via Playwright (replace HTTPX stub)
├── indeed.py        # Implement: BS4 HTML parsing
└── linkedin.py      # Implement: stealth + cookies + login flow

data/               # NEW dir, created at runtime by LinkedInScraper._setup()
└── .gitkeep

tests/
├── fixtures/
│   ├── wttj/
│   │   ├── search_results.json      # 3 complete offers (XHR intercept format)
│   │   ├── job_no_salary.json       # offer with null salary fields
│   │   └── job_expired.json         # offer with status=expired
│   ├── indeed/
│   │   ├── search_results.html      # page with 3 job cards
│   │   ├── job_daily_rate.html      # card with "700€/jour"
│   │   └── job_no_location.html     # card with missing location
│   └── linkedin/
│       ├── search_results.html      # job cards list page
│       └── job_detail.html          # single job detail page
└── test_scrapers.py   # Full implementation (replaces stubs)
```

---

## Test Cases

| Test | WTTJ | Indeed | LinkedIn | Notes |
|---|---|---|---|---|
| `test_parse_complete_job` | ✓ | ✓ | ✓ | All fields present and normalised |
| `test_parse_missing_salary` | ✓ | ✓ | ✓ | salary_min/max = None, no crash |
| `test_parse_salary_annual` | ✓ | ✓ | ✓ | "80k-100k €/an" → (80000, 100000) |
| `test_parse_salary_daily_rate` | ✓ | ✓ | ✓ | "700€/jour" → (154000, 154000) |
| `test_parse_remote_detection` | ✓ | ✓ | ✓ | Keyword in title → is_remote=True |
| `test_excluded_keyword_dropped` | ✓ | ✓ | ✓ | "junior" in title → job filtered out |
| `test_deduplication_in_batch` | ✓ | ✓ | ✓ | Same URL twice → one result |
| `test_deduplication_seen_urls` | ✓ | ✓ | ✓ | URL in seen_urls param → skipped |
| `test_rate_limit_retry` | ✓ | ✓ | ✓ | AsyncMock 429 × 3 → RateLimitError (no fixture file needed) |
| `test_parse_error_skipped` | ✓ | ✓ | ✓ | Malformed fixture → ParseError logged, continues |
| `test_cookie_load_skips_login` | | | ✓ | Valid cookie file → no login attempt |
| `test_missing_credentials_raises` | | | ✓ | No cookies + no .env → AuthenticationError |
| `test_2fa_challenge_raises` | | | ✓ | Login page shows challenge → AuthenticationError |

All tests: `pytest-asyncio` + `AsyncMock` for Playwright. Zero network calls.

---

## Constraints

- `dry_run` has no effect on scraping (read-only operation)
- Scrapers never persist to DB directly — callers (`JobScheduler`) handle persistence and pass `seen_urls`
- LinkedIn credentials never logged, never stored outside `data/linkedin_cookies.json`
- 2FA and CAPTCHA on LinkedIn are out of scope for Phase 1 — raise `AuthenticationError`, user resolves manually
- `location` parameter only supports `"remote"` in Phase 1; city-based search deferred
