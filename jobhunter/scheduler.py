from __future__ import annotations

from jobhunter.app import run_daily_collection
from jobhunter.daily_report import generate_daily_report


def run_daily_jobs_and_report():
    jobs = run_daily_collection()
    report_path = generate_daily_report(jobs[:10])
    return jobs, report_path


if __name__ == "__main__":
    run_daily_jobs_and_report()
