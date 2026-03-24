"""Tests for GET/PUT /settings."""
from cryptography.fernet import Fernet


def test_get_settings_returns_defaults(client, auth_headers):
    resp = client.get("/settings", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["llm_provider"] == "anthropic"
    assert data["min_match_score"] == 80
    assert data["dry_run"] is True
    assert data["profile_yaml"] is None
    assert data["api_key"] is None
    assert data["has_api_key"] is False


def test_put_settings_updates_preferences(client, auth_headers):
    resp = client.put(
        "/settings",
        json={"min_match_score": 75, "dry_run": False, "active_sources": "wttj,indeed"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    get_resp = client.get("/settings", headers=auth_headers)
    assert get_resp.json()["min_match_score"] == 75
    assert get_resp.json()["dry_run"] is False


def test_put_settings_stores_encrypted_api_key(client, auth_headers):
    from src.config.settings import settings
    settings.fernet_key = Fernet.generate_key().decode()
    resp = client.put(
        "/settings",
        json={"llm_provider": "anthropic", "api_key": "sk-ant-test"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    get_resp = client.get("/settings", headers=auth_headers)
    assert get_resp.json().get("api_key") is None
    assert get_resp.json()["has_api_key"] is True


def test_put_settings_updates_profile_yaml(client, auth_headers):
    yaml_content = "name: Test User\ntarget_roles:\n  - Engineer\n"
    resp = client.put("/settings", json={"profile_yaml": yaml_content}, headers=auth_headers)
    assert resp.status_code == 200
    get_resp = client.get("/settings", headers=auth_headers)
    assert get_resp.json()["profile_yaml"] == yaml_content
