"""SQLAlchemy ORM models for JobHunter AI."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class JobStatus(StrEnum):
    NEW = "new"               # Just scraped, not yet scored
    MATCHED = "matched"       # Score >= min_match_score, awaiting review
    SKIPPED = "skipped"       # Score too low or manually dismissed
    PENDING = "pending"       # Human approved, CV/letter being generated
    APPLIED = "applied"       # Application submitted
    REJECTED = "rejected"     # Recruiter replied with rejection


class ApplicationStatus(StrEnum):
    DRAFT = "draft"                       # CV/letter generated, not yet validated
    PENDING_VALIDATION = "pending_validation"  # Awaiting human approval
    SUBMITTED = "submitted"               # Sent to recruiter
    REPLIED = "replied"                   # Recruiter replied
    INTERVIEW = "interview"               # Interview scheduled
    REJECTED = "rejected"                 # Rejected at application stage
    OFFER = "offer"                       # Offer received


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    sector = Column(String(100))                   # fintech, saas, consulting
    size = Column(String(50))                      # e.g. "50-200"
    website = Column(String(500))
    linkedin_url = Column(String(500))
    notes = Column(Text)
    is_target = Column(Boolean, default=False)     # From profile.yaml target list
    created_at = Column(DateTime, default=datetime.utcnow)

    jobs = relationship("Job", back_populates="company", cascade="all, delete-orphan")
    recruiters = relationship("Recruiter", back_populates="company", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Company {self.name!r}>"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    url = Column(String(1000), nullable=False, unique=True)
    source = Column(String(50), nullable=False)    # linkedin | indeed | wttj
    description = Column(Text)
    salary_raw = Column(String(200))               # Original string from listing
    salary_min = Column(Integer, nullable=True)    # Parsed, in EUR/year
    salary_max = Column(Integer, nullable=True)    # Parsed, in EUR/year
    is_remote = Column(Boolean, default=False)
    location = Column(String(200))
    contract_type = Column(String(50))             # CDI, Freelance, Contract…
    match_score = Column(Float, nullable=True)     # 0–100, set by Scorer
    match_reasoning = Column(Text, nullable=True)  # Claude explanation
    status: Column[str] = Column(SAEnum(JobStatus), default=JobStatus.NEW, nullable=False)
    scraped_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="jobs")
    application = relationship("Application", back_populates="job", uselist=False)
    match_result = relationship("MatchResult", back_populates="job", uselist=False)

    def __repr__(self) -> str:
        return f"<Job {self.title!r} @ {self.source} score={self.match_score}>"


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("job_id", name="uq_application_job"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    cv_path = Column(String(500))                  # Path to generated PDF
    cover_letter = Column(Text)                    # Generated text
    status: Column[str] = Column(
        SAEnum(ApplicationStatus), default=ApplicationStatus.DRAFT, nullable=False
    )
    submitted_at = Column(DateTime, nullable=True)
    recruiter_id = Column(Integer, ForeignKey("recruiters.id"), nullable=True)
    gmail_thread_id = Column(String(200), nullable=True)  # For tracking replies
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = relationship("Job", back_populates="application")
    recruiter = relationship("Recruiter", back_populates="applications")

    def __repr__(self) -> str:
        return f"<Application job_id={self.job_id} status={self.status}>"


class Recruiter(Base):
    __tablename__ = "recruiters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255))
    email = Column(String(255), unique=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    gmail_thread_id = Column(String(200), nullable=True)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="recruiters")
    applications = relationship("Application", back_populates="recruiter")

    def __repr__(self) -> str:
        return f"<Recruiter {self.name!r} <{self.email}>>"


class MatchResult(Base):
    __tablename__ = "match_results"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    job_id         = Column(Integer, ForeignKey("jobs.id"), unique=True, nullable=False)
    score          = Column(Float, nullable=False)
    reasoning      = Column(Text, nullable=False)
    strengths_json = Column(Text, nullable=True)
    concerns_json  = Column(Text, nullable=True)
    model_used     = Column(String(100), nullable=False)
    scored_at      = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job", back_populates="match_result")

    def __repr__(self) -> str:
        return f"<MatchResult job_id={self.job_id} score={self.score}>"
