from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler  # noqa: E402

from jobhunter.config.settings import (
    BASE_DIR,
    JOB_SEARCH_URLS,
    MAX_PERSISTED_JOBS,
    OUTPUT_DIR,
)
from jobhunter.daily_report import generate_daily_report
from jobhunter.filter import filter_jobs
from jobhunter.scoring.engine import score_jobs
from jobhunter.scoring.feedback import FeedbackModel
from jobhunter.scraper.collector import (
    BaseScraper,
    canonical_job_url,
    collect_jobs_from_urls,
)
from jobhunter.scraper.dedupe import dedupe_jobs
from jobhunter.scraper.enrich import enrich_descriptions
from jobhunter.scraper.sources import build_default_scrapers
from jobhunter.tracker.db import (
    ensure_database,
    filter_applied_jobs,
    get_feedback_examples,
    purge_nonlocal_jobs,
    purge_placeholder_jobs,
    purge_red_flag_jobs,
    save_jobs,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_COLLECTION_HOUR = 8
DEFAULT_COLLECTION_MINUTE = 0


@dataclass(frozen=True)
class CollectionDependencies:
    """Local database and output dependencies for one collection pipeline."""

    ensure_database: Callable[[], Any] = ensure_database
    purge_placeholder_jobs: Callable[[], Any] = purge_placeholder_jobs
    purge_nonlocal_jobs: Callable[[], Any] = purge_nonlocal_jobs
    purge_red_flag_jobs: Callable[[], Any] = purge_red_flag_jobs
    filter_applied_jobs: Callable[[Iterable[dict[str, Any]]], list[dict[str, Any]]] = (
        filter_applied_jobs
    )
    save_jobs: Callable[[list[dict[str, Any]]], int] = save_jobs
    output_dir: Path = OUTPUT_DIR


class IPipelineStage(ABC):
    """Abstract interface for a job collection pipeline stage."""

    @abstractmethod
    def process(self, context: dict[str, Any]) -> dict[str, Any]: ...


class ExtractionStage(IPipelineStage):
    """Scrapes raw job listings from multiple sources and deduplicates by URL."""

    def __init__(
        self, scrapers: list[BaseScraper] | None = None, fallback_urls: list[str] | None = None
    ):
        # Every configured source: aggregators for breadth, employer ATS boards and
        # career pages for fresher first-party postings (see scraper/sources.py).
        self.scrapers = scrapers or build_default_scrapers()
        self.fallback_urls = fallback_urls or JOB_SEARCH_URLS

    def process(self, context: dict[str, Any]) -> dict[str, Any]:
        jobs: list[dict[str, Any]] = []
        source_counts: dict[str, int] = {}
        for scraper in self.scrapers:
            name = scraper.__class__.__name__
            try:
                scraped = scraper.scrape()
                jobs.extend(scraped)
                source_counts[name] = len(scraped)
                if not scraped and getattr(scraper, "companies", None) is not None:
                    LOGGER.info("%s returned 0 postings (no boards configured).", name)
                else:
                    LOGGER.info("%s returned %s postings.", name, len(scraped))
            except Exception:
                source_counts[name] = 0
                LOGGER.exception("Scraper %s failed during collection.", name)
        context["source_counts"] = source_counts

        if not jobs:
            try:
                jobs = collect_jobs_from_urls(self.fallback_urls)
            except Exception:
                LOGGER.exception("Fallback URL collection failed.")

        deduped_by_url = {}
        for job in jobs:
            url = str(job.get("url") or "").strip()
            if url:
                deduped_by_url[canonical_job_url(url)] = job
        # Same role listed on several boards: keep the employer's own copy, longest text.
        deduped = dedupe_jobs(deduped_by_url.values())
        # Aggregator snippets hide skills/years; fetch fuller text for plausible local roles.
        try:
            enriched = enrich_descriptions(deduped)
            context["enriched_descriptions"] = enriched
        except Exception:
            LOGGER.exception("Description enrichment failed; scoring with available text.")
        context["raw_jobs"] = deduped
        return context


class ScoringStage(IPipelineStage):
    """Scores candidate jobs based on profile alignment."""

    def __init__(self, feedback: FeedbackModel | None = None, use_feedback: bool = True):
        self.feedback = feedback
        self.use_feedback = use_feedback

    def _feedback_model(self) -> FeedbackModel | None:
        """Preference model from what you applied to vs dismissed (inactive until enough data)."""
        if self.feedback is not None or not self.use_feedback:
            return self.feedback
        try:
            liked, disliked = get_feedback_examples()
            model = FeedbackModel(liked, disliked)
            return model if model.active else None
        except Exception:
            LOGGER.debug("Preference feedback unavailable; scoring without it.", exc_info=True)
            return None

    def process(self, context: dict[str, Any]) -> dict[str, Any]:
        raw_jobs = context.get("raw_jobs", [])
        context["scored_jobs"] = score_jobs(raw_jobs, feedback=self._feedback_model())
        return context


class FilteringStage(IPipelineStage):
    """Filters scored jobs according to target criteria and threshold."""

    def process(self, context: dict[str, Any]) -> dict[str, Any]:
        scored_jobs = context.get("scored_jobs", [])
        context["filtered_jobs"] = filter_jobs(scored_jobs)
        return context


class PersistenceStage(IPipelineStage):
    """Persists top filtered jobs to database repository and exports JSON."""

    def __init__(
        self, limit: int | None = None, dependencies: CollectionDependencies | None = None
    ):
        self.limit = limit if limit is not None else MAX_PERSISTED_JOBS
        self.dependencies = dependencies

    def process(self, context: dict[str, Any]) -> dict[str, Any]:
        dependencies = self.dependencies or CollectionDependencies()
        filtered_jobs = context.get("filtered_jobs", [])
        unseen_jobs = dependencies.filter_applied_jobs(filtered_jobs)
        top_jobs = unseen_jobs[: self.limit]
        saved_count = dependencies.save_jobs(top_jobs)
        context["persisted_count"] = saved_count if isinstance(saved_count, int) else len(top_jobs)

        output_path = dependencies.output_dir / "daily_jobs.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=output_path.parent,
                prefix=f".{output_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as output_file:
                json.dump(top_jobs, output_file, indent=2, ensure_ascii=False)
                temporary_path = Path(output_file.name)
            os.replace(temporary_path, output_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return context


class JobCollectionPipeline:
    """Orchestrates end-to-end collection, scoring, filtering, and persistence."""

    def __init__(
        self,
        stages: list[IPipelineStage] | None = None,
        *,
        dependencies: CollectionDependencies | None = None,
    ):
        self.dependencies = dependencies or CollectionDependencies()
        self.stages = (
            list(stages)
            if stages is not None
            else [
                ExtractionStage(),
                ScoringStage(),
                FilteringStage(),
                PersistenceStage(dependencies=self.dependencies),
            ]
        )
        for stage in self.stages:
            if isinstance(stage, PersistenceStage) and stage.dependencies is None:
                stage.dependencies = self.dependencies
        self._run_lock = threading.Lock()
        self.last_persisted_count = 0

    def run(self) -> list[dict[str, Any]]:
        with self._run_lock:
            self.dependencies.ensure_database()
            self.dependencies.purge_placeholder_jobs()
            self.dependencies.purge_nonlocal_jobs()
            self.dependencies.purge_red_flag_jobs()
            context: dict[str, Any] = {}
            for stage in self.stages:
                context = stage.process(context)
            self.last_persisted_count = context.get("persisted_count", 0)
            return context.get("filtered_jobs", [])


# Default pipeline instance
_default_pipeline = JobCollectionPipeline()


def run_daily_collection() -> list[dict]:
    return _default_pipeline.run()


def run_scheduled_collection() -> None:
    """Collect jobs and write the dashboard data without stopping the server."""
    try:
        jobs = run_daily_collection()
        report_path = generate_daily_report(jobs[:10])
        persisted_count = getattr(_default_pipeline, "last_persisted_count", 0)
        LOGGER.info(
            "Scheduled collection found %s eligible jobs, persisted %s, report: %s",
            len(jobs),
            persisted_count,
            report_path,
        )
    except Exception:
        LOGGER.exception("Scheduled collection failed.")


def create_daily_scheduler(
    hour: int = DEFAULT_COLLECTION_HOUR, minute: int = DEFAULT_COLLECTION_MINUTE
) -> BackgroundScheduler:
    """Create a scheduler that collects jobs once a day at the requested local time."""
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("hour must be 0-23 and minute must be 0-59")

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_scheduled_collection,
        trigger="cron",
        hour=hour,
        minute=minute,
        id="daily-job-collection",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler


def start_dashboard() -> subprocess.Popen:
    """Launch Streamlit as a child process so app.py remains the only command required."""
    dashboard_path = BASE_DIR / "dashboard" / "app.py"
    port = os.getenv("JOBHUNTER_DASHBOARD_PORT", "8501")
    # Loopback by default: the dashboard has no login and shows personal job-search data.
    host = os.getenv("JOBHUNTER_DASHBOARD_HOST", "127.0.0.1")
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(dashboard_path),
        "--server.address",
        host,
        "--server.port",
        port,
        "--browser.gatherUsageStats",
        "false",
    ]
    # Local runs open a browser tab; containers/servers set JOBHUNTER_DASHBOARD_HEADLESS=true.
    if os.getenv("JOBHUNTER_DASHBOARD_HEADLESS", "").strip().lower() in {"1", "true", "yes"}:
        command += ["--server.headless", "true"]
    return subprocess.Popen(command, cwd=BASE_DIR)


def main() -> None:
    ensure_database()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    hour = int(os.getenv("JOBHUNTER_COLLECTION_HOUR", DEFAULT_COLLECTION_HOUR))
    minute = int(os.getenv("JOBHUNTER_COLLECTION_MINUTE", DEFAULT_COLLECTION_MINUTE))
    scheduler = create_daily_scheduler(hour, minute)
    # Dashboard first: the first collection can take minutes, so run it in the background
    # instead of making the app look unresponsive (and failing container health checks).
    dashboard_process = start_dashboard()
    scheduler.start()
    scheduler.add_job(run_scheduled_collection, id="startup-collection")

    port = os.getenv("JOBHUNTER_DASHBOARD_PORT", "8501")
    print(f"Dashboard available at http://localhost:{port}")
    print("Collecting jobs in the background; refresh the dashboard as results arrive.")
    print(f"Daily collection scheduled for {hour:02d}:{minute:02d} local time.")
    print("Press Ctrl+C to stop JobHunter.")

    try:
        dashboard_process.wait()
    except KeyboardInterrupt:
        print("Stopping JobHunter...")
    finally:
        scheduler.shutdown(wait=False)
        if dashboard_process.poll() is None:
            dashboard_process.terminate()
            dashboard_process.wait(timeout=10)


if __name__ == "__main__":
    main()
