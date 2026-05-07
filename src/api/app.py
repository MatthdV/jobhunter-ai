"""FastAPI application — JobHunter AI dashboard."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.api.routes import jobs, pages, pipeline, stats

logger = logging.getLogger(__name__)

app = FastAPI(
    title="JobHunter AI",
    version="0.1.0",
    description="Semi-autonomous job search automation dashboard",
)

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_DIR = Path(__file__).parent.parent.parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# API routers
# ---------------------------------------------------------------------------
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])
app.include_router(stats.router, prefix="/api/stats", tags=["stats"])

# ---------------------------------------------------------------------------
# HTML page routes (must come last to avoid shadowing /api/* paths)
# ---------------------------------------------------------------------------
app.include_router(pages.router, tags=["pages"])


# ---------------------------------------------------------------------------
# Startup event — ensure DB tables exist
# ---------------------------------------------------------------------------
@app.on_event("startup")
def _startup() -> None:
    from src.storage.database import init_db

    try:
        init_db()
        logger.info("Database initialised successfully")
    except Exception:
        logger.exception("Database initialisation failed — continuing anyway")
