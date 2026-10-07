from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

try:
    from jobhunter.config.settings import DB_PATH
    from jobhunter.filter import CompanyRedFlagPredicate
    from jobhunter.models import ApplicationRecord, JobListing
except ModuleNotFoundError:  # pragma: no cover
    from config.settings import DB_PATH
    from filter import CompanyRedFlagPredicate
    from models import ApplicationRecord, JobListing


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    target = Path(db_path) if db_path is not None else DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    return conn


class IJobRepository(Protocol):
    def ensure_schema(self) -> None: ...
    def save(self, job: JobListing | dict[str, Any]) -> int: ...
    def save_many(self, jobs: Iterable[JobListing | dict[str, Any]]) -> int: ...
    def purge_placeholders(self) -> int: ...
    def purge_red_flag_jobs(self) -> int: ...
    def reset_jobs(self) -> int: ...
    def dismiss(self, job: JobListing | dict[str, Any]) -> int: ...
    def find_recent(self, limit: int = 15) -> list[sqlite3.Row]: ...
    def find_top(self, limit: int = 25) -> list[sqlite3.Row]: ...
    def get_stats(self) -> dict[str, Any]: ...


class IApplicationRepository(Protocol):
    def ensure_schema(self) -> None: ...
    def save(self, application: ApplicationRecord | dict[str, Any]) -> int: ...


