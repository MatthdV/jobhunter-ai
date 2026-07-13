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


def test_recruiter_finder_columns_exist():
    from sqlalchemy import inspect

    from src.storage.database import _get_engine

    configure("sqlite:///:memory:")
    init_db()
    insp = inspect(_get_engine())
    recruiter_cols = {c["name"] for c in insp.get_columns("recruiters")}
    assert {"title", "linkedin_url", "source", "confidence", "found_at",
            "draft_subject", "draft_body"} <= recruiter_cols
    company_cols = {c["name"] for c in insp.get_columns("companies")}
    assert {"recruiter_search_status", "recruiter_searched_at",
            "recruiter_search_error"} <= company_cols
    user_cols = {c["name"] for c in insp.get_columns("users")}
    assert "recruiter_auto_find" in user_cols
    drop_all()


def test_recruiters_without_email_coexist():
    """NULL emails are distinct under uq_recruiter_email_user (SQLite semantics)."""
    from src.storage.database import get_session
    from src.storage.models import Recruiter, User

    configure("sqlite:///:memory:")
    init_db()
    with get_session() as db:
        db.add(User(email="r@test.com", hashed_password="h"))
    with get_session() as db:
        uid = db.query(User).first().id
        db.add(Recruiter(name="A", user_id=uid, linkedin_url="https://linkedin.com/in/a"))
        db.add(Recruiter(name="B", user_id=uid, linkedin_url="https://linkedin.com/in/b"))
    with get_session() as db:
        assert db.query(Recruiter).count() == 2
    drop_all()
