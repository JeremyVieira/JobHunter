from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any
from unicodedata import normalize

try:
    from jobhunter.config.settings import USER_PROFILE
    from jobhunter.models import JobListing, UserProfile
except ModuleNotFoundError:  # pragma: no cover
    from config.settings import USER_PROFILE
    from models import JobListing, UserProfile


def _title_matches_target(title: str, profile: UserProfile | dict[str, Any] | None = None) -> bool:
    prof = profile or USER_PROFILE
    text = (title or "").lower()
    target_roles = [
        role.lower()
        for role in (
            prof.target_roles if isinstance(prof, UserProfile) else prof.get("target_roles", [])
        )
    ]
    if any(role in text for role in target_roles):
        return True
    return any(
        keyword in text
        for keyword in [
            "software engineer",
            "software developer",
            "developer",
            "programmer",
            "python",
            "automation",
            "machine learning",
            "ml engineer",
            "ai engineer",
            "data scientist",
            "data engineer",
            "devops",
            "cloud engineer",
            "site reliability",
            "business analyst",
            "systems analyst",
            "technical systems analyst",
            "product analyst",
            "data analyst",
            "business intelligence",
            "it business",
            "functional analyst",
            "product owner",
            "product manager",
            "integration analyst",
            "qa analyst",
            "quality assurance",
            "analyst",
            "analyste",
            "ingenieur",
            "developpeur",
        ]
    )


def _is_relevant_location(location: str) -> bool:
    text = normalize("NFKD", location or "").encode("ascii", "ignore").decode("ascii").lower()
    return (
        "montreal" in text
        or "remote" in text
        or "hybrid" in text
        or "quebec" in text
        or "qc" in text
    )


def _is_entry_level(job: dict[str, Any]) -> bool:
    title = (job.get("title") or "").lower()
    description = (job.get("description") or "").lower()
    title_signals = ("junior", "entry level", "associate", "new grad", "graduate", "coordinator")
    experience_signals = ("0 years", "1 year", "1-2 years", "0-2 years", "up to 2 years")
    return any(signal in title for signal in title_signals) or any(
        signal in description for signal in experience_signals
    )


class IJobPredicate(ABC):
    """Abstract predicate for job filtering."""

    @abstractmethod
    def evaluate(self, job: dict[str, Any]) -> bool:
        pass


class TargetRolePredicate(IJobPredicate):
    def __init__(self, profile: UserProfile | dict[str, Any] | None = None):
        self.profile = profile

    def evaluate(self, job: dict[str, Any]) -> bool:
        title = job.get("title", "") or ""
        return _title_matches_target(title, self.profile)


class LocationAndRemotePredicate(IJobPredicate):
    def evaluate(self, job: dict[str, Any]) -> bool:
        location = job.get("location", "") or ""
        description = (job.get("description", "") or "").lower()
        remote_status = (job.get("remote_status", "") or "").lower()
        if "remote" in remote_status or "remote" in description:
            return True
        return _is_relevant_location(location)


class MinFitScorePredicate(IJobPredicate):
    def __init__(self, min_score: float = 60.0, entry_level_min_score: float = 55.0):
        self.min_score = min_score
        self.entry_level_min_score = entry_level_min_score

    def evaluate(self, job: dict[str, Any]) -> bool:
        fit_score = float(job.get("fit_score", 0) or 0)
        required_score = self.entry_level_min_score if _is_entry_level(job) else self.min_score
        return fit_score >= required_score


class RoleBlacklistPredicate(IJobPredicate):
    DEFAULT_BLACKLIST = (
        "senior",
        "sr ",
        "sr.",
        "lead",
        "principal",
        "staff",
        "manager",
        "director",
        "head of",
        "vice president",
        "vp ",
        "gestionnaire",
        "directeur",
        "chef de",
        "senior software engineer",
        "principal software engineer",
        "lead software engineer",
        "staff software engineer",
        "project coordinator",
        "technical coordinator",
    )

    def __init__(self, blacklist: Iterable[str] | None = None):
        self.blacklist = tuple(blacklist) if blacklist is not None else self.DEFAULT_BLACKLIST

    def evaluate(self, job: dict[str, Any]) -> bool:
        title = (job.get("title", "") or "").lower()
        entry_level_title = any(signal in title for signal in ("junior", "associate", "new grad", "graduate", "engineer i"))
        blocked_terms = tuple(
            term
            for term in self.blacklist
            if not (entry_level_title and term == "full stack developer")
        )
        return not any(term in title for term in blocked_terms)


class CompanyRedFlagPredicate(IJobPredicate):
    """Screens out third-party staffing/recruitment agency postings and tiny/stealth companies."""

    STAFFING_AGENCY_NAMES = (
        "hunter bond",
        "mthree",
        "robert half",
        "michael page",
        "randstad",
        "adecco",
        "manpower",
        "insight global",
        "akkodis",
        "teksystems",
        "robert walters",
        "hays",
        "lhh",
        "aerotek",
        "kelly services",
        "vaco",
        "modis",
        "apex systems",
        "cybercoders",
        "motion recruitment",
    )
    AGENCY_DESCRIPTION_PHRASES = (
        "on behalf of our client",
        "on behalf of a client",
        "confidential client",
        "our client is seeking",
        "our client is looking",
        "undisclosed client",
        "one of our clients",
    )
    TINY_OR_STEALTH_SIGNALS = (
        "1-10 employees",
        "2-10 employees",
        "11-50 employees",
        "stealth mode",
        "stealth startup",
        "pre-seed",
        "pre seed",
        "unpaid",
        "equity only",
    )

    def evaluate(self, job: dict[str, Any]) -> bool:
        company = (job.get("company", "") or "").lower()
        description = (job.get("description", "") or "").lower()

        if any(agency in company for agency in self.STAFFING_AGENCY_NAMES):
            return False
        if any(phrase in description for phrase in self.AGENCY_DESCRIPTION_PHRASES):
            return False
        if any(signal in description or signal in company for signal in self.TINY_OR_STEALTH_SIGNALS):
            return False
        return True


class FilterChain:
    """Chain of Responsibility pipeline to filter jobs through sequential predicates."""

    def __init__(self, predicates: list[IJobPredicate] | None = None):
        self.predicates: list[IJobPredicate] = predicates or [
            TargetRolePredicate(),
            LocationAndRemotePredicate(),
            MinFitScorePredicate(60.0, 55.0),
            RoleBlacklistPredicate(),
            CompanyRedFlagPredicate(),
        ]

    def add_predicate(self, predicate: IJobPredicate) -> FilterChain:
        self.predicates.append(predicate)
        return self

    def apply(self, jobs: Iterable[dict[str, Any] | JobListing]) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for job in jobs:
            job_dict = job.to_dict() if isinstance(job, JobListing) else dict(job)
            if all(predicate.evaluate(job_dict) for predicate in self.predicates):
                filtered.append(job_dict)
        return sorted(filtered, key=lambda item: float(item.get("fit_score", 0) or 0), reverse=True)


# Default chain singleton
_default_filter_chain = FilterChain()


def filter_jobs(jobs: Iterable[dict | JobListing]) -> list[dict]:
    return _default_filter_chain.apply(jobs)
