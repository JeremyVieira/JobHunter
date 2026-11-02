from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable
from functools import lru_cache
from typing import Any

try:
    from jobhunter.config.settings import SCORING_RULES, USER_PROFILE
    from jobhunter.matching.levels import is_entry_level
    from jobhunter.matching.requirements import (
        analyze_posting,
        candidate_inventory,
        compare_requirements,
        extract_required_years,
        skill_score_from_match,
    )
    from jobhunter.matching.skills import expand_inventory, get_matcher
    from jobhunter.models import JobListing, ScoringRulesConfig, UserProfile
    from jobhunter.textutils import (
        contains_any_term,
        days_since,
        normalize_text,
    )
except ModuleNotFoundError:  # pragma: no cover
    from config.settings import SCORING_RULES, USER_PROFILE
    from matching.levels import is_entry_level
    from matching.requirements import (
        analyze_posting,
        candidate_inventory,
        compare_requirements,
        extract_required_years,
        skill_score_from_match,
    )
    from matching.skills import expand_inventory, get_matcher
    from models import JobListing, ScoringRulesConfig, UserProfile
    from textutils import contains_any_term, days_since, normalize_text

# Relative weights used when a config does not override them. Title, experience and
# requirement coverage separate good from bad matches; the remaining dimensions are
# nearly constant across postings, so they carry little weight.
DEFAULT_SCORING_WEIGHTS = {
    "title_match_weight": 24.0,
    "experience_match_weight": 14.0,
    "education_match_weight": 3.0,
    "skills_match_weight": 30.0,
    "salary_estimate_weight": 4.0,
    "remote_preference_weight": 3.0,
    "montreal_proximity_weight": 8.0,
    "commute_preference_weight": 2.0,
}


# --- Role-tier vocabulary shared by title scoring, penalties, and the hard filter ---
# "Senior"-type ICs are penalized heavily but still scored (a strong ML/automation
# match can still surface). Management/executive titles are hard-excluded outright:
# no amount of keyword overlap makes a Director/VP/Manager posting a fit for a new
# grad targeting IC engineering roles. All checks are whole-word matches.
SENIOR_TITLE_TERMS = (
    "senior",
    "sr",
    "lead",
    "leader",
    "principal",
    "staff",
    "expert",
    "intermediate",
    "mid level",
    "advanced",
)

MANAGEMENT_TITLE_TERMS = (
    "manager",
    "director",
    "vp",
    "vice president",
    "head of",
    "chief",
    "president",
    "executive",
    "general manager",
    "gestionnaire",
    "directeur",
    "directrice",
)

# "Associate Product Manager" programs are entry-level despite the word "manager".
ENTRY_MANAGER_EXCEPTIONS = ("associate product manager", "apm")

# Numbered-level title suffixes (Software Engineer II, Developer 2, Analyst III...).
# "I" / "1" is the entry-level tier and is left alone; II and above typically mean
# 2+ years of prior experience expected.
MID_PLUS_LEVEL_TOKENS = {"ii", "iii", "iv", "v", "2", "3", "4", "5"}


def _has_mid_plus_level_suffix(normalized_text: str) -> bool:
    tokens = normalized_text.split()
    return bool(tokens) and tokens[-1] in MID_PLUS_LEVEL_TOKENS


def _is_management_title(normalized_title: str) -> bool:
    if contains_any_term(normalized_title, ENTRY_MANAGER_EXCEPTIONS):
        return False
    return contains_any_term(normalized_title, MANAGEMENT_TITLE_TERMS)


def _profile_get(profile: UserProfile | dict[str, Any] | None, name: str, default: Any) -> Any:
    prof = profile if profile is not None else USER_PROFILE
    if isinstance(prof, UserProfile):
        return getattr(prof, name, default)
    return prof.get(name, default)


def parse_salary(value: str) -> float:
    if not value or value.lower() in {"not disclosed", "n/a", "unknown"}:
        return 85000.0
    matches = re.findall(r"(?<![a-z0-9])(\d[\d,]*(?:\.\d+)?)\s*([kmb]?)", value, re.I)
    if not matches:
        return 85000.0

    multipliers = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
    values = [float(number.replace(",", "")) * multipliers[suffix.lower()] for number, suffix in matches[:2]]
    return sum(values) / len(values)


