"""Recruiter finder — locate the recruiter/hiring manager of a company.

Provider chain: Hunter.io (name + verified email) then Brave Search + LLM
(LinkedIn profile from SERP). Each provider is optional, driven by per-user
API keys. The best candidate is upserted into Company.recruiters, which the
existing email pipeline (job_scheduler / email_handler) already consumes.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlparse

import httpx

from src.llm.base import LLMClient

logger = logging.getLogger(__name__)

_HUNTER_URL = "https://api.hunter.io/v2/domain-search"
_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"
_HTTP_TIMEOUT = 15.0

# Keywords marking a recruiting-related position (EN + FR).
_RECRUITER_TITLE_RE = re.compile(
    r"talent|recruit|people|\bhr\b|hiring|acquisition|recrutement|\brh\b",
    re.IGNORECASE,
)

_BRAVE_LLM_SYSTEM = (
    "You are helping a job seeker identify the recruiter or hiring manager "
    "of a company from LinkedIn profile search results.\n\n"
    "You get a numbered list of search results (title, url, description) and "
    "the company name + job title of the position applied to.\n"
    "Pick the single result most likely to be a recruiter, talent acquisition "
    "person, or hiring manager CURRENTLY at that company. Prefer profiles "
    "matching the job's domain (e.g. tech recruiter for an engineering role).\n\n"
    "Return ONLY valid JSON with this exact schema:\n"
    "{\n"
    '  "best_index": <int index of the chosen result, or null if none fits>,\n'
    '  "name": "<person full name or null>",\n'
    '  "title": "<their job title or null>",\n'
    '  "confidence": <float 0-1, your certainty they recruit for this company>,\n'
    '  "reasoning": "<one short sentence>"\n'
    "}\n"
    "Do not include any text outside the JSON object."
)


@dataclass
class RecruiterCandidate:
    """One potential recruiter contact."""

    name: str
    title: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    source: str = ""
    confidence: float = 0.0


class RecruiterProvider(Protocol):
    name: str

    async def find(
        self,
        company_name: str,
        company_domain: str | None,
        job_title: str,
    ) -> list[RecruiterCandidate]: ...


def _domain_from_website(website: str | None) -> str | None:
    """Extract a bare domain from a website URL ('https://www.acme.io/x' → 'acme.io')."""
    if not website:
        return None
    host = urlparse(website if "://" in website else f"https://{website}").netloc
    host = host.split(":")[0].removeprefix("www.")
    return host or None


def _parse_json_response(text: str) -> dict | None:
    """Parse an LLM JSON response, tolerating markdown fences (CompanyResearcher pattern)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            with contextlib.suppress(json.JSONDecodeError):
                return json.loads(match.group())
    return None


class HunterProvider:
    """Hunter.io Domain Search — HR-department contacts with verified emails."""

    name = "hunter"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def find(
        self,
        company_name: str,
        company_domain: str | None,
        job_title: str,
    ) -> list[RecruiterCandidate]:
        params: dict = {
            "department": "hr",
            "limit": 10,
            "api_key": self._api_key,
        }
        if company_domain:
            params["domain"] = company_domain
        else:
            params["company"] = company_name

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(_HUNTER_URL, params=params)
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:
            logger.warning("Hunter lookup failed for %r: %s", company_name, exc)
            return []

        candidates: list[RecruiterCandidate] = []
        for entry in payload.get("data", {}).get("emails", []) or []:
            name = " ".join(
                p for p in (entry.get("first_name"), entry.get("last_name")) if p
            ).strip()
            if not name:
                continue
            status = (entry.get("verification") or {}).get("status")
            confidence = 0.9 if status == "valid" else 0.6
            position = entry.get("position") or ""
            if position and not _RECRUITER_TITLE_RE.search(position):
                confidence -= 0.15
            candidates.append(
                RecruiterCandidate(
                    name=name,
                    title=position or None,
                    linkedin_url=entry.get("linkedin") or None,
                    email=entry.get("value") or None,
                    source=self.name,
                    confidence=round(confidence, 2),
                )
            )
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates


