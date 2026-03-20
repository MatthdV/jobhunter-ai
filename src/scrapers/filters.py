"""ScraperFilters dataclass — controls post-parse filtering."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScraperFilters:
    """Parameters that control which jobs are kept after parsing.

    Attributes:
        remote_only: When True, only remote jobs are returned.
        contract_types: Accepted contract types (synced with profile.yaml).
        min_salary: Minimum annual salary in EUR. None = no filter.
        excluded_keywords: Jobs whose title or description contains any of these
            strings (case-insensitive) are silently dropped.
    """

    remote_only: bool = True
    contract_types: list[str] = field(
        default_factory=lambda: ["CDI", "Freelance", "Contract"]
    )
    min_salary: int | None = None
    excluded_keywords: list[str] = field(
        default_factory=lambda: ["junior", "stage", "internship", "stagiaire", "alternance"]
    )