def entry_level_salary_benchmark(job_title: str) -> dict[str, int | str]:
    """Return a conservative annual CAD benchmark for an entry-level role family."""
    title = normalize_text(job_title)
    benchmarks = [
        (
            (
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
            ),
            (65000, 85000, "Software engineering, automation, and ML"),
        ),
        (
            ("solutions engineer", "sales engineer", "pre sales", "presales", "customer success engineer"),
            (70000, 90000, "Solutions, pre-sales, and customer engineering"),
        ),
        (
            ("product", "revenue operations", "business operations"),
            (65000, 85000, "Product and business operations"),
        ),
        (
            ("consultant", "implementation", "systems analyst", "business analyst", "data analyst", "integration"),
            (60000, 80000, "Analysis, implementation, and consulting"),
        ),
        (
            ("qa", "quality assurance", "test", "support", "coordinator"),
            (55000, 75000, "Support, QA, and coordination"),
        ),
    ]
    for terms, (minimum, maximum, family) in benchmarks:
        if any(term in title for term in terms):
            return {"minimum": minimum, "maximum": maximum, "family": family}
    return {"minimum": 60000, "maximum": 80000, "family": "Technical and business operations"}


def salary_comparison(salary: str, job_title: str) -> dict[str, int | str | None]:
    """Compare a disclosed salary with the matching entry-level benchmark."""
    benchmark = entry_level_salary_benchmark(job_title)
    minimum = int(benchmark["minimum"])
    maximum = int(benchmark["maximum"])
    if not salary or salary.lower() in {"not disclosed", "n/a", "unknown"}:
        return {**benchmark, "listed_midpoint": None, "comparison": "Not disclosed"}

    listed_midpoint = parse_salary(salary)
    if listed_midpoint < minimum:
        comparison = "Below typical range"
    elif listed_midpoint > maximum:
        comparison = "Above typical range"
    else:
        comparison = "Within typical range"
    return {**benchmark, "listed_midpoint": int(listed_midpoint), "comparison": comparison}


# Self-described early-stage/tiny-team language. Kept in sync with
# scraping.TINY_STARTUP_SIGNAL_TERMS.
TINY_STARTUP_SIGNAL_TERMS = (
    "pre-seed",
    "seed stage",
    "seed-stage",
    "early stage startup",
    "early-stage startup",
    "small but mighty",
    "wear many hats",
    "founding engineer",
    "founding team",
    "series a startup",
    "bootstrapped",
    "small scrappy team",
    "fast paced startup environment",
    "we're a small team",
    "we are a small team",
)


def company_size_penalty(
    job: dict[str, Any] | str,
    company_name_penalty: float = 15.0,
    description_penalty: float = 12.0,
) -> float:
    """Penalty for companies/postings that read as tiny or very early-stage.

    Accepts either a full job dict (checks company name + description) or a bare
    company-name string for backwards compatibility. This is a best-effort proxy -
    free scraping APIs don't expose real headcount - so it only catches companies
    that self-identify as small/early-stage in their name or job description.
    """
    if isinstance(job, str):
        job = {"company": job, "description": ""}
    name = normalize_text(job.get("company", ""))
    description = normalize_text(job.get("description", ""))
    if contains_any_term(name, ("startup", "labs", "forge", "ventures")):
        return company_name_penalty
    if contains_any_term(description, TINY_STARTUP_SIGNAL_TERMS):
        return description_penalty
    return 0.0


def is_clearly_mismatched(job: dict[str, Any]) -> bool:
    """Hard filter for postings that are structurally the wrong track for a new-grad
    IC engineer, regardless of how well the description's keywords overlap.

    Management/executive titles (Manager, Director, VP, Head of, Chief, President,
    Executive) are dropped outright rather than merely down-scored. Entry-level
    "Associate Product Manager" programs are the one exception.
    """
    return _is_management_title(normalize_text(job.get("title", "")))


class IScoringDimension(ABC):
    """Abstract strategy interface for calculating an individual job score dimension."""

    @abstractmethod
    def evaluate(self, job: dict[str, Any], profile: UserProfile | dict[str, Any]) -> float:
        pass


class TitleMatchDimension(IScoringDimension):
    def evaluate(self, job: dict[str, Any], profile: UserProfile | dict[str, Any]) -> float:
        title = job.get("title", "")
        return float(title_match_score(title, profile=profile))


