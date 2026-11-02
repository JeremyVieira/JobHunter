"""Extract what a posting asks for and compare it with what a candidate has.

The comparison is deliberately evidence-based: a skill only counts for the
candidate when it appears in their profile keywords or their own master resume.
Nothing here ever *adds* skills to a resume or letter.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

try:
    from jobhunter.matching.skills import (
        PRIMARY_STACK,
        RELATED_SKILLS,
        SkillMatcher,
        expand_inventory,
        get_matcher,
    )
    from jobhunter.textutils import (
        detect_language,
        html_to_text,
        mentions_bilingual,
        normalize_text,
    )
except ModuleNotFoundError:  # pragma: no cover
    from matching.skills import (
        PRIMARY_STACK,
        RELATED_SKILLS,
        SkillMatcher,
        expand_inventory,
        get_matcher,
    )
    from textutils import detect_language, html_to_text, mentions_bilingual, normalize_text

LEVEL_WEIGHTS = {"required": 1.0, "mentioned": 0.8, "preferred": 0.4}
_LEVEL_RANK = {"preferred": 0, "mentioned": 1, "required": 2}

_PREFERRED_CUES = (
    "nice to have", "preferred", "bonus", "an asset", "asset", "a plus", "is a plus",
    "would be a plus", "ideally", "familiarity with", "exposure to", "an advantage",
    "atout", "est un atout", "un plus", "souhaite", "souhaitable", "idealement",
)
_REQUIRED_CUES = (
    "required", "requirements", "must have", "must", "minimum", "essential",
    "qualifications", "what you bring", "you have", "you will bring", "proficiency in",
    "proficient", "strong knowledge", "exigences", "exige", "requis", "requise",
    "profil recherche", "competences requises", "vous possedez", "vous avez",
    "ce que vous apportez", "doit",
)
_NEUTRAL_HEADINGS = (
    "responsibilities", "about", "benefits", "what you will do", "what you ll do",
    "perks", "we offer", "why join", "our team", "responsabilites", "avantages",
    "a propos", "ce que nous offrons", "your role",
)

_SENTENCE_SPLIT = re.compile(r"(?:\n+|(?<=[.!?;])\s+|\s*[•·▪●◦]\s*)")


@dataclass
class SkillMention:
    skill_id: str
    level: str = "mentioned"
    count: int = 1
    in_title: bool = False

    @property
    def weight(self) -> float:
        return LEVEL_WEIGHTS[self.level]


@dataclass
class PostingRequirements:
    skills: dict[str, SkillMention] = field(default_factory=dict)
    years_required: int | None = None
    language: str = "unknown"
    bilingual: bool = False


@dataclass
class SkillMatch:
    matched: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    missing_preferred: list[str] = field(default_factory=list)
    core_gaps: list[str] = field(default_factory=list)
    coverage: float | None = None  # 0-100, None when the posting names no known skills
    total_weight: float = 0.0

    def to_dict(self, matcher: SkillMatcher | None = None) -> dict:
        label = (matcher or get_matcher()).label
        return {
            "matched": [label(s) for s in self.matched],
            "missing_required": [label(s) for s in self.missing_required],
            "missing_preferred": [label(s) for s in self.missing_preferred],
            "core_gaps": [label(s) for s in self.core_gaps],
            "coverage": None if self.coverage is None else round(self.coverage, 1),
        }


# --------------------------------------------------------------------------
# Years of experience
# --------------------------------------------------------------------------
_RANGE_RE = re.compile(
    r"(?<![\d.])(\d{1,2})\s*(?:\+)?\s*(?:-|–|—|to|à)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?|ans)\b"
)
_SINGLE_RE = re.compile(r"(?<![\d.])(\d{1,2})\s*\+?\s*(?:years?|yrs?|ans)\b")
_EXPERIENCE_WORDS = (
    "experience", "expérience", "experiencia", "exp.", "minimum", "at least", "required",
    "requires", "must have", "au moins", "exigé", "exigée", "of hands-on", "hands-on",
)


def extract_required_years(description: str) -> int | None:
    """Largest *minimum* years-of-experience figure that is tied to "experience".

    Ranges use their lower bound ("2-4 years" -> 2). Numbers with no requirement
    context (company age, "for 20 years we...") and implausible values (>=15) are
    ignored; "3+ years" counts as a requirement even without the word "experience". Returns ``None`` when nothing is stated.
    """
    text = html_to_text(description or "").lower()
    if not text:
        return None
    candidates: list[int] = []
    consumed: list[tuple[int, int]] = []

    def window_has_experience(start: int, end: int) -> bool:
        window = text[max(0, start - 60): end + 60]
        # "3+ years Java" states a requirement even without the word "experience"
        return "+" in text[start:end] or any(word in window for word in _EXPERIENCE_WORDS)

    for match in _RANGE_RE.finditer(text):
        consumed.append(match.span())
        low = int(match.group(1))
        if low < 15 and window_has_experience(*match.span()):
            candidates.append(low)
    for match in _SINGLE_RE.finditer(text):
        if any(start <= match.start() < end for start, end in consumed):
            continue
        value = int(match.group(1))
        if value < 15 and window_has_experience(*match.span()):
            candidates.append(value)
    if candidates:
        return max(candidates)
    if re.search(r"\bno (?:prior |previous )?(?:work )?experience (?:is )?(?:required|necessary|needed)", text):
        return 0
    return None


# --------------------------------------------------------------------------
# Posting analysis
# --------------------------------------------------------------------------
def _has_cue(normalized: str, cues: Iterable[str]) -> bool:
    return any(re.search(r"(?<![a-z0-9])" + re.escape(cue) + r"(?![a-z0-9])", normalized) for cue in cues)


def analyze_posting(title: str, description: str, matcher: SkillMatcher | None = None) -> PostingRequirements:
    matcher = matcher or get_matcher()
    plain = description or ""
    # keep newlines for heading detection; only strip tags/markdown emphasis
    plain = re.sub(r"<(?:br|/p|/li|/h\d)\s*/?>", "\n", plain, flags=re.I)
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"[*_`#]+", " ", plain)

    result = PostingRequirements(
        years_required=extract_required_years(description),
        language=detect_language(f"{title}. {plain}"),
        bilingual=mentions_bilingual(f"{title}. {plain}"),
    )

    def register(skill_id: str, level: str, count: int, in_title: bool = False) -> None:
        current = result.skills.get(skill_id)
        if current is None:
            result.skills[skill_id] = SkillMention(skill_id, level, count, in_title)
            return
        current.count += count
        current.in_title = current.in_title or in_title
        if _LEVEL_RANK[level] > _LEVEL_RANK[current.level]:
            current.level = level

    for skill_id, count in matcher.extract(title).items():
        register(skill_id, "required", count, in_title=True)

    section = "mentioned"
    for raw_segment in _SENTENCE_SPLIT.split(plain):
        segment = raw_segment.strip()
        if not segment:
            continue
        norm = normalize_text(segment)
        if not norm:
            continue
        is_heading = len(segment) <= 70 and (segment.endswith(":") or len(norm.split()) <= 5)
        if is_heading:
            if _has_cue(norm, _PREFERRED_CUES):
                section = "preferred"
            elif _has_cue(norm, _REQUIRED_CUES):
                section = "required"
            elif _has_cue(norm, _NEUTRAL_HEADINGS):
                section = "mentioned"
        level = section
        if _has_cue(norm, _PREFERRED_CUES):
            level = "preferred"
        elif _has_cue(norm, _REQUIRED_CUES):
            level = "required"
        for skill_id, count in matcher.extract(segment).items():
            register(skill_id, level, count)
    return result


# --------------------------------------------------------------------------
# Candidate inventory and comparison
# --------------------------------------------------------------------------
def candidate_inventory(
    keywords: Iterable[str] = (),
    resume_text: str | None = None,
    matcher: SkillMatcher | None = None,
) -> set[str]:
    """Skill ids the candidate can truthfully claim (profile keywords + resume)."""
    matcher = matcher or get_matcher(tuple(keywords))
    inventory: set[str] = set()
    for keyword in keywords:
        found = matcher.extract(keyword)
        if found:
            inventory.update(found)
        else:
            from_custom = [cid for cid, original in matcher.custom.items() if original == keyword.strip()]
            inventory.update(from_custom)
    if resume_text:
        inventory.update(matcher.extract(resume_text))
    return expand_inventory(inventory)


def compare_requirements(
    requirements: PostingRequirements, inventory: set[str]
) -> SkillMatch:
    match = SkillMatch()
    weight_total = 0.0
    weight_have = 0.0
    for skill_id, mention in sorted(requirements.skills.items(), key=lambda kv: -kv[1].weight):
        weight_total += mention.weight
        if skill_id in inventory:
            weight_have += mention.weight
            match.matched.append(skill_id)
            continue
        if mention.level == "preferred":
            match.missing_preferred.append(skill_id)
        else:
            match.missing_required.append(skill_id)
        prominent = mention.in_title or mention.level == "required" or mention.count >= 3
        if skill_id in PRIMARY_STACK and prominent:
            match.core_gaps.append(skill_id)
    match.total_weight = weight_total
    match.coverage = (100.0 * weight_have / weight_total) if weight_total else None
    return match


def skill_score_from_match(match: SkillMatch, no_evidence_score: float = 35.0) -> float:
    """Convert coverage into a 10-100 score, shrinking toward 50 on thin evidence."""
    if match.coverage is None:
        return no_evidence_score
    confidence = min(1.0, match.total_weight / 4.0)
    blended = match.coverage * confidence + 50.0 * (1.0 - confidence)
    return max(10.0, min(100.0, round(blended, 2)))


def closest_related(skill_id: str, inventory: set[str]) -> str | None:
    """Closest skill the candidate really has to ``skill_id``, if the taxonomy knows one."""
    for related in RELATED_SKILLS.get(skill_id, ()):
        if related in inventory:
            return related
    return None
