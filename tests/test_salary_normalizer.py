"""Tests for salary normalization with currency conversion + PPP adjustment."""

import pytest

from src.utils.salary_normalizer import (
    COUNTRY_DATA,
    CountryConfig,
    get_country_config,
    get_supported_countries,
    normalize_salary,
)


class TestNormalizeSalary:
    def test_normalize_usd_to_eur(self) -> None:
        """$100k USD → EUR conversion then PPP adjustment."""
        result = normalize_salary(100_000, "US")
        # 100_000 * 0.92 (to_eur) / 0.85 (ppp) ≈ 108_235.29
        assert result == pytest.approx(108_235.29, rel=0.01)

    def test_normalize_gbp_to_eur(self) -> None:
        """£80k GBP → EUR conversion then PPP adjustment."""
        result = normalize_salary(80_000, "GB")
        # 80_000 * 1.17 / 0.95 ≈ 98_526.32
        assert result == pytest.approx(98_526.32, rel=0.01)

    def test_normalize_chf_with_ppp(self) -> None:
        """CHF 150k → EUR with aggressive PPP (CH is expensive)."""
        result = normalize_salary(150_000, "CH")
        # 150_000 * 0.97 / 0.65 ≈ 223_846.15
        assert result == pytest.approx(223_846.15, rel=0.01)

    def test_normalize_eur_france_is_identity(self) -> None:
        """FR: 1.0 rate, 1.0 PPP → no change."""
        result = normalize_salary(90_000, "FR")
        assert result == 90_000.0

    def test_normalize_sek_to_eur(self) -> None:
        """SEK → EUR with PPP."""
        result = normalize_salary(600_000, "SE")
        # 600_000 * 0.088 / 0.82 ≈ 64_390.24
        assert result == pytest.approx(64_390.24, rel=0.01)

    def test_unknown_country_returns_as_is(self) -> None:
        result = normalize_salary(50_000, "ZZ")
        assert result == 50_000

    def test_case_insensitive_country(self) -> None:
        """get_country_config normalizes to uppercase."""
        config = get_country_config("us")
        assert config is not None
        assert config.currency == "USD"


class TestGetSupportedCountries:
    def test_wttj_only_fr(self) -> None:
        supported = get_supported_countries("wttj")
        assert supported == ["FR"]

    def test_indeed_api_all_countries(self) -> None:
        supported = get_supported_countries("indeed_api")
        assert "FR" in supported
        assert "US" in supported
        assert "GB" in supported
        assert len(supported) == len(COUNTRY_DATA)

    def test_linkedin_all_countries(self) -> None:
        supported = get_supported_countries("linkedin")
        assert "FR" in supported
        assert "US" in supported

    def test_unknown_scraper_returns_empty(self) -> None:
        supported = get_supported_countries("nonexistent")
        assert supported == []


class TestCountryConfig:
    def test_country_data_has_required_countries(self) -> None:
        required = ["FR", "US", "GB", "DE", "NL", "CH", "ES", "BE", "CA", "SE"]
        for code in required:
            assert code in COUNTRY_DATA, f"{code} missing from COUNTRY_DATA"

    def test_fr_is_baseline(self) -> None:
        fr = COUNTRY_DATA["FR"]
        assert fr.currency == "EUR"
        assert fr.to_eur_rate == 1.0
        assert fr.ppp_coefficient == 1.0

    def test_config_has_indeed_domain(self) -> None:
        assert COUNTRY_DATA["US"].indeed_domain == "us"
        assert COUNTRY_DATA["GB"].indeed_domain == "co.uk"
        assert COUNTRY_DATA["FR"].indeed_domain == "fr"
