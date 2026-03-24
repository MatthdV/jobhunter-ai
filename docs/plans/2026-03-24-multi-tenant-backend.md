# Multi-Tenant Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete FastAPI backend (`api/`) with auth, settings, jobs, scan, match, and applications endpoints — all multi-tenant via JWT + user_id row-level isolation.

**Architecture:** Monorepo flat — `api/` imports `src.*` directly. Dependency injection: `api/` creates LLM clients per-request with user's decrypted keys (Fernet). `src/` core unchanged except `models.py` (add User + user_id FKs) and `settings.py` (add `jwt_secret`, `fernet_key`). Alembic replaces `create_all` for migrations.

**Tech Stack:** FastAPI 0.115+, uvicorn, python-jose[cryptography] (JWT HS256), passlib[bcrypt], cryptography (Fernet), Alembic, pytest + fastapi.testclient.TestClient + in-memory SQLite

**Spec:** `docs/specs/2026-03-24-multi-tenant-design.md`

---

## File Map

**Modified:**
- `pyproject.toml` — add `api` optional-deps group
- `src/config/settings.py` — add `jwt_secret`, `fernet_key` fields
- `src/storage/models.py` — add `User` model; add `user_id` FK to `Job`, `Application`, `MatchResult`, `Company`, `Recruiter`; fix unique constraints for multi-tenancy
- `.env.example` — add `JWT_SECRET`, `FERNET_KEY`, `POSTGRES_PASSWORD`, `NEXTAUTH_SECRET`

**Created:**
- `alembic.ini`
- `alembic/env.py`
- `alembic/script.py.mako`
- `alembic/versions/0001_initial.py`
- `api/__init__.py`
- `api/main.py`
- `api/dependencies.py`
- `api/auth/__init__.py`
- `api/auth/router.py`
- `api/auth/schemas.py`
- `api/auth/service.py`
- `api/routes/__init__.py`
- `api/routes/health.py`
- `api/routes/settings.py`
- `api/routes/jobs.py`
- `api/routes/scan.py`
- `api/routes/match.py`
- `api/routes/applications.py`
- `api/middleware/__init__.py`
- `api/middleware/error_handler.py`
- `tests/api/__init__.py`
- `tests/api/conftest.py`
- `tests/api/test_auth.py`
- `tests/api/test_settings.py`
- `tests/api/test_jobs.py`
- `tests/api/test_scan_match.py`
- `tests/api/test_applications.py`

---

## Task 1: Add API dependencies + new settings fields

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/config/settings.py`
- Modify: `.env.example`

- [ ] **Step 1: Add `api` extras to pyproject.toml**

In `pyproject.toml`, add under `[project.optional-dependencies]`:
```toml
api = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "python-jose[cryptography]>=3.3.0",
    "passlib[bcrypt]>=1.7.4",
    "cryptography>=44.0.0",
]
```

Also update `dev` extras to add `httpx` (needed by TestClient):
```toml
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-mock>=3.12.0",
    "httpx>=0.27.0",
    "ruff>=0.3.0",
    "mypy>=1.9.0",
]
```

- [ ] **Step 2: Add `jwt_secret` and `fernet_key` to settings**

In `src/config/settings.py`, add to the `Settings` class after `database_url`:
```python
# --- API / Web ---
jwt_secret: str = Field("", description="JWT signing secret — min 32 chars for HS256")
fernet_key: str = Field("", description="Fernet key for encrypting API keys — generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")

@property
def is_jwt_configured(self) -> bool:
    return len(self.jwt_secret) >= 32
```

**Important:** In `api/auth/router.py` and `api/dependencies.py`, never silently fall back to a dev secret. Instead raise `ConfigurationError` if `jwt_secret` is not configured:
```python
from src.config.settings import ConfigurationError, settings
if not settings.is_jwt_configured:
    raise ConfigurationError("JWT_SECRET must be at least 32 characters")
```
Use `settings.jwt_secret` directly — no `or "dev-secret"` fallback.

- [ ] **Step 3: Update .env.example**

Add at the end:
```bash
# Web / API
JWT_SECRET=changeme-min-32-chars-for-hs256
FERNET_KEY=
POSTGRES_PASSWORD=changeme
NEXTAUTH_SECRET=changeme
NEXT_PUBLIC_API_URL=http://localhost:8000
```

- [ ] **Step 4: Install API deps**

```bash
pip install -e ".[dev,all-llm,api]"
```

Expected: installs fastapi, uvicorn, python-jose, passlib, cryptography.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/config/settings.py .env.example
git commit -m "feat(api): add API deps and jwt/fernet settings fields"
```

---

## Task 2: Update models for multi-tenancy

**Files:**
- Modify: `src/storage/models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/__init__.py` (empty) and `tests/api/conftest.py`:

```python
# tests/api/conftest.py
"""Shared fixtures for API tests."""
import pytest
from fastapi.testclient import TestClient

from src.storage.database import configure, drop_all, init_db


@pytest.fixture(autouse=False)
def db():
    """Fresh in-memory SQLite DB per test. Also sets JWT_SECRET so auth works."""
    from src.config.settings import settings
    settings.jwt_secret = "test-secret-at-least-32-characters-long"
    configure("sqlite:///:memory:")
    init_db()
    yield
    drop_all()


@pytest.fixture
def client(db):
    from api.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    """Register + login, return auth headers."""
    client.post("/auth/register", json={"email": "user@test.com", "password": "Password1!"})
    resp = client.post("/auth/login", json={"email": "user@test.com", "password": "Password1!"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
```

