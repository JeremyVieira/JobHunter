from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

try:
    from jobhunter.config.settings import USER_PROFILE
    from jobhunter.matching.levels import is_entry_level
    from jobhunter.models import JobListing, UserProfile
    from jobhunter.textutils import contains_any_term, normalize_text
except ModuleNotFoundError:  # pragma: no cover
    from config.settings import USER_PROFILE
    from matching.levels import is_entry_level
    from models import JobListing, UserProfile
    from textutils import contains_any_term, normalize_text


def _title_matches_target(title: str, profile: UserProfile | dict[str, Any] | None = None) -> bool:
    prof = profile or USER_PROFILE
    text = normalize_text(title)
    target_roles = [
        role
        for role in (
            prof.target_roles if isinstance(prof, UserProfile) else prof.get("target_roles", [])
        )
        if normalize_text(role)
    ]
    if contains_any_term(text, target_roles):
        return True
    return contains_any_term(
        text,
        [
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
        ],
    )


# Towns that make up Greater Montreal. Postings often list the borough or suburb
# ("Saint-Laurent, QC") instead of "Montreal".
MONTREAL_AREA_TERMS = (
    "montreal", "laval", "longueuil", "brossard", "west island", "south shore",
    "north shore", "saint laurent", "ville saint laurent", "dorval", "pointe claire",
    "kirkland", "dollard des ormeaux", "boucherville", "saint lambert", "westmount",
    "town of mount royal", "anjou", "lasalle", "verdun", "terrebonne", "blainville",
    "repentigny", "vaudreuil",
)

UNKNOWN_LOCATIONS = frozenset({"", "unknown", "n/a", "na", "none", "nan", "not specified", "null"})

# Markers that a "remote" job is only open to residents of another region.
REMOTE_REGION_MARKERS = (
    "us", "usa", "united states", "uk", "united kingdom", "europe", "emea", "apac",
    "latam", "india", "germany", "spain", "poland", "australia", "brazil", "mexico",
    "philippines", "singapore", "ireland", "netherlands",
)
REMOTE_REGION_PHRASES = (
    "us only", "u s only", "usa only", "united states only", "us based", "u s based",
    "must be located in the us", "must be located in the u s",
    "must be located in the united states", "must reside in the us",
    "must reside in the united states", "must live in the us",
    "authorized to work in the us", "authorized to work in the u s",
    "authorized to work in the united states", "eligible to work in the us",
    "eligible to work in the united states", "us work authorization",
    "u s work authorization", "us citizens only", "u s citizens only", "us citizen",
    "within the united states", "residents of the united states",
    "based in the united states", "open to candidates in the us",
    "uk based", "must be based in the uk", "eu based", "right to work in the uk",
)
OPEN_REMOTE_MARKERS = ("canada", "canadian", "worldwide", "anywhere", "global", "north america")


def _is_relevant_location(location: str) -> bool:
    text = normalize_text(location)
    return contains_any_term(text, MONTREAL_AREA_TERMS) or contains_any_term(text, ("remote",))


def is_montreal_area_or_remote(location: str) -> bool:
    """Return whether a posting is local to Greater Montreal or generically remote."""
    return _is_relevant_location(location)


def location_is_unknown(location: str | None) -> bool:
    return normalize_text(location or "") in UNKNOWN_LOCATIONS


def remote_region_restricted(job: dict[str, Any]) -> bool:
    """True for "remote" postings that are only open to another country/region.

    A generic "Remote" label says nothing about where you may live. We reject only
    on explicit evidence (a region in the location, or work-authorization wording in
    the description) and never when the posting also mentions Canada or "worldwide".
    """
    location = normalize_text(job.get("location") or "")
    description = normalize_text(str(job.get("description") or "")[:6000])
    if contains_any_term(location, OPEN_REMOTE_MARKERS) or contains_any_term(
        description, OPEN_REMOTE_MARKERS
    ):
        return False
    if contains_any_term(location, REMOTE_REGION_MARKERS):
        return True
    return contains_any_term(description, REMOTE_REGION_PHRASES)


# Backwards-compatible alias; the implementation now lives in matching.levels.
_is_entry_level = is_entry_level


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
        if location_is_unknown(location):
            # No location at all: only keep the posting if its own text places it in
            # Greater Montreal. (A missing location must never be read as "Remote".)
            text = normalize_text(f"{job.get('title', '')} {str(job.get('description') or '')[:2000]}")
            return contains_any_term(text, MONTREAL_AREA_TERMS)
        # A remote label must not override an explicit non-local office
        # location (for example, a Seattle role whose description mentions
        # occasional remote work). Only generic remote locations are accepted.
        if not is_montreal_area_or_remote(location):
            return False
        local = contains_any_term(normalize_text(location), MONTREAL_AREA_TERMS)
        if local:
            return True
        # Generic remote: reject when it is explicitly limited to another region.
        return not remote_region_restricted(job)


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
        "sr",
        "lead",
        "leader",
        "principal",
        "staff",
        "manager",
        "director",
        "head of",
        "vice president",
        "vp",
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
        title = normalize_text(job.get("title", "") or "")
        entry_level_title = contains_any_term(
            title, ("junior", "associate", "new grad", "graduate", "engineer i")
        )
        # "Associate Product Manager" programs are entry-level despite "manager".
        apm_title = contains_any_term(title, ("associate product manager", "apm"))
        blocked_terms = tuple(
            term
            for term in self.blacklist
            if not (entry_level_title and term == "full stack developer")
            and not (apm_title and normalize_text(term) == "manager")
        )
        return not contains_any_term(title, blocked_terms)


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
        company = normalize_text(job.get("company", "") or "")
        description = normalize_text(job.get("description", "") or "")

        if contains_any_term(company, self.STAFFING_AGENCY_NAMES):
            return False
        if contains_any_term(description, self.AGENCY_DESCRIPTION_PHRASES):
            return False
        if contains_any_term(description, self.TINY_OR_STEALTH_SIGNALS) or contains_any_term(
            company, self.TINY_OR_STEALTH_SIGNALS
        ):
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
