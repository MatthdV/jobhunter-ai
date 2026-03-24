"""Integration tests for /auth endpoints."""


def test_register_creates_user_and_returns_token(client):
    resp = client.post("/auth/register", json={"email": "new@test.com", "password": "Password1!"})
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_register_duplicate_email_returns_409(client):
    payload = {"email": "dup@test.com", "password": "Password1!"}
    client.post("/auth/register", json=payload)
    resp = client.post("/auth/register", json=payload)
    assert resp.status_code == 409


def test_login_valid_credentials_returns_token(client):
    client.post("/auth/register", json={"email": "user@test.com", "password": "Password1!"})
    resp = client.post("/auth/login", json={"email": "user@test.com", "password": "Password1!"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password_returns_401(client):
    client.post("/auth/register", json={"email": "user@test.com", "password": "Password1!"})
    resp = client.post("/auth/login", json={"email": "user@test.com", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_email_returns_401(client):
    resp = client.post("/auth/login", json={"email": "ghost@test.com", "password": "x"})
    assert resp.status_code == 401


def test_protected_endpoint_without_token_returns_403(client):
    resp = client.get("/settings")
    assert resp.status_code in (401, 403)


def test_protected_endpoint_with_token_returns_200(client, auth_headers):
    resp = client.get("/settings", headers=auth_headers)
    assert resp.status_code == 200