Then write `tests/api/test_models.py`:
```python
# tests/api/test_models.py
from src.storage.database import configure, init_db, drop_all
from src.storage.models import User, Job, Application, MatchResult, Company


def test_user_model_exists():
    configure("sqlite:///:memory:")
    init_db()
    from sqlalchemy.orm import Session
    from src.storage.database import _get_session_factory
    session = _get_session_factory()()
    user = User(email="a@b.com", hashed_password="hash")
    session.add(user)
    session.commit()
    assert user.id is not None
    assert user.dry_run is True
    assert user.min_match_score == 80
    session.close()
    drop_all()


def test_job_has_user_id_column():
    from sqlalchemy import inspect
    from src.storage.database import _get_engine
    configure("sqlite:///:memory:")
    init_db()
    cols = {c["name"] for c in inspect(_get_engine()).get_columns("jobs")}
    assert "user_id" in cols
    drop_all()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
SKIP_WEASYPRINT=1 pytest tests/api/test_models.py -v
```
Expected: FAIL — `User` not imported, no `user_id` column.

- [ ] **Step 3: Implement User model and update existing models**

In `src/storage/models.py`, add `User` class before `Company`:

```python
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True)
    hashed_password = Column(String(255), nullable=False)
    profile_yaml = Column(Text, nullable=True)
    encrypted_keys = Column(Text, nullable=True)          # Fernet JSON blob
    llm_provider = Column(String(50), default="anthropic")
    min_match_score = Column(Integer, default=80)
    max_apps_per_day = Column(Integer, default=10)
    active_sources = Column(String(200), default="wttj")  # comma-separated
    dry_run = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    jobs = relationship("Job", back_populates="user", cascade="all, delete-orphan")
    applications = relationship("Application", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User {self.email!r}>"
```

Update `Company`:
- Remove `unique=True` from `name` column (multi-tenant: two users can have the same company)
- Add `user_id` FK:
```python
user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
user = relationship("User")
```

Update `Job`:
- Replace `url = Column(String(1000), nullable=False, unique=True)` with:
```python
url = Column(String(1000), nullable=False)
user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
user = relationship("User", back_populates="jobs")
```
- Add to `__table_args__`: `(UniqueConstraint("url", "user_id", name="uq_job_url_user"),)`

Update `Application`:
- Add `user_id` FK:
```python
user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
user = relationship("User", back_populates="applications")
```

Update `MatchResult`:
- Add `user_id` FK:
```python
user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
```

Update `Recruiter`:
- Remove `unique=True` from `email` column (multi-tenant: two users can have the same recruiter email)
- Add `user_id` FK and composite unique:
```python
user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
```
- Add to `__table_args__`: `(UniqueConstraint("email", "user_id", name="uq_recruiter_email_user"),)`

- [ ] **Step 4: Run tests to verify they pass**

```bash
SKIP_WEASYPRINT=1 pytest tests/api/test_models.py -v
```
Expected: PASS.

- [ ] **Step 5: Run full test suite to check no regressions**

```bash
SKIP_WEASYPRINT=1 pytest tests/ -v --ignore=tests/api
```
Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/storage/models.py tests/api/
git commit -m "feat(models): add User model and user_id FKs for multi-tenancy"
```

---

## Task 3: Alembic setup + initial migration

**Files:**
- Create: `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/0001_initial.py`

- [ ] **Step 1: Initialize Alembic**

```bash
alembic init alembic
```

Expected: creates `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/`.

- [ ] **Step 2: Configure alembic.ini**

In `alembic.ini`, set:
```ini
sqlalchemy.url = sqlite:///./jobhunter.db
```
(This is the dev fallback — Docker overrides via env var in `env.py`.)

- [ ] **Step 3: Configure alembic/env.py**

Replace the generated `env.py` content with:

```python
"""Alembic environment configuration."""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.storage.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Override sqlalchemy.url from environment if set
database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,   # required for SQLite ALTER TABLE
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,   # required for SQLite ALTER TABLE
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Note: `render_as_batch=True` is required for SQLite because SQLite doesn't support `ALTER TABLE ADD COLUMN ... NOT NULL` without it.

- [ ] **Step 4: Delete existing SQLite dev DB and generate initial migration**

```bash
rm -f jobhunter.db
alembic revision --autogenerate -m "initial_schema"
```

Expected: creates `alembic/versions/XXXX_initial_schema.py` with all tables including `users` and `user_id` columns.

- [ ] **Step 5: Verify the generated migration looks correct**

Open the generated file. Check it creates: `users`, `companies`, `jobs`, `recruiters`, `applications`, `match_results` with all columns including `user_id` FKs.

- [ ] **Step 6: Apply migration and verify**

```bash
alembic upgrade head
```

Expected: creates `jobhunter.db` with all tables.

```bash
python -c "from src.storage.database import health_check; print(health_check())"
```

Expected: `True`.

- [ ] **Step 7: Commit**

```bash
git add alembic.ini alembic/
git commit -m "feat(db): initialize alembic and generate initial multi-tenant schema migration"
```

---

## Task 4: API scaffold — main, dependencies, health, error handler

**Files:**
- Create: `api/__init__.py`, `api/main.py`, `api/dependencies.py`
- Create: `api/middleware/__init__.py`, `api/middleware/error_handler.py`
- Create: `api/routes/__init__.py`, `api/routes/health.py`

- [ ] **Step 1: Write failing test**

