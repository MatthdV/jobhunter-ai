"""Shared fixtures for API tests."""
import pytest
from fastapi.testclient import TestClient

from src.storage.database import configure, drop_all, init_db


@pytest.fixture(autouse=False)
def db():
    """Fresh in-memory SQLite DB per test. Also sets JWT_SECRET so auth works."""
    from src.config.settings import settings

    settings.jwt_secret = "test-secret-at-least-32-characters-long"
    configure("sqlite:///:memory:")
    init_db()
    yield
    drop_all()


@pytest.fixture
def client(db):
    from api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    """Register + login, return auth headers."""
    client.post("/auth/register", json={"email": "user@test.com", "password": "Password1!"})
    resp = client.post("/auth/login", json={"email": "user@test.com", "password": "Password1!"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
