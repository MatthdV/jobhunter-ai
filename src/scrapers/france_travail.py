"""France Travail scraper — official API v2 (httpx, no Playwright required).

Auth: OAuth2 client_credentials.
Endpoint: GET https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search
Docs: https://francetravail.io/data/api/offres-emploi

Register at https://francetravail.io to get FRANCE_TRAVAIL_CLIENT_ID + FRANCE_TRAVAIL_CLIENT_SECRET.
Free tier: no hard rate limit documented; use conservative rate limiting.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from src.config.settings import settings
from src.scrapers.base import BaseScraper
from src.scrapers.exceptions import ParseError, RateLimitError
from src.scrapers.filters import ScraperFilters
from src.storage.models import Job

logger = logging.getLogger(__name__)

_TOKEN_URL = (
    "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
    "?realm=%2Fpartenaire"
)
_SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"

_WORK_MODE_MAP: dict[str, str] = {
    "remote": "1",
    "hybrid": "2",
    "on-site": "3",
}

_CONTRACT_MAP: dict[str, str] = {
    "CDI": "CDI",
    "CDD": "CDD",
    "MIS": "Intérim",
    "SAI": "Saisonnier",
    "LIB": "Freelance",
    "REI": "Stage",
    "TTI": "CDD",
    "FRA": "Franchise",
    "CCE": "CDI",
    "DEF": "CDI",
    "DIN": "Intérim",
    "CPI": "CDI",
}


class FranceTravailScraper(BaseScraper):
    """Scrape job offers via the France Travail (ex-Pôle Emploi) official API.

    Requires FRANCE_TRAVAIL_CLIENT_ID and FRANCE_TRAVAIL_CLIENT_SECRET in env/settings.
    The API is free and covers all jobs published on francetravail.fr.

    Usage::

        async with FranceTravailScraper() as scraper:
            jobs = await scraper.search(keywords=["automation engineer"], limit=50)
    """

    source = "france_travail"
    MIN_DELAY = 0.5
    MAX_DELAY = 1.5
    MAX_RPH = 120

    def __init__(self, headless: bool = True, user_id: int | None = None) -> None:
        super().__init__(headless=headless, user_id=user_id)
        self._client: httpx.AsyncClient | None = None
        self._access_token: str = ""
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        self._client = httpx.AsyncClient(timeout=30.0)

    async def _teardown(self) -> None:
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # OAuth2 token management
    # ------------------------------------------------------------------

    def _get_credentials(self) -> tuple[str, str]:
        """Return (client_id, client_secret) from settings or per-user store."""
        client_id = settings.france_travail_client_id
        client_secret = settings.france_travail_client_secret
        if self._user_id is not None:
            try:
                from src.api.user_settings import get_settings_for_user
                from src.storage.database import get_session
                from src.storage.models import User
                with get_session() as session:
                    user = session.get(User, self._user_id)
                    if user:
                        session.expunge(user)
                        u_cfg = get_settings_for_user(user)
                        client_id = u_cfg.get("france_travail_client_id") or client_id
                        client_secret = u_cfg.get("france_travail_client_secret") or client_secret
            except Exception as exc:
                logger.debug("FranceTravail: could not load per-user credentials: %s", exc)
        return client_id, client_secret

    async def _ensure_token(self) -> str:
        """Return a valid Bearer token, refreshing if needed."""
        assert self._client is not None

        if self._access_token and time.time() < self._token_expires_at - 30:
            return self._access_token

        client_id, client_secret = self._get_credentials()
        if not client_id or not client_secret:
            raise ParseError(
                "FRANCE_TRAVAIL_CLIENT_ID / FRANCE_TRAVAIL_CLIENT_SECRET not configured"
            )

        response = await self._client.post(
            _TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "api_offresdemploiv2 o2dsoffre",
            },
        )
        if response.status_code == 401:
            raise ParseError("France Travail: invalid client_id / client_secret (HTTP 401)")
        response.raise_for_status()

        payload = response.json()
        self._access_token = payload["access_token"]
        self._token_expires_at = time.time() + payload.get("expires_in", 1499)
        logger.debug("FranceTravail: new token obtained, expires in %ds", payload.get("expires_in", 1499))
        return self._access_token

    # ------------------------------------------------------------------
    # _fetch_raw
    # ------------------------------------------------------------------

    async def _fetch_raw(
        self,
        keywords: list[str],
        location: str,
        filters: ScraperFilters,
        limit: int,
        country_code: str = "FR",
    ) -> list[Any]:
        if country_code != "FR":
            logger.warning("FranceTravail only supports FR, skipping country=%s", country_code)
            return []

        assert self._client is not None, "_setup() must be called first"

        try:
            token = await self._ensure_token()
        except ParseError as exc:
            logger.warning("FranceTravail: cannot get token — %s", exc)
            return []

        params: dict[str, Any] = {
            "motsCles": " ".join(keywords),
            "range": f"0-{min(limit, 149)}",
        }

        work_mode = (filters.work_modes or ["remote"])[0]
        teletravail = _WORK_MODE_MAP.get(work_mode)
        if teletravail:
            params["modesTravail"] = teletravail

        if filters.max_days_old:
            from datetime import UTC, datetime, timedelta
            since = datetime.now(UTC) - timedelta(days=filters.max_days_old)
            params["minCreationDate"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")

        await self._wait()
        response = await self._client.get(
            _SEARCH_URL,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

        if response.status_code == 429:
            raise RateLimitError("France Travail API rate limited (HTTP 429)")
        if response.status_code in (401, 403):
            # Token may have expired mid-session; reset and retry once
            self._access_token = ""
            raise ParseError(f"France Travail API auth error (HTTP {response.status_code})")
        response.raise_for_status()

        data = response.json()
        results: list[dict[str, Any]] = data.get("resultats", [])
        logger.debug("FranceTravail: %d results for %s", len(results), keywords)
        return results[:limit]

    # ------------------------------------------------------------------
    # _parse_raw
    # ------------------------------------------------------------------

    async def _parse_raw(self, raw: Any) -> Job:
        """Map a France Travail API result dict to a Job instance."""
        if not isinstance(raw, dict):
            raise ParseError(f"Expected dict, got {type(raw).__name__}")

        try:
            title: str = raw.get("intitule") or ""
            if not title:
                raise ParseError("Missing required field 'intitule'")

            job_id: str = raw.get("id") or ""
            url: str = (
                raw.get("origineOffre", {}).get("urlOrigine")
                or f"https://candidat.francetravail.fr/offres/recherche/detail/{job_id}"
            )

            # Location
            lieu = raw.get("lieuTravail") or {}
            location_str: str | None = lieu.get("libelle") or None

            # Remote
            modes = raw.get("modesTravail") or []
            mode_code = modes[0].get("code", "") if modes and isinstance(modes[0], dict) else ""
            is_remote = mode_code == "1"

            # Salary
            salaire = raw.get("salaire") or {}
            salary_raw_str: str | None = salaire.get("commentaire") or salaire.get("libelle") or None

            # Contract type
            type_contrat = (raw.get("typeContrat") or raw.get("typeContratLibelle")) or ""
            contract_type: str | None = _CONTRACT_MAP.get(type_contrat, type_contrat) or None

            # Description
            description: str | None = raw.get("description") or None

            return Job(
                title=title,
                url=url,
                source=self.source,
                description=description,
                location=location_str,
                is_remote=is_remote,
                salary_raw=salary_raw_str,
                salary_min=None,
                salary_max=None,
                contract_type=contract_type,
                country_code="FR",
                salary_currency="EUR",
            )

        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(f"Failed to parse France Travail job: {exc}") from exc