class _SearchLLMProvider:
    """Base for web-search + LLM providers: search linkedin.com/in profiles,
    then let the LLM pick the best match.

    The linkedin_url always comes from the SERP, never from the LLM
    (anti-hallucination). Confidence is capped at 0.8 — no verified email here.
    Subclasses implement _search() returning [{title, url, description}, ...].
    """

    name = "search_llm"
    _MAX_CONFIDENCE = 0.8

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    def _query(self, company_name: str) -> str:
        return (
            'site:linkedin.com/in ("talent acquisition" OR "recruiter" OR '
            f'"recrutement") "{company_name}"'
        )

    async def _search(self, query: str) -> list[dict]:
        raise NotImplementedError

    async def find(
        self,
        company_name: str,
        company_domain: str | None,
        job_title: str,
    ) -> list[RecruiterCandidate]:
        try:
            raw = await self._search(self._query(company_name))
        except Exception as exc:
            logger.warning("%s search failed for %r: %s", self.name, company_name, exc)
            return []

        results = [r for r in raw if "linkedin.com/in" in (r.get("url") or "")]
        if not results:
            return []

        numbered = "\n".join(
            f'{i}. {r["title"]}\n   url: {r["url"]}\n   {r["description"]}'
            for i, r in enumerate(results)
        )
        prompt = (
            f"Company: {company_name}\n"
            f"Job applied to: {job_title}\n\n"
            f"Search results:\n{numbered}"
        )
        try:
            text = await self._llm.complete(
                prompt=prompt, max_tokens=512, system=_BRAVE_LLM_SYSTEM
            )
        except Exception as exc:
            logger.warning("LLM pick failed for %r: %s", company_name, exc)
            return []

        data = _parse_json_response(text)
        if not data:
            logger.warning("Unparseable LLM recruiter response: %r", text[:200])
            return []
        idx = data.get("best_index")
        if idx is None or not isinstance(idx, int) or not 0 <= idx < len(results):
            return []

        try:
            llm_conf = float(data.get("confidence") or 0.0)
        except (TypeError, ValueError):
            llm_conf = 0.0
        name = (data.get("name") or "").strip()
        if not name:
            return []
        return [
            RecruiterCandidate(
                name=name,
                title=data.get("title") or None,
                linkedin_url=results[idx]["url"],  # from SERP, never from the LLM
                email=None,
                source=self.name,
                confidence=round(min(llm_conf, self._MAX_CONFIDENCE), 2),
            )
        ]


class GoogleCSEProvider(_SearchLLMProvider):
    """Google Programmable Search (Custom Search JSON API) — 100 free queries/day."""

    name = "google_llm"

    def __init__(self, api_key: str, cx: str, llm_client: LLMClient) -> None:
        super().__init__(llm_client)
        self._api_key = api_key
        self._cx = cx

    async def _search(self, query: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                _GOOGLE_CSE_URL,
                params={"key": self._api_key, "cx": self._cx, "q": query, "num": 10},
            )
            resp.raise_for_status()
            payload = resp.json()
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("link", ""),
                "description": r.get("snippet", ""),
            }
            for r in payload.get("items", []) or []
        ]


class BraveLLMProvider(_SearchLLMProvider):
    """Brave Search API — requires a card even on the free tier."""

    name = "brave_llm"

    def __init__(self, api_key: str, llm_client: LLMClient) -> None:
        super().__init__(llm_client)
        self._api_key = api_key

    async def _search(self, query: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                _BRAVE_URL,
                params={"q": query, "count": 10},
                headers={"X-Subscription-Token": self._api_key},
            )
            resp.raise_for_status()
            payload = resp.json()
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("description", ""),
            }
            for r in payload.get("web", {}).get("results", []) or []
        ]


class RecruiterFinder:
    """Try each configured provider in order and keep the best candidate."""

    # A candidate this good with an email short-circuits remaining providers.
    _EARLY_EXIT_CONFIDENCE = 0.5

    def __init__(self, providers: list[RecruiterProvider]) -> None:
        self._providers = providers

    @classmethod
    def from_user_settings(
        cls, user_cfg: dict, llm_client: LLMClient | None
    ) -> "RecruiterFinder":
        providers: list[RecruiterProvider] = []
        if user_cfg.get("hunter_api_key"):
            providers.append(HunterProvider(user_cfg["hunter_api_key"]))
        if (
            user_cfg.get("google_cse_api_key")
            and user_cfg.get("google_cse_cx")
            and llm_client is not None
        ):
            providers.append(GoogleCSEProvider(
                user_cfg["google_cse_api_key"], user_cfg["google_cse_cx"], llm_client
            ))
        if user_cfg.get("brave_api_key") and llm_client is not None:
            providers.append(BraveLLMProvider(user_cfg["brave_api_key"], llm_client))
        return cls(providers)

    @property
    def has_providers(self) -> bool:
        return bool(self._providers)

    async def find(
        self,
        company_name: str,
        company_domain: str | None,
        job_title: str,
    ) -> RecruiterCandidate | None:
        best: RecruiterCandidate | None = None
        for provider in self._providers:
            try:
                candidates = await provider.find(company_name, company_domain, job_title)
            except Exception as exc:  # providers shouldn't raise, but never propagate
                logger.warning("Provider %s raised: %s", provider.name, exc)
                continue
            for cand in candidates:
                if best is None or cand.confidence > best.confidence:
                    best = cand
            if (
                best is not None
                and best.email
                and best.confidence >= self._EARLY_EXIT_CONFIDENCE
            ):
                return best
        return best


