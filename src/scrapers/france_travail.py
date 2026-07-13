"""France Travail scraper — OAuth2 client_credentials + REST API, no Playwright.

Keys are set globally (Railway ENV) — never entered by users.
    FRANCE_TRAVAIL_CLIENT_ID     : from francetravail.io developer portal
    FRANCE_TRAVAIL_CLIENT_SECRET : from francetravail.io developer portal
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.config.settings import ConfigurationError, settings
from src.scrapers.base import BaseScraper
from src.scrapers.exceptions import ParseError, RateLimitError
from src.scrapers.filters import ScraperFilters
from src.storage.models import Job

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire"
_SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
_SCOPE = "api_offresdemploiv2 o2dsoffre"

_NATURE_CONTRAT_MAP: dict[str, str] = {
    "CDI": "CDI",
    "CDD": "CDD",
    "MIS": "Intérim",
    "SAI": "Saisonnier",
    "DDI": "CDD",
    "FRA": "Franchise",
    "LIB": "Libéral",
    "REP": "Reprise",
    "TTI": "Interim",
    "DIN": "CDI",
}


class FranceTravailScraper(BaseScraper):
    """Search jobs via France Travail (ex Pôle Emploi) API v2.

    Keys come from global Railway ENV — no user credential needed.
    Uses OAuth2 client_credentials flow; token is cached per-instance.

    Usage::

        async with FranceTravailScraper() as scraper:
            jobs = await scraper.search(keywords=["data engineer"], limit=50)
    """

    source = "france_travail"
    MIN_DELAY = 0.3
    MAX_DELAY = 1.0
    MAX_RPH = 300

    def __init__(self, headless: bool = True, user_id: int | None = None) -> None:
        super().__init__(headless=headless, user_id=user_id)
        client_id = settings.france_travail_client_id
        client_secret = settings.france_travail_client_secret
        if not client_id or not client_secret:
            raise ConfigurationError(
                "FRANCE_TRAVAIL_CLIENT_ID and FRANCE_TRAVAIL_CLIENT_SECRET must be set "
                "— keys are provided globally via Railway ENV"
            )
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token: str | None = None
        self._client: httpx.AsyncClient | None = None

    async def _setup(self) -> None:
        self._client = httpx.AsyncClient(timeout=30.0)
        await self._refresh_token()

    async def _teardown(self) -> None:
        if self._client:
            await self._client.aclose()

    async def _refresh_token(self) -> None:
        assert self._client is not None
        response = await self._client.post(
            _TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": _SCOPE,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            raise ConfigurationError(
                f"France Travail OAuth failed (HTTP {response.status_code}): {response.text[:200]}"
            )
        self._access_token = response.json().get("access_token")
        if not self._access_token:
            raise ConfigurationError("France Travail OAuth returned no access_token")

    async def _fetch_raw(
        self,
        keywords: list[str],
        location: str,
        filters: ScraperFilters,
        limit: int,
        country_code: str = "FR",
    ) -> list[Any]:
        assert self._client is not None, "_setup() must be called first"

        query = " ".join(keywords)
        params: dict[str, Any] = {
            "motsCles": query,
            "range": f"0-{min(149, limit - 1)}",
        }
        # Location: France Travail uses INSEE commune codes or département
        # Pass as free-text lieu — API will fuzzy-match
        if location and location.lower() not in ("remote", "france", ""):
            params["lieu"] = location

        await self._wait()
        response = await self._client.get(
            _SEARCH_URL,
            params=params,
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Accept": "application/json",
            },
        )

        # Token expired — refresh once and retry
        if response.status_code == 401:
            await self._refresh_token()
            response = await self._client.get(
                _SEARCH_URL,
                params=params,
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Accept": "application/json",
                },
            )
            if response.status_code == 401:
                raise ConfigurationError(
                    "France Travail token refresh succeeded but API still rejects — "
                    "check CLIENT_ID/SECRET scope includes 'api_offresdemploiv2 o2dsoffre'"
                )

        self._check_response(response)

        if not response.content:
            return []

        data = response.json()
        return (data.get("resultats") or [])[:limit]

    async def _parse_raw(self, raw: Any) -> Job:
        title: str = raw.get("intitule") or ""
        url: str = raw.get("origineOffre", {}).get("urlOrigine") or (
            f"https://candidat.francetravail.fr/offres/recherche/detail/{raw.get('id', '')}"
        )

        company: str | None = (raw.get("entreprise") or {}).get("nom") or None
        # (also attached to the returned Job as a transient company_name below)

        lieu = raw.get("lieuTravail") or {}
        location_str: str | None = lieu.get("libelle") or None

        description: str | None = raw.get("description") or None

        salary_raw_str: str | None = None
        salaire = raw.get("salaire") or {}
        if salaire.get("libelle"):
            salary_raw_str = salaire["libelle"]

        nature_code: str = (raw.get("typeContrat") or "").upper()
        contract_type: str | None = _NATURE_CONTRAT_MAP.get(nature_code)

        if company and description:
            description = f"[{company}]\n\n{description}"
        elif company:
            description = f"[{company}]"

        job = Job(
            title=title,
            url=url,
            source=self.source,
            location=location_str,
            description=description,
            salary_min=None,
            salary_max=None,
            salary_raw=salary_raw_str,
            contract_type=contract_type,
        )
        job.company_name = company  # type: ignore[attr-defined]
        return job

    def _check_response(self, response: httpx.Response) -> None:
        if response.status_code == 429:
            raise RateLimitError("France Travail API rate limited (HTTP 429)")
        if response.status_code in (401, 403):
            raise ConfigurationError(
                f"France Travail token invalid or expired (HTTP {response.status_code})"
            )
        response.raise_for_status()
