"""Pydantic response schemas for the JobHunter AI API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sector: str | None = None
    size: str | None = None
    website: str | None = None
    is_target: bool = False


class RecruiterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None = None
    email: str | None = None


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    cv_path: str | None = None
    cover_letter: str | None = None
    submitted_at: datetime | None = None
    gmail_thread_id: str | None = None
    notes: str | None = None
    created_at: datetime


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    url: str
    source: str
    status: str
    match_score: float | None = None
    match_reasoning: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_raw: str | None = None
    is_remote: bool = False
    location: str | None = None
    contract_type: str | None = None
    scraped_at: datetime
    company: CompanyOut | None = None
    application: ApplicationOut | None = None


class JobListOut(BaseModel):
    items: list[JobOut]
    total: int
    limit: int
    offset: int


class JobPatchIn(BaseModel):
    status: str | None = None


class StatsToday(BaseModel):
    scanned: int
    matched: int
    applied: int
    replied: int


class StatsTotal(BaseModel):
    scanned: int
    matched: int
    applied: int
    replied: int


class StatsOut(BaseModel):
    today: StatsToday
    total: StatsTotal
    pipeline_status: dict[str, dict]


class PipelineStartResponse(BaseModel):
    status: str
    phase: str
    message: str


class PipelineStatusResponse(BaseModel):
    phases: dict[str, dict]
