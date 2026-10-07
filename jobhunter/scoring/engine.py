from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

try:
    from jobhunter.config.settings import SCORING_RULES, USER_PROFILE
    from jobhunter.models import JobListing, ScoringRulesConfig, UserProfile
except ModuleNotFoundError:  # pragma: no cover
    from config.settings import SCORING_RULES, USER_PROFILE
    from models import JobListing, ScoringRulesConfig, UserProfile


DEFAULT_SCORING_WEIGHTS = {
    "title_match_weight": 30.0,
    "experience_match_weight": 15.0,
    "education_match_weight": 7.0,
    "skills_match_weight": 22.0,
    "salary_estimate_weight": 8.0,
    "remote_preference_weight": 6.0,
    "montreal_proximity_weight": 8.0,
    "commute_preference_weight": 4.0,
}


# --- Role-tier vocabulary shared by title scoring, penalties, and the hard filter ---
# "Senior"-type ICs are penalized heavily but still scored (a strong ML/automation
# match can still surface). Management/executive titles are hard-excluded outright:
# no amount of keyword overlap makes a Director/VP/Manager posting a fit for a new
# grad targeting IC engineering roles.
SENIOR_TITLE_TERMS = (
    "senior",
    "sr.",
    "sr ",
    "lead",
    "principal",
    "staff",
    "expert",
    "intermediate",
    "mid level",
    "mid-level",
    "advanced",
)

MANAGEMENT_TITLE_TERMS = (
    "manager",
    "director",
    "vp ",
    "vice president",
    "head of",
    "chief",
    "president",
    "executive",
    "general manager",
)

# Numbered-level title suffixes (Software Engineer II, Developer 2, Analyst III...).
# "I" / "1" is the entry-level tier and is left alone; II and above typically mean
# 2+ years of prior experience expected, which is why these were slipping through
# even after the SENIOR_TITLE_TERMS penalty (the word "senior" never appears).
MID_PLUS_LEVEL_TOKENS = {"ii", "iii", "iv", "v", "2", "3", "4", "5"}