class ExperienceMatchDimension(IScoringDimension):
    def evaluate(self, job: dict[str, Any], profile: UserProfile | dict[str, Any]) -> float:
        description = job.get("description", "")
        years = _profile_get(profile, "experience_years", 0) or 0
        return float(experience_match_score(description, candidate_years=int(years)))


class EducationMatchDimension(IScoringDimension):
    def evaluate(self, job: dict[str, Any], profile: UserProfile | dict[str, Any]) -> float:
        description = job.get("description", "")
        return float(education_match_score(description))


@lru_cache(maxsize=16)
def _cached_inventory(keywords: tuple[str, ...], resume_skills: tuple[str, ...]) -> frozenset[str]:
    matcher = get_matcher(keywords)
    inventory = candidate_inventory(keywords, None, matcher)
    inventory |= expand_inventory(resume_skills)
    return frozenset(inventory)


def _inventory_for(profile: UserProfile | dict[str, Any] | None) -> tuple[frozenset[str], tuple[str, ...]]:
    keywords = tuple(_profile_get(profile, "keywords", []) or [])
    resume_skills = tuple(_profile_get(profile, "resume_skills", []) or [])
    return _cached_inventory(keywords, resume_skills), keywords


class SkillMatchDimension(IScoringDimension):
    """Scores how much of what the posting asks for the candidate actually has."""

    def details(self, job: dict[str, Any], profile: UserProfile | dict[str, Any]):
        inventory, keywords = _inventory_for(profile)
        matcher = get_matcher(keywords)
        requirements = analyze_posting(job.get("title", ""), job.get("description", ""), matcher)
        match = compare_requirements(requirements, set(inventory))
        return skill_score_from_match(match), match, requirements, matcher

    def evaluate(self, job: dict[str, Any], profile: UserProfile | dict[str, Any]) -> float:
        return float(self.details(job, profile)[0])


class SalaryMatchDimension(IScoringDimension):
    def evaluate(self, job: dict[str, Any], profile: UserProfile | dict[str, Any]) -> float:
        salary_raw = job.get("salary", "Not disclosed")
        salary_value = parse_salary(salary_raw)
        return float(parse_salary_score(salary_raw, salary_value))


class RemotePreferenceDimension(IScoringDimension):
    def evaluate(self, job: dict[str, Any], profile: UserProfile | dict[str, Any]) -> float:
        desc = normalize_text(job.get("description", ""))
        remote_st = normalize_text(job.get("remote_status", ""))
        return 95.0 if (contains_any_term(remote_st, ("remote",)) or contains_any_term(desc, ("remote",))) else 80.0


class MontrealProximityDimension(IScoringDimension):
    def evaluate(self, job: dict[str, Any], profile: UserProfile | dict[str, Any]) -> float:
        loc = normalize_text(job.get("location", ""))
        return 95.0 if contains_any_term(loc, ["montreal", "quebec", "qc"]) else 75.0


class CommutePreferenceDimension(IScoringDimension):
    FAR_COMMUTE_TERMS = (
        "longueuil", "south shore", "north shore", "laval", "west island",
        "40 min", "45 min", "50 min", "60 min",
        "commute 40", "commute 45", "commute 50", "commute 60",
    )
    TRANSIT_TERMS = (
        "metro", "subway", "station", "downtown", "plateau", "verdun", "rosemont",
        "mont royal", "bonaventure", "public transit", "transit", "near metro",
        "close to metro", "accessible by metro", "easy commute", "30 min", "25 min", "20 min",
    )

    def evaluate(self, job: dict[str, Any], profile: UserProfile | dict[str, Any]) -> float:
        loc = normalize_text(job.get("location", ""))
        desc = normalize_text(job.get("description", ""))

        if contains_any_term(loc, self.FAR_COMMUTE_TERMS) or contains_any_term(desc, self.FAR_COMMUTE_TERMS):
            return 72.0
        if contains_any_term(loc, self.TRANSIT_TERMS) or contains_any_term(desc, self.TRANSIT_TERMS):
            return 92.0
        if contains_any_term(loc, ["montreal", "quebec", "qc"]):
            return 82.0
        if contains_any_term(loc, ["remote", "hybrid"]):
            return 88.0
        return 70.0


