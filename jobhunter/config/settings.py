"""Resolve application settings from the environment.

This is the application's only environment-parsing boundary. Existing uppercase
exports are retained for integrations; new defaults belong in ``defaults.py``.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from jobhunter.config import env
from jobhunter.config.defaults import (
    DEFAULT_COMPANY_CAREER_URLS,
    DEFAULT_KEYWORDS,
    DEFAULT_SCORING_RULES,
    GREENHOUSE_SEED_BOARDS,
    PRIORITY_TARGET_ROLES,
    TARGET_ROLES,
)
from jobhunter.matching.inventory import resume_skill_ids
from jobhunter.models import ScoringRulesConfig, UserProfile

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(REPOSITORY_ROOT / ".env")

DATA_DIR = env.path("JOBHUNTER_DATA_DIR", BASE_DIR / "data")
LOG_DIR = env.path("JOBHUNTER_LOG_DIR", BASE_DIR / "logs")
OUTPUT_DIR = env.path("JOBHUNTER_OUTPUT_DIR", BASE_DIR / "outputs")
RESUME_DIR = OUTPUT_DIR / "resumes"
DB_PATH = env.path("JOBHUNTER_DB_PATH", DATA_DIR / "jobhunter.db")
RESUME_SOURCE_DIR = env.path("JOBHUNTER_RESUME_DIR", BASE_DIR / "resume")

_values = env.declare({
    "JOB_SEARCH_TERMS": ("JOB_SEARCH_TERMS", env.string_list, ()),
    "JOB_SEARCH_LOCATION": ("JOB_SEARCH_LOCATION", env.string, "Montreal, QC"),
    "JOBSPY_SITES": ("JOBSPY_SITES", env.string_list, ("indeed", "linkedin", "zip_recruiter", "glassdoor", "google")),
    "COMPANY_CAREER_URLS": ("COMPANY_CAREER_URLS", env.string_list, DEFAULT_COMPANY_CAREER_URLS),
    "ADZUNA_APP_ID": ("ADZUNA_APP_ID", env.string, ""),
    "ADZUNA_APP_KEY": ("ADZUNA_APP_KEY", env.string, ""),
    "JOOBLE_API_KEY": ("JOOBLE_API_KEY", env.string, ""),
    "MUSE_ENABLED": ("MUSE_ENABLED", env.boolean, True),
    "JOBSPY_HOURS_OLD": ("JOBSPY_HOURS_OLD", env.integer, 72),
    "JOBSPY_RESULTS_PER_TERM": ("JOBSPY_RESULTS_PER_TERM", env.integer, 15),
    "JOBSPY_FETCH_LINKEDIN_DESCRIPTIONS": ("JOBSPY_FETCH_LINKEDIN_DESCRIPTIONS", env.boolean, True),
    "MAX_JOB_AGE_DAYS": ("MAX_JOB_AGE_DAYS", env.integer, 14),
    "VERIFY_LISTING_URLS": ("VERIFY_LISTING_URLS", env.boolean, True),
    "MAX_LISTING_URL_CHECKS": ("MAX_LISTING_URL_CHECKS", env.integer, 40),
    "LISTING_URL_TIMEOUT_SECONDS": ("LISTING_URL_TIMEOUT_SECONDS", env.number, 8.0),
    "MAX_PERSISTED_JOBS": ("MAX_PERSISTED_JOBS", env.integer, 40),
    "ENRICH_MAX_FETCHES": ("ENRICH_MAX_FETCHES", env.integer, 40),
    "CAREER_PAGE_MAX_DETAIL_PAGES": ("CAREER_PAGE_MAX_DETAIL_PAGES", env.integer, 15),
    "REQUEST_DELAY_SECONDS": ("REQUEST_DELAY_SECONDS", env.number, 0.3),
    "RESUME_LAYOUT": ("RESUME_LAYOUT", env.string, "auto"),
    "RESUME_INCLUDE_STREET_ADDRESS": ("RESUME_INCLUDE_STREET_ADDRESS", env.boolean, False),
    "COLLECTION_HOUR": ("JOBHUNTER_COLLECTION_HOUR", env.integer, 8),
    "COLLECTION_MINUTE": ("JOBHUNTER_COLLECTION_MINUTE", env.integer, 0),
    "DASHBOARD_PORT": ("JOBHUNTER_DASHBOARD_PORT", env.integer, 8501),
    "DASHBOARD_HOST": ("JOBHUNTER_DASHBOARD_HOST", env.string, "127.0.0.1"),
    "DASHBOARD_HEADLESS": (
        "JOBHUNTER_DASHBOARD_HEADLESS",
        lambda name, default: (env.string(name).lower() in {"1", "true", "yes"}) if os.getenv(name) else default,
        False,
    ),
    "DEMO_MODE": ("JOBHUNTER_DEMO", lambda name, default: os.getenv(name) == "1", False),
})
globals().update(_values)
RESUME_LAYOUT = str(RESUME_LAYOUT).lower() or "auto"  # noqa: F821

for _name, _env_name, _size, _default in (
    ("GREENHOUSE_BOARDS", "GREENHOUSE_COMPANIES", 2, GREENHOUSE_SEED_BOARDS),
    ("LEVER_BOARDS", "LEVER_COMPANIES", 2, ()),
    ("ASHBY_BOARDS", "ASHBY_COMPANIES", 2, ()),
    ("WORKABLE_BOARDS", "WORKABLE_COMPANIES", 2, ()),
    ("SMARTRECRUITERS_BOARDS", "SMARTRECRUITERS_COMPANIES", 2, ()),
    ("RECRUITEE_BOARDS", "RECRUITEE_COMPANIES", 2, ()),
    ("WORKDAY_BOARDS", "WORKDAY_COMPANIES", 4, ()),
    ("RSS_FEEDS", "RSS_FEEDS", 2, ()),
):
    _values[_name] = env.tuples(_env_name, _size, _default)
globals().update(_values)

JOBSPY_PROXIES = env.string_list("JOBSPY_PROXIES") or None
JOB_SEARCH_URLS = [
    "https://www.linkedin.com/jobs/search/?keywords=Junior%20Software%20Engineer%20Python%20Montreal",
    "https://www.indeed.com/jobs?q=Junior+Software+Engineer+Python&l=Montreal%2C+QC",
    "https://www.indeed.com/jobs?q=Automation+Engineer&l=Montreal%2C+QC",
    "https://www.indeed.com/jobs?q=Machine+Learning+Engineer+New+Grad&l=Montreal%2C+QC",
    "https://www.workday.com/en-us/company/careers.html?search=Junior%20Software%20Engineer%20Montreal",
]

USER_PROFILE_DATA = UserProfile(
    name=env.string("USER_NAME", "Your Name"),
    location=env.string("USER_LOCATION", "Your City, Region"),
    email=env.string("USER_EMAIL", "your.email@example.com"),
    phone=env.string("USER_PHONE"),
    github=env.string("USER_GITHUB"),
    near_downtown_montreal=env.true_only("USER_NEAR_DOWNTOWN_MONTREAL"),
    experience_years=env.integer("USER_EXPERIENCE_YEARS", 0),
    degree=env.string("USER_DEGREE", "Add your education"),
    experience_summary=env.string("USER_EXPERIENCE_SUMMARY", "Add a short summary of your relevant experience."),
    languages=[language.lower() for language in env.string_list("USER_LANGUAGES", ("en", "fr"))],
    resume_skills=resume_skill_ids(
        RESUME_SOURCE_DIR / "master_resume.txt", RESUME_SOURCE_DIR / "master_resume_fr.txt"
    ),
    target_roles=env.string_list("USER_TARGET_ROLES", TARGET_ROLES),
    priority_target_roles=env.string_list("USER_PRIORITY_TARGET_ROLES", PRIORITY_TARGET_ROLES),
    keywords=env.string_list("USER_KEYWORDS", DEFAULT_KEYWORDS),
).to_dict()
USER_PROFILE = USER_PROFILE_DATA
SCORING_RULES = dict(DEFAULT_SCORING_RULES)
SCORING_CONFIG = ScoringRulesConfig.from_dict(SCORING_RULES)