```python
# tests/api/test_health.py
def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
```

Run: `SKIP_WEASYPRINT=1 pytest tests/api/test_health.py -v`
Expected: FAIL — `api.main` not found.

- [ ] **Step 2: Create api/__init__.py (empty)**

```python
# api/__init__.py
```

- [ ] **Step 3: Create api/routes/health.py**

```python
# api/routes/health.py
"""Health check endpoint."""
from fastapi import APIRouter
from src.storage.database import health_check

router = APIRouter()


@router.get("/health")
def get_health() -> dict[str, str]:
    db_ok = health_check()
    return {"status": "ok" if db_ok else "degraded", "db": "ok" if db_ok else "error"}
```

- [ ] **Step 4: Create api/middleware/error_handler.py**

```python
# api/middleware/error_handler.py
"""Uniform JSON error responses for HTTPExceptions."""
from fastapi import Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
```

- [ ] **Step 5: Create api/main.py**

```python
# api/main.py
"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.middleware.error_handler import http_exception_handler
from api.routes.health import router as health_router
from src.storage.database import configure, init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure()
    init_db()
    yield


app = FastAPI(title="JobHunter AI API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Only handle HTTPException — let system errors propagate normally
app.add_exception_handler(HTTPException, http_exception_handler)
app.include_router(health_router)
```

- [ ] **Step 6: Create api/dependencies.py (stub — filled in Task 6)**

```python
# api/dependencies.py
"""FastAPI shared dependencies."""
```

- [ ] **Step 7: Run test**

```bash
SKIP_WEASYPRINT=1 pytest tests/api/test_health.py -v
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add api/ tests/api/test_health.py
git commit -m "feat(api): add FastAPI scaffold with health endpoint"
```

---

## Task 5: Auth service — password hashing + JWT

**Files:**
- Create: `api/auth/__init__.py`, `api/auth/service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/api/test_auth_service.py
"""Unit tests for auth crypto primitives — no DB needed."""
import pytest
from api.auth.service import (
    create_jwt,
    decode_jwt,
    decrypt_api_key,
    encrypt_api_key,
    hash_password,
    verify_password,
)

SECRET = "test-secret-at-least-32-characters-long"


def test_hash_and_verify_password():
    hashed = hash_password("mysecret")
    assert hashed != "mysecret"
    assert verify_password("mysecret", hashed)
    assert not verify_password("wrong", hashed)


def test_create_and_decode_jwt():
    token = create_jwt(user_id=1, email="a@b.com", secret=SECRET)
    payload = decode_jwt(token, SECRET)
    assert payload["sub"] == "1"
    assert payload["email"] == "a@b.com"


def test_decode_jwt_invalid_raises():
    with pytest.raises(Exception):
        decode_jwt("bad.token.here", SECRET)


def test_encrypt_decrypt_api_key():
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    encrypted = encrypt_api_key(key, "anthropic", "sk-ant-test", existing=None)
    result = decrypt_api_key(key, encrypted, "anthropic")
    assert result == "sk-ant-test"


def test_encrypt_api_key_merges_providers():
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    enc1 = encrypt_api_key(key, "anthropic", "sk-ant", existing=None)
    enc2 = encrypt_api_key(key, "openai", "sk-oai", existing=enc1)
    assert decrypt_api_key(key, enc2, "anthropic") == "sk-ant"
    assert decrypt_api_key(key, enc2, "openai") == "sk-oai"


def test_decrypt_missing_provider_returns_empty():
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    enc = encrypt_api_key(key, "anthropic", "sk-ant", existing=None)
    assert decrypt_api_key(key, enc, "openai") == ""
```

Run: `SKIP_WEASYPRINT=1 pytest tests/api/test_auth_service.py -v`
Expected: FAIL — module not found.

- [ ] **Step 2: Implement api/auth/service.py**

```python
# api/auth/service.py
"""Cryptographic primitives: password hashing, JWT, Fernet key encryption."""
import json
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from jose import jwt
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def create_jwt(user_id: int, email: str, secret: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.now(tz=timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str, secret: str) -> dict[str, str]:
    return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])  # type: ignore[no-any-return]


def encrypt_api_key(fernet_key: str, provider: str, api_key: str, existing: str | None) -> str:
    """Encrypt a provider API key and merge with existing encrypted blob."""
    f = Fernet(fernet_key.encode())
    keys: dict[str, str] = {}
    if existing:
        try:
            keys = json.loads(f.decrypt(existing.encode()).decode())
        except Exception:
            keys = {}
    keys[provider] = api_key
    return f.encrypt(json.dumps(keys).encode()).decode()


def decrypt_api_key(fernet_key: str, encrypted: str, provider: str) -> str:
    """Return decrypted API key for provider, or empty string if not found."""
    f = Fernet(fernet_key.encode())
    try:
        keys: dict[str, str] = json.loads(f.decrypt(encrypted.encode()).decode())
        return keys.get(provider, "")
    except Exception:
        return ""
```

- [ ] **Step 3: Create api/auth/__init__.py (empty)**

```python
# api/auth/__init__.py
```

- [ ] **Step 4: Run tests**

```bash
SKIP_WEASYPRINT=1 pytest tests/api/test_auth_service.py -v
```
Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add api/auth/ tests/api/test_auth_service.py
git commit -m "feat(auth): add password hashing, JWT, and Fernet key encryption"
```

---

## Task 6: Auth router — register + login + get_current_user dependency

**Files:**
- Create: `api/auth/schemas.py`, `api/auth/router.py`
- Modify: `api/dependencies.py`, `api/main.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/api/test_auth.py
"""Integration tests for /auth endpoints."""