class CompositeScorer:
    """Composite scoring engine applying dimension strategies, weights, and penalty rules."""

    def __init__(
        self,
        config: ScoringRulesConfig | dict[str, Any] | None = None,
        profile: UserProfile | dict[str, Any] | None = None,
        feedback: Any | None = None,
    ):
        self.config = config or SCORING_RULES
        self.profile = profile or USER_PROFILE
        # Optional preference model (see scoring.feedback.FeedbackModel)
        self.feedback = feedback

        self.title_dim = TitleMatchDimension()
        self.exp_dim = ExperienceMatchDimension()
        self.edu_dim = EducationMatchDimension()
        self.skill_dim = SkillMatchDimension()
        self.salary_dim = SalaryMatchDimension()
        self.remote_dim = RemotePreferenceDimension()
        self.prox_dim = MontrealProximityDimension()
        self.commute_dim = CommutePreferenceDimension()

    def _get_config_val(self, key: str, default: float) -> float:
        if isinstance(self.config, dict):
            return float(self.config.get(key, default))
        return float(getattr(self.config, key, default))

    def calculate_penalties(self, job: dict[str, Any]) -> float:
        title = normalize_text(job.get("title", ""))
        penalty = 0.0

        penalty += company_size_penalty(
            job,
            company_name_penalty=self._get_config_val("startup_penalty", 15.0),
            description_penalty=self._get_config_val("tiny_company_description_penalty", 12.0),
        )

        # Senior/staff-tier ICs: heavily penalized but still scoreable, since a strong
        # ML/automation posting might still be worth seeing.
        if contains_any_term(title, SENIOR_TITLE_TERMS):
            penalty += self._get_config_val("senior_developer_penalty", 25.0)

        # Numbered-level suffix (Engineer II, Developer 2...): same idea as the
        # senior-term penalty above, for titles that signal seniority via a level number.
        if _has_mid_plus_level_suffix(title):
            penalty += self._get_config_val("mid_level_numeral_penalty", 20.0)

        # Management/executive titles: is_clearly_mismatched() drops these from results
        # entirely in score_jobs(); this is a backstop for pipelines that skip filtering.
        if _is_management_title(title):
            penalty += self._get_config_val("management_penalty", 40.0)

        years = extract_required_years(job.get("description", ""))
        if years is not None and years >= 7:
            penalty += self._get_config_val("seven_years_penalty", 20.0)

        return penalty

    def calculate_entry_level_bonus(self, job: dict[str, Any]) -> float:
        if is_entry_level(job):
            return self._get_config_val("entry_level_bonus", 8.0)
        return 0.0

    def calculate_culture_bonus(self, job: dict[str, Any]) -> float:
        description = normalize_text(job.get("description", ""))
        culture_signals = (
            "great culture",
            "award winning culture",
            "award winning workplace",
            "work life balance",
            "employee wellness",
            "inclusive culture",
            "collaborative culture",
            "supportive team",
            "mentorship program",
            "learning and development",
            "career growth opportunities",
            "best places to work",
            "great place to work",
            "highly rated on glassdoor",
            "top employer",
        )
        if contains_any_term(description, culture_signals):
            return self._get_config_val("culture_bonus", 6.0)
        return 0.0

    # Well-known, established employers (large, stable, publicly recognizable).
    # Not exhaustive - absence just means no bonus, it does not penalize the company.
    # Matched as whole words, so "ey" no longer matches Honeywell or Disney.
    KNOWN_ESTABLISHED_COMPANIES = (
        "rbc", "royal bank", "td bank", "td canada trust", "scotiabank", "bmo",
        "bank of montreal", "national bank", "desjardins", "cmls", "coveo", "sun life",
        "manulife", "intact", "cgi", "cae", "bombardier", "air canada", "hydro quebec",
        "loto quebec", "caisse de depot", "bell canada", "rogers", "telus", "videotron",
        "shopify", "lightspeed", "nuvia", "nuvei", "ubisoft", "ericsson", "ibm",
        "microsoft", "google", "amazon", "meta", "salesforce", "sap", "oracle", "cisco",
        "deloitte", "pwc", "ey", "kpmg", "accenture", "loblaw", "metro inc",
        "canadian tire",
    )

    def calculate_established_bonus(self, job: dict[str, Any]) -> float:
        company = normalize_text(job.get("company", ""))
        description = normalize_text(job.get("description", ""))

        if contains_any_term(company, self.KNOWN_ESTABLISHED_COMPANIES):
            return self._get_config_val("established_bonus", 6.0)

        established_signals = (
            "fortune 500",
            "publicly traded",
            "nasdaq",
            "tsx",
            "founded in 19",
            "since 19",
            "industry leader",
            "global leader",
            "market leader",
            "employees worldwide",
            "offices worldwide",
            "offices around the world",
            "multinational",
        )
        if contains_any_term(description, established_signals):
            return self._get_config_val("established_bonus", 6.0)
        return 0.0

    def calculate_freshness_adjustment(self, job: dict[str, Any]) -> float:
        """Small bonus for fresh postings, small penalty for likely-stale/ghost ones."""
        age = days_since(str(job.get("posting_date") or ""))
        if age is None or age < 0:
            return 0.0
        bonus = self._get_config_val("freshness_bonus", 3.0)
        if age <= 3:
            return bonus
        if age <= 7:
            return bonus / 2
        if age > 45:
            return -self._get_config_val("stale_penalty", 3.0)
        return 0.0

    def score_job(self, job: dict[str, Any] | JobListing) -> dict[str, Any]:
        job_dict = job.to_dict() if isinstance(job, JobListing) else dict(job)

        title_score = self.title_dim.evaluate(job_dict, self.profile)
        experience_score = self.exp_dim.evaluate(job_dict, self.profile)
        education_score = self.edu_dim.evaluate(job_dict, self.profile)
        skill_score, skill_match, requirements, matcher = self.skill_dim.details(job_dict, self.profile)
        salary_score = self.salary_dim.evaluate(job_dict, self.profile)
        remote_score = self.remote_dim.evaluate(job_dict, self.profile)
        prox_score = self.prox_dim.evaluate(job_dict, self.profile)
        commute_score = self.commute_dim.evaluate(job_dict, self.profile)

        weighted_dimensions = (
            (title_score, "title_match_weight"),
            (experience_score, "experience_match_weight"),
            (education_score, "education_match_weight"),
            (skill_score, "skills_match_weight"),
            (salary_score, "salary_estimate_weight"),
            (remote_score, "remote_preference_weight"),
            (prox_score, "montreal_proximity_weight"),
            (commute_score, "commute_preference_weight"),
        )
        total_weight = sum(
            self._get_config_val(name, DEFAULT_SCORING_WEIGHTS[name]) for _, name in weighted_dimensions
        )
        weighted_score = (
            sum(
                score * self._get_config_val(name, DEFAULT_SCORING_WEIGHTS[name])
                for score, name in weighted_dimensions
            )
            / total_weight
            if total_weight > 0
            else 0.0
        )

        penalties = self.calculate_penalties(job_dict)
        entry_level_bonus = self.calculate_entry_level_bonus(job_dict)
        culture_bonus = self.calculate_culture_bonus(job_dict)
        established_bonus = self.calculate_established_bonus(job_dict)
        freshness_adjustment = self.calculate_freshness_adjustment(job_dict)

        # Hard-stack gaps (Java/C#/... named prominently and absent from the candidate's
        # skills) cost points instead of silently scoring as "partial coverage".
        core_gap_penalty = min(
            self._get_config_val("core_gap_penalty_cap", 20.0),
            self._get_config_val("core_gap_penalty", 8.0) * len(skill_match.core_gaps),
        )

        languages = {str(lang).lower() for lang in (_profile_get(self.profile, "languages", ["en"]) or ["en"])}
        bilingual_bonus = 0.0
        language_penalty = 0.0
        if requirements.bilingual and {"en", "fr"} <= languages:
            bilingual_bonus = self._get_config_val("bilingual_bonus", 4.0)
        if requirements.language == "fr" and "fr" not in languages:
            language_penalty = self._get_config_val("language_mismatch_penalty", 15.0)

        feedback_adjustment = float(self.feedback.adjust(job_dict)) if self.feedback is not None else 0.0

        total = (
            weighted_score
            + entry_level_bonus
            + culture_bonus
            + established_bonus
            + bilingual_bonus
            + freshness_adjustment
            + feedback_adjustment
            - penalties
            - core_gap_penalty
            - language_penalty
        )

        max_score = self._get_config_val("max_score", 100.0)
        fit = max(0, min(max_score, round(total, 2)))
        interview_chance = max(0, min(100, round((fit * 0.75) + (skill_score * 0.25), 2)))
        growth_potential = max(0, min(100, round((fit * 0.6) + 25, 2)))

        salary_value = parse_salary(job_dict.get("salary", "Not disclosed"))
        salary_potential = max(0, min(100, round((salary_value / 150000) * 100, 2)))

        match_details = {
            "skills": skill_match.to_dict(matcher),
            "years_required": requirements.years_required,
            "posting_language": requirements.language,
            "bilingual_posting": requirements.bilingual,
            "adjustments": {
                "entry_level": round(entry_level_bonus, 2),
                "culture": round(culture_bonus, 2),
                "established": round(established_bonus, 2),
                "bilingual": round(bilingual_bonus, 2),
                "freshness": round(freshness_adjustment, 2),
                "preference_feedback": round(feedback_adjustment, 2),
                "penalties": round(penalties, 2),
                "core_skill_gaps": round(core_gap_penalty, 2),
                "language_mismatch": round(language_penalty, 2),
            },
        }

        return {
            "fit_score": fit,
            "interview_chance": interview_chance,
            "growth_potential": growth_potential,
            "salary_potential": salary_potential,
            "title_match": round(title_score, 2),
            "experience_match": round(experience_score, 2),
            "education_match": round(education_score, 2),
            "skills_match": round(skill_score, 2),
            "commute_match": round(commute_score, 2),
            "entry_level_bonus": round(entry_level_bonus, 2),
            "culture_bonus": round(culture_bonus, 2),
            "established_bonus": round(established_bonus, 2),
            "match_details": match_details,
        }


