"""Application tracking features."""

from .db import (
    dismiss_job,
    ensure_database,
    get_job_stats,
    get_recent_jobs,
    save_application,
    save_jobs,
)

__all__ = [
    "ensure_database",
    "save_jobs",
    "save_application",
    "dismiss_job",
    "get_job_stats",
    "get_recent_jobs",
]
