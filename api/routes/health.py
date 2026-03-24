"""Health check endpoint."""
from fastapi import APIRouter

from src.storage.database import health_check

router = APIRouter()


@router.get("/health")
def get_health() -> dict[str, str]:
    db_ok = health_check()
    return {"status": "ok" if db_ok else "degraded", "db": "ok" if db_ok else "error"}