class SQLiteJobRepository:
    """Repository implementation for SQLite storage of job listings."""

    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)

    def _get_connection(self) -> sqlite3.Connection:
        try:
            return get_connection(self.db_path)
        except TypeError:
            return get_connection()

    def ensure_schema(self) -> None:
        conn = self._get_connection()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    company TEXT,
                    location TEXT,
                    remote_status TEXT,
                    salary TEXT,
                    description TEXT,
                    posting_date TEXT,
                    url TEXT UNIQUE,
                    fit_score REAL,
                    interview_chance REAL,
                    growth_potential REAL,
                    salary_potential REAL,
                    source TEXT,
                    en_resume_pdf TEXT,
                    en_resume_docx TEXT,
                    en_cover_letter_docx TEXT,
                    fr_resume_pdf TEXT,
                    fr_resume_docx TEXT,
                    fr_cover_letter_docx TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for col in [
                "en_resume_pdf",
                "en_resume_docx",
                "en_cover_letter_docx",
                "fr_resume_pdf",
                "fr_resume_docx",
                "fr_cover_letter_docx",
            ]:
                try:
                    conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:
                    pass
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dismissed_jobs (
                    url TEXT PRIMARY KEY,
                    title TEXT,
                    company TEXT,
                    dismissed_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def save(self, job: JobListing | dict[str, Any]) -> int:
        return self.save_many([job])

    def save_many(self, jobs: Iterable[JobListing | dict[str, Any]]) -> int:
        count = 0
        conn = self._get_connection()
        try:
            for job in jobs:
                if isinstance(job, JobListing):
                    job_dict = job.to_dict()
                else:
                    job_dict = dict(job)

                conn.execute(
                    """
                    INSERT INTO jobs (
                        title, company, location, remote_status, salary, description,
                        posting_date, url, fit_score, interview_chance, growth_potential,
                        salary_potential, source, en_resume_pdf, en_resume_docx,
                        en_cover_letter_docx, fr_resume_pdf, fr_resume_docx, fr_cover_letter_docx
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET
                        title = excluded.title,
                        company = excluded.company,
                        location = excluded.location,
                        remote_status = excluded.remote_status,
                        salary = excluded.salary,
                        description = excluded.description,
                        posting_date = excluded.posting_date,
                        fit_score = excluded.fit_score,
                        interview_chance = excluded.interview_chance,
                        growth_potential = excluded.growth_potential,
                        salary_potential = excluded.salary_potential,
                        source = excluded.source,
                        en_resume_pdf = COALESCE(NULLIF(excluded.en_resume_pdf, ''), jobs.en_resume_pdf),
                        en_resume_docx = COALESCE(NULLIF(excluded.en_resume_docx, ''), jobs.en_resume_docx),
                        en_cover_letter_docx = COALESCE(NULLIF(excluded.en_cover_letter_docx, ''), jobs.en_cover_letter_docx),
                        fr_resume_pdf = COALESCE(NULLIF(excluded.fr_resume_pdf, ''), jobs.fr_resume_pdf),
                        fr_resume_docx = COALESCE(NULLIF(excluded.fr_resume_docx, ''), jobs.fr_resume_docx),
                        fr_cover_letter_docx = COALESCE(NULLIF(excluded.fr_cover_letter_docx, ''), jobs.fr_cover_letter_docx)
                    """,
                    (
                        job_dict.get("title"),
                        job_dict.get("company"),
                        job_dict.get("location"),
                        job_dict.get("remote_status"),
                        job_dict.get("salary"),
                        job_dict.get("description"),
                        job_dict.get("posting_date"),
                        job_dict.get("url"),
                        job_dict.get("fit_score"),
                        job_dict.get("interview_chance"),
                        job_dict.get("growth_potential"),
                        job_dict.get("salary_potential"),
                        job_dict.get("source"),
                        job_dict.get("en_resume_pdf"),
                        job_dict.get("en_resume_docx"),
                        job_dict.get("en_cover_letter_docx"),
                        job_dict.get("fr_resume_pdf"),
                        job_dict.get("fr_resume_docx"),
                        job_dict.get("fr_cover_letter_docx"),
                    ),
                )
                count += 1
            conn.commit()
        finally:
            conn.close()
        return count

    def purge_placeholders(self) -> int:
        """Remove historic records that are not actual job postings."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                DELETE FROM jobs
                WHERE LOWER(COALESCE(company, '')) = 'unknown'
                   OR LOWER(COALESCE(title, '')) IN ('manual entry', 'generic role', 'unknown role')
                         OR LOWER(COALESCE(title, '')) LIKE '%project coordinator%'
                         OR LOWER(COALESCE(title, '')) LIKE '%technical coordinator%'
                           OR LOWER(COALESCE(title, '')) LIKE '%senior%'
                           OR LOWER(COALESCE(title, '')) LIKE 'sr %'
                           OR LOWER(COALESCE(title, '')) LIKE 'sr.%'
                           OR LOWER(COALESCE(title, '')) LIKE '%lead%'
                           OR LOWER(COALESCE(title, '')) LIKE '%principal%'
                           OR LOWER(COALESCE(title, '')) LIKE '%staff%'
                           OR LOWER(COALESCE(title, '')) LIKE '%manager%'
                           OR LOWER(COALESCE(title, '')) LIKE '%director%'
                           OR LOWER(COALESCE(title, '')) LIKE '%gestionnaire%'
                           OR LOWER(COALESCE(title, '')) LIKE '%directeur%'
                   OR COALESCE(url, '') = ''
                   OR LOWER(COALESCE(source, '')) = 'demo'
                """
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def purge_red_flag_jobs(self) -> int:
        """Remove previously stored jobs that fail the current staffing-agency / tiny-company screen."""
        predicate = CompanyRedFlagPredicate()
        conn = self._get_connection()
        try:
            rows = conn.execute("SELECT url, company, description FROM jobs").fetchall()
            bad_urls = [row["url"] for row in rows if not predicate.evaluate(dict(row))]
            if not bad_urls:
                return 0
            conn.executemany("DELETE FROM jobs WHERE url = ?", [(url,) for url in bad_urls])
            conn.commit()
            return len(bad_urls)
        finally:
            conn.close()

    def reset_jobs(self) -> int:
        """Wipe every row from the `jobs` table (found/scored postings) while
        leaving `applications` and `dismissed_jobs` untouched.

        Safe to call any time: applied/dismissed status is tracked in those two
        separate tables keyed by URL, not in the jobs table itself, so a fresh
        scrape after this will re-populate `jobs` and previously
        applied/dismissed postings will still be correctly hidden by
        find_recent()/find_top() the moment they reappear.
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute("DELETE FROM jobs")
            # Reset the autoincrement counter too, if present, so new ids start
            # from 1 again instead of continuing from wherever they left off.
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'jobs'")
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def dismiss(self, job: JobListing | dict[str, Any]) -> int:
        """Persist a posting rejection so it is never shown or saved again."""
        job_dict = job.to_dict() if isinstance(job, JobListing) else dict(job)
        url = str(job_dict.get("url") or "").strip()
        if not url:
            raise ValueError("A job URL is required to dismiss a posting")

        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                INSERT OR REPLACE INTO dismissed_jobs (url, title, company)
                VALUES (?, ?, ?)
                """,
                (url, job_dict.get("title"), job_dict.get("company")),
            )
            conn.execute("DELETE FROM jobs WHERE LOWER(TRIM(url)) = LOWER(TRIM(?))", (url,))
            conn.commit()
            return int(cursor.rowcount)
        finally:
            conn.close()

    def find_recent(self, limit: int = 15) -> list[sqlite3.Row]:
        conn = self._get_connection()
        try:
            return conn.execute(
                """
                SELECT jobs.* FROM jobs
                WHERE NOT EXISTS (
                    SELECT 1 FROM applications
                    WHERE LOWER(TRIM(applications.url)) = LOWER(TRIM(jobs.url))
                      AND LOWER(COALESCE(applications.status, '')) = 'applied'
                )
                AND NOT EXISTS (
                    SELECT 1 FROM dismissed_jobs
                    WHERE LOWER(TRIM(dismissed_jobs.url)) = LOWER(TRIM(jobs.url))
                )
                ORDER BY fit_score DESC, created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        finally:
            conn.close()

    def find_top(self, limit: int = 25) -> list[sqlite3.Row]:
        conn = self._get_connection()
        try:
            return conn.execute(
                """
                                SELECT jobs.* FROM jobs
                                WHERE jobs.fit_score IS NOT NULL
                                    AND NOT EXISTS (
                                            SELECT 1 FROM applications
                                            WHERE LOWER(TRIM(applications.url)) = LOWER(TRIM(jobs.url))
                                                AND LOWER(COALESCE(applications.status, '')) = 'applied'
                                    )
                                      AND NOT EXISTS (
                                          SELECT 1 FROM dismissed_jobs
                                          WHERE LOWER(TRIM(dismissed_jobs.url)) = LOWER(TRIM(jobs.url))
                                      )
                ORDER BY fit_score DESC, salary DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        finally:
            conn.close()

    def get_stats(self) -> dict[str, Any]:
        conn = self._get_connection()
        try:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_jobs,
                    AVG(fit_score) AS avg_fit_score,
                    MAX(fit_score) AS max_fit_score,
                    AVG(salary_potential) AS avg_growth,
                    SUM(CASE WHEN fit_score >= 80 THEN 1 ELSE 0 END) AS high_fit_jobs
                FROM jobs
                WHERE NOT EXISTS (
                    SELECT 1 FROM applications
                    WHERE LOWER(TRIM(applications.url)) = LOWER(TRIM(jobs.url))
                      AND LOWER(COALESCE(applications.status, '')) = 'applied'
                )
                AND NOT EXISTS (
                    SELECT 1 FROM dismissed_jobs
                    WHERE LOWER(TRIM(dismissed_jobs.url)) = LOWER(TRIM(jobs.url))
                )
                """
            ).fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()


class SQLiteApplicationRepository:
    """Repository implementation for SQLite storage of job applications."""

    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)

    def _get_connection(self) -> sqlite3.Connection:
        try:
            return get_connection(self.db_path)
        except TypeError:
            return get_connection()

    def ensure_schema(self) -> None:
        conn = self._get_connection()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company TEXT,
                    role TEXT,
                    salary TEXT,
                    fit_score REAL,
                    application_date TEXT,
                    status TEXT,
                    interview_date TEXT,
                    notes TEXT,
                    url TEXT
                )
                """
            )
            try:
                conn.execute("ALTER TABLE applications ADD COLUMN url TEXT")
            except sqlite3.OperationalError:
                pass
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_date TEXT,
                    summary TEXT,
                    html_path TEXT
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def save(self, application: ApplicationRecord | dict[str, Any]) -> int:
        if isinstance(application, ApplicationRecord):
            app_dict = application.to_dict()
        else:
            app_dict = dict(application)

        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO applications (company, role, salary, fit_score, application_date, status, interview_date, notes, url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    app_dict.get("company"),
                    app_dict.get("role"),
                    app_dict.get("salary"),
                    app_dict.get("fit_score"),
                    app_dict.get("application_date"),
                    app_dict.get("status", "saved"),
                    app_dict.get("interview_date"),
                    app_dict.get("notes"),
                    app_dict.get("url"),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()


# Default singleton repository instances for convenience
_default_job_repo = SQLiteJobRepository()
_default_app_repo = SQLiteApplicationRepository()


def ensure_database() -> None:
    _default_job_repo.ensure_schema()
    _default_app_repo.ensure_schema()


def save_jobs(jobs: Iterable[dict[str, Any] | JobListing]) -> int:
    return _default_job_repo.save_many(jobs)


def purge_placeholder_jobs() -> int:
    return _default_job_repo.purge_placeholders()


def purge_red_flag_jobs() -> int:
    return _default_job_repo.purge_red_flag_jobs()


def reset_jobs() -> int:
    """Wipe found/scored postings but keep applied + dismissed history intact."""
    return _default_job_repo.reset_jobs()


def dismiss_job(job: dict[str, Any] | JobListing) -> int:
    return _default_job_repo.dismiss(job)


def save_application(application: dict[str, Any] | ApplicationRecord) -> int:
    return _default_app_repo.save(application)


def get_recent_jobs(limit: int = 15):
    return _default_job_repo.find_recent(limit)


def get_job_stats():
    return _default_job_repo.get_stats()


def get_top_jobs(limit: int = 25):
    return _default_job_repo.find_top(limit)


def get_applied_urls() -> set[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
                        """SELECT DISTINCT url FROM applications
                             WHERE url IS NOT NULL AND TRIM(url) != ''
                                 AND LOWER(COALESCE(status, '')) = 'applied'"""
        ).fetchall()
        return {str(row["url"]).strip().lower() for row in rows if str(row["url"]).strip()}
    finally:
        conn.close()


def get_dismissed_urls() -> set[str]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT url FROM dismissed_jobs").fetchall()
        return {str(row["url"]).strip().lower() for row in rows if str(row["url"]).strip()}
    finally:
        conn.close()


def filter_applied_jobs(jobs: Iterable[dict[str, Any] | JobListing]) -> list[dict[str, Any]]:
    excluded_urls = get_applied_urls() | get_dismissed_urls()
    filtered: list[dict[str, Any]] = []
    for job in jobs:
        job_dict = job.to_dict() if isinstance(job, JobListing) else dict(job)
        url = str(job_dict.get("url") or "").strip().lower()
        if not url or url not in excluded_urls:
            filtered.append(job_dict)
    return filtered
