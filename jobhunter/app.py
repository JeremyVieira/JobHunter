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

# Ensure project root is in sys.path when script is run directly
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apscheduler.schedulers.background import BackgroundScheduler  # noqa: E402

try:
    from jobhunter.config.settings import (
        BASE_DIR,
        JOB_SEARCH_URLS,
        OUTPUT_DIR,
    )
    from jobhunter.daily_report import generate_daily_report
    from jobhunter.filter import filter_jobs
    from jobhunter.scoring.engine import score_jobs
    from jobhunter.scraper.collector import (
        ArbeitnowScraper,
        BaseScraper,
        JobicyScraper,
        JobSpyScraper,
        RemotiveScraper,
        canonical_job_url,
        collect_jobs_from_urls,
    )
    from jobhunter.tracker.db import (
        ensure_database,
        filter_applied_jobs,
        purge_placeholder_jobs,
        purge_red_flag_jobs,
        save_jobs,
    )
except ModuleNotFoundError:  # pragma: no cover
    from config.settings import BASE_DIR, JOB_SEARCH_URLS, OUTPUT_DIR
    from daily_report import generate_daily_report
    from filter import filter_jobs
    from scoring.engine import score_jobs
    from scraper.collector import (
        ArbeitnowScraper,
        BaseScraper,
        JobicyScraper,
        JobSpyScraper,
        RemotiveScraper,
        canonical_job_url,
        collect_jobs_from_urls,
    )
    from tracker.db import (
        ensure_database,
        filter_applied_jobs,
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
    purge_red_flag_jobs: Callable[[], Any] = purge_red_flag_jobs
    filter_applied_jobs: Callable[[Iterable[dict[str, Any]]], list[dict[str, Any]]] = (
        filter_applied_jobs
    )
    save_jobs: Callable[[list[dict[str, Any]]], int] = save_jobs
    output_dir: Path = OUTPUT_DIR


class IPipelineStage(ABC):
    """Abstract interface for a job collection pipeline stage."""

    @abstractmethod
    def process(self, context: dict[str, Any]) -> dict[str, Any]:
        pass


class ExtractionStage(IPipelineStage):
    """Scrapes raw job listings from multiple sources and deduplicates by URL."""

    def __init__(
        self, scrapers: list[BaseScraper] | None = None, fallback_urls: list[str] | None = None
    ):
        self.scrapers = scrapers or [
            JobSpyScraper(),
            JobicyScraper(),
            RemotiveScraper(),
            ArbeitnowScraper(),
        ]
        self.fallback_urls = fallback_urls or JOB_SEARCH_URLS

    def process(self, context: dict[str, Any]) -> dict[str, Any]:
        jobs: list[dict[str, Any]] = []
        for scraper in self.scrapers:
            try:
                scraped = scraper.scrape()
                jobs.extend(scraped)
            except Exception:
                LOGGER.exception("Scraper %s failed during collection.", scraper.__class__.__name__)

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
        deduped = list(deduped_by_url.values())
        context["raw_jobs"] = deduped
        return context


class ScoringStage(IPipelineStage):
    """Scores candidate jobs based on profile alignment."""

    def process(self, context: dict[str, Any]) -> dict[str, Any]:
        raw_jobs = context.get("raw_jobs", [])
        context["scored_jobs"] = score_jobs(raw_jobs)
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
        self, limit: int = 25, dependencies: CollectionDependencies | None = None
    ):
        self.limit = limit
        self.dependencies = dependencies

    def process(self, context: dict[str, Any]) -> dict[str, Any]:
        dependencies = self.dependencies or CollectionDependencies()
        filtered_jobs = context.get("filtered_jobs", [])
        unseen_jobs = dependencies.filter_applied_jobs(filtered_jobs)
        top_jobs = unseen_jobs[: self.limit]
        saved_count = dependencies.save_jobs(top_jobs)
        context["persisted_count"] = (
            saved_count if isinstance(saved_count, int) else len(top_jobs)
        )

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
        self.stages = list(stages) if stages is not None else [
            ExtractionStage(),
            ScoringStage(),
            FilteringStage(),
            PersistenceStage(dependencies=self.dependencies),
        ]
        for stage in self.stages:
            if isinstance(stage, PersistenceStage) and stage.dependencies is None:
                stage.dependencies = self.dependencies
        self._run_lock = threading.Lock()
        self.last_persisted_count = 0

    def run(self) -> list[dict[str, Any]]:
        with self._run_lock:
            self.dependencies.ensure_database()
            self.dependencies.purge_placeholder_jobs()
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
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(dashboard_path),
        "--server.address",
        "127.0.0.1",
        "--server.port",
        port,
    ]
    return subprocess.Popen(command, cwd=BASE_DIR)


def main() -> None:
    ensure_database()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    hour = int(os.getenv("JOBHUNTER_COLLECTION_HOUR", DEFAULT_COLLECTION_HOUR))
    minute = int(os.getenv("JOBHUNTER_COLLECTION_MINUTE", DEFAULT_COLLECTION_MINUTE))
    scheduler = create_daily_scheduler(hour, minute)
    run_scheduled_collection()
    dashboard_process = start_dashboard()
    scheduler.start()

    port = os.getenv("JOBHUNTER_DASHBOARD_PORT", "8501")
    print(f"Dashboard available at http://127.0.0.1:{port}")
    print(f"Daily collection scheduled for {hour:02d}:{minute:02d} local time.")
    print("Press Ctrl+C to stop JobHunterAI.")

    try:
        dashboard_process.wait()
    except KeyboardInterrupt:
        print("Stopping JobHunterAI...")
    finally:
        scheduler.shutdown(wait=False)
        if dashboard_process.poll() is None:
            dashboard_process.terminate()
            dashboard_process.wait(timeout=10)


if __name__ == "__main__":
    main()
