"""Structured resume model shared by the DOCX and PDF renderers.

The master/tailored resume is plain text. This module turns it into a typed document
(contact block, sections, entries with company/location/role/dates/links, skill groups)
and holds the *formatting-only* helpers the renderers need:

* contact line cleanup: no street address or postal code, short link labels;
* date normalisation (``April 2024 - Current`` -> ``Apr 2024 – Present``);
* link extraction (``Project repository: https://...`` becomes a link on the heading);
* metric emphasis (numbers like ``123%`` or ``$1M`` are bolded).

Nothing here adds, removes or rewrites content; it only decides how existing text is shown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from jobhunter.resume.tailoring import (
    DATE_LINE_PATTERN,
    EDUCATION_HEADERS,
    EXPERIENCE_HEADERS,
    LANGUAGE_HEADERS,
    PROJECT_HEADERS,
    SECTION_HEADERS,
    SKILLS_HEADERS,
    SUMMARY_HEADERS,
    link_bullet_url,
    strip_tags,
)

# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass
class Link:
    label: str
    url: str


@dataclass
class Contact:
    location: str = ""
    phone: str = ""
    email: str = ""
    links: list[Link] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)  # e.g. "Dual Citizenship"


@dataclass
class Entry:
    kind: str  # "experience" | "education" | "project"
    name: str
    location: str = ""
    role: str = ""
    dates: str = ""
    links: list[Link] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)


@dataclass
class SkillGroup:
    label: str
    items: str


@dataclass
class Section:
    kind: str  # summary | experience | education | projects | skills | languages | other
    title: str
    paragraphs: list[str] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)
    skills: list[SkillGroup] = field(default_factory=list)


@dataclass
class ResumeDoc:
    name: str
    contact: Contact
    sections: list[Section] = field(default_factory=list)


# --------------------------------------------------------------------------
# Contact block
# --------------------------------------------------------------------------
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[\d(][\d\s().\-]{7,}\d$")
_URL_RE = re.compile(r"^(?:https?://|www\.)", re.IGNORECASE)
_DOMAIN_RE = re.compile(r"^[\w.-]+\.(?:com|ca|io|dev|org|net|me|co)(?:/\S*)?$", re.IGNORECASE)
_POSTAL_CA = re.compile(r"\s*,?\s*\b[A-Za-z]\d[A-Za-z][ -]?\d[A-Za-z]\d\b")
_ZIP_US = re.compile(r"\s*,?\s*\b\d{5}(?:-\d{4})?\b")
# "558 Gounod" or "558 Gounod, Montréal": a civic number followed by a street name
_STREET_RE = re.compile(r"^\d+[A-Za-z]?\s+[^\d@/:,]+(?:,\s*(?P<rest>[^\d@/:]+))?$")


def short_url(url: str) -> str:
    """``https://www.linkedin.com/in/name/`` -> ``linkedin.com/in/name``."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower().removeprefix("www.")
    return f"{host}{parsed.path}".rstrip("/")


def link_label(url: str) -> str:
    """Compact label for a link shown next to a heading: ``GitHub``, ``LinkedIn`` or the domain."""
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower().removeprefix("www.")
    if host.endswith("github.com"):
        return "GitHub"
    if host.endswith("linkedin.com"):
        return "LinkedIn"
    return host or url


def clean_location(text: str) -> str:
    """Drop postal/ZIP codes from a location (``Montreal, H2R 1B9`` -> ``Montreal``)."""
    return _clean_location(text)


def _clean_location(text: str) -> str:
    text = _POSTAL_CA.sub("", text)
    text = _ZIP_US.sub("", text)
    return re.sub(r"\s*,\s*$", "", text).strip()


def looks_like_street(item: str) -> bool:
    """``558 Gounod`` / ``123 Example Street``: a street address, not a phone number."""
    item = item.strip()
    return bool(_STREET_RE.match(_clean_location(item))) and not _PHONE_RE.match(item) and "@" not in item


def has_postal_code(item: str) -> bool:
    return bool(_POSTAL_CA.search(item) or _ZIP_US.search(item)) and not _PHONE_RE.match(item.strip())


