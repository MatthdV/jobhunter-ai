"""FastAPI application — JobHunter AI dashboard."""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.api.routes import jobs, pages, pipeline, stats
from src.api.routes import auth

logger = logging.getLogger(__name__)

app = FastAPI(
    title="JobHunter AI",
    version="0.1.0",
    description="Semi-autonomous job search automation dashboard",
)

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_DIR = Path(__file__).parent.parent.parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request) -> HTMLResponse:
    return auth.login_page(request)


@app.get("/register", response_class=HTMLResponse, include_in_schema=False)
def register_page(request: Request) -> HTMLResponse:
    return auth.register_page(request)


# ---------------------------------------------------------------------------
# API routers
# ---------------------------------------------------------------------------
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])
app.include_router(stats.router, prefix="/api/stats", tags=["stats"])

# ---------------------------------------------------------------------------
# Profile and credentials routes
# ---------------------------------------------------------------------------
from src.api.routes.profile_routes import router as profile_router
app.include_router(profile_router, prefix="/api", tags=["profile"])

# ---------------------------------------------------------------------------
# HTML page routes (must come last to avoid shadowing /api/* paths)
# ---------------------------------------------------------------------------
app.include_router(pages.router, tags=["pages"])


# ---------------------------------------------------------------------------
# Startup event — ensure DB tables exist + integrity check
# ---------------------------------------------------------------------------
@app.on_event("startup")
def _startup() -> None:
    from sqlalchemy import text

    from src.storage.database import _get_engine, init_db

    init_db()  # raises on failure — don't silently continue with a broken DB
    logger.info("Database initialised successfully")

    # Run integrity check on SQLite only (no-op on Postgres).
    # Given two past corruption events, catching corruption at startup beats
    # getting mysterious 500s mid-session.
    engine = _get_engine()
    db_url = str(engine.url)
    if db_url.startswith("sqlite") and ":memory:" not in db_url:
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA integrity_check")).scalar()
        if result != "ok":
            logger.error("SQLite integrity_check FAILED: %s — DB may be corrupt", result)
        else:
            logger.info("SQLite integrity_check: ok")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
