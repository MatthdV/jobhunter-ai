"""FastAPI application entry point."""
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

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

app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]

app.include_router(health_router)

# Auth — loaded after app creation to avoid circular imports
from api.auth.router import router as auth_router  # noqa: E402
from api.routes.applications import router as applications_router  # noqa: E402
from api.routes.jobs import router as jobs_router  # noqa: E402
from api.routes.match import router as match_router  # noqa: E402
from api.routes.scan import router as scan_router  # noqa: E402
from api.routes.settings import router as settings_router  # noqa: E402

app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(jobs_router)
app.include_router(scan_router)
app.include_router(match_router)
app.include_router(applications_router)
