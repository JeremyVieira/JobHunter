from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is in sys.path when script is run directly
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from jobhunter.app import run_daily_collection
    from jobhunter.daily_report import generate_daily_report
except ModuleNotFoundError:  # pragma: no cover
    from app import run_daily_collection
    from daily_report import generate_daily_report


def run_daily_jobs_and_report():
    jobs = run_daily_collection()
    report_path = generate_daily_report(jobs[:10])
    return jobs, report_path


if __name__ == "__main__":
    run_daily_jobs_and_report()
