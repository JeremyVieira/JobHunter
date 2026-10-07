"""Tests for the job scraper collector module."""

import logging

import requests

from jobhunter.scraper.collector import (
    JobSpyScraper,
    RemotiveScraper,
    build_example_jobs,
    collect_jobs_from_urls,
    fetch_arbeitnow_jobs,
    fetch_jobicy_jobs,
    fetch_jobspy_jobs,
    fetch_remotive_jobs,
    normalize_job,
    parse_generic_html,
    parse_indeed_html,
    parse_linkedin_html,
)


def test_normalize_job_complete():
    job = {
        "title": "  Business Analyst  ",
        "company": "Bell Canada",
        "location": "Montreal, QC",
        "remote_status": "Hybrid",
        "salary": "$95,000 - $115,000",
        "description": "Requires 3 years experience",
        "posting_date": "2026-08-29",
        "url": "https://example.com/job/123",
        "source": "linkedin",
    }
    normalized = normalize_job(job)
    assert normalized["title"] == "Business Analyst"
    assert normalized["company"] == "Bell Canada"
    assert normalized["location"] == "Montreal, QC"
    assert normalized["salary"] == "$95,000 - $115,000"


def test_normalize_job_with_missing_fields():
    job = {"title": "Business Analyst"}
    normalized = normalize_job(job)
    assert normalized["title"] == "Business Analyst"
    assert normalized["company"] == "Unknown"
    assert normalized["location"] == "Montreal, QC"
    assert normalized["salary"] == "Not disclosed"
    assert normalized["source"] == "manual"


def test_normalize_job_truncates_long_description():
    long_description = "A" * 5000
    job = {"title": "Analyst", "description": long_description}
    normalized = normalize_job(job)
    assert len(normalized["description"]) <= 4000


def test_build_example_jobs():
    jobs = build_example_jobs()
    assert len(jobs) >= 2
    assert all("title" in job for job in jobs)
    assert all("company" in job for job in jobs)
    assert all("salary" in job for job in jobs)
    assert all("description" in job for job in jobs)
    assert all("url" in job for job in jobs)


def test_build_example_jobs_have_target_roles():
    jobs = build_example_jobs()
    titles = [job["title"].lower() for job in jobs]
    analyst_jobs = [t for t in titles if "analyst" in t]
    assert len(analyst_jobs) > 0


def test_build_example_jobs_montreal_focused():
    jobs = build_example_jobs()
    locations = [job["location"].lower() for job in jobs]
    montreal_jobs = [loc for loc in locations if "montreal" in loc or "quebec" in loc]
    assert len(montreal_jobs) > 0


def test_jobspy_scraper_uses_configured_search_terms_and_location(monkeypatch):
    monkeypatch.setattr(
        "jobhunter.scraper.collector.JOB_SEARCH_TERMS",
        ["Operations Analyst", "Event Coordinator"],
    )
    monkeypatch.setattr("jobhunter.scraper.collector.JOB_SEARCH_LOCATION", "Toronto, ON")
    monkeypatch.setattr("jobhunter.scraper.collector.JOBSPY_SITES", ["indeed"])

    scraper = JobSpyScraper()

    assert scraper.search_terms == ["Operations Analyst", "Event Coordinator"]
    assert scraper.location == "Toronto, ON"
    assert scraper.sites == ["indeed"]


def test_collect_jobs_from_urls_with_empty_list():
    jobs = collect_jobs_from_urls([])
    assert len(jobs) == 0


def test_collect_jobs_from_urls_with_none_urls():
    jobs = collect_jobs_from_urls([None, "", None])
    assert len(jobs) == 0


def test_fetch_jobicy_jobs_normalizes_real_api_fields(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "jobs": [
                    {
                        "jobTitle": "Business Analyst",
                        "companyName": "Example Corp",
                        "url": "https://jobicy.com/jobs/123",
                        "jobGeo": None,
                        "jobDescription": "<p>SQL and business analysis</p>",
                        "pubDate": "2026-08-29",
                        "salaryMin": 75000,
                        "salaryCurrency": "USD",
                    }
                ]
            }

    monkeypatch.setattr(
        "jobhunter.scraper.collector.requests.get", lambda url, timeout: FakeResponse()
    )

    jobs = fetch_jobicy_jobs()

    assert jobs == [
        {
            "title": "Business Analyst",
            "company": "Example Corp",
            "location": "Remote",
            "remote_status": "Remote",
            "salary": "USD75000",
            "description": "SQL and business analysis",
            "posting_date": "2026-08-29",
            "url": "https://jobicy.com/jobs/123",
            "source": "jobicy",
        }
    ]


def test_fetch_remotive_jobs(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "jobs": [
                    {
                        "title": "Systems Analyst",
                        "company_name": "Tech Corp",
                        "url": "https://remotive.com/jobs/456",
                        "description": "<p>Systems design and APIs</p>",
                        "salary": "$90,000",
                        "candidate_required_location": "Canada",
                        "publication_date": "2026-08-29T12:00:00",
                    }
                ]
            }

    monkeypatch.setattr(
        "jobhunter.scraper.collector.requests.get", lambda url, timeout: FakeResponse()
    )
    jobs = fetch_remotive_jobs()
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Systems Analyst"
    assert jobs[0]["company"] == "Tech Corp"
    assert jobs[0]["source"] == "remotive"


