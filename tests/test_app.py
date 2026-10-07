"""Integration tests for the main app flow."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from time import sleep

import pytest

from jobhunter.app import (
    ExtractionStage,
    create_daily_scheduler,
    run_daily_collection,
    start_dashboard,
)


@pytest.fixture(autouse=True)
def mock_scrapers(monkeypatch, tmp_path):
    """Keep app integration tests deterministic and isolated from local data."""
    import jobhunter.app as app_module

    test_output_dir = tmp_path / "outputs"
    dependencies = app_module.CollectionDependencies(
        ensure_database=lambda: None,
        purge_placeholder_jobs=lambda: None,
        purge_red_flag_jobs=lambda: None,
        filter_applied_jobs=lambda jobs: list(jobs),
        save_jobs=lambda jobs: len(jobs),
        output_dir=test_output_dir,
    )
    monkeypatch.setattr(
        app_module,
        "_default_pipeline",
        app_module.JobCollectionPipeline(dependencies=dependencies),
    )

    sample_jobs = [
        {
            "title": "Business Systems Analyst",
            "company": "Bank of Montreal",
            "location": "Montreal, QC",
            "remote_status": "Hybrid",
            "salary": "$95,000 - $115,000",
            "description": "SQL Excel Jira requirements gathering stakeholder communication",
            "posting_date": "2026-08-29",
            "url": "https://example.com/job/bsa-app-test",
            "source": "jobspy",
        }
    ]
    monkeypatch.setattr(
        "jobhunter.scraper.collector.JobSpyScraper.scrape", lambda self: sample_jobs
    )
    monkeypatch.setattr("jobhunter.scraper.collector.JobicyScraper.scrape", lambda self: [])
    monkeypatch.setattr("jobhunter.scraper.collector.RemotiveScraper.scrape", lambda self: [])
    monkeypatch.setattr("jobhunter.scraper.collector.ArbeitnowScraper.scrape", lambda self: [])
    monkeypatch.setattr("jobhunter.app.collect_jobs_from_urls", lambda urls: sample_jobs)


def test_run_daily_collection_returns_list():
    """Verify that daily collection returns a list of jobs."""
    result = run_daily_collection()
    assert isinstance(result, list)
    assert len(result) >= 0


def test_run_daily_collection_jobs_have_required_fields():
    """Verify that returned jobs have all required fields."""
    result = run_daily_collection()
    if result:
        for job in result:
            assert "title" in job
            assert "company" in job
            assert "fit_score" in job
            assert job.get("fit_score") >= 60 or job.get("fit_score") == 0


def test_extraction_deduplicates_tracking_url_variants():
    jobs = [
        {
            "title": "Operations Analyst",
            "company": "Example Co",
            "url": "https://www.example.com/jobs/123?utm_source=board",
        },
        {
            "title": "Operations Analyst",
            "company": "Example Co",
            "url": "https://example.com/jobs/123/?fbclid=tracking#details",
        },
    ]

    class FakeScraper:
        def scrape(self):
            return jobs

    context = ExtractionStage(scrapers=[FakeScraper()]).process({})

    assert len(context["raw_jobs"]) == 1
    assert context["raw_jobs"][0]["url"] == jobs[-1]["url"]


def test_run_daily_collection_saves_output():
    """Verify that daily collection saves output file."""
    run_daily_collection()

    import jobhunter.app as app_module

    output_file = app_module._default_pipeline.dependencies.output_dir / "daily_jobs.json"
    assert output_file.exists(), f"Output file {output_file} should exist"
    assert "pytest-of-" in str(output_file)
    assert not list(output_file.parent.glob(".daily_jobs.json.*.tmp"))


def test_pipeline_serializes_concurrent_collection_runs(monkeypatch, tmp_path):
    import jobhunter.app as app_module

    start = Barrier(3)
    state_lock = Lock()
    active_runs = 0
    maximum_active_runs = 0

    class TrackingStage:
        def process(self, context):
            nonlocal active_runs, maximum_active_runs
            with state_lock:
                active_runs += 1
                maximum_active_runs = max(maximum_active_runs, active_runs)
            sleep(0.05)
            with state_lock:
                active_runs -= 1
            context["filtered_jobs"] = []
            return context

    pipeline = app_module.JobCollectionPipeline(
        stages=[TrackingStage()],
        dependencies=app_module.CollectionDependencies(
            ensure_database=lambda: None,
            purge_placeholder_jobs=lambda: None,
            purge_red_flag_jobs=lambda: None,
            filter_applied_jobs=lambda jobs: list(jobs),
            save_jobs=lambda jobs: len(jobs),
            output_dir=tmp_path / "concurrent-output",
        ),
    )

    def run_collection():
        start.wait()
        return pipeline.run()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_collection) for _ in range(2)]
        start.wait()
        assert [future.result() for future in futures] == [[], []]

    assert maximum_active_runs == 1


def test_scheduled_collection_refreshes_report_and_logs_saved_count(monkeypatch, caplog):
    import jobhunter.app as app_module

    jobs = [{"title": "Operations Analyst"}]
    report_paths = []
    monkeypatch.setattr(app_module, "run_daily_collection", lambda: jobs)
    monkeypatch.setattr(
        app_module,
        "generate_daily_report",
        lambda report_jobs: report_paths.append(report_jobs) or "daily_report.html",
    )
    monkeypatch.setattr(app_module._default_pipeline, "last_persisted_count", 1)

    with caplog.at_level("INFO", logger="jobhunter.app"):
        app_module.run_scheduled_collection()

    assert report_paths == [jobs]
    assert "persisted 1" in caplog.text


def test_create_daily_scheduler_runs_once_per_day_at_configured_time():
    scheduler = create_daily_scheduler(hour=6, minute=30)
    job = scheduler.get_job("daily-job-collection")

    assert job is not None
    assert str(job.trigger) == "cron[hour='6', minute='30']"
    assert job.max_instances == 1


def test_start_dashboard_uses_local_streamlit_server(monkeypatch):
    captured = {}

    def fake_popen(command, cwd):
        captured["command"] = command
        captured["cwd"] = cwd
        return object()

    monkeypatch.setattr("jobhunter.app.subprocess.Popen", fake_popen)

    start_dashboard()

    assert captured["command"][1:3] == ["-m", "streamlit"]
    assert "--server.address" in captured["command"]
    assert captured["command"][captured["command"].index("--server.address") + 1] == "127.0.0.1"


def test_main_collects_before_starting_dashboard_and_scheduler(monkeypatch):
    import jobhunter.app as app_module

    events = []

    class FakeScheduler:
        def start(self):
            events.append("scheduler-start")

        def shutdown(self, wait):
            events.append("scheduler-stop")

    class FakeDashboardProcess:
        def wait(self):
            events.append("dashboard-wait")

        def poll(self):
            return 0

    monkeypatch.setattr(app_module, "ensure_database", lambda: events.append("database"))
    monkeypatch.setattr(
        app_module,
        "create_daily_scheduler",
        lambda hour, minute: events.append("scheduler-create") or FakeScheduler(),
    )
    monkeypatch.setattr(app_module, "run_scheduled_collection", lambda: events.append("collection"))
    monkeypatch.setattr(
        app_module,
        "start_dashboard",
        lambda: events.append("dashboard-start") or FakeDashboardProcess(),
    )

    app_module.main()

    assert events.index("collection") < events.index("dashboard-start")
    assert events.index("collection") < events.index("scheduler-start")
