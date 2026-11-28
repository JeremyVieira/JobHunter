"""Quality filters that drop mismatched or low-quality postings before scoring/storage."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from jobhunter.config.defaults import (
    COLLECTION_ESTABLISHED_COMPANIES,
    MANAGEMENT_TITLE_TERMS,
    TINY_STARTUP_SIGNAL_TERMS,
)
from jobhunter.textutils import contains_any_term, normalize_text

# Company-name fragments that signal the poster is hiding who they are, which
# correlates strongly with low-quality or scammy postings (fake "confidential"
# listings, resume-harvesting, recruiting-agency spam with no real employer named).
SHADY_COMPANY_NAME_TERMS = (
    "confidential",
    "undisclosed",
    "anonymous",
    "stealth",
    "various clients",
    "a client of",
    "our client",
)

# Description-level red flags for scams / pyramid-scheme-adjacent postings and
# postings that aren't real jobs (unpaid, pay-to-apply, "guaranteed income" spam).
SHADY_DESCRIPTION_TERMS = (
    "unpaid position",
    "no salary",
    "equity only",
    "must pay",
    "training fee",
    "pay to apply",
    "registration fee",
    "guaranteed income",
    "be your own boss",
    "unlimited earning potential",
    "wire transfer",
    "processing fee",
    "send your bank details",
)

# A real posting almost always runs longer than this; a description this thin is
# usually a stub/spam listing rather than an actual job ad worth reading.
MIN_DESCRIPTION_LENGTH = 80


def _normalize_for_filter(value: str) -> str:
    return normalize_text(value or "")


def is_excluded_title(title: str) -> bool:
    """True if a title is a structural mismatch (management/executive) regardless
    of how well the rest of the posting reads. Whole-word match; entry-level
    "Associate Product Manager" programs are the one exception."""
    text = _normalize_for_filter(title)
    if contains_any_term(text, ("associate product manager", "apm")):
        return False
    return contains_any_term(text, MANAGEMENT_TITLE_TERMS)


def is_shady_posting(job: dict[str, Any]) -> bool:
    """True for postings that look like spam, scams, or resume-harvesting rather
    than a real job: an unnamed employer, pay-to-apply / unpaid-position language,
    or a description too thin to be a genuine ad."""
    company = _normalize_for_filter(job.get("company", ""))
    description = _normalize_for_filter(job.get("description", ""))

    if contains_any_term(company, SHADY_COMPANY_NAME_TERMS):
        return True
    if contains_any_term(description, SHADY_DESCRIPTION_TERMS):
        return True
    if description and len(description) < MIN_DESCRIPTION_LENGTH:
        return True
    return False


def is_likely_tiny_startup(job: dict[str, Any]) -> bool:
    """Best-effort proxy for 'tiny/very early-stage company'. Free scraping APIs
    don't expose employee counts or funding data, so this only catches companies
    whose own name or job description self-identifies as small/early-stage. It
    will under-flag (a real tiny startup that doesn't say so in the JD slips
    through) but should rarely over-flag a genuinely established employer."""
    company = _normalize_for_filter(job.get("company", ""))
    if contains_any_term(company, COLLECTION_ESTABLISHED_COMPANIES):
        return False
    if contains_any_term(company, ("labs", "forge", "ventures", "startup")):
        return True
    description = _normalize_for_filter(job.get("description", ""))
    if contains_any_term(description, TINY_STARTUP_SIGNAL_TERMS):
        return True
    return False


def filter_relevant_jobs(
    jobs: Iterable[dict[str, Any]],
    exclude_tiny_startups: bool = True,
) -> list[dict[str, Any]]:
    """Drop management/executive titles, shady/spammy postings, and (optionally)
    self-described tiny/early-stage startups from a combined jobs list.

    Call this once, after merging results from all scrapers and before handing the
    list to scoring.score_jobs() (which also filters management titles by default)
    or to the persistence layer, so mismatched/low-quality postings don't clutter
    storage either. Set exclude_tiny_startups=False if you'd rather see small
    companies ranked normally instead of removed — the signal is best-effort, so
    over-filtering is possible.
    """
    filtered = [job for job in jobs if not is_excluded_title(job.get("title", ""))]
    filtered = [job for job in filtered if not is_shady_posting(job)]
    if exclude_tiny_startups:
        filtered = [job for job in filtered if not is_likely_tiny_startup(job)]
    return filtered
