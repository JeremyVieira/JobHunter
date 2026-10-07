"""Tests for the daily report and email summary module."""

from pathlib import Path

from jobhunter.daily_report import generate_daily_report, generate_email_summary


def test_generate_email_summary_empty():
    summary = generate_email_summary([])
    assert "No matching opportunities found" in summary


def test_generate_email_summary_single_job():
    jobs = [
        {
            "title": "Business Analyst",
            "company": "Bell Canada",
            "salary": "$95,000 - $115,000",
            "fit_score": 92,
            "location": "Montreal, QC",
            "url": "https://example.com/job/1",
        }
    ]
    summary = generate_email_summary(jobs)
    assert "Bell Canada" in summary
    assert "Business Analyst" in summary
    assert "92" in summary
    assert "Montreal, QC" in summary


def test_generate_email_summary_multiple_jobs():
    jobs = [
        {
            "title": "Business Analyst",
            "company": "Bell Canada",
            "salary": "$95,000 - $115,000",
            "fit_score": 92,
            "location": "Montreal, QC",
            "url": "https://example.com/job/1",
        },
        {
            "title": "Systems Analyst",
            "company": "TD Bank",
            "salary": "$100,000 - $120,000",
            "fit_score": 88,
            "location": "Toronto, ON",
            "url": "https://example.com/job/2",
        },
        {
            "title": "Product Analyst",
            "company": "RBC",
            "salary": "$85,000 - $105,000",
            "fit_score": 78,
            "location": "Montreal, QC",
            "url": "https://example.com/job/3",
        },
    ]
    summary = generate_email_summary(jobs)
    assert "1. Business Analyst" in summary
    assert "2. Systems Analyst" in summary
    assert "3. Product Analyst" in summary
    assert "92" in summary
    assert "88" in summary
    assert "78" in summary


def test_generate_email_summary_caps_at_ten():
    jobs = [
        {
            "title": f"Analyst {i}",
            "company": f"Company {i}",
            "salary": f"${80000 + i * 1000}",
            "fit_score": 75 + i,
            "location": "Montreal, QC",
            "url": f"https://example.com/job/{i}",
        }
        for i in range(15)
    ]
    summary = generate_email_summary(jobs)
    lines = summary.split("\n")
    job_lines = [line for line in lines if line.strip().startswith(("1.", "2.", "3."))]
    assert len(job_lines) <= 10


def test_generate_email_summary_missing_fields():
    jobs = [
        {
            "title": "Analyst",
        }
    ]
    summary = generate_email_summary(jobs)
    assert "Analyst" in summary
    assert "Unknown" in summary
    assert "N/A" in summary


def test_generate_daily_report_empty():
    report_path = generate_daily_report([])
    assert Path(report_path).exists()
    content = Path(report_path).read_text(encoding="utf-8")
    assert "JobHunterAI Daily Report" in content


def test_generate_daily_report_with_jobs():
    jobs = [
        {
            "title": "Business Analyst",
            "company": "Bell Canada",
            "salary": "$95,000 - $115,000",
            "fit_score": 92,
            "location": "Montreal, QC",
            "url": "https://example.com/job/1",
        },
        {
            "title": "Systems Analyst",
            "company": "TD Bank",
            "salary": "$100,000 - $120,000",
            "fit_score": 88,
            "location": "Toronto, ON",
            "url": "https://example.com/job/2",
        },
    ]
    report_path = generate_daily_report(jobs)
    assert Path(report_path).exists()
    content = Path(report_path).read_text(encoding="utf-8")

    assert "JobHunterAI Daily Report" in content
    assert "Bell Canada" in content
    assert "Business Analyst" in content
    assert "TD Bank" in content
    assert "Systems Analyst" in content
    assert "<table>" in content
    assert "<thead>" in content
    assert "<tbody>" in content


def test_generate_daily_report_is_html():
    jobs = [
        {
            "title": "Analyst",
            "company": "Company",
            "salary": "$80,000",
            "fit_score": 75,
            "location": "Montreal, QC",
            "url": "https://example.com/job/1",
        }
    ]
    report_path = generate_daily_report(jobs)
    content = Path(report_path).read_text(encoding="utf-8")

    assert content.startswith("<html>") or "<html>" in content
    assert "</html>" in content
    assert "<head>" in content
    assert "<body>" in content
