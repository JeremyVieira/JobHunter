"""Tests for the database tracker module."""

import sqlite3
import tempfile
from pathlib import Path

from jobhunter.tracker.db import (
    dismiss_job,
    ensure_database,
    filter_applied_jobs,
    get_job_stats,
    get_recent_jobs,
    get_top_jobs,
    purge_placeholder_jobs,
    save_application,
    save_jobs,
)


def test_ensure_database_creates_tables():
    """Verify that ensure_database creates required tables."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Patch the DB_PATH temporarily
        import jobhunter.tracker.db as db_module

        original_get_connection = db_module.get_connection
        original_db_path = db_module.DB_PATH

        def patched_get_connection():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn

        db_module.get_connection = patched_get_connection
        db_module.DB_PATH = db_path

        try:
            ensure_database()
            conn = patched_get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
            assert cursor.fetchone() is not None

            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='applications'"
            )
            assert cursor.fetchone() is not None

            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_reports'"
            )
            assert cursor.fetchone() is not None

            conn.close()
        finally:
            db_module.get_connection = original_get_connection
            db_module.DB_PATH = original_db_path


def test_save_jobs_single():
    """Test saving a single job."""
    import jobhunter.tracker.db as db_module

    original_get_connection = db_module.get_connection

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        def patched_get_connection():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn

        db_module.get_connection = patched_get_connection

        try:
            ensure_database()

            jobs = [
                {
                    "title": "Business Analyst",
                    "company": "Bell Canada",
                    "location": "Montreal, QC",
                    "remote_status": "Hybrid",
                    "salary": "$95,000",
                    "description": "Test job",
                    "posting_date": "2026-08-29",
                    "url": "https://example.com/job/1",
                    "fit_score": 92.0,
                    "interview_chance": 85.0,
                    "growth_potential": 75.0,
                    "salary_potential": 65.0,
                    "source": "test",
                }
            ]

            count = save_jobs(jobs)
            assert count == 1

            conn = patched_get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM jobs")
            result = cursor.fetchone()
            assert result["cnt"] == 1
            conn.close()
        finally:
            db_module.get_connection = original_get_connection


def test_save_jobs_multiple():
    """Test saving multiple jobs."""
    import jobhunter.tracker.db as db_module

    original_get_connection = db_module.get_connection

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        def patched_get_connection():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn

        db_module.get_connection = patched_get_connection

        try:
            ensure_database()

            jobs = [
                {
                    "title": f"Analyst {i}",
                    "company": f"Company {i}",
                    "location": "Montreal, QC",
                    "remote_status": "Hybrid",
                    "salary": f"${80000 + i * 1000}",
                    "description": "Test job",
                    "posting_date": "2026-08-29",
                    "url": f"https://example.com/job/{i}",
                    "fit_score": float(75 + i),
                    "interview_chance": 75.0,
                    "growth_potential": 75.0,
                    "salary_potential": 65.0,
                    "source": "test",
                }
                for i in range(5)
            ]

            count = save_jobs(jobs)
            assert count == 5

            conn = patched_get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM jobs")
            result = cursor.fetchone()
            assert result["cnt"] == 5
            conn.close()
        finally:
            db_module.get_connection = original_get_connection


def test_purge_placeholder_jobs_removes_only_synthetic_rows():
    import jobhunter.tracker.db as db_module

    original_get_connection = db_module.get_connection
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        def patched_get_connection():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn

        db_module.get_connection = patched_get_connection
        try:
            ensure_database()
            save_jobs(
                [
                    {
                        "title": "Business Analyst",
                        "company": "Bell Canada",
                        "url": "https://jobs.example.com/1",
                        "fit_score": 80,
                        "source": "test",
                    },
                    {
                        "title": "Manual Entry",
                        "company": "Unknown",
                        "url": "https://indeed.example.com",
                        "source": "manual",
                    },
                    {"title": "Generic role", "company": "Unknown", "url": "", "source": "workday"},
                ]
            )

            assert purge_placeholder_jobs() == 2
            assert len(get_top_jobs()) == 1
        finally:
            db_module.get_connection = original_get_connection


def test_filter_applied_jobs_excludes_applied_urls():
    import jobhunter.tracker.db as db_module

    original_get_connection = db_module.get_connection
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        def patched_get_connection():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn

        db_module.get_connection = patched_get_connection

        try:
            ensure_database()
            save_application(
                {
                    "company": "Bell Canada",
                    "role": "Business Analyst",
                    "url": "https://example.com/job/duplicate",
                    "salary": "$95,000",
                    "fit_score": 90,
                    "application_date": "2026-08-29",
                    "status": "applied",
                    "notes": "Applied",
                }
            )

            filtered = filter_applied_jobs(
                [
                    {"url": "https://example.com/job/duplicate"},
                    {"url": "https://example.com/job/new"},
                ]
            )
            assert [job["url"] for job in filtered] == ["https://example.com/job/new"]
        finally:
            db_module.get_connection = original_get_connection


def test_filter_applied_jobs_keeps_saved_urls_visible():
    import jobhunter.tracker.db as db_module

    original_get_connection = db_module.get_connection
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        def patched_get_connection():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn

        db_module.get_connection = patched_get_connection
        try:
            ensure_database()
            save_application({"url": "https://example.com/saved", "status": "saved"})
            save_application({"url": "https://example.com/applied", "status": "applied"})

            visible = filter_applied_jobs(
                [
                    {"url": "https://example.com/saved"},
                    {"url": "https://example.com/applied"},
                ]
            )

            assert [job["url"] for job in visible] == ["https://example.com/saved"]
        finally:
            db_module.get_connection = original_get_connection


def test_scrape_upsert_preserves_generated_document_paths():
    import jobhunter.tracker.db as db_module

    original_get_connection = db_module.get_connection
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        def patched_get_connection():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn

        db_module.get_connection = patched_get_connection
        try:
            ensure_database()
            save_jobs(
                [
                    {
                        "title": "Operations Analyst",
                        "company": "Example Co",
                        "url": "https://example.com/job/1",
                        "en_resume_pdf": "outputs/resume.pdf",
                        "fit_score": 82,
                    }
                ]
            )
            save_jobs(
                [
                    {
                        "title": "Operations Analyst II",
                        "company": "Example Co",
                        "url": "https://example.com/job/1",
                        "fit_score": 84,
                    }
                ]
            )

            conn = patched_get_connection()
            row = conn.execute(
                "SELECT title, en_resume_pdf FROM jobs WHERE url = ?",
                ("https://example.com/job/1",),
            ).fetchone()
            conn.close()

            assert row["title"] == "Operations Analyst II"
            assert row["en_resume_pdf"] == "outputs/resume.pdf"
        finally:
            db_module.get_connection = original_get_connection


def test_get_top_jobs_excludes_applied_postings():
    import jobhunter.tracker.db as db_module

    original_get_connection = db_module.get_connection
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        def patched_get_connection():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn

        db_module.get_connection = patched_get_connection
        try:
            ensure_database()
            save_jobs([
                {"title": "Applied Analyst", "company": "Company A", "url": "https://example.com/applied", "fit_score": 85},
                {"title": "New Analyst", "company": "Company B", "url": "https://example.com/new", "fit_score": 80},
            ])
            save_application({"url": "https://example.com/applied", "status": "applied"})

            top_jobs = get_top_jobs()

            assert [job["title"] for job in top_jobs] == ["New Analyst"]
            assert get_job_stats()["total_jobs"] == 1
        finally:
            db_module.get_connection = original_get_connection


def test_dismissed_posting_is_removed_and_not_reintroduced():
    import jobhunter.tracker.db as db_module

    original_get_connection = db_module.get_connection
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        def patched_get_connection():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn

        db_module.get_connection = patched_get_connection
        try:
            ensure_database()
            dismissed_job = {
                "title": "Business Analyst",
                "company": "Company A",
                "url": "https://example.com/dismissed",
                "fit_score": 85,
            }
            new_job = {"title": "Data Analyst", "company": "Company B", "url": "https://example.com/new", "fit_score": 80}
            save_jobs([dismissed_job, new_job])

            dismiss_job(dismissed_job)

            assert [job["title"] for job in get_top_jobs()] == ["Data Analyst"]
            assert filter_applied_jobs([dismissed_job, new_job]) == [new_job]
        finally:
            db_module.get_connection = original_get_connection


def test_save_application():
    """Test saving an application record."""
    import jobhunter.tracker.db as db_module

    original_get_connection = db_module.get_connection

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        def patched_get_connection():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn

        db_module.get_connection = patched_get_connection

        try:
            ensure_database()

            application = {
                "company": "Bell Canada",
                "role": "Business Analyst",
                "salary": "$95,000",
                "fit_score": 92.0,
                "application_date": "2026-08-29",
                "status": "applied",
                "interview_date": "2026-09-05",
                "notes": "Good fit",
            }

            app_id = save_application(application)
            assert isinstance(app_id, int)
            assert app_id > 0
        finally:
            db_module.get_connection = original_get_connection


def test_dashboard_job_row_normalizes_to_dict():
    """SQLite rows should be safely converted to dict-like job records."""
    import sqlite3

    from jobhunter.dashboard.app import as_job_dict

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE jobs (id INTEGER, title TEXT, url TEXT)"
    )
    conn.execute("INSERT INTO jobs (id, title, url) VALUES (?, ?, ?)", (1, "Analyst", "https://example.com/job/1"))
    row = conn.execute("SELECT * FROM jobs WHERE id = 1").fetchone()
    conn.close()

    job = as_job_dict(row)
    assert job["url"] == "https://example.com/job/1"
    assert job.get("title") == "Analyst"


def test_get_job_stats():
    """Test retrieving job statistics."""
    import jobhunter.tracker.db as db_module

    original_get_connection = db_module.get_connection

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        def patched_get_connection():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn

        db_module.get_connection = patched_get_connection

        try:
            ensure_database()

            jobs = [
                {
                    "title": f"Analyst {i}",
                    "company": f"Company {i}",
                    "location": "Montreal, QC",
                    "remote_status": "Hybrid",
                    "salary": "$80,000",
                    "description": "Test",
                    "posting_date": "2026-08-29",
                    "url": f"https://example.com/job/{i}",
                    "fit_score": float(75 + i * 5),
                    "interview_chance": 75.0,
                    "growth_potential": 75.0,
                    "salary_potential": 65.0,
                    "source": "test",
                }
                for i in range(3)
            ]

            save_jobs(jobs)
            stats = get_job_stats()

            assert stats["total_jobs"] == 3
            assert stats["avg_fit_score"] is not None
            assert stats["max_fit_score"] is not None
            assert stats["high_fit_jobs"] >= 0
        finally:
            db_module.get_connection = original_get_connection


def test_get_recent_jobs():
    """Test retrieving recent jobs."""
    import jobhunter.tracker.db as db_module

    original_get_connection = db_module.get_connection

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        def patched_get_connection():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn

        db_module.get_connection = patched_get_connection

        try:
            ensure_database()

            jobs = [
                {
                    "title": f"Analyst {i}",
                    "company": f"Company {i}",
                    "location": "Montreal, QC",
                    "remote_status": "Hybrid",
                    "salary": "$80,000",
                    "description": "Test",
                    "posting_date": "2026-08-29",
                    "url": f"https://example.com/job/{i}",
                    "fit_score": float(75 + i),
                    "interview_chance": 75.0,
                    "growth_potential": 75.0,
                    "salary_potential": 65.0,
                    "source": "test",
                }
                for i in range(10)
            ]

            save_jobs(jobs)
            recent = get_recent_jobs(limit=5)

            assert len(recent) == 5
            assert all("title" in dict(r) for r in recent)
            assert all("fit_score" in dict(r) for r in recent)
        finally:
            db_module.get_connection = original_get_connection


def test_get_top_jobs():
    """Test retrieving top jobs."""
    import jobhunter.tracker.db as db_module

    original_get_connection = db_module.get_connection

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        def patched_get_connection():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn

        db_module.get_connection = patched_get_connection

        try:
            ensure_database()

            jobs = [
                {
                    "title": f"Analyst {i}",
                    "company": f"Company {i}",
                    "location": "Montreal, QC",
                    "remote_status": "Hybrid",
                    "salary": f"${80000 + i * 5000}",
                    "description": "Test",
                    "posting_date": "2026-08-29",
                    "url": f"https://example.com/job/{i}",
                    "fit_score": float(60 + i * 2),
                    "interview_chance": 75.0,
                    "growth_potential": 75.0,
                    "salary_potential": float(60 + i),
                    "source": "test",
                }
                for i in range(8)
            ]

            save_jobs(jobs)
            top = get_top_jobs(limit=5)

            assert len(top) <= 5
            assert len(top) > 0
            # Verify they are sorted by fit_score descending
            fit_scores = [dict(r)["fit_score"] for r in top]
            assert fit_scores == sorted(fit_scores, reverse=True)
        finally:
            db_module.get_connection = original_get_connection
