# JobHunter AI — Multi-Tenant Web App Design

**Date:** 2026-03-24
**Status:** Approved by user

---

## Context

JobHunter AI is currently a single-tenant Python CLI. This design transforms it into a multi-tenant web application with a FastAPI backend (`api/`) and a Next.js 14 frontend (`web/`), while keeping the existing `src/` core intact.

**Decisions made:**
- `src/` integration: dependency injection (DI option A) — `api/` creates LLM clients per-request with user keys; global `settings` singleton remains for non-user values
- Profile storage: YAML blob in `users.profile_yaml` (option A)
- Migrations: Alembic (option A)
- Architecture: monorepo flat (option A) — `api/` imports `src.*` directly, single `pyproject.toml`

---

## 1. Database & Migrations

### New `users` table

```sql
CREATE TABLE users (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  email            VARCHAR(255) UNIQUE NOT NULL,
  hashed_password  VARCHAR(255) NOT NULL,         -- bcrypt
  profile_yaml     TEXT,                          -- YAML blob, nullable until onboarding
  encrypted_keys   TEXT,                          -- Fernet JSON: {"provider": "encrypted_key"}
  llm_provider     VARCHAR(50) DEFAULT 'anthropic',
  min_match_score  INTEGER DEFAULT 80,
  max_apps_per_day INTEGER DEFAULT 10,
  active_sources   TEXT DEFAULT 'wttj',           -- comma-separated
  dry_run          BOOLEAN DEFAULT TRUE,
  created_at       DATETIME,
  updated_at       DATETIME
);
```

### FK `user_id` added to

- `jobs.user_id → users.id`
- `applications.user_id → users.id`
- `match_results.user_id → users.id`
- `companies.user_id → users.id`

### Alembic migration strategy

1. `alembic init alembic` at project root
2. Migration `0001_initial` — current tables without `user_id`
3. Migration `0002_add_users_and_user_id_fks` — `users` table + nullable `user_id` columns, then `NOT NULL` constraint after backfill
4. `api` service runs `alembic upgrade head` in its entrypoint before starting `uvicorn`

---

## 2. Backend `api/`

### File structure

```
api/
├── main.py                    # FastAPI app, lifespan, CORS
├── dependencies.py            # get_current_user(), get_user_db_session(), get_llm_client()
├── auth/
│   ├── router.py              # POST /auth/register, POST /auth/login
│   ├── schemas.py             # RegisterRequest, LoginRequest, TokenResponse
│   └── service.py             # hash_password(), verify_password(), create_jwt(), decode_jwt()
├── routes/
│   ├── settings.py            # GET/PUT /settings
│   ├── scan.py                # POST /scan
│   ├── jobs.py                # GET /jobs
│   ├── match.py               # POST /match
│   ├── applications.py        # GET /applications, POST /applications/{id}/generate
│   └── health.py              # GET /health
└── middleware/
    └── error_handler.py       # Uniform JSON error responses
```

### Auth flow

- `POST /auth/register` → bcrypt hash → insert user → return JWT (24h TTL)
- `POST /auth/login` → verify hash → return JWT
- JWT payload: `{ sub: user_id, email, exp }` signed with `JWT_SECRET` env var
- `get_current_user()` dependency injected on all protected endpoints

### Dependency injection

```python
# api/dependencies.py
async def get_llm_client(user: User = Depends(get_current_user)) -> LLMClient:
    key = decrypt_key(user.encrypted_keys, user.llm_provider)
    return get_client(user.llm_provider, api_key=key)  # src.llm.factory
```

The `src/config/settings` singleton is preserved for global values (`log_level`, etc.). User-specific values (API keys, profile, preferences) come from the injected `User` model.

### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Create account |
| POST | `/auth/login` | Return JWT |
| GET | `/settings` | Read profile + keys + preferences |
| PUT | `/settings` | Update profile + keys + preferences |
| POST | `/scan` | Launch scraping (source, limit, keywords) |
| GET | `/jobs` | List jobs with filters, pagination, score sort |
| POST | `/match` | Run LLM scoring on NEW jobs |
| GET | `/applications` | Pipeline with status |
| POST | `/applications/{id}/generate` | Generate CV + cover letter |
| GET | `/health` | DB connectivity + status |

### Async execution

`/scan` and `/match` are long-running. They launch via `asyncio.create_task()` and immediately return `{ "status": "started", "task_id": "..." }`. No Celery — out of scope for this phase.

---

## 3. Frontend `web/`

### File structure