def test_register_creates_user_and_returns_token(client):
    resp = client.post("/auth/register", json={"email": "new@test.com", "password": "Password1!"})
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_register_duplicate_email_returns_409(client):
    payload = {"email": "dup@test.com", "password": "Password1!"}
    client.post("/auth/register", json=payload)
    resp = client.post("/auth/register", json=payload)
    assert resp.status_code == 409


def test_login_valid_credentials_returns_token(client):
    client.post("/auth/register", json={"email": "user@test.com", "password": "Password1!"})
    resp = client.post("/auth/login", json={"email": "user@test.com", "password": "Password1!"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password_returns_401(client):
    client.post("/auth/register", json={"email": "user@test.com", "password": "Password1!"})
    resp = client.post("/auth/login", json={"email": "user@test.com", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_email_returns_401(client):
    resp = client.post("/auth/login", json={"email": "ghost@test.com", "password": "x"})
    assert resp.status_code == 401


def test_protected_endpoint_without_token_returns_403(client):
    resp = client.get("/settings")
    assert resp.status_code in (401, 403)


def test_protected_endpoint_with_token_returns_200(client, auth_headers):
    resp = client.get("/settings", headers=auth_headers)
    assert resp.status_code == 200
```

Run: `SKIP_WEASYPRINT=1 pytest tests/api/test_auth.py -v`
Expected: FAIL.

- [ ] **Step 2: Create api/auth/schemas.py**

```python
# api/auth/schemas.py
from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
```

Note: `pydantic` ships with `EmailStr` support when `email-validator` is installed. Add it to api extras in pyproject.toml: `"email-validator>=2.0.0"`.

- [ ] **Step 3: Create api/auth/router.py**

```python
# api/auth/router.py
"""Authentication endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.auth.schemas import LoginRequest, RegisterRequest, TokenResponse
from api.auth.service import create_jwt, hash_password, verify_password
from api.dependencies import get_db
from src.config.settings import ConfigurationError, settings
from src.storage.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _require_jwt_secret() -> str:
    if not settings.is_jwt_configured:
        raise ConfigurationError("JWT_SECRET must be set and at least 32 characters long")
    return settings.jwt_secret


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(email=body.email, hashed_password=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_jwt(user_id=user.id, email=user.email, secret=_require_jwt_secret())
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_jwt(user_id=user.id, email=user.email, secret=_require_jwt_secret())
    return TokenResponse(access_token=token)
```

- [ ] **Step 4: Implement api/dependencies.py**

```python
# api/dependencies.py
"""FastAPI shared dependencies."""
from collections.abc import Generator

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from api.auth.service import decode_jwt
from src.config.settings import settings
from src.storage.database import get_session
from src.storage.models import User

_bearer = HTTPBearer()


def get_db() -> Generator[Session, None, None]:
    with get_session() as session:
        yield session


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if not settings.is_jwt_configured:
        raise HTTPException(status_code=500, detail="JWT not configured")
    try:
        payload = decode_jwt(credentials.credentials, settings.jwt_secret)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_llm_client(user: User = Depends(get_current_user)) -> object:
    """Return an LLMClient for the current user's provider and API key."""
    from api.auth.service import decrypt_api_key
    from src.llm.factory import get_client

    if not user.encrypted_keys or not settings.fernet_key:
        raise HTTPException(status_code=400, detail="No API key configured")
    key = decrypt_api_key(settings.fernet_key, user.encrypted_keys, user.llm_provider or "anthropic")
    if not key:
        raise HTTPException(status_code=400, detail=f"No key for provider {user.llm_provider}")
    return get_client(user.llm_provider or "anthropic", api_key=key)
```

- [ ] **Step 5: Register auth router in api/main.py**

In `api/main.py`, add:
```python
from api.auth.router import router as auth_router
# ...
app.include_router(auth_router)
```

Also add a stub settings route for the test `test_protected_endpoint_with_token_returns_200` — create a minimal `api/routes/settings.py` returning `{}` for now:
```python
# api/routes/settings.py (stub)
from fastapi import APIRouter, Depends
from api.dependencies import get_current_user
from src.storage.models import User

router = APIRouter(tags=["settings"])

@router.get("/settings")
def get_settings(user: User = Depends(get_current_user)) -> dict:
    return {}
```
And include it in `api/main.py`.

- [ ] **Step 6: Add email-validator to pyproject.toml api extras**

```toml
api = [
    ...
    "email-validator>=2.0.0",
]
```

Run `pip install -e ".[dev,all-llm,api]"` to install.

- [ ] **Step 7: Run tests**

```bash
SKIP_WEASYPRINT=1 pytest tests/api/test_auth.py -v
```
Expected: all 7 PASS.

- [ ] **Step 8: Commit**

```bash
git add api/ tests/api/test_auth.py pyproject.toml
git commit -m "feat(auth): add register/login endpoints and JWT dependency"
```

---

## Task 7: Settings route — profile YAML + API keys + preferences

**Files:**
- Modify: `api/routes/settings.py` (replace stub)

- [ ] **Step 1: Write failing tests**

```python
# tests/api/test_settings.py
"""Tests for GET/PUT /settings."""


def test_get_settings_returns_defaults(client, auth_headers):
    resp = client.get("/settings", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["llm_provider"] == "anthropic"
    assert data["min_match_score"] == 80
    assert data["dry_run"] is True
    assert data["profile_yaml"] is None
    assert data["api_key"] is None  # never expose raw key


def test_put_settings_updates_preferences(client, auth_headers):
    resp = client.put(
        "/settings",
        json={"min_match_score": 75, "dry_run": False, "active_sources": "wttj,indeed"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    get_resp = client.get("/settings", headers=auth_headers)
    assert get_resp.json()["min_match_score"] == 75
    assert get_resp.json()["dry_run"] is False


def test_put_settings_stores_encrypted_api_key(client, auth_headers):
    from cryptography.fernet import Fernet
    from src.config.settings import settings
    # Patch fernet_key so encryption works in tests
    settings.fernet_key = Fernet.generate_key().decode()
    resp = client.put(
        "/settings",
        json={"llm_provider": "anthropic", "api_key": "sk-ant-test"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    # Key should NOT be returned in GET
    get_resp = client.get("/settings", headers=auth_headers)
    assert get_resp.json().get("api_key") is None
    # But has_api_key should be True
    assert get_resp.json()["has_api_key"] is True


def test_put_settings_updates_profile_yaml(client, auth_headers):
    yaml_content = "name: Test User\ntarget_roles:\n  - Engineer\n"
    resp = client.put("/settings", json={"profile_yaml": yaml_content}, headers=auth_headers)
    assert resp.status_code == 200
    get_resp = client.get("/settings", headers=auth_headers)
    assert get_resp.json()["profile_yaml"] == yaml_content
```

Run: `SKIP_WEASYPRINT=1 pytest tests/api/test_settings.py -v`
Expected: partial FAIL (some assertions may not match the stub).

- [ ] **Step 2: Implement api/routes/settings.py**

```python
# api/routes/settings.py
"""Settings endpoints — profile YAML, API keys, preferences."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth.service import decrypt_api_key, encrypt_api_key
from api.dependencies import get_current_user, get_db
from src.config.settings import settings as app_settings
from src.storage.models import User

router = APIRouter(tags=["settings"])


class SettingsResponse(BaseModel):
    llm_provider: str
    min_match_score: int
    max_apps_per_day: int
    active_sources: str
    dry_run: bool
    profile_yaml: str | None
    has_api_key: bool
    api_key: None = None  # Never returned


class SettingsUpdateRequest(BaseModel):
    llm_provider: str | None = None
    min_match_score: int | None = None
    max_apps_per_day: int | None = None
    active_sources: str | None = None
    dry_run: bool | None = None
    profile_yaml: str | None = None
    api_key: str | None = None  # Provider key to encrypt and store


@router.get("/settings", response_model=SettingsResponse)
def get_settings(user: User = Depends(get_current_user)) -> SettingsResponse:
    has_key = bool(user.encrypted_keys)  # don't expose whether fernet_key is configured
    return SettingsResponse(
        llm_provider=user.llm_provider or "anthropic",
        min_match_score=user.min_match_score or 80,
        max_apps_per_day=user.max_apps_per_day or 10,
        active_sources=user.active_sources or "wttj",
        dry_run=user.dry_run if user.dry_run is not None else True,
        profile_yaml=user.profile_yaml,
        has_api_key=has_key,
    )


@router.put("/settings", response_model=SettingsResponse)
def update_settings(
    body: SettingsUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SettingsResponse:
    if body.llm_provider is not None:
        user.llm_provider = body.llm_provider
    if body.min_match_score is not None:
        user.min_match_score = body.min_match_score
    if body.max_apps_per_day is not None:
        user.max_apps_per_day = body.max_apps_per_day
    if body.active_sources is not None:
        user.active_sources = body.active_sources
    if body.dry_run is not None:
        user.dry_run = body.dry_run
    if body.profile_yaml is not None:
        user.profile_yaml = body.profile_yaml
    if body.api_key is not None and app_settings.fernet_key:
        provider = body.llm_provider or user.llm_provider or "anthropic"
        user.encrypted_keys = encrypt_api_key(
            app_settings.fernet_key, provider, body.api_key, user.encrypted_keys
        )
    db.add(user)
    db.commit()
    db.refresh(user)
    return get_settings(user)
```

- [ ] **Step 3: Register settings router in api/main.py**

```python
from api.routes.settings import router as settings_router
app.include_router(settings_router)
```

(Replace the stub settings router include.)

- [ ] **Step 4: Run tests**

```bash
SKIP_WEASYPRINT=1 pytest tests/api/test_settings.py -v
```
Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routes/settings.py tests/api/test_settings.py api/main.py
git commit -m "feat(api): add settings endpoints with encrypted API key storage"
```

---

## Task 8: Jobs route — list with filters, pagination, score sort

**Files:**
- Create: `api/routes/jobs.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/api/test_jobs.py
"""Tests for GET /jobs."""
from datetime import datetime

from src.storage.database import get_session
from src.storage.models import Job, JobStatus, User


def _seed_jobs(user_id: int, count: int = 3) -> None:
    with get_session() as db:
        for i in range(count):
            db.add(Job(
                title=f"Engineer {i}",
                url=f"https://example.com/{user_id}/{i}",
                source="wttj",
                user_id=user_id,
                match_score=float(70 + i * 5),
                status=JobStatus.NEW,
                scraped_at=datetime.utcnow(),
            ))


def _get_user_id(client, auth_headers) -> int:
    # Register a second user to get IDs
    resp = client.get("/settings", headers=auth_headers)
    # Use token to decode — just use a simple approach via DB
    from src.storage.database import get_session
    from src.storage.models import User
    with get_session() as db:
        user = db.query(User).first()
        return user.id  # type: ignore[return-value]


def test_get_jobs_returns_only_current_user_jobs(client, auth_headers):
    user_id = _get_user_id(client, auth_headers)
    _seed_jobs(user_id, count=2)
    # Register second user
    client.post("/auth/register", json={"email": "other@test.com", "password": "pass"})
    resp2 = client.post("/auth/login", json={"email": "other@test.com", "password": "pass"})
    other_token = resp2.json()["access_token"]
    with get_session() as db:
        other_user = db.query(User).filter(User.email == "other@test.com").first()
        other_id = other_user.id  # type: ignore[union-attr]
    _seed_jobs(other_id, count=5)

    resp = client.get("/jobs", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2


def test_get_jobs_default_sort_by_score_desc(client, auth_headers):
    user_id = _get_user_id(client, auth_headers)
    _seed_jobs(user_id, count=3)
    resp = client.get("/jobs", headers=auth_headers)
    scores = [j["match_score"] for j in resp.json()["items"]]
    assert scores == sorted(scores, reverse=True)


def test_get_jobs_pagination(client, auth_headers):
    user_id = _get_user_id(client, auth_headers)
    _seed_jobs(user_id, count=5)
    resp = client.get("/jobs?limit=2&offset=0", headers=auth_headers)
    assert len(resp.json()["items"]) == 2
    assert resp.json()["total"] == 5


def test_get_jobs_filter_by_source(client, auth_headers):
    user_id = _get_user_id(client, auth_headers)
    _seed_jobs(user_id, count=3)
    with get_session() as db:
        db.add(Job(title="LinkedIn Job", url=f"https://li.com/{user_id}", source="linkedin",
                   user_id=user_id, status=JobStatus.NEW))
    resp = client.get("/jobs?source=linkedin", headers=auth_headers)
    assert resp.json()["total"] == 1
```

Run: `SKIP_WEASYPRINT=1 pytest tests/api/test_jobs.py -v`
Expected: FAIL.

- [ ] **Step 2: Implement api/routes/jobs.py**

```python
# api/routes/jobs.py
"""Jobs list endpoint with filters, pagination, and score sort."""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from src.storage.models import Job, JobStatus, User

router = APIRouter(tags=["jobs"])


class JobItem(BaseModel):
    id: int
    title: str
    url: str
    source: str
    location: str | None
    contract_type: str | None
    salary_raw: str | None
    match_score: float | None
    match_reasoning: str | None
    status: str
    is_remote: bool

    model_config = {"from_attributes": True}


class JobsResponse(BaseModel):
    items: list[JobItem]
    total: int
    offset: int
    limit: int


@router.get("/jobs", response_model=JobsResponse)
def list_jobs(
    source: str | None = Query(None),
    status: str | None = Query(None),
    min_score: float | None = Query(None),
    q: str | None = Query(None, description="Search in title and description"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobsResponse:
    query = db.query(Job).filter(Job.user_id == user.id)
    if source:
        query = query.filter(Job.source == source)
    if status:
        query = query.filter(Job.status == status)
    if min_score is not None:
        query = query.filter(Job.match_score >= min_score)
    if q:
        query = query.filter(
            Job.title.ilike(f"%{q}%") | Job.description.ilike(f"%{q}%")
        )
    total = query.count()
    # Use coalesce(-1) to sort NULLs last — compatible with both SQLite and PostgreSQL
    from sqlalchemy.sql import func
    items = (
        query.order_by(func.coalesce(Job.match_score, -1).desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return JobsResponse(items=items, total=total, offset=offset, limit=limit)
```

- [ ] **Step 3: Register in api/main.py**

```python
from api.routes.jobs import router as jobs_router
app.include_router(jobs_router)
```

- [ ] **Step 4: Run tests**

```bash
SKIP_WEASYPRINT=1 pytest tests/api/test_jobs.py -v
```
Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routes/jobs.py tests/api/test_jobs.py api/main.py
git commit -m "feat(api): add jobs list endpoint with filters and pagination"
```

---

## Task 9: Scan + Match routes — async background tasks

**Files:**
- Create: `api/routes/scan.py`, `api/routes/match.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/api/test_scan_match.py
"""Tests for POST /scan and POST /match."""
from unittest.mock import AsyncMock, patch


def test_post_scan_returns_started(client, auth_headers):
    resp = client.post(
        "/scan",
        json={"source": "wttj", "limit": 5, "keywords": ["python", "engineer"]},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "started"
    assert "task_id" in data


def test_post_scan_invalid_source_returns_422(client, auth_headers):
    resp = client.post(
        "/scan",
        json={"source": "invalid_source", "limit": 5},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_post_match_returns_started(client, auth_headers):
    resp = client.post("/match", headers=auth_headers)
    assert resp.status_code == 202
    assert resp.json()["status"] == "started"
```

Run: `SKIP_WEASYPRINT=1 pytest tests/api/test_scan_match.py -v`
Expected: FAIL.

- [ ] **Step 2: Implement api/routes/scan.py**

```python
# api/routes/scan.py
"""Scan endpoint — launches scraping as a background task."""
import asyncio
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_current_user
from src.storage.models import User

router = APIRouter(tags=["scan"])

VALID_SOURCES = {"wttj", "indeed", "linkedin"}


class ScanRequest(BaseModel):
    source: str
    limit: int = 20
    keywords: list[str] = []


class TaskStarted(BaseModel):
    status: Literal["started"] = "started"
    task_id: str


async def _run_scan(user_id: int, source: str, limit: int, keywords: list[str]) -> None:
    """Background task: scrape jobs and persist for given user.

    The scrapers use `async with ScraperClass() as scraper: await scraper.search(...)`.
    We instantiate the correct scraper based on source name.
    """
    from src.storage.database import get_session
    from src.storage.models import Job, JobStatus

    _SCRAPER_MAP = {
        "wttj": "src.scrapers.wttj.WTTJScraper",
        "indeed": "src.scrapers.indeed.IndeedScraper",
        "linkedin": "src.scrapers.linkedin.LinkedInScraper",
    }

    try:
        import importlib
        module_path, class_name = _SCRAPER_MAP[source].rsplit(".", 1)
        module = importlib.import_module(module_path)
        ScraperClass = getattr(module, class_name)
        async with ScraperClass() as scraper:
            jobs_data = await scraper.search(keywords=keywords, limit=limit)
        with get_session() as db:
            for job in jobs_data:
                existing = db.query(Job).filter(
                    Job.url == job.url, Job.user_id == user_id
                ).first()
                if not existing:
                    job.user_id = user_id
                    job.status = JobStatus.NEW
                    db.add(job)
    except Exception:
        pass  # Errors are logged by scraper — don't crash the background task


@router.post("/scan", response_model=TaskStarted, status_code=202)
def start_scan(
    body: ScanRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
) -> TaskStarted:
    if body.source not in VALID_SOURCES:
        raise HTTPException(status_code=422, detail=f"Invalid source. Valid: {VALID_SOURCES}")
    task_id = str(uuid.uuid4())
    background_tasks.add_task(_run_scan, user.id, body.source, body.limit, body.keywords)
    return TaskStarted(task_id=task_id)
```

Note: `src.scrapers.get_scraper` may not exist yet — add a stub if needed, or wrap in try/except. The scan endpoint's job is to enqueue the task, not to execute it synchronously.

- [ ] **Step 3: Implement api/routes/match.py**

```python
# api/routes/match.py
"""Match endpoint — launches LLM scoring as a background task."""
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from api.dependencies import get_current_user
from src.storage.models import User

router = APIRouter(tags=["match"])


class TaskStarted(BaseModel):
    status: Literal["started"] = "started"
    task_id: str


async def _run_match(user_id: int, llm_provider: str, encrypted_keys: str | None) -> None:
    """Background task: score all NEW jobs for the user."""
    from api.auth.service import decrypt_api_key
    from src.config.settings import settings
    from src.llm.factory import get_client
    from src.matching.scorer import Scorer
    from src.storage.database import get_session
    from src.storage.models import Job, JobStatus

    if not encrypted_keys or not settings.fernet_key:
        return
    api_key = decrypt_api_key(settings.fernet_key, encrypted_keys, llm_provider)
    if not api_key:
        return

    llm = get_client(llm_provider, api_key=api_key)
    scorer = Scorer(llm_client=llm)

    with get_session() as db:
        jobs = db.query(Job).filter(Job.user_id == user_id, Job.status == JobStatus.NEW).all()
        for job in jobs:
            result = await scorer.score(job)
            job.match_score = result.score
            job.match_reasoning = result.reasoning
            job.status = JobStatus.MATCHED if result.score >= 80 else JobStatus.SKIPPED
            db.add(job)


@router.post("/match", response_model=TaskStarted, status_code=202)
def start_match(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
) -> TaskStarted:
    task_id = str(uuid.uuid4())
    background_tasks.add_task(
        _run_match, user.id, user.llm_provider or "anthropic", user.encrypted_keys
    )
    return TaskStarted(task_id=task_id)
```

- [ ] **Step 4: Register routes in api/main.py**

```python
from api.routes.scan import router as scan_router
from api.routes.match import router as match_router
app.include_router(scan_router)
app.include_router(match_router)
```

- [ ] **Step 5: Run tests**

```bash
SKIP_WEASYPRINT=1 pytest tests/api/test_scan_match.py -v
```
Expected: all 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add api/routes/scan.py api/routes/match.py tests/api/test_scan_match.py api/main.py
git commit -m "feat(api): add scan and match endpoints with async background tasks"
```

---

## Task 10: Applications route — list + generate

**Files:**
- Create: `api/routes/applications.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/api/test_applications.py
"""Tests for GET /applications and POST /applications/{id}/generate."""
from src.storage.database import get_session
from src.storage.models import Application, ApplicationStatus, Job, JobStatus, User


def _seed_application(user_id: int) -> int:
    with get_session() as db:
        job = Job(
            title="Staff Engineer",
            url=f"https://co.com/{user_id}",
            source="wttj",
            user_id=user_id,
            status=JobStatus.MATCHED,
            match_score=85.0,
        )
        db.add(job)
        db.flush()
        app = Application(
            job_id=job.id,
            user_id=user_id,
            status=ApplicationStatus.DRAFT,
        )
        db.add(app)
        db.flush()
        return app.id  # type: ignore[return-value]


def _get_user_id(auth_headers) -> int:
    from src.storage.database import get_session
    from src.storage.models import User
    with get_session() as db:
        user = db.query(User).first()
        return user.id  # type: ignore[return-value]


def test_get_applications_returns_user_apps(client, auth_headers):
    user_id = _get_user_id(auth_headers)
    _seed_application(user_id)
    resp = client.get("/applications", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["status"] == "draft"


def test_get_applications_isolates_users(client, auth_headers):
    user_id = _get_user_id(auth_headers)
    _seed_application(user_id)
    # Register other user with no applications
    client.post("/auth/register", json={"email": "other@test.com", "password": "pass"})
    resp2 = client.post("/auth/login", json={"email": "other@test.com", "password": "pass"})
    other_token = resp2.json()["access_token"]
    resp = client.get("/applications", headers={"Authorization": f"Bearer {other_token}"})
    assert resp.json()["total"] == 0


def test_generate_application_returns_202(client, auth_headers):
    user_id = _get_user_id(auth_headers)
    app_id = _seed_application(user_id)
    resp = client.post(f"/applications/{app_id}/generate", headers=auth_headers)
    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


def test_generate_application_not_found_returns_404(client, auth_headers):
    resp = client.post("/applications/99999/generate", headers=auth_headers)
    assert resp.status_code == 404
```

Run: `SKIP_WEASYPRINT=1 pytest tests/api/test_applications.py -v`
Expected: FAIL.

- [ ] **Step 2: Implement api/routes/applications.py**

```python
# api/routes/applications.py
"""Applications list and generation endpoints."""
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from src.storage.models import Application, User

router = APIRouter(tags=["applications"])


class ApplicationItem(BaseModel):
    id: int
    job_id: int
    status: str
    cover_letter: str | None
    cv_path: str | None
    submitted_at: str | None
    created_at: str | None

    model_config = {"from_attributes": True}


class ApplicationsResponse(BaseModel):
    items: list[ApplicationItem]
    total: int


class TaskStarted(BaseModel):
    status: Literal["started"] = "started"
    task_id: str


async def _run_generate(application_id: int, user_id: int, encrypted_keys: str | None) -> None:
    """Background task: generate CV + cover letter for an application."""
    from api.auth.service import decrypt_api_key
    from src.config.settings import settings
    from src.generators.cover_letter import CoverLetterGenerator
    from src.llm.factory import get_client
    from src.storage.database import get_session
    from src.storage.models import Application, ApplicationStatus

    if not encrypted_keys or not settings.fernet_key:
        return

    with get_session() as db:
        app = db.query(Application).filter(
            Application.id == application_id, Application.user_id == user_id
        ).first()
        if not app or not app.job:
            return

        user = app.user
        api_key = decrypt_api_key(settings.fernet_key, encrypted_keys, user.llm_provider or "anthropic")
        if not api_key:
            return

        llm = get_client(user.llm_provider or "anthropic", api_key=api_key)
        generator = CoverLetterGenerator(llm_client=llm)
        cover_letter = await generator.generate(job=app.job, profile_yaml=user.profile_yaml or "")
        app.cover_letter = cover_letter
        app.status = ApplicationStatus.DRAFT
        db.add(app)


@router.get("/applications", response_model=ApplicationsResponse)
def list_applications(
    status: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplicationsResponse:
    query = db.query(Application).filter(Application.user_id == user.id)
    if status:
        query = query.filter(Application.status == status)
    total = query.count()
    items = query.order_by(Application.created_at.desc()).all()
    return ApplicationsResponse(items=items, total=total)


@router.post("/applications/{application_id}/generate", response_model=TaskStarted, status_code=202)
def generate_application(
    application_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskStarted:
    app = db.query(Application).filter(
        Application.id == application_id, Application.user_id == user.id
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    task_id = str(uuid.uuid4())
    background_tasks.add_task(_run_generate, application_id, user.id, user.encrypted_keys)
    return TaskStarted(task_id=task_id)
```

- [ ] **Step 3: Register in api/main.py**

```python
from api.routes.applications import router as applications_router
app.include_router(applications_router)
```

- [ ] **Step 4: Run tests**

```bash
SKIP_WEASYPRINT=1 pytest tests/api/test_applications.py -v
```
Expected: all 4 PASS.

- [ ] **Step 5: Run full backend test suite**

```bash
SKIP_WEASYPRINT=1 pytest tests/ -v
```
Expected: all tests pass (existing + new API tests).

- [ ] **Step 6: Run lint and type checks**

```bash
ruff check api/ src/storage/models.py src/config/settings.py
mypy api/ --ignore-missing-imports
```
Fix any issues before committing.

- [ ] **Step 7: Commit**

```bash
git add api/routes/applications.py tests/api/test_applications.py api/main.py
git commit -m "feat(api): add applications list and generation endpoints"
```

---

## Task 11: Verify API runs end-to-end

- [ ] **Step 1: Start the API server**

```bash
JWT_SECRET=dev-secret-32-chars-minimum-here FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") uvicorn api.main:app --reload --port 8000
```

- [ ] **Step 2: Smoke test with curl**

```bash
# Register
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","password":"Password1!"}' | python -m json.tool

# Health
curl -s http://localhost:8000/health | python -m json.tool

# Docs
open http://localhost:8000/docs
```

Expected: register returns a JWT, health returns `{"status": "ok", "db": "ok"}`, Swagger UI opens.

- [ ] **Step 3: Commit final wiring**

```bash
git add api/main.py
git commit -m "feat(api): wire all routes and verify API runs"
```

---

## Next Plans

- **Plan 2:** `docs/plans/2026-03-24-multi-tenant-frontend.md` — Next.js 14 + shadcn/ui + NextAuth
- **Plan 3:** `docs/plans/2026-03-24-multi-tenant-docker.md` — docker-compose with db + api + web
