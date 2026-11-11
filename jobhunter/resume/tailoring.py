"""Evidence-based resume tailoring.

Tailoring here means *selecting and ordering* facts that already exist in the master
resume - never rewriting them or adding new ones:

* bullets inside each experience/project entry are reordered by how much of what the
  posting asks for they demonstrate;
* the most relevant projects are chosen from the master list (no hardcoded project
  names: any project is scored from its own bullets);
* skill groups and the items inside each group are reordered by relevance;
* optionally the summary is swapped for one of *your own* pre-written variants
  (``summary_variants.json``) chosen by role family.

Bullets may carry optional explicit tags (``- Built X [tags: gcp, terraform]``). Tags
are stripped from every rendered resume; without them skills are detected from the
bullet text automatically.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jobhunter.matching.requirements import PostingRequirements, analyze_posting
from jobhunter.matching.skills import SkillMatcher, get_matcher
from jobhunter.textutils import normalize_text

SECTION_HEADERS = {
    "PROFESSIONAL SUMMARY",
    "EXPERIENCE",
    "EDUCATION",
    "PROJECTS",
    "TECHNICAL SKILLS",
    "LANGUAGES",
    "PROFIL PROFESSIONNEL",
    "EXPÉRIENCE",
    "FORMATION",
    "COMPÉTENCES TECHNIQUES",
    "LANGUES",
    "PROJETS",
}
SUMMARY_HEADERS = {"PROFESSIONAL SUMMARY", "PROFIL PROFESSIONNEL"}
EXPERIENCE_HEADERS = {"EXPERIENCE", "EXPÉRIENCE"}
PROJECT_HEADERS = {"PROJECTS", "PROJETS"}
EDUCATION_HEADERS = {"EDUCATION", "FORMATION"}
SKILLS_HEADERS = {"TECHNICAL SKILLS", "COMPÉTENCES TECHNIQUES"}
LANGUAGE_HEADERS = {"LANGUAGES", "LANGUES"}

DATE_LINE_PATTERN = re.compile(r"(19|20)\d{2}")
TAG_RE = re.compile(r"\s*\[tags?:\s*([^\]]*)\]\s*$", re.IGNORECASE)
MAX_PROJECTS = 2

VARIANTS_FILENAME = "summary_variants.json"

FAMILY_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "data_ml",
        (
            "machine learning",
            "data scientist",
            "ml engineer",
            "ai engineer",
            "deep learning",
            "data engineer",
            "computer vision",
            "nlp",
            "artificial intelligence",
            "mlops",
            "data science",
            "apprentissage automatique",
            "scientifique de donnees",
        ),
    ),
    (
        "devops_cloud",
        (
            "devops",
            "cloud",
            "site reliability",
            "sre",
            "infrastructure",
            "platform engineer",
            "infonuagique",
        ),
    ),
    (
        "analyst",
        (
            "analyst",
            "analyste",
            "business intelligence",
            "product owner",
            "consultant",
            "bi developer",
            "functional",
        ),
    ),
    (
        "support",
        (
            "support",
            "help desk",
            "service desk",
            "technical support",
            "it support",
            "desktop",
            "technicien",
            "soutien",
        ),
    ),
    (
        "software",
        (
            "software",
            "developer",
            "engineer",
            "programmer",
            "developpeur",
            "full stack",
            "backend",
            "python",
            "qa",
            "automation",
            "ingenieur",
        ),
    ),
)


def strip_tags(line: str) -> str:
    """Remove a trailing ``[tags: ...]`` marker from a resume line."""
    return TAG_RE.sub("", line)


def split_tags(line: str) -> tuple[str, list[str]]:
    match = TAG_RE.search(line)
    if not match:
        return line, []
    tags = [tag.strip() for tag in match.group(1).split(",") if tag.strip()]
    return line[: match.start()], tags


def strip_tags_from_text(text: str) -> str:
    return "\n".join(strip_tags(line) for line in text.splitlines())


# --------------------------------------------------------------------------
# Structured view of the plain-text master resume
# --------------------------------------------------------------------------
@dataclass
class Bullet:
    line_index: int
    text: str  # without leading "-" and without tags
    tags: list[str] = field(default_factory=list)


@dataclass
class Entry:
    start: int
    end: int  # exclusive
    heading: str
    bullets: list[Bullet] = field(default_factory=list)


@dataclass
class Section:
    header: str
    start: int  # index of the header line
    end: int  # exclusive
    entries: list[Entry] = field(default_factory=list)


def parse_sections(lines: list[str]) -> list[Section]:
    sections: list[Section] = []
    header_indexes = [i for i, line in enumerate(lines) if line.strip() in SECTION_HEADERS]
    for position, start in enumerate(header_indexes):
        end = header_indexes[position + 1] if position + 1 < len(header_indexes) else len(lines)
        header = lines[start].strip()
        section = Section(header=header, start=start, end=end)
        if header in EXPERIENCE_HEADERS | PROJECT_HEADERS | EDUCATION_HEADERS:
            section.entries = _parse_entries(lines, section)
        sections.append(section)
    return sections


def _parse_entries(lines: list[str], section: Section) -> list[Entry]:
    is_project = section.header in PROJECT_HEADERS
    entries: list[Entry] = []
    current: Entry | None = None
    for index in range(section.start + 1, section.end):
        stripped = lines[index].strip()
        if not stripped:
            continue
        if stripped.startswith("-"):
            if current is None:
                continue
            text, tags = split_tags(stripped[1:].strip())
            current.bullets.append(Bullet(index, text.strip(), tags))
            continue
        starts_entry = is_project or not DATE_LINE_PATTERN.search(stripped)
        if starts_entry:
            if current is not None:
                current.end = index
            current = Entry(start=index, end=section.end, heading=stripped)
            entries.append(current)
    return entries


# --------------------------------------------------------------------------
# Posting weights
# --------------------------------------------------------------------------
def posting_weights(requirements: PostingRequirements) -> dict[str, float]:
    weights: dict[str, float] = {}
    for skill_id, mention in requirements.skills.items():
        weight = mention.weight * (1.5 if mention.in_title else 1.0)
        if mention.count >= 3:
            weight += 0.25
        weights[skill_id] = weight
    return weights


def _skills_in(text: str, tags: list[str], matcher: SkillMatcher) -> set[str]:
    found = set(matcher.extract(text))
    for tag in tags:
        found.update(matcher.extract(tag))
    return found


def bullet_score(bullet: Bullet, weights: dict[str, float], matcher: SkillMatcher) -> float:
    return sum(weights.get(skill, 0.0) for skill in _skills_in(bullet.text, bullet.tags, matcher))


def entry_score(entry: Entry, weights: dict[str, float], matcher: SkillMatcher) -> float:
    scores = sorted((bullet_score(b, weights, matcher) for b in entry.bullets), reverse=True)
    heading_score = sum(weights.get(s, 0.0) for s in matcher.extract(entry.heading))
    return sum(scores[:3]) + 0.5 * heading_score


# --------------------------------------------------------------------------
# Role family + summary variants
# --------------------------------------------------------------------------
def classify_role_family(job_title: str, job_description: str = "") -> str:
    """Coarse role family used to pick a summary variant ("default" when unclear)."""
    title = normalize_text(job_title)
    for family, terms in FAMILY_TERMS:
        if any(
            re.search(r"(?<![a-z0-9])" + re.escape(normalize_text(t)) + r"(?![a-z0-9])", title)
            for t in terms
        ):
            return family
    return "default"


def _variants_path() -> Path:
    from jobhunter.config.settings import RESUME_SOURCE_DIR

    return Path(RESUME_SOURCE_DIR) / VARIANTS_FILENAME


def load_summary_variants(language: str = "en") -> dict[str, str]:
    """Your own pre-written summaries keyed by role family (empty if none configured)."""
    path = _variants_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    variants = data.get(language, {}) if isinstance(data, dict) else {}
    if not isinstance(variants, dict):
        return {}
    return {
        str(key): str(value).strip()
        for key, value in variants.items()
        if isinstance(value, str) and value.strip() and not str(key).startswith("_")
    }


def _apply_summary_variant(lines: list[str], sections: list[Section], variant: str) -> list[str]:
    summary = next((s for s in sections if s.header in SUMMARY_HEADERS), None)
    if summary is None:
        return lines
    body = [i for i in range(summary.start + 1, summary.end) if lines[i].strip()]
    if not body:
        return lines
    new_lines = list(lines)
    new_lines[body[0]] = variant
    for index in reversed(body[1:]):
        del new_lines[index]
    return new_lines


# --------------------------------------------------------------------------
# Skills section
# --------------------------------------------------------------------------
def _item_weight(
    item: str, weights: dict[str, float], matcher: SkillMatcher, posting_norm: str
) -> float:
    ids = matcher.extract(item)
    if ids:
        return max((weights.get(skill_id, 0.0) for skill_id in ids), default=0.0)
    norm = normalize_text(item)
    if norm and re.search(r"(?<![a-z0-9])" + re.escape(norm) + r"(?![a-z0-9])", posting_norm):
        return 0.8
    return 0.0


def _reorder_skill_items(line: str, weights, matcher, posting_norm) -> tuple[str, float]:
    """Reorder a comma-separated skills bullet; never adds/removes/rewords an item."""
    prefix = "- " if line.strip().startswith("-") else ""
    body = line.strip()[1:].strip() if prefix else line.strip()
    text, tags = split_tags(body)
    items = [item.strip() for item in text.split(",") if item.strip()]
    scored = [
        (_item_weight(item, weights, matcher, posting_norm), index, item)
        for index, item in enumerate(items)
    ]
    total = sum(weight for weight, _, _ in scored)
    if total <= 0:
        return line, 0.0
    ordered = [item for _, _, item in sorted(scored, key=lambda t: (-t[0], t[1]))]
    suffix = f" [tags: {', '.join(tags)}]" if tags else ""
    return f"{prefix}{', '.join(ordered)}{suffix}", total


def _reorder_skills_section(
    lines: list[str], section: Section, weights, matcher, posting_norm
) -> list[str]:
    body = lines[section.start + 1 : section.end]
    groups: list[list[str]] = []
    for line in body:
        if not line.strip():
            if groups:
                groups[-1].append(line)
            continue
        if line.strip().startswith("-") and groups:
            groups[-1].append(line)
        else:
            groups.append([line])
    scored_groups: list[tuple[float, int, list[str]]] = []
    for index, group in enumerate(groups):
        group_total = 0.0
        new_group = []
        for line in group:
            if line.strip().startswith("-"):
                new_line, total = _reorder_skill_items(line, weights, matcher, posting_norm)
                group_total += total
                new_group.append(new_line)
            else:
                new_group.append(line)
        scored_groups.append((group_total, index, new_group))
    if any(total > 0 for total, _, _ in scored_groups):
        scored_groups.sort(key=lambda t: (-t[0], t[1]))
    rebuilt = [line for _, _, group in scored_groups for line in group]
    return lines[: section.start + 1] + rebuilt + lines[section.end :]


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------
def tailor_resume_text(
    resume_text: str,
    job_title: str,
    job_description: str = "",
    language: str = "en",
    *,
    max_projects: int = MAX_PROJECTS,
    variants: dict[str, str] | None = None,
    matcher: SkillMatcher | None = None,
) -> str:
    """Return ``resume_text`` reordered/selected for the posting (tags stripped)."""
    target = f"{job_title}\n{job_description}".strip()
    if not target or not resume_text.strip():
        return strip_tags_from_text(resume_text)

    matcher = matcher or get_matcher()
    requirements = analyze_posting(job_title, job_description, matcher)
    weights = posting_weights(requirements)
    posting_norm = normalize_text(target)

    lines = resume_text.splitlines()
    sections = parse_sections(lines)

    # 1) reorder bullets within each experience/project entry (stable on ties)
    new_lines = list(lines)
    for section in sections:
        if section.header not in EXPERIENCE_HEADERS | PROJECT_HEADERS:
            continue
        for entry in section.entries:
            if len(entry.bullets) < 2:
                continue
            ranked = sorted(
                enumerate(entry.bullets),
                key=lambda pair: (-bullet_score(pair[1], weights, matcher), pair[0]),
            )
            for slot, (_, bullet) in zip(entry.bullets, ranked, strict=True):
                new_lines[slot.line_index] = lines[bullet.line_index]
    lines = new_lines

    # 2) pick the most relevant projects (re-parse: line positions are unchanged)
    sections = parse_sections(lines)
    project_section = next((s for s in sections if s.header in PROJECT_HEADERS), None)
    if project_section and project_section.entries:
        ranked_entries = sorted(
            enumerate(project_section.entries),
            key=lambda pair: (-entry_score(pair[1], weights, matcher), pair[0]),
        )
        chosen = [entry for _, entry in ranked_entries[:max_projects]]
        chosen_lines = [line for entry in chosen for line in lines[entry.start : entry.end]]
        before = lines[: project_section.start + 1]
        after = lines[project_section.end :]
        if chosen_lines and chosen_lines[-1].strip() and after:
            chosen_lines.append("")
        lines = before + chosen_lines + after
        sections = parse_sections(lines)

    # 3) skills: reorder groups and the items inside each group
    skills_section = next((s for s in sections if s.header in SKILLS_HEADERS), None)
    if skills_section and weights:
        lines = _reorder_skills_section(lines, skills_section, weights, matcher, posting_norm)
        sections = parse_sections(lines)

    # 4) optional summary variant authored by the candidate
    variants = load_summary_variants(language) if variants is None else variants
    if variants:
        family = classify_role_family(job_title, job_description)
        variant = variants.get(family) or variants.get("default")
        if variant:
            lines = _apply_summary_variant(lines, sections, variant)

    return strip_tags_from_text("\n".join(lines))


def resume_entries(resume_text: str) -> dict[str, list[Entry]]:
    """Entries by section header (used by cover-letter evidence selection)."""
    lines = resume_text.splitlines()
    return {section.header: section.entries for section in parse_sections(lines)}


def entry_label_parts(entry: Entry) -> tuple[str, str]:
    """``("Company or project name", "role/subtitle")`` from an entry heading."""
    heading = re.sub(r"\s*\(https?://[^)]*\)", "", entry.heading).strip()
    parts = re.split(r"\s+[—–-]\s+", heading, maxsplit=1)
    name = parts[0].split(",")[0].strip() if parts else heading
    role = parts[1].strip() if len(parts) > 1 else ""
    return name, role


def metadata(resume_text: str) -> dict[str, Any]:
    """Small helper for tests/diagnostics: counts of parsed structures."""
    sections = parse_sections(resume_text.splitlines())
    return {s.header: len(s.entries) for s in sections}
