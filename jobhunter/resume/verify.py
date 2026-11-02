"""Mechanical fabrication checks for generated application documents.

These checks make "no made-up information" enforceable instead of assumed:

* a tailored resume may only contain lines that exist in the master resume (skill
  lists may be reordered, nothing else may change) - except a summary variant you
  wrote yourself;
* a cover letter may not contain numbers or known skills that appear in neither your
  resume nor the job posting.

``verify_*`` functions return human-readable issue strings; an empty list means clean.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

try:
    from jobhunter.matching.skills import get_matcher
    from jobhunter.resume.tailoring import SECTION_HEADERS, strip_tags
    from jobhunter.textutils import html_to_text, normalize_text
except ModuleNotFoundError:  # pragma: no cover
    from matching.skills import get_matcher
    from resume.tailoring import SECTION_HEADERS, strip_tags
    from textutils import html_to_text, normalize_text

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?%?")


def _norm_line(line: str) -> str:
    return " ".join(strip_tags(line).split())


def _skill_items(line: str) -> frozenset[str]:
    body = strip_tags(line).strip()
    if body.startswith("-"):
        body = body[1:].strip()
    return frozenset(item.strip().lower() for item in body.split(",") if item.strip())


def verify_resume(
    tailored_text: str,
    master_text: str,
    allowed_extra_lines: Iterable[str] = (),
) -> list[str]:
    """Lines in ``tailored_text`` that are not (a reordering of) master-resume lines."""
    master_lines = {_norm_line(line) for line in master_text.splitlines() if line.strip()}
    master_item_sets = {
        _skill_items(line) for line in master_text.splitlines() if "," in line and line.strip().startswith("-")
    }
    extras = {" ".join(line.split()) for line in allowed_extra_lines}
    issues: list[str] = []
    for raw in tailored_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line in SECTION_HEADERS:
            continue
        normalized = _norm_line(line)
        if normalized in master_lines or normalized in extras:
            continue
        if line.startswith("-") and _skill_items(line) in master_item_sets:
            continue
        issues.append(f"Resume line not found in master resume: {line[:100]}")
    return issues


def _numbers(text: str) -> set[str]:
    return {match.group(0).replace(",", ".") for match in _NUMBER_RE.finditer(text)}


def verify_letter(
    letter: str,
    resume_text: str,
    posting_text: str = "",
    allowed_text: Iterable[str] = (),
) -> list[str]:
    """Numbers and taxonomy skills in ``letter`` that neither resume nor posting contain."""
    source = "\n".join([resume_text, html_to_text(posting_text), *allowed_text])
    source_numbers = _numbers(source)
    matcher = get_matcher()
    source_skills = set(matcher.extract(source))
    issues: list[str] = []
    for number in sorted(_numbers(letter) - source_numbers):
        issues.append(f"Number in letter not found in resume or posting: {number}")
    for skill_id in sorted(set(matcher.extract(letter)) - source_skills):
        issues.append(f"Skill in letter not found in resume or posting: {matcher.label(skill_id)}")
    return issues


def unsupported_resume_skills(letter: str, resume_text: str) -> list[str]:
    """Skills a letter *claims* that the resume does not contain (stricter than verify_letter)."""
    matcher = get_matcher()
    resume_skills = set(matcher.extract(resume_text))
    return [matcher.label(s) for s in sorted(set(matcher.extract(letter)) - resume_skills)]


def normalized_words(text: str) -> set[str]:
    return set(normalize_text(text).split())
