from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class JobListing:
    """Represents a job listing fetched and normalized from any job board."""

    title: str = ""
    company: str = ""
    location: str = ""
    remote_status: str = "On-site"
    salary: str = "Not specified"
    description: str = ""
    posting_date: str = ""
    url: str = ""
    source: str = "Unknown"

    # Optional tailored resume paths
    en_resume_pdf: str | None = None
    en_resume_docx: str | None = None
    en_cover_letter_docx: str | None = None
    fr_resume_pdf: str | None = None
    fr_resume_docx: str | None = None
    fr_cover_letter_docx: str | None = None

    # Scores
    fit_score: float | None = None
    interview_chance: float | None = None
    growth_potential: float | None = None
    salary_potential: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobListing:
        known_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


@dataclass
class ScoreBreakdown:
    """Detailed breakdown of fit score calculations for transparency and auditability."""

    title_match: float = 0.0
    experience_match: float = 0.0
    education_match: float = 0.0
    skills_match: float = 0.0
    company_size_match: float = 0.0
    salary_estimate: float = 0.0
    remote_preference: float = 0.0
    montreal_proximity: float = 0.0
    penalties: float = 0.0
    total_fit_score: float = 0.0
    interview_chance: float = 0.0
    growth_potential: float = 0.0
    salary_potential: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UserProfile:
    """User profile data for matching and tailoring."""

    name: str = "Your Name"
    location: str = "Your City, Region"
    email: str = "your.email@example.com"
    phone: str = ""
    github: str = ""
    near_downtown_montreal: bool = False
    experience_years: int = 0
    degree: str = "Add your education"
    experience_summary: str = ""
    preferred_company_size: str = "medium"
    wants_stable_companies: bool = True
    prefers_hybrid_or_downtown: bool = True
    avoid_heavy_coding_roles: bool = False
    career_growth: bool = True
    salary_focus: bool = True
    target_roles: list[str] = field(default_factory=list)
    priority_target_roles: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserProfile:
        known_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


@dataclass
class ScoringRulesConfig:
    """Configurable weights and penalties for the scoring engine."""

    title_match_weight: float = 30.0
    experience_match_weight: float = 15.0
    education_match_weight: float = 7.0
    skills_match_weight: float = 22.0
    salary_estimate_weight: float = 8.0
    remote_preference_weight: float = 6.0
    montreal_proximity_weight: float = 8.0
    commute_preference_weight: float = 4.0
    startup_penalty: float = 15.0
    senior_developer_penalty: float = 10.0
    seven_years_penalty: float = 15.0
    tiny_company_description_penalty: float = 12.0
    mid_level_numeral_penalty: float = 20.0
    management_penalty: float = 40.0
    entry_level_bonus: float = 8.0
    culture_bonus: float = 6.0
    established_bonus: float = 6.0
    entry_level_min_fit_score: float = 55.0
    max_score: float = 100.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScoringRulesConfig:
        known_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


@dataclass
class ApplicationRecord:
    """Database record for job application tracking."""

    id: int | None = None
    company: str = ""
    role: str = ""
    salary: str = ""
    fit_score: float | None = None
    application_date: str = ""
    status: str = "saved"
    interview_date: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApplicationRecord:
        known_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)
