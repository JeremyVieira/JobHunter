"""Evidence-based cover letters.

Every sentence about the candidate is built from a real bullet in the master resume
that matches something the posting asks for. Nothing is invented: no company
research, no claimed skills the resume lacks, no numbers that are not in the resume.
A company-specific line is only included when *you* supply it (``company_hook``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

try:
    from jobhunter.matching.requirements import (
        analyze_posting,
        candidate_inventory,
        closest_related,
        compare_requirements,
    )
    from jobhunter.matching.skills import SkillMatcher, get_matcher
    from jobhunter.resume.tailoring import (
        EDUCATION_HEADERS,
        EXPERIENCE_HEADERS,
        LANGUAGE_HEADERS,
        PROJECT_HEADERS,
        SUMMARY_HEADERS,
        Entry,
        classify_role_family,
        entry_label_parts,
        parse_sections,
        posting_weights,
    )
    from jobhunter.textutils import normalize_text
except ModuleNotFoundError:  # pragma: no cover
    from matching.requirements import (
        analyze_posting,
        candidate_inventory,
        closest_related,
        compare_requirements,
    )
    from matching.skills import SkillMatcher, get_matcher
    from resume.tailoring import (
        EDUCATION_HEADERS,
        EXPERIENCE_HEADERS,
        LANGUAGE_HEADERS,
        PROJECT_HEADERS,
        SUMMARY_HEADERS,
        Entry,
        classify_role_family,
        entry_label_parts,
        parse_sections,
        posting_weights,
    )
    from textutils import normalize_text

_MONTHS = {
    "jan": 1, "january": 1, "janvier": 1, "feb": 2, "february": 2, "fevrier": 2,
    "mar": 3, "march": 3, "mars": 3, "apr": 4, "april": 4, "avril": 4, "may": 5, "mai": 5,
    "jun": 6, "june": 6, "juin": 6, "jul": 7, "july": 7, "juillet": 7, "aug": 8,
    "august": 8, "aout": 8, "sep": 9, "sept": 9, "september": 9, "septembre": 9,
    "oct": 10, "october": 10, "octobre": 10, "nov": 11, "november": 11, "novembre": 11,
    "dec": 12, "december": 12, "decembre": 12,
}
_ONGOING = ("current", "present", "aujourd", "en cours", "actuel")
_FLUENT = ("fluent", "native", "courant", "bilingue", "langue maternelle", "maternelle")


@dataclass
class Evidence:
    entry_key: tuple[str, int]
    kind: str  # "experience" | "project"
    name: str
    text: str
    skills: set[str]


@dataclass
class Education:
    school: str
    degree: str
    completed: bool


def _lower_first(text: str) -> str:
    first = text.split(" ", 1)[0] if text else ""
    if len(first) > 1 and first[0].isupper() and first[1:].islower():
        return text[0].lower() + text[1:]
    return text


def _join_list(items: list[str], conjunction: str) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {conjunction} " + items[-1]


def _parse_education(entry: Entry, lines: list[str], today: date) -> Education | None:
    heading = entry.heading
    parts = re.split(r"\s+[—–-]\s+", heading, maxsplit=1)
    school = parts[0].split(",")[0].strip()
    degree = parts[1].strip() if len(parts) > 1 else ""
    if not school or not degree:
        return None
    completed = False
    for index in range(entry.start + 1, entry.end):
        line = lines[index].strip()
        years = re.findall(r"(?:19|20)\d{2}", line)
        if not years:
            continue
        norm = normalize_text(line)
        if any(word in norm for word in _ONGOING):
            completed = False
            break
        end_year = int(years[-1])
        last_segment = re.split(r"\s+[—–-]\s+|\s+to\s+|\s+a\s+", line)[-1]
        month = next(
            (_MONTHS[token] for token in normalize_text(last_segment).split() if token in _MONTHS),
            None,
        )
        if month is None:
            completed = end_year < today.year
        else:
            completed = (end_year, month) <= (today.year, today.month)
        break
    return Education(school=school, degree=degree, completed=completed)


def _language_claim(lines: list[str], sections) -> str | None:
    """``"fluent"`` when both languages are listed as fluent, ``"bilingual"`` when only the
    summary says so, else ``None``."""
    language_section = next((s for s in sections if s.header in LANGUAGE_HEADERS), None)
    if language_section:
        body = [
            normalize_text(lines[i])
            for i in range(language_section.start + 1, language_section.end)
            if lines[i].strip()
        ]
        fluent = [line for line in body if any(word in line for word in _FLUENT)]
        wants = {"french": ("french", "francais"), "english": ("english", "anglais")}
        if all(any(any(alias in line for alias in aliases) for line in fluent) for aliases in wants.values()):
            return "fluent"
    summary = next((s for s in sections if s.header in SUMMARY_HEADERS), None)
    if summary:
        text = normalize_text(" ".join(lines[summary.start + 1: summary.end]))
        if "bilingual" in text or "bilingue" in text:
            return "bilingual"
    return None


def _evidence_candidates(resume_text: str, matcher: SkillMatcher, prefer_projects: bool):
    lines = resume_text.splitlines()
    sections = parse_sections(lines)
    candidates: list[Evidence] = []
    ordering = [(PROJECT_HEADERS, "project"), (EXPERIENCE_HEADERS, "experience")]
    if not prefer_projects:
        ordering.reverse()
    for headers, kind in ordering:
        for section in sections:
            if section.header not in headers:
                continue
            for index, entry in enumerate(section.entries):
                name, _ = entry_label_parts(entry)
                for bullet in entry.bullets:
                    skills = set(matcher.extract(bullet.text))
                    for tag in bullet.tags:
                        skills.update(matcher.extract(tag))
                    candidates.append(
                        Evidence((section.header, index), kind, name, bullet.text.rstrip(". "), skills)
                    )
    education = None
    for section in sections:
        if section.header in EDUCATION_HEADERS and section.entries:
            education = _parse_education(section.entries[0], lines, date.today())
            break
    return candidates, education, _language_claim(lines, sections)


def select_evidence(candidates: list[Evidence], weights: dict[str, float], max_items: int = 3) -> list[Evidence]:
    """Greedy cover: best new-requirement coverage first, at most one bullet per entry."""
    chosen: list[Evidence] = []
    covered: set[str] = set()
    used: set[tuple[str, int]] = set()
    while len(chosen) < max_items:
        best: Evidence | None = None
        best_gain = 0.0
        for candidate in candidates:
            if candidate.entry_key in used:
                continue
            gain = sum(weights[s] for s in candidate.skills if s in weights and s not in covered)
            if gain > best_gain + 1e-9:
                best, best_gain = candidate, gain
        if best is None:
            break
        chosen.append(best)
        covered |= best.skills & set(weights)
        used.add(best.entry_key)
    return chosen


def _fallback_evidence(candidates: list[Evidence], count: int = 2) -> list[Evidence]:
    chosen: list[Evidence] = []
    used: set[tuple[str, int]] = set()
    for candidate in candidates:
        if candidate.entry_key in used:
            continue
        chosen.append(candidate)
        used.add(candidate.entry_key)
        if len(chosen) == count:
            break
    return chosen


def _sentence_en(item: Evidence) -> str:
    lead = f"In my role at {item.name}" if item.kind == "experience" else f"In my {item.name} project"
    first = item.text.split(" ", 1)[0].lower()
    if first.endswith("ing"):
        return f"{lead}, my work included {_lower_first(item.text)}."
    return f"{lead}, I {_lower_first(item.text)}."


def _sentence_fr(item: Evidence) -> str:
    lead = f"Chez {item.name}" if item.kind == "experience" else f"Dans le projet {item.name}"
    first = item.text.split(" ", 1)[0].lower()
    if first.endswith(("é", "i", "u")) and len(first) > 2:
        return f"{lead}, j'ai {_lower_first(item.text)}."
    return f"{lead} : {_lower_first(item.text)}."


def build_cover_letter(
    job_title: str,
    company_name: str,
    job_description: str,
    resume_text: str,
    *,
    language: str = "en",
    user_name: str = "",
    user_location: str = "",
    company_hook: str = "",
    mention_gaps: bool = True,
) -> str:
    fr = language == "fr"
    title = job_title or ("poste recherché" if fr else "Software Engineer")
    company = company_name or ("votre organisation" if fr else "Hiring Company")
    signoff = ("Cordialement," if fr else "Sincerely,") + f"\n{user_name}\n{user_location}"
    salutation = "Madame, Monsieur," if fr else f"Dear {company} Hiring Team,"

    matcher = get_matcher()
    requirements = analyze_posting(job_title, job_description, matcher)
    weights = posting_weights(requirements)
    family = classify_role_family(job_title, job_description)
    candidates, education, language_claim = _evidence_candidates(
        resume_text, matcher, prefer_projects=family in {"software", "data_ml", "devops_cloud", "default"}
    )
    inventory = candidate_inventory((), resume_text, matcher)
    comparison = compare_requirements(requirements, inventory)

    evidence = select_evidence(candidates, weights) or _fallback_evidence(candidates)

    # --- paragraph 1: the role, optional user-written hook, education
    opening = (
        f"Je vous soumets ma candidature au poste de {title} chez {company}."
        if fr
        else f"I am writing to apply for the {title} position at {company}."
    )
    p1 = [opening]
    if company_hook.strip():
        p1.append(company_hook.strip())
    if education:
        if fr:
            p1.append(
                f"Mon parcours académique : {education.degree}, {education.school}."
                if education.completed
                else f"Je poursuis actuellement mes études : {education.degree}, {education.school}."
            )
        else:
            p1.append(
                f"I hold a {education.degree} from {education.school}."
                if education.completed
                else f"I am completing a {education.degree} at {education.school}."
            )
    paragraphs = [" ".join(p1)]

    # --- paragraph 2: evidence mapped to the posting
    if evidence:
        matched_ids = [s for s in comparison.matched if s in weights]
        labels = [matcher.label(s) for s in matched_ids[:3]]
        if fr:
            intro = (
                f"L'offre met l'accent sur {_join_list(labels, 'et')}. Voici où mon expérience correspond :"
                if labels
                else "Voici l'expérience que j'apporterais à ce poste :"
            )
            body = " ".join(_sentence_fr(item) for item in evidence)
        else:
            intro = (
                f"Your posting emphasizes {_join_list(labels, 'and')}. Here is where my experience lines up:"
                if labels
                else "Here is the experience I would bring to this role:"
            )
            body = " ".join(_sentence_en(item) for item in evidence)
        paragraphs.append(f"{intro} {body}")

    # --- paragraph 3: honest gap + bilingual (only when supported by the resume)
    extras: list[str] = []
    if mention_gaps:
        for gap in comparison.core_gaps[:1]:
            related = closest_related(gap, inventory)
            if related:
                if fr:
                    extras.append(
                        f"Je n'ai pas encore travaillé avec {matcher.label(gap)}; "
                        f"l'outil le plus proche que j'ai utilisé est {matcher.label(related)}."
                    )
                else:
                    extras.append(
                        f"I have not yet worked with {matcher.label(gap)}; the closest tool I have "
                        f"used is {matcher.label(related)}."
                    )
    posting_norm = normalize_text(f"{title} {job_description}")
    wants_french = requirements.bilingual or requirements.language == "fr" or "french" in posting_norm or "francais" in posting_norm
    if language_claim and wants_french:
        if fr:
            extras.append("Je travaille couramment en français et en anglais." if language_claim == "fluent" else "Je suis bilingue (français et anglais).")
        else:
            extras.append("I am fluent in both English and French." if language_claim == "fluent" else "I am bilingual in English and French.")
    if extras:
        paragraphs.append(" ".join(extras))

    if not evidence and not education:
        paragraphs.append(
            "Vous trouverez mon curriculum vitæ en pièce jointe." if fr else "I have included my resume for your review."
        )

    closing = (
        f"Je serais heureux de discuter de ma contribution possible chez {company}. Merci de votre temps et de votre considération."
        if fr
        else f"I would welcome the opportunity to discuss how I can contribute to {company}. Thank you for your time and consideration."
    )
    return "\n\n".join([salutation, *paragraphs, closing, signoff])
