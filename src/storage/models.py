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


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True)
    hashed_password = Column(String(255), nullable=False)
    profile_yaml = Column(Text, nullable=True)
    encrypted_keys = Column(Text, nullable=True)           # Fernet-encrypted JSON blob
    llm_provider = Column(String(50), default="anthropic")
    min_match_score = Column(Integer, default=80)
    max_apps_per_day = Column(Integer, default=10)
    active_sources = Column(String(200), default="wttj")   # comma-separated
    dry_run = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    jobs = relationship("Job", back_populates="user", cascade="all, delete-orphan")
    applications = relationship("Application", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User {self.email!r}>"


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("name", "user_id", name="uq_company_name_user"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    sector = Column(String(100))                   # fintech, saas, consulting
    size = Column(String(50))                      # e.g. "50-200"
    website = Column(String(500))
    linkedin_url = Column(String(500))
    notes = Column(Text)
    is_target = Column(Boolean, default=False)     # From profile.yaml target list
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
    jobs = relationship("Job", back_populates="company", cascade="all, delete-orphan")
    recruiters = relationship("Recruiter", back_populates="company", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Company {self.name!r}>"


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("url", "user_id", name="uq_job_url_user"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    url = Column(String(1000), nullable=False)
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
    user = relationship("User", back_populates="jobs")
    application = relationship("Application", back_populates="job", uselist=False)
    match_result = relationship("MatchResult", back_populates="job", uselist=False)

    def __repr__(self) -> str:
        return f"<Job {self.title!r} @ {self.source} score={self.match_score}>"


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("job_id", name="uq_application_job"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
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
    user = relationship("User", back_populates="applications")
    recruiter = relationship("Recruiter", back_populates="applications")

    def __repr__(self) -> str:
        return f"<Application job_id={self.job_id} status={self.status}>"


class Recruiter(Base):
    __tablename__ = "recruiters"
    __table_args__ = (UniqueConstraint("email", "user_id", name="uq_recruiter_email_user"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255))
    email = Column(String(255))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    score = Column(Float, nullable=False)
    reasoning = Column(Text, nullable=False)
    strengths_json = Column(Text, nullable=True)
    concerns_json = Column(Text, nullable=True)
    model_used = Column(String(100), nullable=False)
    scored_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job", back_populates="match_result")

    def __repr__(self) -> str:
        return f"<MatchResult job_id={self.job_id} score={self.score}>"
