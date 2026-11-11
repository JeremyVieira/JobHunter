"""Demo mode: explore the full dashboard with synthetic data and a fictional candidate.

``python -m jobhunter demo`` builds an isolated database (it never touches your real
one), seeds ~20 invented postings that exercise every scoring behaviour (skill gaps,
seniority, bilingual/French postings, stale vs. fresh, snippets...), logs a few
fictional applications so the funnel has something to show, and opens the dashboard
with a fictional profile. Every company, URL and person here is made up.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from jobhunter.config.settings import BASE_DIR, DATA_DIR
from jobhunter.filter import filter_jobs
from jobhunter.matching.inventory import resume_skill_ids
from jobhunter.models import UserProfile
from jobhunter.scoring.engine import CompositeScorer
from jobhunter.tracker.db import SQLiteApplicationRepository, SQLiteJobRepository

DEMO_DATA_DIR = BASE_DIR / "demo_data"

DEMO_ENV = {
    "USER_NAME": "Alex Example",
    "USER_LOCATION": "Montreal, QC",
    "USER_EMAIL": "alex.example@example.com",
    "USER_PHONE": "(514) 555-0100",
    "USER_GITHUB": "https://github.com/alex-example",
    "USER_DEGREE": "Bachelor of Science in Software Engineering",
    "USER_EXPERIENCE_YEARS": "1",
    "USER_LANGUAGES": "en,fr",
    "USER_TARGET_ROLES": "Software Developer, Python Developer, Machine Learning Engineer, "
    "Data Analyst, Business Analyst, QA Analyst, IT Support Analyst",
    "USER_PRIORITY_TARGET_ROLES": "Software Developer, Python Developer, Machine Learning Engineer",
    "USER_KEYWORDS": "python, sql, docker, git, ci/cd, rest api, scikit-learn, pytorch, react, "
    "gcp, unit testing, automation, troubleshooting",
}

# (title, company, location, remote_status, source, days_ago, salary, description)
_SAMPLE_JOBS: list[tuple[str, str, str, str, str, int, str, str]] = [
    (
        "Junior Python Developer",
        "Northwind Analytics",
        "Montreal, QC",
        "Hybrid",
        "ashby",
        1,
        "$70,000 - $85,000 CAD/yr",
        "Join our platform team building data services. Requirements: Python, SQL, REST APIs and "
        "Docker. Experience with CI/CD pipelines and Git is expected. 1-2 years experience. "
        "Nice to have: Kubernetes. We offer mentorship and a hybrid schedule.",
    ),
    (
        "Software Developer, New Grad",
        "Lakeview Systems",
        "Montreal, QC",
        "Hybrid",
        "greenhouse",
        2,
        "Not disclosed",
        "Recent graduates welcome. You will build and test web services in Python and TypeScript with "
        "React front ends. Requirements: Git, unit testing, REST APIs, agile teams. Collaborative "
        "culture with a mentorship program.",
    ),
    (
        "Machine Learning Engineer (Junior)",
        "Aurora Vision",
        "Montreal, QC",
        "On-site",
        "ashby",
        3,
        "$80,000 - $95,000 CAD/yr",
        "Train and evaluate computer vision models. Requirements: Python, PyTorch, scikit-learn and "
        "machine learning fundamentals; Docker for deployment. 1+ years experience. Bilingual "
        "English and French is an asset.",
    ),
    (
        "Backend Developer (Kotlin/Spring)",
        "Maple Mutual",
        "Montreal, QC",
        "Hybrid",
        "workday",
        4,
        "Not disclosed",
        "Requirements: 3+ years of experience with Kotlin and Spring Boot, SQL and microservices. "
        "Maple Mutual is a publicly traded insurer with offices worldwide.",
    ),
    (
        "Développeur logiciel junior",
        "Groupe Boréal",
        "Montréal, QC",
        "Hybrid",
        "workday",
        2,
        "Not disclosed",
        "Nous recherchons un développeur pour notre équipe afin de concevoir des services avec "
        "Python, SQL et Git. Vous allez travailler avec nos clients dans un environnement agile. "
        "Une expérience de 1 an est un atout.",
    ),
    (
        "Bilingual Software Developer",
        "Quai Digital",
        "Montreal, QC",
        "Hybrid",
        "linkedin",
        1,
        "$68,000 - $82,000 CAD/yr",
        "Bilingual (English and French) developer for customer-facing products. Requirements: "
        "JavaScript, React, Node.js, SQL and Git. Great place to work with work life balance.",
    ),
    (
        "Senior Software Engineer",
        "Orion Cloud",
        "Montreal, QC",
        "Hybrid",
        "indeed",
        5,
        "$130,000 - $160,000 CAD/yr",
        "Lead architecture for our platform. Requirements: 8+ years of experience, Go, Kubernetes, "
        "distributed systems and AWS.",
    ),
    (
        "Data Analyst",
        "Pinecrest Retail",
        "Montreal, QC",
        "Hybrid",
        "indeed",
        2,
        "$62,000 - $75,000 CAD/yr",
        "Analyze sales data and build dashboards. Requirements: SQL, Excel, Power BI or Tableau, "
        "data analysis and stakeholder communication. 2 years experience preferred.",
    ),
    (
        "IT Support Analyst",
        "Harborline Logistics",
        "Montreal, QC",
        "On-site",
        "linkedin",
        6,
        "$52,000 - $60,000 CAD/yr",
        "First-line and second-line support. Requirements: Active Directory, Microsoft 365, "
        "troubleshooting, ITIL and service desk tooling. Bilingual preferred.",
    ),
    (
        "QA Automation Engineer",
        "Fieldstone Games",
        "Montreal, QC",
        "Hybrid",
        "themuse",
        3,
        "Not disclosed",
        "Automate regression suites. Requirements: Python, pytest, Selenium and CI/CD. Experience "
        "with test automation frameworks and Agile. 1-3 years experience.",
    ),
    (
        "DevOps Engineer (Junior)",
        "Stratus Labs",
        "Montreal, QC",
        "Remote",
        "greenhouse",
        4,
        "Not disclosed",
        "We're a small team and you will wear many hats. Requirements: Docker, Terraform, GCP, Linux "
        "and CI/CD. Founding team energy; bootstrapped and fast moving.",
    ),
    (
        "Full Stack Developer",
        "Cobalt Commerce",
        "Montreal, QC",
        "Hybrid",
        "greenhouse",
        8,
        "$75,000 - $90,000 CAD/yr",
        "Build storefront features end to end. Requirements: React, Node.js, TypeScript, PostgreSQL "
        "and REST APIs. 2 years experience.",
    ),
    (
        "C# .NET Developer",
        "Meridian Bank",
        "Montreal, QC",
        "Hybrid",
        "workday",
        5,
        "Not disclosed",
        "Requirements: C#, .NET, SQL Server and Azure. 2+ years of experience building internal "
        "banking applications. Fortune 500 employer.",
    ),
    (
        "Business Analyst",
        "Summit Utilities",
        "Montreal, QC",
        "Hybrid",
        "indeed",
        7,
        "$65,000 - $80,000 CAD/yr",
        "Requirements gathering, SQL, stakeholder communication and UAT for energy applications. "
        "3 years of experience required.",
    ),
    (
        "Associate Software Engineer",
        "Crescent Health",
        "Montreal, QC",
        "Hybrid",
        "ashby",
        1,
        "$72,000 - $88,000 CAD/yr",
        "0-2 years experience. Build clinical tooling with Python, Flask, SQL and Docker. Unit "
        "testing and code review are part of daily work. Bilingual English and French required.",
    ),
    (
        "Software Engineer II",
        "Redwood Payments",
        "Montreal, QC",
        "On-site",
        "linkedin",
        9,
        "$95,000 - $115,000 CAD/yr",
        "Own payment features. Requirements: 4 years of experience, Java or Python, SQL and AWS.",
    ),
    (
        "Automation Developer (Python)",
        "Tidewater Energy",
        "Laval, QC",
        "On-site",
        "adzuna",
        2,
        "Not disclosed",
        "Python scripting and automation for operations.",
    ),
    (
        "React Native Mobile Developer",
        "Pixel Harbor",
        "Montreal, QC",
        "Hybrid",
        "themuse",
        4,
        "$70,000 - $84,000 CAD/yr",
        "Ship our consumer app. Requirements: React Native, Expo, JavaScript and REST APIs. "
        "Git and CI/CD experience helpful. 2 years experience.",
    ),
    (
        "Data Engineer (Junior)",
        "Glacier Data",
        "Montreal, QC",
        "Hybrid",
        "greenhouse",
        3,
        "$78,000 - $92,000 CAD/yr",
        "Build ETL pipelines. Requirements: Python, SQL, Airflow and GCP. Docker is a plus. "
        "1-3 years experience.",
    ),
    (
        "PHP / Go Developer",
        "Violet Media",
        "Montreal, QC",
        "Hybrid",
        "indeed",
        60,
        "Not disclosed",
        "Requirements: 3 years of experience with PHP, Laravel and Go. MySQL and Linux.",
    ),
]

# job index -> final status, for the funnel (fictional outcomes). Applied jobs leave the
# "new opportunities" list, so the strongest postings are deliberately left unapplied.
_SAMPLE_APPLICATIONS: dict[int, str] = {
    11: "interview",
    9: "interview",
    13: "screening",
    7: "rejected",
    12: "rejected",
    8: "ghosted",
    10: "ghosted",
    16: "applied",
    14: "applied",
}


def demo_profile(resume_dir: Path | None = None) -> UserProfile:
    resume_paths = [Path(resume_dir) / "master_resume.txt"] if resume_dir else []
    keywords = [k.strip() for k in DEMO_ENV["USER_KEYWORDS"].split(",")]
    return UserProfile(
        target_roles=[r.strip() for r in DEMO_ENV["USER_TARGET_ROLES"].split(",")],
        priority_target_roles=[
            r.strip() for r in DEMO_ENV["USER_PRIORITY_TARGET_ROLES"].split(",")
        ],
        keywords=keywords,
        experience_years=int(DEMO_ENV["USER_EXPERIENCE_YEARS"]),
        languages=["en", "fr"],
        resume_skills=resume_skill_ids(*resume_paths),
    )


def sample_jobs(today: date | None = None) -> list[dict[str, Any]]:
    today = today or date.today()
    jobs = []
    for index, (title, company, location, remote, source, days, salary, description) in enumerate(
        _SAMPLE_JOBS
    ):
        jobs.append(
            {
                "title": title,
                "company": company,
                "location": location,
                "remote_status": remote,
                "salary": salary,
                "description": description,
                "posting_date": (today - timedelta(days=days)).isoformat(),
                "url": f"https://example.com/jobs/{index + 1}",
                "source": source,
            }
        )
    return jobs


def seed_demo(demo_dir: Path | None = None, today: date | None = None) -> dict[str, Path]:
    """(Re)build the isolated demo workspace and return its paths."""
    demo_dir = Path(demo_dir) if demo_dir else DATA_DIR / "demo"
    resume_dir = demo_dir / "resume"
    for sub in (resume_dir, demo_dir / "outputs", demo_dir / "logs"):
        sub.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DEMO_DATA_DIR / "demo_resume_en.txt", resume_dir / "master_resume.txt")
    shutil.copyfile(DEMO_DATA_DIR / "demo_resume_fr.txt", resume_dir / "master_resume_fr.txt")

    db_path = demo_dir / "demo.db"
    if db_path.exists():
        db_path.unlink()
    jobs_repo = SQLiteJobRepository(db_path)
    apps_repo = SQLiteApplicationRepository(db_path)
    jobs_repo.ensure_schema()
    apps_repo.ensure_schema()

    scorer = CompositeScorer(profile=demo_profile(resume_dir))
    scored = []
    for job in sample_jobs(today):
        scored.append({**job, **scorer.score_job(job)})
    # Show what the real pipeline would keep: it drops senior/management/low-fit postings
    # before saving. Applications are logged for every sample job regardless (fictional history).
    jobs_repo.save_many(filter_jobs(scored))

    for index, status in _SAMPLE_APPLICATIONS.items():
        job = scored[index]
        app_id = apps_repo.save(
            {
                "company": job["company"],
                "role": job["title"],
                "salary": job["salary"],
                "fit_score": job["fit_score"],
                "application_date": (today or date.today()).isoformat(),
                "status": "applied",
                "notes": "Demo data (fictional).",
                "url": job["url"],
                "source": job["source"],
            }
        )
        if status != "applied":
            apps_repo.update_status(app_id, status)
    return {
        "dir": demo_dir,
        "db": db_path,
        "resume_dir": resume_dir,
        "outputs": demo_dir / "outputs",
    }


def demo_environment(paths: dict[str, Path]) -> dict[str, str]:
    """Environment that points a child process at the demo workspace and fictional profile."""
    env = os.environ.copy()
    env.update(DEMO_ENV)
    env.update(
        {
            "JOBHUNTER_DB_PATH": str(paths["db"]),
            "JOBHUNTER_DATA_DIR": str(paths["dir"]),
            "JOBHUNTER_OUTPUT_DIR": str(paths["outputs"]),
            "JOBHUNTER_RESUME_DIR": str(paths["resume_dir"]),
            "JOBHUNTER_LOG_DIR": str(paths["dir"] / "logs"),
            "JOBHUNTER_DEMO": "1",
        }
    )
    return env


def run_demo(host: str = "127.0.0.1", port: int = 8502, open_browser: bool = True) -> int:
    paths = seed_demo()
    print(f"Demo workspace ready at {paths['dir']} (your real data is untouched).")
    print(f"Open http://localhost:{port}  - press Ctrl+C to stop.")
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(BASE_DIR / "dashboard" / "app.py"),
        "--server.address",
        host,
        "--server.port",
        str(port),
        "--browser.gatherUsageStats",
        "false",
    ]
    if not open_browser:
        command += ["--server.headless", "true"]
    try:
        return subprocess.call(command, cwd=BASE_DIR, env=demo_environment(paths))
    except KeyboardInterrupt:
        return 0
