"""Fetch fuller descriptions for postings that only arrived with a snippet.

Scoring is only as good as the text it sees. Aggregator results (Adzuna, Jooble, some
JobSpy sites) often carry two or three sentences, so skills and years of experience go
unseen. For the few postings that survive the cheap title/location filters we fetch
the posting page and read its schema.org ``JobPosting`` JSON-LD - the same data search
engines read. Sites that forbid scraping or need a login (LinkedIn, Indeed, Glassdoor,
ZipRecruiter, Google) are never fetched here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

try:
    from jobhunter.config import settings as _settings
    from jobhunter.filter import (
        _title_matches_target,
        is_montreal_area_or_remote,
        location_is_unknown,
    )
    from jobhunter.scraper.collector import (
        CompanyCareerPageScraper,
        _polite_sleep,
        _request_get,
        is_excluded_title,
    )
except ModuleNotFoundError:  # pragma: no cover
    from config import settings as _settings
    from filter import _title_matches_target, is_montreal_area_or_remote, location_is_unknown
    from scraper.collector import (
        CompanyCareerPageScraper,
        _polite_sleep,
        _request_get,
        is_excluded_title,
    )

LOGGER = logging.getLogger(__name__)

BLOCKED_HOSTS = ("linkedin.com", "indeed.com", "glassdoor.", "ziprecruiter.com", "google.com")
SHORT_DESCRIPTION_CHARS = 300


def _host_blocked(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(blocked in host for blocked in BLOCKED_HOSTS)


def worth_enriching(job: dict[str, Any]) -> bool:
    """Cheap pre-filter: plausible title, not management, local or unknown location."""
    title = str(job.get("title") or "")
    if is_excluded_title(title) or not _title_matches_target(title):
        return False
    location = str(job.get("location") or "")
    return location_is_unknown(location) or is_montreal_area_or_remote(location)


def enrich_descriptions(
    jobs: list[dict[str, Any]],
    *,
    min_length: int = SHORT_DESCRIPTION_CHARS,
    max_fetches: int | None = None,
    fetcher: Callable[..., Any] | None = None,
) -> int:
    """Replace short descriptions in-place with fuller JobPosting text. Returns #enriched."""
    limit = max_fetches if max_fetches is not None else int(getattr(_settings, "ENRICH_MAX_FETCHES", 40))
    fetch = fetcher or _request_get
    fetched = enriched = 0
    for job in jobs:
        description = str(job.get("description") or "")
        url = str(job.get("url") or "")
        if len(description) >= min_length or not url or _host_blocked(url) or not worth_enriching(job):
            continue
        if fetched >= limit:
            break
        fetched += 1
        try:
            _polite_sleep()
            response = fetch(url, headers=CompanyCareerPageScraper.HEADERS, timeout=20)
            candidates = CompanyCareerPageScraper._parse_page(
                response.text, str(job.get("company") or ""), url
            )
        except Exception:
            LOGGER.debug("Description enrichment failed for %s", url, exc_info=True)
            continue
        fuller = max((str(c.get("description") or "") for c in candidates), key=len, default="")
        if len(fuller) > len(description):
            job["description"] = fuller
            enriched += 1
    return enriched
