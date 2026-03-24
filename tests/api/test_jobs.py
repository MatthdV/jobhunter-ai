"""Tests for GET /jobs."""
from datetime import datetime

from src.storage.database import get_session
from src.storage.models import Job, JobStatus


def _get_first_user_id() -> int:
    from src.storage.models import User
    with get_session() as db:
        user = db.query(User).first()
        return user.id  # type: ignore[return-value]


def _seed_jobs(user_id: int, count: int = 3, source: str = "wttj") -> None:
    with get_session() as db:
        for i in range(count):
            db.add(Job(
                title=f"Engineer {i}",
                url=f"https://example.com/{user_id}/{source}/{i}",
                source=source,
                user_id=user_id,
                match_score=float(70 + i * 5),
                status=JobStatus.NEW,
                scraped_at=datetime.utcnow(),
            ))


def test_get_jobs_returns_only_current_user_jobs(client, auth_headers):
    uid = _get_first_user_id()
    _seed_jobs(uid, count=2)
    client.post("/auth/register", json={"email": "other@test.com", "password": "pass123!"})
    resp2 = client.post("/auth/login", json={"email": "other@test.com", "password": "pass123!"})
    other_token = resp2.json()["access_token"]
    with get_session() as db:
        from src.storage.models import User
        other = db.query(User).filter(User.email == "other@test.com").first()
        other_id = other.id  # type: ignore[union-attr]
    _seed_jobs(other_id, count=5)
    resp = client.get("/jobs", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


def test_get_jobs_default_sort_by_score_desc(client, auth_headers):
    uid = _get_first_user_id()
    _seed_jobs(uid, count=3)
    resp = client.get("/jobs", headers=auth_headers)
    scores = [j["match_score"] for j in resp.json()["items"]]
    assert scores == sorted(scores, reverse=True)


def test_get_jobs_pagination(client, auth_headers):
    uid = _get_first_user_id()
    _seed_jobs(uid, count=5)
    resp = client.get("/jobs?limit=2&offset=0", headers=auth_headers)
    assert len(resp.json()["items"]) == 2
    assert resp.json()["total"] == 5


def test_get_jobs_filter_by_source(client, auth_headers):
    uid = _get_first_user_id()
    _seed_jobs(uid, count=2, source="wttj")
    _seed_jobs(uid, count=1, source="linkedin")
    resp = client.get("/jobs?source=linkedin", headers=auth_headers)
    assert resp.json()["total"] == 1
