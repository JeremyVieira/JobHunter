"""Normalization helpers shared by every scraper and the fallback URL collector."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from jobhunter.textutils import html_to_text, normalize_salary

# Long enough to keep requirement sections that sit at the bottom of a posting.
MAX_DESCRIPTION_CHARS = 12000


def normalize_job(job: dict) -> dict:  # noqa: ANN001
    normalized = {
        "title": (job.get("title") or "Unknown role").strip(),
        "company": (job.get("company") or "Unknown").strip(),
        # A missing location is "Unknown" (never silently Montreal or Remote): the
        # location filter decides what to do with it.
        "location": (job.get("location") or "Unknown").strip(),
        "remote_status": (job.get("remote_status") or "Hybrid/Remote").strip(),
        "salary": normalize_salary(str(job.get("salary") or "")),
        "description": html_to_text(str(job.get("description") or ""))[:MAX_DESCRIPTION_CHARS],
        "posting_date": (job.get("posting_date") or "Unknown").strip(),
        "url": (job.get("url") or "").strip(),
        "source": (job.get("source") or "manual").strip(),
    }
    return normalized


def canonical_job_url(url: str) -> str:
    parsed = urlsplit((url or "").strip())
    hostname = parsed.netloc.lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    ignored_parameters = {"fbclid", "gclid", "msclkid", "ref", "referrer"}
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in ignored_parameters
        )
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), hostname, path, query, ""))


def jobspy_text(value: Any, default: str = "") -> str:
    """Stringify a JobSpy cell; jobspy emits NaN for missing values."""
    if value is None or str(value).lower() == "nan":
        return default
    return str(value).strip() or default