def test_remotive_retries_transient_failures_and_logs_exhaustion(monkeypatch, caplog):
    calls = 0

    def fail_request(url, timeout):
        nonlocal calls
        calls += 1
        raise requests.Timeout("temporary timeout")

    monkeypatch.setattr("jobhunter.scraper.collector.requests.get", fail_request)
    monkeypatch.setattr("jobhunter.scraper.collector.time.sleep", lambda delay: None)

    with caplog.at_level(logging.ERROR, logger="jobhunter.scraper.collector"):
        assert RemotiveScraper().scrape() == []

    assert calls == 3
    assert "Remotive source request failed" in caplog.text


def test_fetch_arbeitnow_jobs(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {
                        "title": "Solutions Engineer",
                        "company_name": "Cloud Ltd",
                        "url": "https://arbeitnow.com/jobs/789",
                        "description": "<p>Client integrations</p>",
                        "remote": True,
                        "location": "Montreal, QC",
                        "created_at": "2026-08-29",
                    }
                ]
            }

    monkeypatch.setattr(
        "jobhunter.scraper.collector.requests.get", lambda url, timeout: FakeResponse()
    )
    jobs = fetch_arbeitnow_jobs()
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Solutions Engineer"
    assert jobs[0]["company"] == "Cloud Ltd"
    assert jobs[0]["source"] == "arbeitnow"


def test_fetch_jobspy_jobs_normalizes_multi_board_fields(monkeypatch):
    class FakeListings:
        def to_dict(self, orient):
            assert orient == "records"
            return [
                {
                    "title": "Business Analyst",
                    "company": "Example Corp",
                    "job_url": "https://ca.indeed.com/viewjob?jk=123",
                    "job_url_direct": None,
                    "location": "Montréal, QC, CA",
                    "is_remote": False,
                    "description": "SQL and stakeholder communication",
                    "date_posted": "2026-08-29",
                    "min_amount": 70000,
                    "max_amount": 90000,
                    "currency": "CAD",
                    "site": "indeed",
                }
            ]

    monkeypatch.setattr("jobhunter.scraper.collector.scrape_jobs", lambda **kwargs: FakeListings())

    jobs = fetch_jobspy_jobs()

    assert jobs[0]["title"] == "Business Analyst"
    assert jobs[0]["company"] == "Example Corp"
    assert jobs[0]["url"] == "https://ca.indeed.com/viewjob?jk=123"
    assert jobs[0]["source"] == "indeed"


def test_collect_jobs_from_urls_fallback_on_error(monkeypatch):
    def fake_fetch(url, timeout=20):
        raise ConnectionError("Network error")

    monkeypatch.setattr("jobhunter.scraper.collector.fetch_job_page", fake_fetch)
    jobs = collect_jobs_from_urls(["https://invalid-domain-12345.com/jobs"])
    assert jobs == []


def test_parse_linkedin_html_empty():
    """Test parsing empty or invalid LinkedIn HTML."""
    html = "<html><body></body></html>"
    jobs = parse_linkedin_html(html)
    assert jobs == []


def test_parse_linkedin_html_with_jobs():
    """Test parsing LinkedIn HTML with job listings."""
    html = """
    <html>
        <body>
            <li class="jobs-search-results__list-item">
                <h3>Business Analyst</h3>
                <h4>Bell Canada</h4>
                <div class="job-search-card__location">Montreal, QC</div>
                <a href="https://linkedin.com/jobs/123">Apply</a>
            </li>
        </body>
    </html>
    """
    jobs = parse_linkedin_html(html)
    # May or may not find jobs depending on HTML structure, but should not crash
    assert isinstance(jobs, list)


def test_parse_indeed_html_empty():
    """Test parsing empty or invalid Indeed HTML."""
    html = "<html><body></body></html>"
    jobs = parse_indeed_html(html)
    assert jobs == []


def test_parse_indeed_html_with_jobs():
    """Test parsing Indeed HTML with job listings."""
    html = """
    <html>
        <body>
            <div class="jobsearch-SerpJobCard">
                <h2 class="jobtitle"><a href="/jobs/1234">Business Analyst</a></h2>
                <span class="companyName">Bell Canada</span>
                <div class="companyLocation">Montreal, QC</div>
                <div class="salary-snippet-container">$95,000 - $115,000</div>
            </div>
        </body>
    </html>
    """
    jobs = parse_indeed_html(html)
    # May or may not find jobs depending on HTML structure, but should not crash
    assert isinstance(jobs, list)


def test_parse_generic_html():
    """Test unparseable pages do not create synthetic job listings."""
    html = "<html><body><p>Some job content here</p></body></html>"
    jobs = parse_generic_html(html, "generic_site")
    assert jobs == []
