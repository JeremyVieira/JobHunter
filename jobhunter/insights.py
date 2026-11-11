"""Insights computed from the postings you have already collected.

* ``skills_to_learn`` - what your best-scoring postings ask for that you cannot yet claim;
* ``top_matched_skills`` - the skills that carry most of your matches;
* ``filter_and_sort_jobs`` - dashboard filtering, search and ordering.

Everything works from the ``match_details`` the scorer stores with each job, so nothing here
re-reads postings or guesses.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import date
from typing import Any

from jobhunter.textutils import days_since, normalize_text
from jobhunter.tracker.db import parse_match_details


def _skills_block(job: dict[str, Any]) -> dict[str, Any]:
    return parse_match_details(job.get("match_details")).get("skills", {}) or {}


def skills_to_learn(
    jobs: Iterable[dict[str, Any]], *, min_fit: float = 60.0, top_n: int = 12
) -> list[dict[str, Any]]:
    """Skills missing from your record that recur across postings worth applying to.

    Only postings scoring at least ``min_fit`` count, so one-off requirements of poor
    matches do not drown out what your realistic targets keep asking for. A skill named as a
    hard-stack gap counts as a gap in that posting too, never twice.
    """
    analysed = 0
    postings: Counter[str] = Counter()
    hard_gaps: Counter[str] = Counter()
    for job in jobs:
        if float(job.get("fit_score") or 0) < min_fit:
            continue
        skills = _skills_block(job)
        if not skills:
            continue
        analysed += 1
        missing = set(skills.get("missing_required", [])) | set(skills.get("core_gaps", []))
        for skill in missing:
            postings[skill] += 1
        for skill in skills.get("core_gaps", []):
            hard_gaps[skill] += 1
    rows = [
        {
            "skill": skill,
            "postings": count,
            "share": round(100 * count / analysed) if analysed else 0,
            "hard_stack_gap": hard_gaps.get(skill, 0),
        }
        for skill, count in postings.most_common(top_n)
    ]
    return rows


def top_matched_skills(
    jobs: Iterable[dict[str, Any]], *, min_fit: float = 60.0, top_n: int = 10
) -> list[dict[str, Any]]:
    """Skills you already have that most often satisfy a requirement in good postings."""
    analysed = 0
    counts: Counter[str] = Counter()
    for job in jobs:
        if float(job.get("fit_score") or 0) < min_fit:
            continue
        skills = _skills_block(job)
        if not skills:
            continue
        analysed += 1
        counts.update(set(skills.get("matched", [])))
    return [
        {
            "skill": skill,
            "postings": count,
            "share": round(100 * count / analysed) if analysed else 0,
        }
        for skill, count in counts.most_common(top_n)
    ]


def analysed_job_count(jobs: Iterable[dict[str, Any]], min_fit: float = 60.0) -> int:
    return sum(
        1 for job in jobs if float(job.get("fit_score") or 0) >= min_fit and _skills_block(job)
    )


def source_breakdown(jobs: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(job.get("source") or "unknown") for job in jobs)
    return dict(counts.most_common())


SORT_OPTIONS = ("Best match", "Newest", "Company A-Z")


def filter_and_sort_jobs(
    jobs: Iterable[dict[str, Any]],
    *,
    min_score: float = 0.0,
    sources: Iterable[str] | None = None,
    query: str = "",
    max_age_days: int | None = None,
    sort: str = "Best match",
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Filter by score/source/text/age and order the result (pure; no I/O)."""
    wanted_sources = {s for s in (sources or []) if s}
    needle = normalize_text(query)
    kept: list[dict[str, Any]] = []
    for job in jobs:
        if float(job.get("fit_score") or 0) < min_score:
            continue
        if wanted_sources and str(job.get("source") or "unknown") not in wanted_sources:
            continue
        if needle:
            haystack = normalize_text(
                " ".join(
                    str(job.get(k) or "") for k in ("title", "company", "location", "description")
                )
            )
            if not all(token in haystack for token in needle.split()):
                continue
        if max_age_days is not None:
            age = days_since(str(job.get("posting_date") or ""), today)
            if age is not None and age > max_age_days:
                continue
        kept.append(job)

    if sort == "Newest":

        def newest_key(job: dict[str, Any]):
            age = days_since(str(job.get("posting_date") or ""), today)
            return (age if age is not None else 10**6, -float(job.get("fit_score") or 0))

        kept.sort(key=newest_key)
    elif sort == "Company A-Z":
        kept.sort(
            key=lambda job: (
                normalize_text(str(job.get("company") or "")),
                -float(job.get("fit_score") or 0),
            )
        )
    else:
        kept.sort(key=lambda job: -float(job.get("fit_score") or 0))
    return kept