def header_items(text: str) -> list[str]:
    """Raw contact items (split on ``|``) between the name line and the first section."""
    lines = [strip_tags(line).strip() for line in text.splitlines()]
    first_section = next((i for i, line in enumerate(lines) if line in SECTION_HEADERS), len(lines))
    items: list[str] = []
    for raw in lines[1:first_section]:
        items.extend(part.strip() for part in raw.split("|") if part.strip())
    return items


def parse_contact(items: list[str], include_street: bool = False) -> Contact:
    """Classify header items. Street addresses are dropped unless ``include_street``."""
    contact = Contact()
    for raw in items:
        item = raw.strip()
        if not item:
            continue
        if _EMAIL_RE.match(item):
            contact.email = contact.email or item
        elif _URL_RE.match(item) or _DOMAIN_RE.match(item):
            url = item if "://" in item else f"https://{item}"
            contact.links.append(Link(short_url(url), url))
        elif _PHONE_RE.match(item):
            contact.phone = contact.phone or item
        elif _STREET_RE.match(_clean_location(item)):
            street = _STREET_RE.match(_clean_location(item))
            city = (street.group("rest") or "").strip() if street else ""
            if include_street and not contact.location:
                contact.location = item
            elif city and not contact.location:
                contact.location = _clean_location(city)  # keep "Montréal", drop "558 Gounod"
            # otherwise: a street address has no place on a resume
        elif not contact.location:
            contact.location = _clean_location(item)
        else:
            contact.extras.append(item)
    return contact


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------
_EN_MONTHS = {
    "january": "Jan", "february": "Feb", "march": "Mar", "april": "Apr", "may": "May",
    "june": "Jun", "july": "Jul", "august": "Aug", "september": "Sep", "sept": "Sep",
    "october": "Oct", "november": "Nov", "december": "Dec",
}
_ONGOING_EN = re.compile(r"\b(current|currently|present|ongoing|now|today)\b", re.IGNORECASE)
_ONGOING_FR = re.compile(r"\b(en cours|actuel|actuellement|aujourd['’]hui|pr[ée]sent)\b", re.IGNORECASE)
_MONTH_RE = re.compile(r"\b(" + "|".join(sorted(_EN_MONTHS, key=len, reverse=True)) + r")\b", re.IGNORECASE)


def format_dates(text: str) -> str:
    """Normalise a date range for display: abbreviated months, en dash, ``Present``."""
    out = text.strip()
    french = bool(_ONGOING_FR.search(out))
    out = _ONGOING_FR.sub("Présent", out)
    out = _ONGOING_EN.sub("Présent" if french else "Present", out)
    out = _MONTH_RE.sub(lambda m: _EN_MONTHS[m.group(1).lower()], out)
    out = re.sub(r"\s*[-–—]\s*", " – ", out)
    return re.sub(r"\s+", " ", out).strip()


# --------------------------------------------------------------------------
# Metric emphasis
# --------------------------------------------------------------------------
_METRIC_RE = re.compile(
    r"(?<![\w.\-/$€£])"
    r"(?P<num>(?:[$€£]\s?)?\d[\d,]*(?:\.\d+)?)"
    r"(?P<unit>\s?(?:%|\+|[kKmMbB]\+?(?![A-Za-z])|[xX](?![A-Za-z])))?"
    r"(?![\w\-/])"
)


def _is_metric(num: str, unit: str | None) -> bool:
    digits = re.sub(r"[^\d]", "", num)
    if unit or num[:1] in "$€£":
        return True
    if "." in num:  # versions like 3.12 or ratios without a unit are not highlights
        return False
    if re.fullmatch(r"(?:19|20)\d{2}", digits):  # a year
        return False
    return len(digits) >= 2 or "," in num


def emphasize_metrics(text: str) -> list[tuple[str, bool]]:
    """Split ``text`` into ``(segment, is_metric)`` pieces; metrics are numbers with units
    (``123%``, ``$1M``, ``50+``) or plain numbers of two or more digits (``298``)."""
    segments: list[tuple[str, bool]] = []
    cursor = 0
    for match in _METRIC_RE.finditer(text):
        if not _is_metric(match.group("num"), match.group("unit")):
            continue
        if match.start() > cursor:
            segments.append((text[cursor : match.start()], False))
        segments.append((match.group(0), True))
        cursor = match.end()
    if cursor < len(text):
        segments.append((text[cursor:], False))
    return segments or [(text, False)]


