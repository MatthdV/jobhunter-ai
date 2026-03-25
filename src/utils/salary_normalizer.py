"""Salary normalization: currency conversion + PPP adjustment."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CountryConfig:
    """Configuration for a supported country."""

    currency: str
    to_eur_rate: float        # 1 unit of currency = X EUR
    ppp_coefficient: float    # cost-of-living relative to FR (FR=1.0)
    indeed_domain: str        # e.g. "us", "co.uk", "de"
    indeed_country_code: str  # JSearch API country param
    supported_scrapers: list[str] = field(default_factory=list)


COUNTRY_DATA: dict[str, CountryConfig] = {
    "FR": CountryConfig("EUR", 1.0, 1.0, "fr", "FR", ["wttj", "indeed_api", "indeed", "linkedin"]),
    "US": CountryConfig("USD", 0.92, 0.85, "us", "US", ["indeed_api", "indeed", "linkedin"]),
    "GB": CountryConfig("GBP", 1.17, 0.95, "co.uk", "GB", ["indeed_api", "indeed", "linkedin"]),
    "DE": CountryConfig("EUR", 1.0, 0.95, "de", "DE", ["indeed_api", "indeed", "linkedin"]),
    "NL": CountryConfig("EUR", 1.0, 0.97, "nl", "NL", ["indeed_api", "indeed", "linkedin"]),
    "CH": CountryConfig("CHF", 0.97, 0.65, "ch", "CH", ["indeed_api", "indeed", "linkedin"]),
    "ES": CountryConfig("EUR", 1.0, 1.15, "es", "ES", ["indeed_api", "indeed", "linkedin"]),
    "BE": CountryConfig("EUR", 1.0, 0.98, "be", "BE", ["indeed_api", "indeed", "linkedin"]),
    "CA": CountryConfig("CAD", 0.68, 0.88, "ca", "CA", ["indeed_api", "indeed", "linkedin"]),
    "SE": CountryConfig("SEK", 0.088, 0.82, "se", "SE", ["indeed_api", "indeed", "linkedin"]),
}


def normalize_salary(
    amount: float, country_code: str, base_currency: str = "EUR"
) -> float:
    """Convert salary to EUR and adjust for purchasing power parity.

    Args:
        amount: Salary amount in local currency.
        country_code: ISO 3166-1 alpha-2 country code.
        base_currency: Target currency (currently only EUR supported).

    Returns:
        PPP-normalized amount in EUR, rounded to 2 decimals.
    """
    config = COUNTRY_DATA.get(country_code.upper())
    if not config:
        return amount
    eur_amount = amount * config.to_eur_rate
    normalized = eur_amount / config.ppp_coefficient
    return round(normalized, 2)


def get_country_config(country_code: str) -> CountryConfig | None:
    """Return the CountryConfig for a given country code, or None."""
    return COUNTRY_DATA.get(country_code.upper())


def get_supported_countries(scraper_name: str) -> list[str]:
    """Return country codes that a given scraper supports."""
    return [
        code
        for code, cfg in COUNTRY_DATA.items()
        if scraper_name in cfg.supported_scrapers
    ]
