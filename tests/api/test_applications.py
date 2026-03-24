"""Tests for GET /applications and POST /applications/{id}/generate."""
from src.storage.database import get_session
from src.storage.models import Application, ApplicationStatus, Job, JobStatus


def _get_first_user_id() -> int:
    from src.storage.models import User
    with get_session() as db:
        user = db.query(User).first()
        return user.id  # type: ignore[return-value]


def _seed_application(user_id: int) -> int:
    with get_session() as db:
        job = Job(title="Staff Eng", url=f"https://co.com/{user_id}", source="wttj",
                  user_id=user_id, status=JobStatus.MATCHED, match_score=85.0)
        db.add(job)
        db.flush()
        app = Application(job_id=job.id, user_id=user_id, status=ApplicationStatus.DRAFT)
        db.add(app)
        db.flush()
        return app.id  # type: ignore[return-value]


def test_get_applications_returns_user_apps(client, auth_headers):
    uid = _get_first_user_id()
    _seed_application(uid)
    resp = client.get("/applications", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1


def test_get_applications_isolates_users(client, auth_headers):
    uid = _get_first_user_id()
    _seed_application(uid)
    client.post("/auth/register", json={"email": "other@test.com", "password": "pass123!"})
    resp2 = client.post("/auth/login", json={"email": "other@test.com", "password": "pass123!"})
    other_token = resp2.json()["access_token"]
    resp = client.get("/applications", headers={"Authorization": f"Bearer {other_token}"})
    assert resp.json()["total"] == 0


def test_generate_application_returns_202(client, auth_headers):
    uid = _get_first_user_id()
    app_id = _seed_application(uid)
    resp = client.post(f"/applications/{app_id}/generate", headers=auth_headers)
    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


def test_generate_application_not_found_returns_404(client, auth_headers):
    resp = client.post("/applications/99999/generate", headers=auth_headers)
    assert resp.status_code == 404