# Default composite scorer instance
_default_scorer = CompositeScorer()


def title_match_score(job_title: str, profile: UserProfile | dict[str, Any] | None = None) -> int:
    prof = profile or USER_PROFILE
    target_roles = (
        prof.target_roles if isinstance(prof, UserProfile) else prof.get("target_roles", [])
    )
    priority_roles = (
        prof.priority_target_roles
        if isinstance(prof, UserProfile)
        else prof.get("priority_target_roles", [])
    )
    priority_roles_norm = {normalize_text(role) for role in priority_roles}
    text = normalize_text(job_title)
    score = 0
    for role in target_roles:
        role_norm = normalize_text(role)
        if not role_norm or not text:
            continue
        if _phrase_in(text, role_norm) or _phrase_in(role_norm, text):
            # Roles outside the priority set (e.g. analyst/support) still match, but
            # rank below priority roles (e.g. software engineering) when both exist.
            if not priority_roles_norm or role_norm in priority_roles_norm:
                score = max(score, 100)
            else:
                score = max(score, 75)

    segments = [
        normalize_text(segment)
        for segment in re.split(r"\s+(?:[-–—|/])\s+", job_title or "")
        if normalize_text(segment)
    ]
    matched_segments = sum(
        any(
            _phrase_in(segment, normalize_text(role)) or _phrase_in(normalize_text(role), segment)
            for role in target_roles
            if normalize_text(role)
        )
        for segment in segments
    )
    # Highest priority: Python, automation, and ML/AI focused roles
    coding_core_terms = [
        "python",
        "automation",
        "machine learning",
        "ml engineer",
        "ai engineer",
        "artificial intelligence",
        "data scientist",
        "data engineer",
        "data pipeline",
        "rpa",
        "test automation",
        "qa automation",
    ]
    # General software engineering / coding roles
    general_swe_terms = ["software engineer", "software developer", "engineer", "developer", "programmer"]
    # Broader, less-picky fallback roles for a new grad. Scored well below actual
    # engineering/developer roles so analyst/business postings don't crowd out real
    # SWE/ML/automation matches. Whole-word matching: "bi" no longer matches "Bilingual".
    analyst_business_terms = [
        "analyst",
        "analyste",
        "systems",
        "systemes",
        "business",
        "affaires",
        "product",
        "produit",
        "data",
        "donnees",
        "bi",
        "functional",
        "fonctionnel",
        "consultant",
        "solutions",
        "integration",
        "qa",
        "assurance",
    ]
    # Deprioritized: pure web/frontend roles (less interested in web dev)
    web_only_terms = ["frontend", "front end", "front-end", "ui developer", "web designer", "wordpress", "shopify"]

    if score < 100:
        if contains_any_term(text, coding_core_terms):
            score = max(score, 95)
        elif contains_any_term(text, general_swe_terms):
            score = max(score, 88)
        elif contains_any_term(text, analyst_business_terms):
            score = max(score, 45)

    # "Full stack" is still a developer role worth seeing, so it only takes a light ding.
    if contains_any_term(text, ["full stack"]):
        score -= 10
    if contains_any_term(text, web_only_terms) and not contains_any_term(text, coding_core_terms):
        score -= 15
    # Senior/staff-tier ICs can't coast to a high score on keyword overlap.
    if contains_any_term(text, SENIOR_TITLE_TERMS):
        score -= 40
    # Numbered-level suffix (Engineer II, Developer 2, Analyst III...).
    if _has_mid_plus_level_suffix(text):
        score -= 35
    # Management/executive titles (normally hard-excluded earlier by is_clearly_mismatched).
    if _is_management_title(text):
        score -= 70
    # Whole-word: "International" / "Internal" no longer count as "intern".
    if contains_any_term(text, ["intern", "internship", "co op", "coop", "stagiaire"]):
        score -= 30
    if matched_segments > 1:
        score = min(score, 75)
    return max(0, min(100, score))


