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

# Only handle HTTPException — let system errors propagate normally
app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
app.include_router(health_router)
