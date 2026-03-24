"""Verify User model and user_id columns exist after models update."""
from src.storage.database import configure, drop_all, init_db


def test_user_model_exists():
    from sqlalchemy.orm import Session

    from src.storage.database import _get_session_factory
    from src.storage.models import User

    configure("sqlite:///:memory:")
    init_db()
    session: Session = _get_session_factory()()
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


def test_company_has_user_id_column():
    from sqlalchemy import inspect

    from src.storage.database import _get_engine

    configure("sqlite:///:memory:")
    init_db()
    cols = {c["name"] for c in inspect(_get_engine()).get_columns("companies")}
    assert "user_id" in cols
    drop_all()
