"""Shared text helpers: normalization, whole-word matching, language and date parsing.

Why this module exists: several scoring and filtering checks used raw substring
tests (``"excel" in text`` matches "excellent", ``"ey" in company`` matches
"Honeywell"). Everything that needs to decide whether a *term* appears in a
piece of text should go through ``contains_term`` so matches are whole-word.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from functools import lru_cache

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_TAG_RE = re.compile(r"<[^>]+>")
_MARKDOWN_RE = re.compile(r"[*_`#]+")
_SPACE_RE = re.compile(r"\s+")


def strip_accents(value: str) -> str:
    """Return ``value`` without diacritics (``Montréal`` -> ``Montreal``)."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_text(value: str) -> str:
    """Lowercase, accent-folded text where every non-alphanumeric run is one space."""
    return _NON_ALNUM.sub(" ", strip_accents(value or "").lower()).strip()


@lru_cache(maxsize=4096)
def _term_regex(normalized_term: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9])" + re.escape(normalized_term) + r"(?![a-z0-9])")


def contains_term(normalized_text: str, term: str) -> bool:
    """True when ``term`` appears in ``normalized_text`` as whole word(s).

    ``normalized_text`` must already be passed through :func:`normalize_text`.
    The term is normalized the same way, so ``"ci/cd"`` and ``"scikit-learn"``
    match the normalized forms ``"ci cd"`` and ``"scikit learn"``.
    """
    needle = normalize_text(term)
    if not needle or not normalized_text:
        return False
    return _term_regex(needle).search(normalized_text) is not None


def contains_any_term(normalized_text: str, terms) -> bool:
    return any(contains_term(normalized_text, term) for term in terms)


def html_to_text(value: str) -> str:
    """Strip HTML tags and markdown emphasis from scraped descriptions."""
    plain = _TAG_RE.sub(" ", value or "")
    plain = _MARKDOWN_RE.sub(" ", plain)
    return _SPACE_RE.sub(" ", plain).strip()


# --------------------------------------------------------------------------
# Language detection (English vs French) - deliberately tiny, no dependencies.
# --------------------------------------------------------------------------
_FR_WORDS = frozenset(
    "le la les des une un et pour avec vous nous votre notre dans sur est sont "
    "au aux du de ce cette ces qui que poste equipe experience competences "
    "recherchons offre emploi travail connaissance maitrise exigences "
    "responsabilites candidat entreprise".split()
)
_EN_WORDS = frozenset(
    "the and for with you your our we are will this that from have has "
    "team role experience skills required responsibilities about work "
    "looking candidate company join opportunity ability strong".split()
)


def detect_language(text: str) -> str:
    """Return ``"fr"``, ``"en"`` or ``"unknown"`` using stop-word frequency."""
    tokens = normalize_text(text).split()
    if len(tokens) < 8:
        return "unknown"
    fr = sum(token in _FR_WORDS for token in tokens)
    en = sum(token in _EN_WORDS for token in tokens)
    if fr == en == 0:
        return "unknown"
    if fr > en * 1.25:
        return "fr"
    if en > fr * 1.25:
        return "en"
    return "unknown"


_BILINGUAL_TERMS = (
    "bilingual",
    "bilingue",
    "english and french",
    "french and english",
    "francais et anglais",
    "anglais et francais",
    "fluent in french",
    "fluent french",
    "francais courant",
    "maitrise du francais",
    "excellent french",
)


def mentions_bilingual(text: str) -> bool:
    norm = normalize_text(text)
    return contains_any_term(norm, _BILINGUAL_TERMS)


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------
_RELATIVE_RE = re.compile(r"(\d+)\+?\s*(hour|day|week|month)s?\s+ago", re.I)


def parse_posting_date(value: str | None, today: date | None = None) -> date | None:
    """Parse ISO dates, datetimes and simple relative phrases ("3 days ago")."""
    if not value:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"unknown", "n/a", "none", "nan", "nat"}:
        return None
    today = today or date.today()
    lowered = text.lower()
    if "today" in lowered or "just posted" in lowered or "aujourd" in lowered:
        return today
    if "yesterday" in lowered or "hier" in lowered:
        return today - timedelta(days=1)
    match = _RELATIVE_RE.search(lowered)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        days = {"hour": 0, "day": 1, "week": 7, "month": 30}[unit] * amount
        return today - timedelta(days=days)
    for candidate in (text[:10], text[:19], text):
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date()
        except ValueError:
            continue
    try:  # pragma: no cover - dateutil is a declared dependency but stay defensive
        from dateutil import parser as date_parser

        return date_parser.parse(text, fuzzy=True).date()
    except (ImportError, ValueError, OverflowError):
        return None


def days_since(value: str | None, today: date | None = None) -> int | None:
    parsed = parse_posting_date(value, today)
    if parsed is None:
        return None
    return ((today or date.today()) - parsed).days