def _has_mid_plus_level_suffix(normalized_text: str) -> bool:
    tokens = normalized_text.split()
    return bool(tokens) and tokens[-1] in MID_PLUS_LEVEL_TOKENS


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


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
    company-name string for backwards compatibility. This is a best-effort proxy —
    free scraping APIs don't expose real headcount — so it only catches companies
    that self-identify as small/early-stage in their name or job description.
    """
    if isinstance(job, str):
        job = {"company": job, "description": ""}
    name = normalize_text(job.get("company", ""))
    description = normalize_text(job.get("description", ""))
    if any(term in name for term in ("startup", "labs", "forge", "ventures")):
        return company_name_penalty
    if any(normalize_text(term) in description for term in TINY_STARTUP_SIGNAL_TERMS):
        return description_penalty
    return 0.0


def is_clearly_mismatched(job: dict[str, Any]) -> bool:
    """Hard filter for postings that are structurally the wrong track for a new-grad
    IC engineer, regardless of how well the description's keywords overlap.

    Management/executive titles (Manager, Director, VP, Head of, Chief, President,
    Executive) are dropped outright rather than merely down-scored: no amount of
    Python/ML keyword density in the description makes a Director role reachable
    or desirable for a candidate targeting individual-contributor engineering work.
    """
    title = normalize_text(job.get("title", ""))
    return any(term in title for term in MANAGEMENT_TITLE_TERMS)


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
        return float(experience_match_score(description))


class EducationMatchDimension(IScoringDimension):
    def evaluate(self, job: dict[str, Any], profile: UserProfile | dict[str, Any]) -> float:
        description = job.get("description", "")
        return float(education_match_score(description))


class SkillMatchDimension(IScoringDimension):
    def evaluate(self, job: dict[str, Any], profile: UserProfile | dict[str, Any]) -> float:
        description = job.get("description", "")
        return float(skill_match_score(description, profile=profile))


class SalaryMatchDimension(IScoringDimension):
    def evaluate(self, job: dict[str, Any], profile: UserProfile | dict[str, Any]) -> float:
        salary_raw = job.get("salary", "Not disclosed")
        salary_value = parse_salary(salary_raw)
        return float(parse_salary_score(salary_raw, salary_value))


class RemotePreferenceDimension(IScoringDimension):
    def evaluate(self, job: dict[str, Any], profile: UserProfile | dict[str, Any]) -> float:
        desc = normalize_text(job.get("description", ""))
        remote_st = normalize_text(job.get("remote_status", ""))
        return 95.0 if ("remote" in remote_st or "remote" in desc) else 80.0


class MontrealProximityDimension(IScoringDimension):
    def evaluate(self, job: dict[str, Any], profile: UserProfile | dict[str, Any]) -> float:
        loc = normalize_text(job.get("location", ""))
        return 95.0 if any(term in loc for term in ["montreal", "quebec", "qc"]) else 75.0


class CommutePreferenceDimension(IScoringDimension):
    def evaluate(self, job: dict[str, Any], profile: UserProfile | dict[str, Any]) -> float:
        loc = normalize_text(job.get("location", ""))
        desc = normalize_text(job.get("description", ""))

        far_commute_terms = [
            "longueuil",
            "south shore",
            "north shore",
            "laval",
            "west island",
            "40 min",
            "45 min",
            "50 min",
            "60 min",
            "commute 40",
            "commute 45",
            "commute 50",
            "commute 60",
        ]
        if any(term in loc or term in desc for term in far_commute_terms):
            return 72.0

        transit_terms = [
            "metro",
            "subway",
            "station",
            "downtown",
            "plateau",
            "verdun",
            "rosemont",
            "mont royal",
            "bonaventure",
            "public transit",
            "transit",
            "near metro",
            "close to metro",
            "accessible by metro",
            "easy commute",
            "30 min",
            "25 min",
            "20 min",
        ]
        if any(term in loc or term in desc for term in transit_terms):
            return 92.0

        if any(term in loc for term in ["montreal", "quebec", "qc"]):
            return 82.0
        if any(term in loc for term in ["remote", "hybrid"]):
            return 88.0
        return 70.0


class CompositeScorer:
    """Composite scoring engine applying dimension strategies, weights, and penalty rules."""

    def __init__(
        self,
        config: ScoringRulesConfig | dict[str, Any] | None = None,
        profile: UserProfile | dict[str, Any] | None = None,
    ):
        self.config = config or SCORING_RULES
        self.profile = profile or USER_PROFILE

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
        description = normalize_text(job.get("description", ""))
        penalty = 0.0

        penalty += company_size_penalty(
            job,
            company_name_penalty=self._get_config_val("startup_penalty", 15.0),
            description_penalty=self._get_config_val("tiny_company_description_penalty", 12.0),
        )

        # Senior/staff-tier ICs: heavily penalized (raised from 10 -> 25) but still
        # scoreable, since a strong ML/automation posting might still be worth seeing.
        if any(term in title for term in SENIOR_TITLE_TERMS):
            penalty += self._get_config_val("senior_developer_penalty", 25.0)

        # Numbered-level suffix (Engineer II, Developer 2...): same idea as the
        # senior-term penalty above, for titles that signal seniority via a level
        # number instead of a word like "senior".
        if _has_mid_plus_level_suffix(title):
            penalty += self._get_config_val("mid_level_numeral_penalty", 20.0)

        # Management/executive titles: is_clearly_mismatched() drops these from
        # results entirely in score_jobs(), so this penalty is a defense-in-depth
        # backstop for any pipeline that scores without filtering first.
        if any(term in title for term in MANAGEMENT_TITLE_TERMS):
            penalty += self._get_config_val("management_penalty", 40.0)

        if re.search(r"7\s*\+\s*years|7\s*years|8\s*\+\s*years|10\s*\+\s*years", description):
            penalty += self._get_config_val("seven_years_penalty", 20.0)

        return penalty

    def calculate_entry_level_bonus(self, job: dict[str, Any]) -> float:
        title = normalize_text(job.get("title", ""))
        description = normalize_text(job.get("description", ""))
        title_signals = ("junior", "entry level", "associate", "new grad", "graduate", "coordinator")
        experience_signals = ("0 years", "1 year", "1 2 years", "0 2 years", "up to 2 years")
        if any(signal in title for signal in title_signals) or any(
            signal in description for signal in experience_signals
        ):
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
        if any(signal in description for signal in culture_signals):
            return self._get_config_val("culture_bonus", 6.0)
        return 0.0

    # Well-known, established employers (large, stable, publicly recognizable).
    # Not exhaustive - absence just means no bonus, it does not penalize the company.
    KNOWN_ESTABLISHED_COMPANIES = (
        "rbc",
        "royal bank",
        "td bank",
        "td canada trust",
        "scotiabank",
        "bmo",
        "bank of montreal",
        "national bank",
        "desjardins",
        "sun life",
        "manulife",
        "intact",
        "cgi",
        "cae",
        "bombardier",
        "air canada",
        "hydro quebec",
        "loto quebec",
        "caisse de depot",
        "bell canada",
        "rogers",
        "telus",
        "videotron",
        "shopify",
        "lightspeed",
        "nuvia",
        "nuvei",
        "ubisoft",
        "ericsson",
        "ibm",
        "microsoft",
        "google",
        "amazon",
        "meta",
        "salesforce",
        "sap",
        "oracle",
        "cisco",
        "deloitte",
        "pwc",
        "ey",
        "kpmg",
        "accenture",
        "loblaw",
        "metro inc",
        "canadian tire",
    )

    def calculate_established_bonus(self, job: dict[str, Any]) -> float:
        company = normalize_text(job.get("company", ""))
        description = normalize_text(job.get("description", ""))

        if any(name in company for name in self.KNOWN_ESTABLISHED_COMPANIES):
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
        if any(signal in description for signal in established_signals):
            return self._get_config_val("established_bonus", 6.0)
        return 0.0

    def score_job(self, job: dict[str, Any] | JobListing) -> dict[str, Any]:
        job_dict = job.to_dict() if isinstance(job, JobListing) else dict(job)

        title_score = self.title_dim.evaluate(job_dict, self.profile)
        experience_score = self.exp_dim.evaluate(job_dict, self.profile)
        education_score = self.edu_dim.evaluate(job_dict, self.profile)
        skill_score = self.skill_dim.evaluate(job_dict, self.profile)
        salary_score = self.salary_dim.evaluate(job_dict, self.profile)
        remote_score = self.remote_dim.evaluate(job_dict, self.profile)
        prox_score = self.prox_dim.evaluate(job_dict, self.profile)
        commute_score = self.commute_dim.evaluate(job_dict, self.profile)

        # Rebalanced weights: title and skill match (the two signals that actually
        # distinguish "SWE/ML/automation" from "analyst/senior/manager") carry more
        # weight; education and salary (mostly undisclosed, mostly "bachelor's" for
        # everyone) carry less. Still sums to 1.00.
        weighted_dimensions = (
            (title_score, "title_match_weight", DEFAULT_SCORING_WEIGHTS["title_match_weight"]),
            (experience_score, "experience_match_weight", DEFAULT_SCORING_WEIGHTS["experience_match_weight"]),
            (education_score, "education_match_weight", DEFAULT_SCORING_WEIGHTS["education_match_weight"]),
            (skill_score, "skills_match_weight", DEFAULT_SCORING_WEIGHTS["skills_match_weight"]),
            (salary_score, "salary_estimate_weight", DEFAULT_SCORING_WEIGHTS["salary_estimate_weight"]),
            (remote_score, "remote_preference_weight", DEFAULT_SCORING_WEIGHTS["remote_preference_weight"]),
            (prox_score, "montreal_proximity_weight", DEFAULT_SCORING_WEIGHTS["montreal_proximity_weight"]),
            (commute_score, "commute_preference_weight", DEFAULT_SCORING_WEIGHTS["commute_preference_weight"]),
        )
        total_weight = sum(
            self._get_config_val(name, default) for _, name, default in weighted_dimensions
        )
        weighted_score = (
            sum(
                score * self._get_config_val(name, default)
                for score, name, default in weighted_dimensions
            )
            / total_weight
            if total_weight > 0
            else 0.0
        )

        penalties = self.calculate_penalties(job_dict)
        entry_level_bonus = self.calculate_entry_level_bonus(job_dict)
        culture_bonus = self.calculate_culture_bonus(job_dict)
        established_bonus = self.calculate_established_bonus(job_dict)
        total = weighted_score + entry_level_bonus + culture_bonus + established_bonus - penalties

        max_score = self._get_config_val("max_score", 100.0)
        fit = max(0, min(max_score, round(total, 2)))
        interview_chance = max(0, min(100, round((fit * 0.75) + (skill_score * 0.25), 2)))
        growth_potential = max(0, min(100, round((fit * 0.6) + 25, 2)))

        salary_value = parse_salary(job_dict.get("salary", "Not disclosed"))
        salary_potential = max(0, min(100, round((salary_value / 150000) * 100, 2)))

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
        if role_norm in text or text in role_norm:
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
            normalize_text(role) in segment or segment in normalize_text(role)
            for role in target_roles
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
    # engineering/developer roles (was 65, now 45) so analyst/business postings no
    # longer crowd out real SWE/ML/automation matches in the ranking.
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
        if any(term in text for term in coding_core_terms):
            score = max(score, 95)
        elif any(term in text for term in general_swe_terms):
            score = max(score, 88)
        elif any(term in text for term in analyst_business_terms):
            score = max(score, 45)

    # "Full stack" is still a developer role worth seeing (and the scraper actively
    # searches for it), so it only takes a light ding, not the same penalty as an
    # actual seniority/management mismatch.
    if "full stack" in text:
        score -= 10
    if any(term in text for term in web_only_terms) and not any(
        term in text for term in coding_core_terms
    ):
        score -= 15
    # Senior/staff-tier ICs: penalized more than before (was -25) so they can no
    # longer coast to a high score purely on strong keyword overlap.
    if any(term in text for term in SENIOR_TITLE_TERMS):
        score -= 40
    # Numbered-level suffix (Engineer II, Developer 2, Analyst III...): these carry
    # no "senior"-type word so they'd otherwise slip past the check above entirely.
    if _has_mid_plus_level_suffix(text):
        score -= 35
    # Management/executive titles: penalized hard in the title score itself. In
    # practice these are also hard-excluded by is_clearly_mismatched() before this
    # function ever gets weighted into a fit score, but this keeps the function
    # correct if it's ever called standalone.
    if any(term in text for term in MANAGEMENT_TITLE_TERMS):
        score -= 70
    if "intern" in text or "co op" in text or "coop" in text or "stagiaire" in text:
        score -= 30
    if matched_segments > 1:
        score = min(score, 75)
    return max(0, min(100, score))


def experience_match_score(job_description: str) -> int:
    text = normalize_text(job_description)
    years = 0
    if re.search(r"(\d+)\s*\+\s*years", text):
        years = int(re.search(r"(\d+)\s*\+\s*years", text).group(1))
    elif re.search(r"(\d+)\s*years?", text):
        years = int(re.search(r"(\d+)\s*years?", text).group(1))
    if years >= 7:
        return 10
    if years <= 3:
        return 90
    if years <= 5:
        return 70
    return 60


def education_match_score(job_description: str) -> int:
    text = normalize_text(job_description)
    if "bachelor" in text or "degree" in text or "college" in text:
        return 95
    if "master" in text:
        return 80
    return 85


def skill_match_score(
    job_description: str, profile: UserProfile | dict[str, Any] | None = None
) -> int:
    prof = profile or USER_PROFILE
    keywords = prof.keywords if isinstance(prof, UserProfile) else prof.get("keywords", [])
    text = normalize_text(job_description)
    keyword_count = 0
    for keyword in keywords:
        if keyword in text:
            keyword_count += 1
    # Calibrated non-linear scaling: matching 5-6 core keywords in a real job posting
    # indicates a strong match (85-95%), avoiding unrealistic requirement of 17/17 keywords.
    if keyword_count >= 6:
        return min(100, 85 + (keyword_count - 6) * 3)
    if keyword_count == 5:
        return 80
    if keyword_count == 4:
        return 70
    if keyword_count == 3:
        return 55
    if keyword_count == 2:
        return 40
    if keyword_count == 1:
        return 25
    return 10


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
) -> list[dict[str, Any]]:
    """Score and rank jobs.

    exclude_mismatched=True (default) drops management/executive-titled postings
    (Manager, Director, VP, Head of, Chief, President, Executive) before scoring,
    since no keyword overlap makes those a fit for a new-grad IC engineering search.
    Set to False if you'd rather see them ranked low instead of removed entirely.
    """
    scored = []
    for job in jobs:
        job_dict = job.to_dict() if isinstance(job, JobListing) else dict(job)
        if exclude_mismatched and is_clearly_mismatched(job_dict):
            continue
        scores = fit_score(job_dict)
        scored_job = {**job_dict, **scores}
        scored.append(scored_job)
    return sorted(scored, key=lambda item: item.get("fit_score", 0), reverse=True)
