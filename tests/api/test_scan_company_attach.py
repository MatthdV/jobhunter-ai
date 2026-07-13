"""Tests for _attach_company_and_poster (scan persistence)."""

import pytest

from src.api.routes.pipeline import _attach_company_and_poster
from src.storage.database import configure, drop_all, get_session, init_db
from src.storage.models import Company, Job, Recruiter, User


@pytest.fixture(autouse=True)
def db():
    configure("sqlite:///:memory:")
    init_db()
    with get_session() as s:
        s.add(User(email="u@test.com", hashed_password="h"))
    yield
    drop_all()


def _uid() -> int:
    with get_session() as s:
        return s.query(User).first().id


def _make_job(url: str, company_name=None, poster=None) -> Job:
    job = Job(title="AI Engineer", url=url, source="linkedin")
    if company_name is not None:
        job.company_name = company_name
    if poster:
        job.poster_name = poster["name"]
        job.poster_title = poster.get("title")
        job.poster_linkedin_url = poster.get("url")
    return job


def test_creates_company_and_links_job():
    uid = _uid()
    with get_session() as s:
        job = _make_job("https://x/1", company_name="Sekoia")
        job.user_id = uid
        s.add(job)
        _attach_company_and_poster(s, job, uid)
    with get_session() as s:
        job = s.query(Job).one()
        assert job.company.name == "Sekoia"


def test_reuses_existing_company():
    uid = _uid()
    with get_session() as s:
        s.add(Company(name="Sekoia", user_id=uid))
    with get_session() as s:
        job = _make_job("https://x/2", company_name="Sekoia")
        job.user_id = uid
        s.add(job)
        _attach_company_and_poster(s, job, uid)
    with get_session() as s:
        assert s.query(Company).count() == 1


def test_no_company_name_is_noop():
    uid = _uid()
    with get_session() as s:
        job = _make_job("https://x/3")
        job.user_id = uid
        s.add(job)
        _attach_company_and_poster(s, job, uid)
    with get_session() as s:
        assert s.query(Job).one().company_id is None
        assert s.query(Company).count() == 0


def test_poster_creates_high_confidence_recruiter():
    uid = _uid()
    with get_session() as s:
        job = _make_job(
            "https://x/4",
            company_name="Sekoia",
            poster={"name": "Clémentine Scolan",
                    "title": "Talent Acquisition Manager - Cybersecurity",
                    "url": "https://fr.linkedin.com/in/clémentine-scolan"},
        )
        job.user_id = uid
        s.add(job)
        _attach_company_and_poster(s, job, uid)
    with get_session() as s:
        rec = s.query(Recruiter).one()
        assert rec.name == "Clémentine Scolan"
        assert rec.source == "linkedin_poster"
        assert rec.confidence == 0.95
        assert rec.linkedin_url.endswith("scolan")
        company = s.query(Company).one()
        assert company.recruiter_search_status == "found"


def test_first_poster_wins_for_same_company():
    uid = _uid()
    for i, name in enumerate(["Alice A", "Bob B"]):
        with get_session() as s:
            job = _make_job(f"https://x/5{i}", company_name="Sekoia",
                            poster={"name": name})
            job.user_id = uid
            s.add(job)
            _attach_company_and_poster(s, job, uid)
    with get_session() as s:
        rec = s.query(Recruiter).one()
        assert rec.name == "Alice A"


def test_poster_overwrites_brave_result_but_not_email():
    uid = _uid()
    with get_session() as s:
        company = Company(name="Sekoia", user_id=uid)
        s.add(company)
        s.flush()
        s.add(Recruiter(name="Old Guess", source="brave_llm", confidence=0.6,
                        email="hr@sekoia.io", user_id=uid, company_id=company.id))
    with get_session() as s:
        job = _make_job("https://x/6", company_name="Sekoia",
                        poster={"name": "Clémentine Scolan"})
        job.user_id = uid
        s.add(job)
        _attach_company_and_poster(s, job, uid)
    with get_session() as s:
        rec = s.query(Recruiter).one()
        assert rec.name == "Clémentine Scolan"
        assert rec.source == "linkedin_poster"
        assert rec.email == "hr@sekoia.io"  # kept
