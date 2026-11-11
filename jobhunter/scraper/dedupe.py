"""Cross-source de-duplication.

The same opening usually appears on several boards (LinkedIn, Indeed, the company's
own ATS...) under different URLs. URL-only dedupe keeps every copy, which wastes
review time and makes the best copy random. Here duplicates are keyed by
(company, title, city); the copy from the employer's own ATS wins, with the longest
description kept.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from jobhunter.filter import MONTREAL_AREA_TERMS
from jobhunter.textutils import contains_any_term, normalize_text

# Lower number = more authoritative copy of the posting.
SOURCE_PRIORITY: dict[str, int] = {
    "greenhouse": 0,
    "lever": 0,
    "ashby": 0,
    "workable": 0,
    "smartrecruiters": 0,
    "recruitee": 0,
    "workday": 0,
    "company-career-page": 0,
    "themuse": 1,
    "adzuna": 2,
    "jooble": 2,
    "remotive": 2,
    "jobicy": 2,
    "arbeitnow": 2,
    "indeed": 3,
    "linkedin": 3,
    "zip_recruiter": 3,
    "glassdoor": 3,
    "google": 3,
}
_COMPANY_SUFFIX = re.compile(r"\b(inc|ltd|ltee|limited|corp|corporation|llc|canada|group|co)\b")


def _company_key(company: str) -> str:
    return " ".join(_COMPANY_SUFFIX.sub(" ", normalize_text(company)).split())


def _city_key(location: str) -> str:
    norm = normalize_text(location)
    if contains_any_term(norm, MONTREAL_AREA_TERMS):
        return "montreal"
    if contains_any_term(norm, ("remote",)):
        return "remote"
    return normalize_text(str(location or "").split(",")[0])


def identity(company: Any, title: Any) -> tuple[str, str]:
    """(company, title) identity used to recognise a role you already applied to/dismissed."""
    return _company_key(str(company or "")), normalize_text(str(title or ""))


def dedupe_key(job: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _company_key(str(job.get("company") or "")),
        normalize_text(str(job.get("title") or "")),
        _city_key(str(job.get("location") or "")),
    )


def _rank(job: dict[str, Any]) -> tuple[int, int]:
    priority = SOURCE_PRIORITY.get(str(job.get("source") or "").lower().split(":")[0], 4)
    return priority, -len(str(job.get("description") or ""))


def dedupe_jobs(jobs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse postings that are the same role at the same company in the same city."""
    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str]] = []
    for job in jobs:
        key = dedupe_key(job)
        if not key[0] or not key[1] or key[0] == "unknown":
            # cannot safely merge records with no usable identity
            key = (f"__unique__{len(order)}", key[1], key[2])
        current = best.get(key)
        if current is None:
            best[key] = dict(job)
            order.append(key)
            continue
        winner, loser = (job, current) if _rank(job) < _rank(current) else (current, job)
        merged = dict(winner)
        if len(str(loser.get("description") or "")) > len(str(merged.get("description") or "")):
            merged["description"] = loser["description"]
        best[key] = merged
    return [best[key] for key in order]