```
web/
├── app/
│   ├── layout.tsx                 # Root layout, NextAuth SessionProvider
│   ├── page.tsx                   # / landing page
│   ├── (auth)/
│   │   ├── login/page.tsx
│   │   └── register/page.tsx
│   ├── dashboard/page.tsx         # Jobs list + scores
│   ├── applications/page.tsx      # Kanban
│   └── settings/page.tsx          # 3 tabs
├── components/
│   ├── ui/                        # shadcn/ui (Button, Card, Badge, etc.)
│   ├── job-card.tsx
│   ├── kanban-board.tsx
│   └── settings-tabs.tsx
├── lib/
│   ├── api-client.ts              # Typed fetch wrapper → FastAPI :8000
│   └── auth.ts                    # NextAuth config (credentials provider)
└── middleware.ts                  # Redirect unauthenticated → /login
```

### Pages

**`/`** — Landing: 3-line pitch, CTA "S'inscrire" + "Se connecter". Static, no auth required.

**`/login` + `/register`** — Simple forms. NextAuth credentials provider calls `POST /auth/login` or `POST /auth/register` on FastAPI, stores JWT in NextAuth session.

**`/dashboard`** — Jobs table. Filters: source, min score, status, text search. Sort by score desc. Pagination. Score badge: green ≥ 80, orange 60–79, red < 60. "Lancer scan" + "Scorer" buttons.

**`/applications`** — Visual Kanban. Columns: `Draft → Applied → Interview → Offer → Rejected`. Drag & drop via `@dnd-kit`. Each card: job title, company, date, "Générer CV/LM" button.

**`/settings`** — 3 tabs:
- **API Keys**: provider selector + masked key input + test button
- **Profil**: structured form (name, target roles, salary, skills, target companies) — serializes/deserializes the YAML blob
- **Préférences**: active sources (checkboxes), matching threshold (slider), daily cap, dry-run toggle

### `lib/api-client.ts`

Typed wrapper that automatically injects `Authorization: Bearer <jwt>` from the NextAuth session. Exported functions: `getJobs()`, `triggerScan()`, `triggerMatch()`, `getApplications()`, `generateApplication()`, `getSettings()`, `updateSettings()`.

### Auth middleware

`middleware.ts` protects all routes except `/`, `/login`, `/register`. Redirects to `/login` if no session.

---

## 4. Docker & Infrastructure

### `docker-compose.yml`

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: jobhunter
      POSTGRES_USER: jobhunter
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U jobhunter"]
      interval: 5s
      retries: 5

  api:
    build: .
    command: >
      sh -c "alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port 8000"
    ports: ["8000:8000"]
    env_file: .env
    environment:
      - DATABASE_URL=postgresql://jobhunter:${POSTGRES_PASSWORD}@db:5432/jobhunter
    depends_on:
      db: { condition: service_healthy }

  web:
    build: ./web
    ports: ["3000:3000"]
    environment:
      - NEXTAUTH_URL=http://localhost:3000
      - NEXTAUTH_SECRET=${NEXTAUTH_SECRET}
      - NEXT_PUBLIC_API_URL=http://api:8000
    depends_on: [api]

  jobhunter-cron:
    build: .
    env_file: .env
    environment:
      - DATABASE_URL=postgresql://jobhunter:${POSTGRES_PASSWORD}@db:5432/jobhunter
    depends_on:
      db: { condition: service_healthy }
    command: >
      sh -c "chmod 0644 /etc/cron.d/jobhunter-cron
      && crontab /etc/cron.d/jobhunter-cron
      && cron -f"

volumes:
  pg_data:
```

### Dockerfiles

- **Root `Dockerfile`** (existing) — extended to install `fastapi`, `uvicorn`, `python-jose`, `passlib[bcrypt]`, `cryptography` as `api` extras in `pyproject.toml`
- **`web/Dockerfile`** — standard Next.js multi-stage build (`node:20-alpine` builder + runner)

### New env vars (`.env.example`)

```bash
POSTGRES_PASSWORD=changeme
JWT_SECRET=changeme-min-32-chars
NEXTAUTH_SECRET=changeme
FERNET_KEY=                        # generate via: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Implementation order

1. **Alembic setup + DB migration** — foundation for everything
2. **`api/auth`** — register + login + JWT
3. **`api/routes/settings`** — API keys (Fernet encrypt/decrypt) + profile YAML
4. **`api/routes/jobs` + `scan` + `match`** — core job pipeline
5. **`api/routes/applications`** — generation endpoint
6. **`web/` bootstrap** — Next.js 14 + shadcn/ui + NextAuth
7. **`web/` pages** — landing → auth → dashboard → applications → settings
8. **Docker** — update `docker-compose.yml` + `web/Dockerfile`
9. **Tests** — auth, settings, jobs, applications (pytest + vitest)
