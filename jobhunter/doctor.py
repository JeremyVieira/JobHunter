"""``python -m jobhunter doctor``: check that the app is set up and say what to fix.

Pure inspection - it never writes to your data and never touches the network.
"""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from jobhunter.config import settings

OK, WARN, FAIL = "ok", "warn", "fail"
_ICONS = {OK: "✓", WARN: "!", FAIL: "✗"}


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def _module_available(name: str) -> bool:
    try:
        importlib.import_module(name)
    except Exception:
        return False
    return True


def run_checks() -> list[Check]:
    checks: list[Check] = []

    if sys.version_info >= (3, 10):  # noqa: UP036 - runtime guard for older installs
        checks.append(Check("Python", OK, sys.version.split()[0]))
    else:
        checks.append(
            Check("Python", FAIL, sys.version.split()[0], "Python 3.10 or newer is required.")
        )

    required = {
        "streamlit": "dashboard",
        "requests": "collection",
        "bs4": "collection",
        "dotenv": "configuration",
        "apscheduler": "scheduling",
        "pandas": "dashboard",
    }
    optional = {
        "jobspy": "LinkedIn/Indeed/Glassdoor/ZipRecruiter/Google search",
        "docx": "Word resume and cover-letter export",
        "reportlab": "PDF resume export",
    }
    for module, purpose in required.items():
        if not _module_available(module):
            checks.append(
                Check(
                    f"Package {module}",
                    FAIL,
                    f"missing ({purpose})",
                    "pip install -r jobhunter/requirements.txt",
                )
            )
    for module, purpose in optional.items():
        if not _module_available(module):
            checks.append(
                Check(
                    f"Package {module}",
                    WARN,
                    f"missing - {purpose} unavailable",
                    "pip install -r jobhunter/requirements.txt",
                )
            )
    if all(_module_available(m) for m in list(required) + list(optional)):
        checks.append(Check("Dependencies", OK, "all installed"))

    env_file = Path(settings.REPOSITORY_ROOT) / ".env"
    if env_file.exists():
        checks.append(Check(".env file", OK, str(env_file)))
    else:
        checks.append(
            Check(
                ".env file",
                WARN,
                "not found - built-in defaults are in use",
                "copy .env.example to .env and fill in your details",
            )
        )

    profile = settings.USER_PROFILE
    if profile.get("name") in {"", "Your Name"}:
        checks.append(
            Check(
                "Profile name",
                WARN,
                "still the placeholder",
                "set USER_NAME in .env (it appears on your resume and letters)",
            )
        )
    else:
        checks.append(Check("Profile name", OK, str(profile["name"])))
    if not os.getenv("USER_KEYWORDS"):
        checks.append(
            Check(
                "Skill keywords",
                WARN,
                "using generic defaults",
                "set USER_KEYWORDS in .env to the skills you can truthfully claim",
            )
        )
    if not os.getenv("JOB_SEARCH_TERMS"):
        checks.append(
            Check(
                "Search terms",
                WARN,
                "using built-in defaults",
                "set JOB_SEARCH_TERMS (comma-separated) to broaden or focus results",
            )
        )

    resume_dir = Path(settings.RESUME_SOURCE_DIR)
    en = resume_dir / "master_resume.txt"
    fr = resume_dir / "master_resume_fr.txt"
    if en.exists():
        checks.append(Check("Master resume (EN)", OK, str(en)))
    else:
        checks.append(
            Check(
                "Master resume (EN)",
                FAIL,
                f"missing: {en}",
                "copy master_resume.template.txt to master_resume.txt and fill in your real content",
            )
        )
    if fr.exists():
        checks.append(Check("Master resume (FR)", OK, str(fr)))
    else:
        checks.append(
            Check(
                "Master resume (FR)",
                WARN,
                "missing - French documents fall back to the template",
                "optional: copy master_resume_fr.template.txt to master_resume_fr.txt",
            )
        )
    if (resume_dir / "summary_variants.json").exists():
        checks.append(Check("Summary variants", OK, "found"))
    else:
        checks.append(
            Check(
                "Summary variants",
                WARN,
                "none - your resume summary is used unchanged",
                "optional: copy summary_variants.template.json to summary_variants.json",
            )
        )

    db_dir = Path(settings.DB_PATH).parent
    probe = db_dir if db_dir.exists() else next((p for p in db_dir.parents if p.exists()), db_dir)
    if os.access(probe, os.W_OK):
        checks.append(Check("Database location", OK, str(settings.DB_PATH)))
    else:
        checks.append(
            Check(
                "Database location",
                FAIL,
                f"not writable: {probe}",
                "set JOBHUNTER_DATA_DIR to a writable folder",
            )
        )

    sources = [f"JobSpy ({', '.join(settings.JOBSPY_SITES)})"]
    if settings.MUSE_ENABLED:
        sources.append("The Muse")
    for label, boards in (
        ("Greenhouse", settings.GREENHOUSE_BOARDS),
        ("Lever", settings.LEVER_BOARDS),
        ("Ashby", settings.ASHBY_BOARDS),
        ("Workable", settings.WORKABLE_BOARDS),
        ("SmartRecruiters", settings.SMARTRECRUITERS_BOARDS),
        ("Recruitee", settings.RECRUITEE_BOARDS),
        ("Workday", settings.WORKDAY_BOARDS),
    ):
        if boards:
            sources.append(f"{label} x{len(boards)}")
    if settings.COMPANY_CAREER_URLS:
        sources.append(f"career pages x{len(settings.COMPANY_CAREER_URLS)}")
    if settings.ADZUNA_APP_ID and settings.ADZUNA_APP_KEY:
        sources.append("Adzuna")
    if settings.JOOBLE_API_KEY:
        sources.append("Jooble")
    if settings.RSS_FEEDS:
        sources.append(f"RSS x{len(settings.RSS_FEEDS)}")
    checks.append(Check("Job sources", OK, "; ".join(sources)))
    if not settings.COMPANY_CAREER_URLS:
        checks.append(
            Check(
                "Employer career pages",
                WARN,
                "none configured",
                "add COMPANY_CAREER_URLS (Name|url,...) for fresher first-party postings",
            )
        )
    return checks


def format_report(checks: list[Check]) -> str:
    lines = ["JobHunter setup check", ""]
    for check in checks:
        lines.append(f"  {_ICONS[check.status]} {check.name}: {check.detail}")
        if check.fix and check.status != OK:
            lines.append(f"      -> {check.fix}")
    fails = sum(c.status == FAIL for c in checks)
    warns = sum(c.status == WARN for c in checks)
    lines += ["", f"{fails} problem(s), {warns} suggestion(s)."]
    return "\n".join(lines)


def main() -> int:
    checks = run_checks()
    print(format_report(checks))
    return 1 if any(c.status == FAIL for c in checks) else 0
