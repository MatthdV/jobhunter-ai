"""Tests for POST /scan and POST /match."""


def test_post_scan_returns_started(client, auth_headers):
    resp = client.post(
        "/scan",
        json={"source": "wttj", "limit": 5, "keywords": ["python"]},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "started"
    assert "task_id" in data


def test_post_scan_invalid_source_returns_422(client, auth_headers):
    resp = client.post(
        "/scan",
        json={"source": "invalid_source", "limit": 5},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_post_match_returns_started(client, auth_headers):
    resp = client.post("/match", headers=auth_headers)
    assert resp.status_code == 202
    assert resp.json()["status"] == "started"