def _phrase_in(haystack: str, needle: str) -> bool:
    """Whole-word containment of one normalized phrase in another."""
    return contains_any_term(haystack, (needle,))


def experience_match_score(job_description: str, candidate_years: int | None = None) -> int:
    """How comfortably the candidate's experience meets the posting's stated minimum.

    The candidate is allowed to stretch one year past what they have. A posting that
    states nothing scores neutral-good (80) rather than best-case, since silence is not
    evidence the role is junior; an explicit "no experience required" scores highest.
    """
    years = extract_required_years(job_description)
    if candidate_years is None:
        candidate_years = int(_profile_get(None, "experience_years", 0) or 0)
    if years is None:
        return 80
    if years >= 7:
        return 10
    if years == 0:
        return 95
    gap = years - (candidate_years + 1)
    if gap <= 0:
        return 95
    return {1: 75, 2: 55, 3: 35}.get(gap, 15)


def education_match_score(job_description: str) -> int:
    text = normalize_text(job_description)
    if contains_any_term(text, ["bachelor", "degree", "college", "baccalaureat", "licence"]):
        return 95
    if contains_any_term(text, ["master", "maitrise"]):
        return 80
    return 85


def skill_match_score(
    job_description: str,
    profile: UserProfile | dict[str, Any] | None = None,
    title: str = "",
) -> int:
    """Requirement-coverage score (10-100): how much of what the posting names is covered.

    Skills are detected with whole-word, alias-aware matching (so "CI/CD" and
    "scikit-learn" count and "excellent" does not trigger "Excel"). Skills named as
    required or in the title weigh more than nice-to-haves.
    """
    dimension = SkillMatchDimension()
    score, _, _, _ = dimension.details(
        {"title": title, "description": job_description}, profile if profile is not None else USER_PROFILE
    )
    return int(round(score))