# --------------------------------------------------------------------------
# Headings
# --------------------------------------------------------------------------
_HEADING_SPLIT = re.compile(r"\s+[—–]\s+|\s+-\s+")
_PAREN_URL = re.compile(r"\s*\((https?://[^)\s]+)\)")


def split_heading(heading: str, kind: str) -> tuple[str, str, str, list[Link]]:
    """``"Company, City — Title"`` -> ``(name, location, role, links)``.

    A URL in parentheses (``Plazio (https://plazio.io/en) — Capstone``) becomes a link.
    Projects keep their whole left side as the name (no location split).
    """
    links: list[Link] = []
    for match in _PAREN_URL.finditer(heading):
        links.append(Link(link_label(match.group(1)), match.group(1)))
    cleaned = _PAREN_URL.sub("", heading).strip()
    parts = _HEADING_SPLIT.split(cleaned, maxsplit=1)
    left = parts[0].strip()
    role = parts[1].strip() if len(parts) > 1 else ""
    if kind == "project":
        return left, "", role, links
    name, _, location = left.partition(",")
    return name.strip(), location.strip(), role, links


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
_SECTION_KIND = (
    ("summary", SUMMARY_HEADERS),
    ("experience", EXPERIENCE_HEADERS),
    ("education", EDUCATION_HEADERS),
    ("projects", PROJECT_HEADERS),
    ("skills", SKILLS_HEADERS),
    ("languages", LANGUAGE_HEADERS),
)


def _kind_for(header: str) -> str:
    for kind, headers in _SECTION_KIND:
        if header in headers:
            return kind
    return "other"


def parse_resume(text: str, include_street: bool = False) -> ResumeDoc:
    """Parse a (tailored or master) plain-text resume into a :class:`ResumeDoc`."""
    lines = [strip_tags(line).strip() for line in text.splitlines()]
    first_section = next((i for i, line in enumerate(lines) if line in SECTION_HEADERS), len(lines))
    name = lines[0] if lines else ""
    items: list[str] = []
    for raw in lines[1:first_section]:
        items.extend(part.strip() for part in raw.split("|") if part.strip())
    doc = ResumeDoc(name=name, contact=parse_contact(items, include_street))

    section: Section | None = None
    entry: Entry | None = None
    group: SkillGroup | None = None
    for line in lines[first_section:]:
        if not line:
            continue
        if line in SECTION_HEADERS:
            section = Section(kind=_kind_for(line), title=line)
            doc.sections.append(section)
            entry = None
            group = None
            continue
        if section is None:
            continue

        if section.kind in {"summary", "languages"}:
            section.paragraphs.append(line.lstrip("- ").strip())
        elif section.kind == "skills":
            if line.startswith("-"):
                items_text = line[1:].strip()
                if group is None:
                    group = SkillGroup("", items_text)
                    section.skills.append(group)
                else:
                    group.items = f"{group.items}, {items_text}" if group.items else items_text
            else:
                group = SkillGroup(line.rstrip(":"), "")
                section.skills.append(group)
        elif section.kind in {"experience", "education", "projects"}:
            kind = "project" if section.kind == "projects" else section.kind
            if line.startswith("-"):
                if entry is None:
                    continue
                bullet = line[1:].strip()
                url = link_bullet_url(bullet)
                if url:
                    entry.links.append(Link(link_label(url), url))
                else:
                    entry.bullets.append(bullet)
            elif entry is not None and not entry.dates and not entry.bullets and (
                section.kind != "projects" and DATE_LINE_PATTERN.search(line)
            ):
                entry.dates = format_dates(line)
            else:
                name_, location, role, links = split_heading(line, kind)
                entry = Entry(kind, name_, location, role, links=links)
                section.entries.append(entry)
        else:
            section.paragraphs.append(line.lstrip("- ").strip())
    return doc


def contact_items(contact: Contact) -> list[str]:
    """Plain-text contact items in display order (for tests and the TXT/ATS view)."""
    items = [contact.location, contact.phone, contact.email]
    items += [link.label for link in contact.links]
    items += contact.extras
    return [item for item in items if item]
