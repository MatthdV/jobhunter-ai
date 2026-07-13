"""Database engine, session factory, and helpers."""

import logging
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from src.config.settings import settings
from src.storage.models import Base

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine factory — call configure() to swap URL (e.g. in tests)
# ---------------------------------------------------------------------------
# Note: alembic is declared as a dependency but migrations are not yet
# initialised. Phase 2 will run `alembic init` and generate the first
# migration from the current models. Until then, use init_db() directly.
# ---------------------------------------------------------------------------

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _make_engine(url: str) -> Engine:
    connect_args: dict[str, bool] = {}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        connect_args = {"check_same_thread": False}
    engine = create_engine(
        url,
        connect_args=connect_args,
        echo=(settings.log_level == "DEBUG"),
    )
    if is_sqlite:
        # Enable WAL mode on every new connection.
        # WAL prevents the write-exclusive lock that caused past corruption
        # (jobhunter.db.corrupt, 900KB backup). With WAL, readers never block
        # writers and a crash leaves the -wal file recoverable.
        # synchronous=NORMAL is safe with WAL and avoids fsync on every txn.
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _connection_record):  # type: ignore[misc]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


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


def _get_session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        configure()
    assert _SessionLocal is not None
    return _SessionLocal


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def _migrate_schema(engine: Engine) -> None:
    """Apply additive schema changes for columns added after initial create_all.

    SQLite supports ALTER TABLE ADD COLUMN. OperationalError = column exists, safe to ignore.
    """
    new_columns = [
        ("users", "max_days_old INTEGER DEFAULT 30"),
        # Multi-tenant columns added after initial deploy
        ("applications", "user_id INTEGER REFERENCES users(id)"),
        ("companies", "user_id INTEGER REFERENCES users(id)"),
        ("companies", "funding_stage VARCHAR(50)"),
        ("companies", "tech_stack_signals TEXT"),
        ("companies", "culture_signals TEXT"),
        ("companies", "glassdoor_rating FLOAT"),
        ("companies", "growth_signals TEXT"),
        ("companies", "red_flags TEXT"),
        ("companies", "researched_at DATETIME"),
        ("recruiters", "user_id INTEGER REFERENCES users(id)"),
        # Recruiter contact finder (find-recruiter feature)
        ("recruiters", "title VARCHAR(255)"),
        ("recruiters", "linkedin_url VARCHAR(500)"),
        ("recruiters", "source VARCHAR(50)"),
        ("recruiters", "confidence FLOAT"),
        ("recruiters", "found_at DATETIME"),
        ("recruiters", "draft_subject TEXT"),
        ("recruiters", "draft_body TEXT"),
        ("companies", "recruiter_search_status VARCHAR(20)"),
        ("companies", "recruiter_searched_at DATETIME"),
        ("companies", "recruiter_search_error TEXT"),
        ("users", "recruiter_auto_find BOOLEAN DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for table, col_def in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_def}"))
                conn.commit()
                logger.info("Migrated: added column %s to %s", col_def.split()[0], table)
            except Exception:
                pass  # column already exists


def init_db(database_url: str | None = None) -> None:
    """Create all tables declared in models.py if they don't already exist.

    Args:
        database_url: Override the database URL (useful for in-memory test DBs).
    """
    if database_url:
        configure(database_url)
    engine = _get_engine()
    Base.metadata.create_all(bind=engine)
    _migrate_schema(engine)


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
