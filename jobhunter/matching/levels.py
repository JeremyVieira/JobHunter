"""Seniority / entry-level detection shared by scoring and filtering."""

from __future__ import annotations

from typing import Any

from jobhunter.matching.requirements import extract_required_years
from jobhunter.textutils import contains_any_term, normalize_text

ENTRY_TITLE_TERMS = (
    "junior",
    "jr",
    "entry level",
    "associate",
    "new grad",
    "graduate",
    "coordinator",
    "engineer i",
    "developer i",
    "analyst i",
    "level 1",
    "debutant",
    "debutante",
)
ENTRY_DESCRIPTION_TERMS = (
    "entry level",
    "new grad",
    "new graduate",
    "recent graduate",
    "recent graduates",
    "graduate program",
    "nouveau diplome",
    "nouvelle diplomee",
    "no experience required",
    "0 2 years",
    "0 1 year",
    "up to 2 years",
    "up to 1 year",
)


def is_entry_level(job: dict[str, Any]) -> bool:
    """Entry-level by title, explicit description wording, or a stated need of <=1 year."""
    title = normalize_text(str(job.get("title") or ""))
    if contains_any_term(title, ENTRY_TITLE_TERMS):
        return True
    description = str(job.get("description") or "")
    if contains_any_term(normalize_text(description), ENTRY_DESCRIPTION_TERMS):
        return True
    years = extract_required_years(description)
    return years is not None and years <= 1
