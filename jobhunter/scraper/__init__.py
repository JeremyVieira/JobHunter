"""Scraper helpers for job discovery."""

from jobhunter.models import JobListing

from .collector import collect_jobs_from_urls, fetch_job_page

__all__ = ["JobListing", "collect_jobs_from_urls", "fetch_job_page"]
