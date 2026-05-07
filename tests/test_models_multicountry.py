"""Tests for multi-country Job model fields."""

from src.storage.models import Job


class TestJobMultiCountryFields:
    def test_country_code_field_exists(self) -> None:
        """Job model has country_code column."""
        job = Job(title="Test", url="https://example.com", source="test", country_code="FR")
        assert job.country_code == "FR"

    def test_country_code_accepts_any_code(self) -> None:
        job = Job(title="Test", url="https://example.com", source="test", country_code="US")
        assert job.country_code == "US"

    def test_salary_currency_field(self) -> None:
        job = Job(title="Test", url="https://example.com", source="test", salary_currency="USD")
        assert job.salary_currency == "USD"

    def test_salary_normalized_fields(self) -> None:
        job = Job(
            title="Test",
            url="https://example.com",
            source="test",
            salary_normalized_min=80000,
            salary_normalized_max=120000,
        )
        assert job.salary_normalized_min == 80000
        assert job.salary_normalized_max == 120000

    def test_salary_normalized_defaults_to_none(self) -> None:
        job = Job(title="Test", url="https://example.com", source="test")
        assert job.salary_normalized_min is None
        assert job.salary_normalized_max is None
        assert job.salary_currency is None

    def test_country_code_column_has_default(self) -> None:
        """The DB column default should be 'FR'."""
        col = Job.__table__.columns["country_code"]
        assert col.default.arg == "FR"
