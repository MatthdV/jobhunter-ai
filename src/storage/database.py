"""Database engine, session factory, and helpers."""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from src.config.settings import settings
from src.storage.models import Base

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_connect_args: dict = {}
if settings.database_url.startswith("sqlite"):
    # Required for SQLite when used across threads (e.g. FastAPI, async tests)
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    echo=(settings.log_level == "DEBUG"),
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create all tables declared in models.py if they don't already exist."""
    Base.metadata.create_all(bind=engine)


def drop_all() -> None:
    """Drop all tables — for tests only, never call in production."""
    Base.metadata.drop_all(bind=engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional database session.

    Usage::

        with get_session() as session:
            session.add(job)
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def health_check() -> bool:
    """Return True if the database is reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
