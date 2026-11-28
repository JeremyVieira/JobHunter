"""Skill taxonomy and whole-word skill extraction.

The taxonomy lives in ``skills_data.json`` next to this module: each entry is
``id -> [display label, category, aliases]``. Aliases are matched as whole words
after :func:`skill_text` normalization (which, unlike ``normalize_text``, keeps
``+ # . /`` so ``c++``, ``c#``, ``.net``, ``node.js`` and ``ci/cd`` survive).
Ambiguous one-letter names (``c``, ``r``, ``go``) are only matched through
unambiguous aliases (``golang``, ``rstudio``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from jobhunter.textutils import strip_accents


def _load_skills() -> dict[str, tuple[str, str, tuple[str, ...]]]:
    raw = json.loads((Path(__file__).with_name("skills_data.json")).read_text(encoding="utf-8"))
    return {key: (label, category, tuple(aliases)) for key, (label, category, aliases) in raw.items()}


SKILLS: dict[str, tuple[str, str, tuple[str, ...]]] = _load_skills()

# Skills whose absence from a candidate's profile is a *hard* gap when the posting
# leans on them (a "Java developer" role is not a fit for someone without Java).
PRIMARY_STACK = frozenset(
    {
        "java",
        "c#",
        ".net",
        "c++",
        "php",
        "ruby",
        "go",
        "rust",
        "kotlin",
        "swift",
        "scala",
        "sap",
        "salesforce",
        "angular",
        "vue",
        "kubernetes",
        "r",
        "matlab",
    }
)

# Candidate-side implications (a PyTorch user does machine-learning work, etc.).
IMPLIED_SKILLS: dict[str, tuple[str, ...]] = {
    "gcp": ("cloud",),
    "aws": ("cloud",),
    "azure": ("cloud",),
    "pytorch": ("machine learning",),
    "tensorflow": ("machine learning",),
    "keras": ("machine learning",),
    "scikit-learn": ("machine learning",),
    "pytest": ("unit testing",),
    "junit": ("unit testing",),
    "sqlite": ("sql",),
    "postgresql": ("sql",),
    "mysql": ("sql",),
    "sql server": ("sql",),
    "pandas": ("data analysis",),
    "terraform": ("infrastructure as code",),
    "ansible": ("infrastructure as code",),
}

# "Closest experience" relationships, used only to word an honest gap statement
# ("I have not used X, my closest experience is Y"), never to claim X.
RELATED_SKILLS: dict[str, tuple[str, ...]] = {
    "aws": ("gcp", "azure"),
    "azure": ("gcp", "aws"),
    "gcp": ("aws", "azure"),
    "tensorflow": ("pytorch", "keras"),
    "keras": ("pytorch", "tensorflow"),
    "pytorch": ("tensorflow", "scikit-learn"),
    "mysql": ("sql", "postgresql", "sqlite"),
    "postgresql": ("sql", "mysql", "sqlite"),
    "sql server": ("sql", "postgresql", "mysql"),
    "oracle": ("sql", "postgresql"),
    "react": ("react native", "javascript", "svelte"),
    "angular": ("react", "typescript", "javascript", "svelte"),
    "vue": ("react", "svelte", "javascript"),
    "svelte": ("react", "javascript"),
    "typescript": ("javascript",),
    "next.js": ("react", "svelte", "javascript"),
    "jenkins": ("ci/cd", "github actions"),
    "gitlab ci": ("ci/cd", "github actions"),
    "github actions": ("ci/cd",),
    "kubernetes": ("docker",),
    "selenium": ("pytest", "test automation"),
    "cypress": ("selenium", "test automation", "javascript"),
    "tableau": ("power bi", "excel"),
    "power bi": ("excel", "tableau"),
    "spark": ("pandas", "etl"),
    "airflow": ("etl", "python"),
    "django": ("flask", "fastapi", "python"),
    "flask": ("django", "fastapi", "python"),
    "fastapi": ("flask", "django", "python"),
    "spring": ("java",),
    "express": ("node.js",),
    "node.js": ("javascript", "express"),
    ".net": ("c#", "java"),
    "c#": ("java",),
    "kotlin": ("java",),
    "swift": ("react native",),
    "terraform": ("ansible",),
    "servicenow": ("itil", "incident management"),
}

_FRENCH_AI = re.compile(r"(?<![a-z])[a-z]'ai(?![a-z])")
_SKILL_CHARS = re.compile(r"[^a-z0-9+#./]+")
_SPECIAL_DOT = re.compile(r"^[a-z0-9+#]+\.[a-z0-9]+$")


def skill_text(value: str) -> str:
    """Lowercase, accent-folded text that keeps ``+ # . /`` inside tokens."""
    lowered = strip_accents(value or "").lower().replace("’", "'")
    # French elisions ("j'ai", "n'ai", "qu'ai") are not the skill "AI"
    lowered = _FRENCH_AI.sub(" ", lowered)
    lowered = _SKILL_CHARS.sub(" ", lowered)
    tokens: list[str] = []
    for token in lowered.split():
        token = token.rstrip(".")
        if token.startswith(".") and token != ".net":
            token = token.lstrip(".")
        token = token.strip("/")
        if "." in token and not _SPECIAL_DOT.match(token) and token != ".net":
            token = token.replace(".", " ")
        if token:
            tokens.append(token)
    return " ".join(tokens)


def label_for(skill_id: str) -> str:
    entry = SKILLS.get(skill_id)
    return entry[0] if entry else skill_id


class SkillMatcher:
    """Finds taxonomy skills (plus optional custom terms) in free text."""

    def __init__(self, extra_terms: Iterable[str] = ()):
        self._patterns: dict[str, re.Pattern[str]] = {}
        for skill_id, (_, _, aliases) in SKILLS.items():
            self._patterns[skill_id] = self._compile(aliases)
        self.custom: dict[str, str] = {}
        for term in extra_terms:
            normalized = skill_text(term)
            if not normalized or self.extract(term):
                continue
            custom_id = normalized
            self.custom[custom_id] = term.strip()
            self._patterns[custom_id] = self._compile((term,))

    @staticmethod
    def _compile(aliases: Iterable[str]) -> re.Pattern[str]:
        parts = sorted(
            {re.escape(skill_text(alias)) for alias in aliases if skill_text(alias)},
            key=len,
            reverse=True,
        )
        return re.compile(r"(?<![a-z0-9+#.])(?:" + "|".join(parts) + r")(?![a-z0-9+#])")

    def extract(self, text: str) -> dict[str, int]:
        """Return ``{skill_id: mention_count}`` for skills found in ``text``."""
        normalized = skill_text(text)
        if not normalized:
            return {}
        normalized = normalized.replace("tableaux de bord", "dashboards").replace(
            "tableau de bord", "dashboard"
        )
        found: dict[str, int] = {}
        for skill_id, pattern in self._patterns.items():
            count = len(pattern.findall(normalized))
            if count:
                found[skill_id] = count
        return found

    def label(self, skill_id: str) -> str:
        return self.custom.get(skill_id) or label_for(skill_id)


@lru_cache(maxsize=32)
def get_matcher(extra_terms: tuple[str, ...] = ()) -> SkillMatcher:
    return SkillMatcher(extra_terms)


def expand_inventory(skill_ids: Iterable[str]) -> set[str]:
    """Add implied skills (GCP -> cloud, pytest -> unit testing, ...)."""
    expanded = set(skill_ids)
    for skill_id in list(expanded):
        expanded.update(IMPLIED_SKILLS.get(skill_id, ()))
    return expanded
