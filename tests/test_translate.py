"""Tests for keyword translation module."""
import pytest
from unittest.mock import AsyncMock

from src.scrapers.translate import detect_language, translate_keywords


class TestDetectLanguage:
    def test_fr_countries(self) -> None:
        assert detect_language(["FR"]) == "fr"
        assert detect_language(["BE"]) == "fr"
        assert detect_language(["CH"]) == "fr"

    def test_en_countries(self) -> None:
        assert detect_language(["GB"]) == "en"
        assert detect_language(["US"]) == "en"
        assert detect_language([]) == "en"

    def test_mixed_keeps_fr(self) -> None:
        assert detect_language(["FR", "GB"]) == "fr"


class TestTranslateKeywords:
    @pytest.mark.asyncio
    async def test_static_dict_hit_en_to_fr(self) -> None:
        result = await translate_keywords(["automation", "engineer"], target_lang="fr")
        assert "automatisation" in result
        assert "ingénieur" in result
        assert "automation" in result
        assert "engineer" in result

    @pytest.mark.asyncio
    async def test_no_translation_for_same_lang(self) -> None:
        result = await translate_keywords(["python"], target_lang="fr")
        assert result.count("python") == 1

    @pytest.mark.asyncio
    async def test_dedup(self) -> None:
        result = await translate_keywords(["python", "python"], target_lang="fr")
        assert result.count("python") == 1

    @pytest.mark.asyncio
    async def test_llm_fallback_called_for_unknown_term(self) -> None:
        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(return_value="chef de projet")
        result = await translate_keywords(
            ["project manager"], target_lang="fr", llm_client=mock_client
        )
        mock_client.complete.assert_called_once()
        assert "chef de projet" in result

    @pytest.mark.asyncio
    async def test_llm_not_called_when_all_in_dict(self) -> None:
        mock_client = AsyncMock()
        await translate_keywords(["automation"], target_lang="fr", llm_client=mock_client)
        mock_client.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_llm_client_unknown_term_kept_as_is(self) -> None:
        result = await translate_keywords(["xenolith platform"], target_lang="fr")
        assert "xenolith platform" in result
