"""Keyword translation — static EN↔FR dict with LLM fallback for unknown terms."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.llm.base import LLMClient

logger = logging.getLogger(__name__)

_EN_TO_FR: dict[str, str] = {
    "engineer": "ingénieur",
    "developer": "développeur",
    "automation": "automatisation",
    "manager": "responsable",
    "architect": "architecte",
    "analyst": "analyste",
    "consultant": "consultant",
    "artificial intelligence": "intelligence artificielle",
    "data engineer": "data engineer",
    "data scientist": "data scientist",
    "software": "logiciel",
    "integration": "intégration",
    "platform": "plateforme",
    "infrastructure": "infrastructure",
    "security": "sécurité",
    "operations": "opérations",
    "product": "produit",
    "revenue": "revenu",
    "growth": "croissance",
    "remote": "télétravail",
    "workflow": "workflow",
    "devops": "devops",
    "cloud": "cloud",
    "python": "python",
    "machine learning": "machine learning",
}

_FR_TO_EN: dict[str, str] = {v: k for k, v in _EN_TO_FR.items()}

_COUNTRY_LANG: dict[str, str] = {
    "FR": "fr",
    "BE": "fr",
    "CH": "fr",
    "LU": "fr",
}


def detect_language(countries: list[str]) -> str:
    """Return 'fr' if any country maps to French, else 'en'."""
    for code in countries:
        if _COUNTRY_LANG.get(code.upper()) == "fr":
            return "fr"
    return "en"


async def translate_keywords(
    terms: list[str],
    target_lang: str,
    llm_client: "LLMClient | None" = None,
) -> list[str]:
    """Return deduplicated list of *terms* + translations into *target_lang*.

    Unknown terms: sent to LLM if *llm_client* provided, otherwise kept as-is.
    """
    src_dict = _EN_TO_FR if target_lang == "fr" else _FR_TO_EN
    result: list[str] = []
    seen: set[str] = set()
    unknown: list[str] = []

    for term in terms:
        lo = term.lower()
        if lo not in seen:
            seen.add(lo)
            result.append(term)
        translated = src_dict.get(lo)
        if translated:
            if translated.lower() not in seen:
                seen.add(translated.lower())
                result.append(translated)
        elif lo not in src_dict.values():
            unknown.append(term)

    if unknown and llm_client is not None:
        try:
            lang_name = "French" if target_lang == "fr" else "English"
            prompt = (
                f"Translate these job search terms to {lang_name}. "
                f"Return ONLY the translated terms, one per line, same order:\n"
                + "\n".join(unknown)
            )
            raw = await llm_client.complete(prompt=prompt, max_tokens=200)
            for translation in raw.strip().splitlines():
                t = translation.strip()
                if t and t.lower() not in seen:
                    seen.add(t.lower())
                    result.append(t)
        except Exception as exc:
            logger.warning("LLM translation failed: %s", exc)

    return result