# ---------------------------------------------------------------------------
# DB orchestration — called by the API route and the post-match pipeline hook
# ---------------------------------------------------------------------------


def _build_llm_client(user_cfg: dict) -> LLMClient | None:
    """Resolve the user's LLM client the same way _run_match does, or None."""
    from src.config.settings import settings
    from src.llm.factory import get_client

    provider = user_cfg.get("llm_provider", settings.llm_provider)
    api_key = user_cfg.get(f"{provider}_api_key", "")
    if not api_key:
        return None
    model = user_cfg.get("llm_model") or None
    return get_client(provider, model=model, api_key=api_key)


async def find_and_persist_recruiter(job_id: int, user_id: int) -> None:
    """Find the recruiter for *job_id*'s company and upsert it in DB.

    Sets Company.recruiter_search_status to searching → found/not_found/error.
    Never raises — designed to run as a FastAPI background task.
    """
    from src.api.user_settings import get_settings_for_user
    from src.storage.database import get_session
    from src.storage.models import Company, Job, User

    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None or job.company_id is None:
            logger.warning("find_recruiter: job %d missing or has no company", job_id)
            return
        company = session.get(Company, job.company_id)
        user = session.get(User, user_id)
        if company is None or user is None:
            return
        company_id = company.id
        company_name = company.name
        company_website = company.website
        job_title = job.title
        company.recruiter_search_status = "searching"
        company.recruiter_search_error = None
        user_cfg = get_settings_for_user(user)

    try:
        finder = RecruiterFinder.from_user_settings(user_cfg, _build_llm_client(user_cfg))
        candidate = (
            await finder.find(
                company_name, _domain_from_website(company_website), job_title
            )
            if finder.has_providers
            else None
        )

        with get_session() as session:
            company = session.get(Company, company_id)
            if company is None:
                return
            now = datetime.now(timezone.utc)
            company.recruiter_searched_at = now
            if candidate is None:
                company.recruiter_search_status = "not_found"
                return
            _upsert_recruiter(session, candidate, company_id, user_id, now)
            company.recruiter_search_status = "found"
    except Exception as exc:
        logger.exception("find_recruiter failed for job %d", job_id)
        with get_session() as session:
            company = session.get(Company, company_id)
            if company is not None:
                company.recruiter_search_status = "error"
                company.recruiter_search_error = str(exc)[:500]
                company.recruiter_searched_at = datetime.now(timezone.utc)


def _upsert_recruiter(session, candidate: RecruiterCandidate, company_id: int,
                      user_id: int, now: datetime) -> None:
    """Insert or update a Recruiter — uq_recruiter_email_user makes emails unique per user."""
    from src.storage.models import Recruiter

    existing = None
    if candidate.email:
        existing = (
            session.query(Recruiter)
            .filter(Recruiter.email == candidate.email, Recruiter.user_id == user_id)
            .one_or_none()
        )
    if existing is None:
        existing = (
            session.query(Recruiter)
            .filter(Recruiter.company_id == company_id, Recruiter.user_id == user_id)
            .order_by(Recruiter.id)
            .first()
        )
    if existing is None:
        existing = Recruiter(user_id=user_id)
        session.add(existing)
    existing.name = candidate.name
    existing.title = candidate.title
    existing.linkedin_url = candidate.linkedin_url
    if candidate.email:
        existing.email = candidate.email
    existing.company_id = company_id
    existing.source = candidate.source
    existing.confidence = candidate.confidence
    existing.found_at = now
