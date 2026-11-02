"""Application lifecycle, funnel statistics and preference examples."""

import pytest

from jobhunter.tracker.db import (
    APPLIED_STATUSES,
    SQLiteApplicationRepository,
    SQLiteJobRepository,
    compute_funnel,
    parse_match_details,
)


@pytest.fixture()
def repos(tmp_path):
    jobs = SQLiteJobRepository(tmp_path / "t.db")
    apps = SQLiteApplicationRepository(tmp_path / "t.db")
    jobs.ensure_schema()
    apps.ensure_schema()
    return jobs, apps


def _app(**kw):
    base = {"company": "Acme", "role": "Developer", "fit_score": 82, "status": "applied", "url": "https://x/1", "source": "linkedin"}
    base.update(kw)
    return base


def test_status_updates_record_response_date_and_interview_date(repos):
    _, apps = repos
    app_id = apps.save(_app())
    assert apps.update_status(app_id, "interview", interview_date="2026-11-05")
    row = apps.funnel_rows()[0]
    assert row["status"] == "interview" and row["interview_date"] == "2026-11-05"
    assert row["response_date"]  # stamped automatically when the employer responds


def test_unknown_status_is_rejected_and_missing_application_returns_false(repos):
    _, apps = repos
    app_id = apps.save(_app())
    with pytest.raises(ValueError):
        apps.update_status(app_id, "banana")
    assert apps.update_status(9999, "rejected") is False


def test_all_progressed_statuses_still_hide_the_job_from_new_lists(repos):
    jobs, apps = repos
    url = "https://x/hidden"
    jobs.save_many([{"title": "Dev", "company": "Acme", "location": "Montreal, QC", "description": "x" * 120, "url": url, "fit_score": 80}])
    assert any(r["url"] == url for r in jobs.find_recent(10))
    app_id = apps.save(_app(url=url))
    for status in APPLIED_STATUSES:
        apps.update_status(app_id, status)
        assert not any(r["url"] == url for r in jobs.find_recent(10)), status
        assert not any(r["url"] == url for r in jobs.find_top(10)), status


def test_funnel_by_band_source_and_language():
    rows = [
        {"status": "interview", "fit_score": 91, "source": "ashby", "language": "en", "interview_date": None},
        {"status": "rejected", "fit_score": 85, "source": "linkedin", "language": "en", "interview_date": None},
        {"status": "ghosted", "fit_score": 72, "source": "linkedin", "language": "fr", "interview_date": None},
        {"status": "applied", "fit_score": 64, "source": "indeed", "language": "fr", "interview_date": None},
        {"status": "offer", "fit_score": 95, "source": "ashby", "language": "en", "interview_date": "2026-11-01"},
    ]
    stats = compute_funnel(rows)
    assert stats["overall"] == {"applied": 5, "responded": 3, "interviews": 2, "offers": 1, "ghosted": 1}
    assert stats["by_band"]["90-100"]["interviews"] == 2
    assert stats["by_source"]["linkedin"]["applied"] == 2
    assert stats["by_language"]["fr"]["ghosted"] == 1


def test_funnel_rows_join_source_and_score_from_the_jobs_table(repos):
    jobs, apps = repos
    url = "https://x/joined"
    jobs.save_many([{"title": "Dev", "company": "Acme", "location": "Montreal, QC", "description": "x" * 120, "url": url, "fit_score": 77, "source": "workday"}])
    apps.save({"company": "Acme", "role": "Dev", "status": "applied", "url": url})
    row = apps.funnel_rows()[0]
    assert row["source"] == "workday" and row["fit_score"] == 77


def test_feedback_examples_and_seen_identities(repos):
    jobs, apps = repos
    apps.save(_app(company="Acme Inc.", role="Python Developer", url="https://x/a"))
    jobs.dismiss({"url": "https://x/d", "title": "Sales Rep", "company": "BadCo"})
    liked, disliked = apps.feedback_examples()
    assert liked == [{"title": "Python Developer", "company": "Acme Inc."}]
    assert disliked == [{"title": "Sales Rep", "company": "BadCo"}]
    identities = apps.seen_identities()
    # same role on another board (different URL, "Acme" vs "Acme Inc.") is recognized
    from jobhunter.scraper.dedupe import identity

    assert identity("Acme", "python developer") in identities
    assert identity("BadCo", "Sales Rep") in identities


def test_match_details_round_trip_through_the_jobs_table(repos):
    jobs, _ = repos
    details = {"skills": {"matched": ["Python"]}, "years_required": 2}
    jobs.save_many([{"title": "Dev", "company": "Acme", "location": "Montreal, QC", "description": "x" * 120, "url": "https://x/m", "fit_score": 80, "match_details": details}])
    row = jobs.find_top(5)[0]
    assert parse_match_details(row["match_details"]) == details
    assert parse_match_details(None) == {} and parse_match_details("not json") == {}