def parse_salary_score(salary_raw: str, salary_value: float) -> float:
    # Over 80% of Canadian listings don't disclose salary. Treat undisclosed neutrally (80/100)
    # rather than heavily penalizing standard corporate postings.
    if not salary_raw or salary_raw.lower() in {"not disclosed", "n/a", "unknown"}:
        return 80.0
    return min(100.0, max(40.0, (salary_value - 50000) / 70000 * 100))


def fit_score(job: dict[str, Any] | JobListing) -> dict[str, Any]:
    return _default_scorer.score_job(job)


def score_jobs(
    jobs: Iterable[dict[str, Any] | JobListing],
    exclude_mismatched: bool = True,
    feedback: Any | None = None,
) -> list[dict[str, Any]]:
    """Score and rank jobs.

    exclude_mismatched=True (default) drops management/executive-titled postings
    (Manager, Director, VP, Head of, Chief, President, Executive) before scoring,
    since no keyword overlap makes those a fit for a new-grad IC engineering search.
    Set to False if you'd rather see them ranked low instead of removed entirely.

    ``feedback`` is an optional :class:`jobhunter.scoring.feedback.FeedbackModel`
    that nudges scores toward the kinds of roles/companies you apply to and away
    from the ones you dismiss.
    """
    scorer = _default_scorer if feedback is None else CompositeScorer(feedback=feedback)
    scored = []
    for job in jobs:
        job_dict = job.to_dict() if isinstance(job, JobListing) else dict(job)
        if exclude_mismatched and is_clearly_mismatched(job_dict):
            continue
        scores = scorer.score_job(job_dict)
        scored_job = {**job_dict, **scores}
        scored.append(scored_job)
    return sorted(scored, key=lambda item: item.get("fit_score", 0), reverse=True)
