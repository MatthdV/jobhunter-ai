"""Tests for src/analysis/recruiter_finder.py."""

import json

import pytest

from src.analysis import recruiter_finder as rf
from src.analysis.recruiter_finder import (
    BraveLLMProvider,
    HunterProvider,
    RecruiterCandidate,
    RecruiterFinder,
    _domain_from_website,
    find_and_persist_recruiter,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("boom", request=None, response=None)


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient — returns a canned response."""

    payload: dict = {}
    status_code: int = 200
    last_params: dict | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, headers=None):
        _FakeAsyncClient.last_params = params
        return _FakeResponse(_FakeAsyncClient.payload, _FakeAsyncClient.status_code)


class _FakeLLM:
    def __init__(self, response: str) -> None:
        self._response = response
        self.last_prompt: str | None = None

    async def complete(self, prompt: str, max_tokens: int, system: str = "") -> str:
        self.last_prompt = prompt
        return self._response


def _hunter_payload(**overrides) -> dict:
    entry = {
        "value": "jane@acme.io",
        "first_name": "Jane",
        "last_name": "Doe",
        "position": "Talent Acquisition Manager",
        "linkedin": "https://linkedin.com/in/janedoe",
        "verification": {"status": "valid"},
    }
    entry.update(overrides)
    return {"data": {"emails": [entry]}}


def _brave_payload(urls: list[str]) -> dict:
    return {
        "web": {
            "results": [
                {"title": f"Profile {i}", "url": u, "description": "desc"}
                for i, u in enumerate(urls)
            ]
        }
    }


@pytest.fixture(autouse=True)
def _patch_httpx(monkeypatch):
    _FakeAsyncClient.payload = {}
    _FakeAsyncClient.status_code = 200
    _FakeAsyncClient.last_params = None
    monkeypatch.setattr(rf.httpx, "AsyncClient", _FakeAsyncClient)


# ---------------------------------------------------------------------------
# HunterProvider
# ---------------------------------------------------------------------------


async def test_hunter_maps_candidates():
    _FakeAsyncClient.payload = _hunter_payload()
    cands = await HunterProvider("k").find("Acme", "acme.io", "AI Engineer")
    assert len(cands) == 1
    c = cands[0]
    assert c.name == "Jane Doe"
    assert c.email == "jane@acme.io"
    assert c.linkedin_url == "https://linkedin.com/in/janedoe"
    assert c.confidence == 0.9
    assert c.source == "hunter"
    assert _FakeAsyncClient.last_params["domain"] == "acme.io"
    assert _FakeAsyncClient.last_params["department"] == "hr"


async def test_hunter_falls_back_to_company_name():
    _FakeAsyncClient.payload = _hunter_payload()
    await HunterProvider("k").find("Acme", None, "AI Engineer")
    assert "domain" not in _FakeAsyncClient.last_params
    assert _FakeAsyncClient.last_params["company"] == "Acme"


async def test_hunter_scoring_unverified_and_non_recruiter_title():
    _FakeAsyncClient.payload = _hunter_payload(
        position="Office Manager", verification={"status": "unknown"}
    )
    cands = await HunterProvider("k").find("Acme", "acme.io", "AI Engineer")
    assert cands[0].confidence == pytest.approx(0.45)


async def test_hunter_http_error_returns_empty():
    _FakeAsyncClient.status_code = 500
    assert await HunterProvider("k").find("Acme", "acme.io", "x") == []


async def test_hunter_skips_nameless_entries():
    _FakeAsyncClient.payload = _hunter_payload(first_name=None, last_name=None)
    assert await HunterProvider("k").find("Acme", "acme.io", "x") == []


# ---------------------------------------------------------------------------
# BraveLLMProvider
# ---------------------------------------------------------------------------


async def test_brave_llm_picks_url_from_serp():
    urls = ["https://linkedin.com/in/a", "https://linkedin.com/in/b"]
    _FakeAsyncClient.payload = _brave_payload(urls)
    llm = _FakeLLM(json.dumps(
        {"best_index": 1, "name": "Bob Ray", "title": "Tech Recruiter",
         "confidence": 0.95, "reasoning": "match"}
    ))
    cands = await BraveLLMProvider("k", llm).find("Acme", None, "AI Engineer")
    assert len(cands) == 1
    assert cands[0].linkedin_url == urls[1]          # from SERP, not the LLM
    assert cands[0].confidence == 0.8                # capped
    assert cands[0].source == "brave_llm"
    assert "Acme" in llm.last_prompt


async def test_brave_llm_null_best_index_returns_empty():
    _FakeAsyncClient.payload = _brave_payload(["https://linkedin.com/in/a"])
    llm = _FakeLLM('{"best_index": null, "name": null, "confidence": 0}')
    assert await BraveLLMProvider("k", llm).find("Acme", None, "x") == []


async def test_brave_llm_malformed_json_returns_empty():
    _FakeAsyncClient.payload = _brave_payload(["https://linkedin.com/in/a"])
    llm = _FakeLLM("not json at all")
    assert await BraveLLMProvider("k", llm).find("Acme", None, "x") == []


async def test_brave_llm_out_of_range_index_returns_empty():
    _FakeAsyncClient.payload = _brave_payload(["https://linkedin.com/in/a"])
    llm = _FakeLLM('{"best_index": 7, "name": "X", "confidence": 0.9}')
    assert await BraveLLMProvider("k", llm).find("Acme", None, "x") == []


async def test_brave_llm_filters_non_profile_urls():
    _FakeAsyncClient.payload = _brave_payload(["https://linkedin.com/company/acme"])
    llm = _FakeLLM('{"best_index": 0, "name": "X", "confidence": 0.9}')
    assert await BraveLLMProvider("k", llm).find("Acme", None, "x") == []


# ---------------------------------------------------------------------------
# RecruiterFinder chain
# ---------------------------------------------------------------------------


class _StubProvider:
    def __init__(self, name: str, cands: list[RecruiterCandidate], raises: bool = False):
        self.name = name
        self._cands = cands
        self._raises = raises
        self.called = False

    async def find(self, *a, **kw):
        self.called = True
        if self._raises:
            raise RuntimeError("provider blew up")
        return self._cands


async def test_finder_early_exit_on_email():
    good = RecruiterCandidate(name="J", email="j@x.io", confidence=0.9, source="hunter")
    p1 = _StubProvider("hunter", [good])
    p2 = _StubProvider("brave_llm", [])
    result = await RecruiterFinder([p1, p2]).find("Acme", None, "x")
    assert result is good
    assert not p2.called


async def test_finder_falls_through_without_email():
    no_email = RecruiterCandidate(name="A", confidence=0.7, source="hunter")
    better = RecruiterCandidate(name="B", confidence=0.8, source="brave_llm")
    result = await RecruiterFinder(
        [_StubProvider("hunter", [no_email]), _StubProvider("brave", [better])]
    ).find("Acme", None, "x")
    assert result is better


async def test_finder_provider_exception_not_fatal():
    ok = RecruiterCandidate(name="B", confidence=0.6, source="brave_llm")
    result = await RecruiterFinder(
        [_StubProvider("hunter", [], raises=True), _StubProvider("brave", [ok])]
    ).find("Acme", None, "x")
    assert result is ok


async def test_finder_no_providers():
    finder = RecruiterFinder.from_user_settings({}, None)
    assert not finder.has_providers
    assert await finder.find("Acme", None, "x") is None


def test_domain_from_website():
    assert _domain_from_website("https://www.acme.io/jobs") == "acme.io"
    assert _domain_from_website("acme.io") == "acme.io"
    assert _domain_from_website(None) is None
    assert _domain_from_website("") is None


# ---------------------------------------------------------------------------
# find_and_persist_recruiter (in-memory DB)
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    from src.storage.database import configure, drop_all, init_db

    configure("sqlite:///:memory:")
    init_db()
    yield
    drop_all()


def _seed(job_kwargs=None):
    from src.storage.database import get_session
    from src.storage.models import Company, Job, User

    with get_session() as s:
        user = User(email="u@test.com", hashed_password="h")
        s.add(user)
        s.flush()
        company = Company(name="Acme", user_id=user.id, website="https://acme.io")
        s.add(company)
        s.flush()
        job = Job(title="AI Engineer", url="https://x/1", source="wttj",
                  user_id=user.id, company_id=company.id, **(job_kwargs or {}))
        s.add(job)
        s.flush()
        return user.id, company.id, job.id


async def test_persist_found(db, monkeypatch):
    uid, cid, jid = _seed()
    cand = RecruiterCandidate(name="Jane Doe", title="TA Manager",
                              linkedin_url="https://linkedin.com/in/jane",
                              email="jane@acme.io", source="hunter", confidence=0.9)

    async def fake_find(self, *a, **kw):
        return cand

    monkeypatch.setattr(rf.RecruiterFinder, "find", fake_find)
    monkeypatch.setattr(rf.RecruiterFinder, "has_providers", property(lambda self: True))
    monkeypatch.setattr(rf.RecruiterFinder, "from_user_settings",
                        classmethod(lambda cls, cfg, llm: cls([])))
    await find_and_persist_recruiter(jid, uid)

    from src.storage.database import get_session
    from src.storage.models import Company, Recruiter

    with get_session() as s:
        company = s.get(Company, cid)
        assert company.recruiter_search_status == "found"
        assert company.recruiter_searched_at is not None
        rec = s.query(Recruiter).one()
        assert rec.name == "Jane Doe"
        assert rec.email == "jane@acme.io"
        assert rec.company_id == cid
        assert rec.user_id == uid


async def test_persist_not_found(db, monkeypatch):
    uid, cid, jid = _seed()

    async def fake_find(self, *a, **kw):
        return None

    monkeypatch.setattr(rf.RecruiterFinder, "find", fake_find)
    monkeypatch.setattr(rf.RecruiterFinder, "has_providers", property(lambda self: True))
    monkeypatch.setattr(rf.RecruiterFinder, "from_user_settings",
                        classmethod(lambda cls, cfg, llm: cls([])))
    await find_and_persist_recruiter(jid, uid)

    from src.storage.database import get_session
    from src.storage.models import Company, Recruiter

    with get_session() as s:
        assert s.get(Company, cid).recruiter_search_status == "not_found"
        assert s.query(Recruiter).count() == 0


async def test_persist_error(db, monkeypatch):
    uid, cid, jid = _seed()

    async def fake_find(self, *a, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(rf.RecruiterFinder, "find", fake_find)
    monkeypatch.setattr(rf.RecruiterFinder, "has_providers", property(lambda self: True))
    monkeypatch.setattr(rf.RecruiterFinder, "from_user_settings",
                        classmethod(lambda cls, cfg, llm: cls([])))
    await find_and_persist_recruiter(jid, uid)

    from src.storage.database import get_session
    from src.storage.models import Company

    with get_session() as s:
        company = s.get(Company, cid)
        assert company.recruiter_search_status == "error"
        assert "network down" in company.recruiter_search_error


async def test_persist_upsert_same_email(db, monkeypatch):
    """Second search with the same email updates the existing row."""
    uid, cid, jid = _seed()
    cand = RecruiterCandidate(name="Jane Doe", email="jane@acme.io",
                              source="hunter", confidence=0.9)

    async def fake_find(self, *a, **kw):
        return cand

    monkeypatch.setattr(rf.RecruiterFinder, "find", fake_find)
    monkeypatch.setattr(rf.RecruiterFinder, "has_providers", property(lambda self: True))
    monkeypatch.setattr(rf.RecruiterFinder, "from_user_settings",
                        classmethod(lambda cls, cfg, llm: cls([])))
    await find_and_persist_recruiter(jid, uid)
    cand.name = "Jane B. Doe"
    await find_and_persist_recruiter(jid, uid)

    from src.storage.database import get_session
    from src.storage.models import Recruiter

    with get_session() as s:
        recs = s.query(Recruiter).all()
        assert len(recs) == 1
        assert recs[0].name == "Jane B. Doe"
