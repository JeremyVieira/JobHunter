from __future__ import annotations

import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv  # noqa: E402

from jobhunter.matching.inventory import resume_skill_ids  # noqa: E402
from jobhunter.models import ScoringRulesConfig, UserProfile  # noqa: E402

load_dotenv(REPOSITORY_ROOT / ".env")


def _list_from_env(name: str, default: list[str]) -> list[str]:
    values = os.getenv(name, "").strip()
    return [value.strip() for value in values.split(",") if value.strip()] if values else default


def _int_from_env(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else default


JOB_SEARCH_TERMS = _list_from_env("JOB_SEARCH_TERMS", [])
JOB_SEARCH_LOCATION = os.getenv("JOB_SEARCH_LOCATION", "Montreal, QC")
JOBSPY_SITES = _list_from_env(
    "JOBSPY_SITES", ["indeed", "linkedin", "zip_recruiter", "glassdoor", "google"]
)

DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
OUTPUT_DIR = BASE_DIR / "outputs"
RESUME_DIR = OUTPUT_DIR / "resumes"
DB_PATH = DATA_DIR / "jobhunter.db"

USER_PROFILE_DATA = {
    "name": os.getenv("USER_NAME", "Your Name"),
    "location": os.getenv("USER_LOCATION", "Your City, Region"),
    "email": os.getenv("USER_EMAIL", "your.email@example.com"),
    "phone": os.getenv("USER_PHONE", ""),
    "github": os.getenv("USER_GITHUB", ""),
    "near_downtown_montreal": os.getenv("USER_NEAR_DOWNTOWN_MONTREAL", "false").lower() == "true",
    "experience_years": _int_from_env("USER_EXPERIENCE_YEARS", 0),
    "degree": os.getenv("USER_DEGREE", "Add your education"),
    "experience_summary": os.getenv(
        "USER_EXPERIENCE_SUMMARY", "Add a short summary of your relevant experience."
    ),
    # Languages the candidate works in (drives bilingual bonus / language mismatch penalty)
    "languages": [lang.lower() for lang in _list_from_env("USER_LANGUAGES", ["en", "fr"])],
    # Skill ids found in the local master resume files (empty when none exist)
    "resume_skills": resume_skill_ids(
        BASE_DIR / "resume" / "master_resume.txt", BASE_DIR / "resume" / "master_resume_fr.txt"
    ),
    "preferred_company_size": "medium",
    "wants_stable_companies": True,
    "prefers_hybrid_or_downtown": True,
    "avoid_heavy_coding_roles": False,
    "career_growth": True,
    "salary_focus": True,
    "target_roles": _list_from_env("USER_TARGET_ROLES", [
        # Core focus: junior software engineering, Python, automation, and ML roles
        "Junior Software Engineer",
        "Software Engineer I",
        "Associate Software Engineer",
        "Graduate Software Engineer",
        "New Grad Software Engineer",
        "Software Engineer",
        "Junior Software Developer",
        "Associate Software Developer",
        "Software Developer",
        "Python Developer",
        "Junior Python Developer",
        "Backend Developer",
        "Backend Engineer",
        "Junior Backend Developer",
        "Full Stack Developer",
        "Full Stack Engineer",
        "Junior Full Stack Developer",
        "Automation Engineer",
        "Junior Automation Engineer",
        "Test Automation Engineer",
        "QA Automation Engineer",
        "Junior Automation QA Engineer",
        "Software QA Engineer",
        "Machine Learning Engineer",
        "Junior Machine Learning Engineer",
        "ML Engineer",
        "AI Engineer",
        "Junior AI Engineer",
        "Data Scientist",
        "Junior Data Scientist",
        "Data Engineer",
        "Junior Data Engineer",
        "Analytics Engineer",
        "DevOps Engineer",
        "Junior DevOps Engineer",
        "Cloud Engineer",
        "Site Reliability Engineer",
        # Broader options, for a new grad who isn't too picky
        "Business Analyst",
        "Systems Analyst",
        "Technical Systems Analyst",
        "IT Business Analyst",
        "Data Analyst",
        "Business Intelligence Analyst",
        "Product Analyst",
        "QA Analyst",
        "Quality Assurance Analyst",
        "Test Analyst",
        "Application Support Analyst",
        "IT Support Analyst",
        "Cloud Support Engineer",
        "Cloud Operations Analyst",
        "Functional Analyst",
        "Analyste de systèmes",
        "Analyste de données",
        "Ingénieur logiciel junior",
        "Développeur logiciel junior",
    ]),
    # Subset of target_roles ranked highest during scoring; analyst/support
    # roles above remain valid matches but score below these when both are present.
    "priority_target_roles": _list_from_env("USER_PRIORITY_TARGET_ROLES", [
        "Junior Software Engineer",
        "Software Engineer I",
        "Associate Software Engineer",
        "Graduate Software Engineer",
        "New Grad Software Engineer",
        "Software Engineer",
        "Junior Software Developer",
        "Associate Software Developer",
        "Software Developer",
        "Python Developer",
        "Junior Python Developer",
        "Backend Developer",
        "Backend Engineer",
        "Junior Backend Developer",
        "Full Stack Developer",
        "Full Stack Engineer",
        "Junior Full Stack Developer",
        "Automation Engineer",
        "Junior Automation Engineer",
        "Test Automation Engineer",
        "QA Automation Engineer",
        "Junior Automation QA Engineer",
        "Software QA Engineer",
        "Machine Learning Engineer",
        "Junior Machine Learning Engineer",
        "ML Engineer",
        "AI Engineer",
        "Junior AI Engineer",
        "Data Scientist",
        "Junior Data Scientist",
        "Data Engineer",
        "Junior Data Engineer",
        "Analytics Engineer",
        "DevOps Engineer",
        "Junior DevOps Engineer",
        "Cloud Engineer",
        "Site Reliability Engineer",
        "Ingénieur logiciel junior",
        "Développeur logiciel junior",
    ]),
    "keywords": _list_from_env("USER_KEYWORDS", [
        "python",
        "automation",
        "machine learning",
        "data pipelines",
        "pandas",
        "numpy",
        "scikit-learn",
        "pytorch",
        "pytest",
        "unit testing",
        "ci/cd",
        "docker",
        "rest api",
        "sql",
        "git",
        "scripting",
        "algorithms",
        "data structures",
        "cloud",
        "agile",
        "troubleshooting",
        "excel",
    ]),
}

# Typed User Profile instance and backward-compatible dict
PROFILE = UserProfile.from_dict(USER_PROFILE_DATA)
USER_PROFILE = USER_PROFILE_DATA

JOB_SEARCH_URLS = [
    "https://www.linkedin.com/jobs/search/?keywords=Junior%20Software%20Engineer%20Python%20Montreal",
    "https://www.indeed.com/jobs?q=Junior+Software+Engineer+Python&l=Montreal%2C+QC",
    "https://www.indeed.com/jobs?q=Automation+Engineer&l=Montreal%2C+QC",
    "https://www.indeed.com/jobs?q=Machine+Learning+Engineer+New+Grad&l=Montreal%2C+QC",
    "https://www.workday.com/en-us/company/careers.html?search=Junior%20Software%20Engineer%20Montreal",
]

# Public company career pages to check in addition to job boards. These pages
# may expose JobPosting JSON-LD or static job links; JavaScript-only pages are
# skipped safely and can be covered by the Greenhouse/Lever adapters.
COMPANY_CAREER_URLS = _list_from_env("COMPANY_CAREER_URLS", [
    "Genetec|https://www.genetec.com/careers",
    "CMLS Financial|https://www.cmls.ca/careers",
    "Shopify|https://www.shopify.com/careers",
    "Coveo|https://www.coveo.com/en/company/careers",
    "Mila|https://mila.quebec/en/careers",
    "Lightspeed|https://www.lightspeedhq.com/careers/",
    "CAE|https://www.cae.com/careers/",
    "Intact|https://careers.intactfc.com/",
    "RBC|https://jobs.rbc.com/ca/en",
    "TD Bank|https://jobs.td.com/en-CA/",
    "Scotiabank|https://jobs.scotiabank.com/",
    "BMO|https://jobs.bmo.com/",
    "National Bank of Canada|https://emplois.bnc.ca/",
    "Desjardins|https://www.desjardins.com/ca/about-us/careers/",
])

# ---------------------------------------------------------------------------
# Additional job sources. Every entry is optional; unset means "not used".
# Formats (comma-separated in .env):
#   *_COMPANIES   "Display Name|board-token"
#   WORKDAY_COMPANIES   "Display Name|tenant|wd3|SiteName"
#   RSS_FEEDS     "Feed Name|https://example.com/jobs.rss"
# Use `python -m jobhunter.scraper.discover <careers-url>` to find tokens.
# ---------------------------------------------------------------------------
def _tuples_from_env(name: str, size: int, default: list[tuple[str, ...]] | None = None):
    raw = os.getenv(name)
    if raw is None:
        return list(default or [])
    parsed: list[tuple[str, ...]] = []
    for entry in raw.split(","):
        parts = tuple(part.strip() for part in entry.split("|"))
        if len(parts) == size and all(parts):
            parsed.append(parts)
    return parsed


GREENHOUSE_BOARDS = _tuples_from_env(
    "GREENHOUSE_COMPANIES",
    2,
    [("Stripe", "stripe"), ("GitLab", "gitlab"), ("Databricks", "databricks")],
)
LEVER_BOARDS = _tuples_from_env("LEVER_COMPANIES", 2, [("Figma", "figma")])
ASHBY_BOARDS = _tuples_from_env("ASHBY_COMPANIES", 2)
WORKABLE_BOARDS = _tuples_from_env("WORKABLE_COMPANIES", 2)
SMARTRECRUITERS_BOARDS = _tuples_from_env("SMARTRECRUITERS_COMPANIES", 2)
RECRUITEE_BOARDS = _tuples_from_env("RECRUITEE_COMPANIES", 2)
WORKDAY_BOARDS = _tuples_from_env("WORKDAY_COMPANIES", 4)
RSS_FEEDS = _tuples_from_env("RSS_FEEDS", 2)

# Keyed aggregator APIs (free tiers). Skipped silently when no key is set.
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "").strip()
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "").strip()
JOOBLE_API_KEY = os.getenv("JOOBLE_API_KEY", "").strip()
MUSE_ENABLED = os.getenv("MUSE_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}

# Collection behaviour
JOBSPY_HOURS_OLD = _int_from_env("JOBSPY_HOURS_OLD", 72)
JOBSPY_RESULTS_PER_TERM = _int_from_env("JOBSPY_RESULTS_PER_TERM", 15)
JOBSPY_FETCH_LINKEDIN_DESCRIPTIONS = os.getenv(
    "JOBSPY_FETCH_LINKEDIN_DESCRIPTIONS", "true"
).strip().lower() not in {"0", "false", "no", "off"}
MAX_PERSISTED_JOBS = _int_from_env("MAX_PERSISTED_JOBS", 40)
ENRICH_MAX_FETCHES = _int_from_env("ENRICH_MAX_FETCHES", 40)
CAREER_PAGE_MAX_DETAIL_PAGES = _int_from_env("CAREER_PAGE_MAX_DETAIL_PAGES", 15)
REQUEST_DELAY_SECONDS = float(os.getenv("REQUEST_DELAY_SECONDS", "0.3") or 0.3)

SCORING_RULES_DATA = {
    # Relative weights (normalized by their sum). Title, experience and requirement
    # coverage separate good from bad matches; the rest are near-constant, so they
    # carry little weight.
    "title_match_weight": 24,
    "experience_match_weight": 14,
    "education_match_weight": 3,
    "skills_match_weight": 30,
    "salary_estimate_weight": 4,
    "remote_preference_weight": 3,
    "montreal_proximity_weight": 8,
    "commute_preference_weight": 2,
    "startup_penalty": 15,
    "senior_developer_penalty": 25,
    "seven_years_penalty": 20,
    "tiny_company_description_penalty": 12,
    "mid_level_numeral_penalty": 20,
    "management_penalty": 40,
    "entry_level_bonus": 8,
    "culture_bonus": 6,
    "established_bonus": 6,
    "core_gap_penalty": 8,
    "core_gap_penalty_cap": 20,
    "bilingual_bonus": 4,
    "language_mismatch_penalty": 15,
    "freshness_bonus": 3,
    "stale_penalty": 3,
    "entry_level_min_fit_score": 55,
    "max_score": 100,
}

# Typed Scoring Rules instance and backward-compatible dict
SCORING_CONFIG = ScoringRulesConfig.from_dict(SCORING_RULES_DATA)
SCORING_RULES = SCORING_RULES_DATA

# Optional proxy configuration for bypassing Cloudflare on Glassdoor & ZipRecruiter
# Format: comma-separated list of proxy URLs, e.g. "http://user:pass@proxy1:port,http://user:pass@proxy2:port"
_raw_proxies = os.getenv("JOBSPY_PROXIES", "").strip()
JOBSPY_PROXIES = [p.strip() for p in _raw_proxies.split(",") if p.strip()] if _raw_proxies else None
