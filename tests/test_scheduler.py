"""Unit tests for the scheduler helper module."""

from unittest.mock import patch

from jobhunter.scheduler import run_daily_jobs_and_report


def test_run_daily_jobs_and_report():
    sample_jobs = [{"title": "Business Analyst", "company": "Bell", "fit_score": 90}]
    with patch("jobhunter.scheduler.run_daily_collection", return_value=sample_jobs) as mock_col, \
         patch("jobhunter.scheduler.generate_daily_report", return_value="daily_report.html") as mock_rep:
        jobs, report = run_daily_jobs_and_report()
        assert jobs == sample_jobs
        assert report == "daily_report.html"
        mock_col.assert_called_once()
        mock_rep.assert_called_once_with(sample_jobs[:10])
