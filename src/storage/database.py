"""Database engine, session factory, and helpers."""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from src.config.settings import settings
from src.storage.models import Base

# ---------------------------------------------------------------------------
# Engine factory — call configure() to swap URL (e.g. in tests)
# ---------------------------------------------------------------------------
# Note: alembic is declared as a dependency but migrations are not yet
# initialised. Phase 2 will run `alembic init` and generate the first
# migration from the current models. Until then, use init_db() directly.
# ---------------------------------------------------------------------------

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _make_engine(url: str) -> Engine:
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(
        url,
        connect_args=connect_args,
        echo=(settings.log_level == "DEBUG"),
    )


def configure(database_url: str | None = None) -> None:
    """(Re-)initialise the engine and session factory.

    Call with no arguments to use the URL from settings (production).
    Call with a URL to override — useful in tests::

        configure("sqlite:///:memory:")
        init_db()
    """
    global _engine, _SessionLocal
    url = database_url or settings.database_url
    _engine = _make_engine(url)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _get_engine() -> Engine:
    if _engine is None:
        configure()
    assert _engine is not None
    return _engine


def _get_session_factory() -> sessionmaker:
    if _SessionLocal is None:
        configure()
    assert _SessionLocal is not None
    return _SessionLocal


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def init_db(database_url: str | None = None) -> None:
    """Create all tables declared in models.py if they don't already exist.

    Args:
        database_url: Override the database URL (useful for in-memory test DBs).
    """
    if database_url:
        configure(database_url)
    Base.metadata.create_all(bind=_get_engine())


def drop_all() -> None:
    """Drop all tables — for tests only, never call in production."""
    Base.metadata.drop_all(bind=_get_engine())


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional database session.

    Usage::

        with get_session() as session:
            session.add(job)
    """
    session = _get_session_factory()()
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
        with _get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
