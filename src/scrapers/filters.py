"""ScraperFilters dataclass — controls post-parse filtering."""

from __future__ import annotations

from dataclasses import dataclass, field

WORK_MODES = frozenset({"remote", "hybrid", "on-site"})


@dataclass
class ScraperFilters:
    """Parameters that control which jobs are kept after parsing.

    Attributes:
        work_modes: Accepted work arrangements. Subset of {"remote", "hybrid", "on-site"}.
            Default ["remote"] preserves backward-compatible behaviour.
        contract_types: Accepted contract types.
        min_salary: Minimum annual salary in EUR. None = no filter.
        excluded_keywords: Jobs dropped when title/description contains any of these
            strings (case-insensitive).
        countries: ISO country codes.
        location: Location string passed to scraper URL.
    """

    work_modes: list[str] = field(default_factory=lambda: ["remote"])
    contract_types: list[str] = field(
        default_factory=lambda: ["CDI", "Freelance", "Contract"]
    )
    min_salary: int | None = None
    excluded_keywords: list[str] = field(
        default_factory=lambda: ["junior", "stage", "internship", "stagiaire", "alternance"]
    )
    countries: list[str] = field(default_factory=lambda: ["FR"])
    location: str = "remote"
    max_days_old: int | None = 30

    @property
    def remote_only(self) -> bool:
        """Backward compat — True iff only remote jobs accepted."""
        return self.work_modes == ["remote"]
