"""Resume audit: find what weakens a master resume and say how to fix it.

``python -m jobhunter resume-audit`` reads your master resume and reports structure,
privacy and content problems the way a recruiter reviewing it would: missing results,
duty-style bullets, vague phrasing, skills with no supporting evidence, unlinked projects,
inconsistent dates. It never rewrites your resume and never invents a number; for bullets
that state no measurable result it asks *you* the question that would surface a real one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from jobhunter.matching.skills import get_matcher
from jobhunter.resume.layout import (
    Entry,
    ResumeDoc,
    emphasize_metrics,
    has_postal_code,
    header_items,
    looks_like_street,
    parse_resume,
)
from jobhunter.resume.tailoring import SECTION_HEADERS, strip_tags
from jobhunter.textutils import detect_language, normalize_text

ERROR, WARN, INFO = "error", "warn", "info"

_WEAK_PHRASES = (
    "responsible for", "worked on", "work on", "helped", "assisted with", "various", "etc",
    "duties included", "involved in", "participated in", "other tasks", "and more",
    "responsable de", "divers", "participé à",
)
_PAST_IRREGULAR = {
    "built", "led", "wrote", "ran", "drove", "made", "taught", "spoke", "chose", "sold", "held",
    "kept", "met", "won", "began", "brought", "grew", "found", "gave", "got", "set", "put", "cut",
    "oversaw", "shipped", "sent", "spent", "took", "thought", "understood", "undertook",
}
_PRESENT_BASES = {
    "resolve", "collaborate", "author", "build", "develop", "maintain", "manage", "lead", "design",
    "implement", "create", "write", "support", "coordinate", "analyze", "provide", "deliver",
    "troubleshoot", "monitor", "configure", "test", "deploy", "automate", "partner", "own", "run",
    "work", "help", "assist", "gather", "document", "train", "mentor", "optimize", "improve",
}
# (whole-word pattern, question). First match wins, so specific prompts come first.
_PROMPTS = (
    (r"model|models|classification|classifier|pipeline|train\w*|accuracy|dataset|datasets|experiments?|"
     r"neural|resnet\w*|cnn|mlp|clustering|preprocessing|augmentation",
     "What accuracy / F1 / precision did it reach, on how much data, compared with which baseline?"),
    (r"tests?|testing|coverage|qa|pytest|unit|integration",
     "How many tests? Coverage before and after? Bugs caught or releases protected?"),
    (r"collaborat\w*|cross-functional|stakeholders?|partner\w*|teams?|agile",
     "With how many teams, people or locations? What did the collaboration produce or speed up?"),
    (r"documentation|knowledge|articles?|guides?|procedures?|runbooks?",
     "How many articles/guides? Who uses them (how many people)? Did tickets or onboarding time drop?"),
    (r"incidents?|tickets?|helpdesk|resolve\w*|troubleshoot\w*|downtime|outages?",
     "How many tickets/incidents per week or month? Average time to resolve? Share resolved at first contact? Users or sites covered?"),
    (r"app|mobile|interface|frontend|dashboard|map|maps|navigation|routing|directions|tracking",
     "How many users/screens/features? Any result: load time, tasks completed, adoption, feedback?"),
    (r"api|apis|integrat\w*|queue|backend|database|sql|schema|infrastructure|terraform|provision\w*|deploy\w*",
     "How much volume (requests, records, emails) does it handle? Latency, reliability or cost result?"),
    (r"build|built|develop\w*|implement\w*|create\w*|automat\w*",
     "What did it replace or save (hours, cost, errors)? How many users, requests or records does it handle?"),
)

_DEFAULT_PROMPT = (
    "Scale (how many / how often), result (faster, cheaper, fewer errors, % better) and scope "
    "(users, teams, systems)? Use only numbers you can back up."
)


@dataclass
class Finding:
    severity: str  # error | warn | info
    area: str
    message: str
    where: str = ""
    fix: str = ""


@dataclass
class AuditReport:
    findings: list[Finding] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    worksheet: list[tuple[str, str, str]] = field(default_factory=list)  # (where, bullet, question)

    def count(self, severity: str) -> int:
        return sum(f.severity == severity for f in self.findings)

    @property
    def has_errors(self) -> bool:
        return self.count(ERROR) > 0


def _words(text: str) -> int:
    return len(re.findall(r"\w[\w'’-]*", text))


def _has_metric(text: str) -> bool:
    return any(is_metric for _, is_metric in emphasize_metrics(text))


def _first_word(text: str) -> str:
    match = re.match(r"[A-Za-zÀ-ÿ]+", text.strip())
    return match.group(0).lower() if match else ""


def _is_past(word: str) -> bool:
    return word in _PAST_IRREGULAR or (word.endswith("ed") and len(word) > 3)


def _prompt_for(bullet: str) -> str:
    norm = normalize_text(bullet)
    for pattern, question in _PROMPTS:
        if re.search(rf"\b(?:{pattern})\b", norm):
            return question
    return _DEFAULT_PROMPT


def _entry_where(entry: Entry) -> str:
    return f"{entry.name}" + (f" ({entry.role})" if entry.role else "")


def _ongoing(dates: str) -> bool:
    return bool(re.search(r"present|current|now|présent|aujourd", dates, re.IGNORECASE))


def audit_resume(text: str, language: str | None = None) -> AuditReport:
    """Audit plain-text master-resume ``text`` (``[tags: ...]`` markers are ignored)."""
    clean = "\n".join(strip_tags(line) for line in text.splitlines())
    language = language or ("fr" if detect_language(clean) == "fr" else "en")
    doc: ResumeDoc = parse_resume(clean, include_street=True)
    report = AuditReport()
    add = report.findings.append

    # ---- header / privacy -------------------------------------------------
    items = header_items(clean)
    for item in items:
        if looks_like_street(item):
            add(Finding(WARN, "Header", "Street address in the header.", item,
                        "Remove it. Recruiters only need your city; the generated resumes already omit it."))
        elif has_postal_code(item):
            add(Finding(INFO, "Header", "Postal/ZIP code in the header.", item,
                        "Drop it (generated resumes remove it automatically)."))
    contact = doc.contact
    if not contact.email:
        add(Finding(ERROR, "Header", "No email address found.", fix="Add a professional email."))
    if not contact.phone:
        add(Finding(INFO, "Header", "No phone number found.", fix="Optional, but many recruiters call first."))
    if not any("github.com" in link.url for link in contact.links):
        add(Finding(WARN, "Header", "No GitHub link.", fix="Software roles expect one; link your best repositories."))
    if not any("linkedin.com" in link.url for link in contact.links):
        add(Finding(INFO, "Header", "No LinkedIn link."))

    # ---- summary -----------------------------------------------------------
    summary = " ".join(p for s in doc.sections if s.kind == "summary" for p in s.paragraphs)
    summary_words = _words(summary)
    if not summary:
        add(Finding(WARN, "Summary", "No summary.", fix="Add 2-3 lines: who you are, what you target, your strongest proof."))
    else:
        if summary_words < 25 or summary_words > 70:
            add(Finding(WARN, "Summary", f"Summary is {summary_words} words; aim for roughly 30-60.",
                        fix="Lead with the role you want and your strongest verifiable proof; cut tool lists."))
        if re.search(r"\b(i|my|je|mon|ma)\b", summary, re.IGNORECASE):
            add(Finding(WARN, "Summary", "Summary uses first-person pronouns.",
                        fix="Write it without 'I'/'my', as recruiters expect."))
        if not re.search(r"english|french|bilingual|bilingue|fran[cç]ais|anglais|spanish|español", summary, re.IGNORECASE) and not any(
            s.kind == "languages" for s in doc.sections
        ):
            add(Finding(INFO, "Summary", "Languages are not stated anywhere.",
                        fix="Name them (for example 'English and French') where they are true and relevant."))

    # ---- entries -------------------------------------------------------------
    matcher = get_matcher()
    bullets_all: list[tuple[str, Entry, str]] = []
    first_words: dict[str, int] = {}
    date_styles: set[str] = set()
    projects = 0
    section_stats: dict[str, tuple[int, int]] = {}
    for section in doc.sections:
        if section.kind not in {"experience", "projects", "education"}:
            continue
        with_metrics = 0
        total = 0
        for entry in section.entries:
            where = _entry_where(entry)
            if section.kind == "projects":
                projects += 1
                if not entry.links:
                    add(Finding(WARN, "Projects", "Project has no link.", where,
                                "Add the repository or live URL; unverifiable projects count for little."))
                if not entry.role:
                    add(Finding(INFO, "Projects", "Project heading has no one-line descriptor.", where,
                                "Use 'Name — what it is' so a skimmer understands it in one glance."))
            if section.kind == "education":
                if not entry.dates:
                    add(Finding(WARN, "Education", "Education entry has no dates.", where))
                continue
            if not entry.dates and section.kind == "experience":
                add(Finding(WARN, "Experience", "Role has no dates.", where))
            if entry.dates:
                date_styles.add("numeric" if re.search(r"\d{1,2}/\d{4}", entry.dates) else
                                "month" if re.search(r"[A-Za-zÀ-ÿ]{3,}", entry.dates) else "year")
            if section.kind == "experience" and len(entry.bullets) < 2:
                add(Finding(INFO, "Experience", "Fewer than two bullets.", where,
                            "Two to four outcome-focused bullets per role is typical."))
            if len(entry.bullets) > 6:
                add(Finding(WARN, entry.kind.title(), f"{len(entry.bullets)} bullets; long lists get skipped.", where,
                            "Keep the 3-5 strongest."))
            tenses = set()
            for bullet in entry.bullets:
                total += 1
                bullets_all.append((section.kind, entry, bullet))
                word = _first_word(bullet)
                first_words[word] = first_words.get(word, 0) + 1
                if _has_metric(bullet):
                    with_metrics += 1
                elif section.kind in {"experience", "projects"}:
                    report.worksheet.append((where, bullet, _prompt_for(bullet)))
                length = _words(bullet)
                if length > 30:
                    add(Finding(WARN, "Bullets", f"Bullet is {length} words; aim for under 25.", f"{where}: {bullet[:60]}…",
                                "Split it or keep the action and the result."))
                elif length < 5:
                    add(Finding(INFO, "Bullets", "Very short bullet.", f"{where}: {bullet}"))
                if language == "en":
                    lowered = bullet.lower()
                    hit = next((p for p in _WEAK_PHRASES if re.search(rf"\b{re.escape(p)}\b", lowered)), None)
                    if hit:
                        add(Finding(WARN, "Bullets", f"Vague phrasing ('{hit}').", f"{where}: {bullet[:70]}",
                                    "Replace it with what you actually did and what changed."))
                    if _is_past(word):
                        tenses.add("past")
                    elif word in _PRESENT_BASES:
                        tenses.add("present")
            if language == "en" and entry.dates and entry.bullets:
                if not _ongoing(entry.dates) and "present" in tenses:
                    add(Finding(WARN, "Bullets", "A past role uses present-tense bullets.", where,
                                "Use past tense for roles that have ended."))
                if len(tenses) == 2 and _ongoing(entry.dates):
                    add(Finding(INFO, "Bullets", "Mixed tenses within a current role.", where,
                                "Present tense for ongoing work, past tense for finished achievements."))
        section_stats[section.kind] = (with_metrics, total)

    for kind, label in (("experience", "Experience"), ("projects", "Projects")):
        with_metrics, total = section_stats.get(kind, (0, 0))
        if total and with_metrics / total < 0.4:
            add(Finding(WARN, label, f"Only {with_metrics} of {total} bullets state a measurable result.",
                        fix="Recruiters scan for numbers (scale, speed, %, users). Use the worksheet below; use only figures you can back up."))
    repeated = sorted(w for w, n in first_words.items() if w and n >= 3)
    if repeated:
        add(Finding(INFO, "Bullets", "Repeated opening verbs: " + ", ".join(repeated) + ".",
                    fix="Vary your verbs; each bullet should open differently."))
    if len(date_styles) > 1:
        add(Finding(WARN, "Dates", "Date formats are inconsistent.",
                    fix="Use one style everywhere, e.g. 'Apr 2024 – Present' (rendering normalises display)."))

    # ---- skills --------------------------------------------------------------
    skills_text = " ".join(
        f"{g.label} {g.items}" for s in doc.sections if s.kind == "skills" for g in s.skills
    )
    evidence_text = " ".join([summary] + [b for _, _, b in bullets_all]
                             + [e.name + " " + e.role for s in doc.sections if s.kind in {"experience", "projects"} for e in s.entries])
    listed = set(matcher.extract(skills_text))
    evidenced = set(matcher.extract(evidence_text))
    if skills_text:
        unevidenced = sorted(matcher.label(s) for s in listed - evidenced)
        if unevidenced:
            add(Finding(INFO, "Skills", "Listed but not shown in any bullet: " + ", ".join(unevidenced) + ".",
                        fix="Be ready to discuss each in an interview; add a bullet that proves the ones that matter."))
        unlisted = sorted(matcher.label(s) for s in evidenced - listed)
        if unlisted:
            add(Finding(WARN, "Skills", "Shown in bullets but missing from the skills section: " + ", ".join(unlisted) + ".",
                        fix="Add the ones you can truthfully claim; ATS keyword filters read the skills section."))
        item_count = sum(len([i for i in g.items.split(",") if i.strip()]) for s in doc.sections if s.kind == "skills" for g in s.skills)
        if item_count > 40:
            add(Finding(WARN, "Skills", f"{item_count} skills listed; long lists dilute the strong ones.",
                        fix="Keep the 20-30 you would defend in an interview."))
    else:
        add(Finding(WARN, "Skills", "No skills section.", fix="Add grouped skills; ATS filters read them."))

    # ---- structure -----------------------------------------------------------
    headers = [line.strip() for line in clean.splitlines() if line.strip() in SECTION_HEADERS]
    if projects > 3:
        add(Finding(INFO, "Projects", f"{projects} projects in the master; generated resumes show the 2-3 most relevant.",
                    fix="That is intended: the master is your library."))
    if headers and headers[0] != headers[0].upper():
        add(Finding(INFO, "Structure", "Section headings are not uppercase."))

    bullet_words = [_words(b) for _, _, b in bullets_all]
    total_bullets = len(bullets_all)
    metric_bullets = sum(1 for _, _, b in bullets_all if _has_metric(b))
    report.stats = {
        "language": language,
        "summary_words": summary_words,
        "bullets": total_bullets,
        "bullets_with_metrics": metric_bullets,
        "metric_rate": round(metric_bullets / total_bullets, 2) if total_bullets else 0.0,
        "avg_bullet_words": round(sum(bullet_words) / total_bullets, 1) if total_bullets else 0.0,
        "projects": projects,
        "skills_listed": len(listed),
    }
    order = {ERROR: 0, WARN: 1, INFO: 2}
    report.findings.sort(key=lambda f: order[f.severity])
    return report


def format_report(report: AuditReport, markdown: bool = False) -> str:
    icons = {ERROR: "✗", WARN: "!", INFO: "·"}
    stats = report.stats
    lines = ["Resume audit", ""]
    if stats:
        lines.append(
            f"{stats['bullets']} bullets, {stats['bullets_with_metrics']} with a measurable result "
            f"({int(stats['metric_rate'] * 100)}%), average {stats['avg_bullet_words']} words; "
            f"summary {stats['summary_words']} words; {stats['projects']} projects."
        )
        lines.append("")
    if not report.findings:
        lines.append("No findings.")
    for finding in report.findings:
        head = f"  {icons[finding.severity]} [{finding.area}] {finding.message}"
        lines.append(head)
        if finding.where:
            lines.append(f"      at: {finding.where}")
        if finding.fix:
            lines.append(f"      fix: {finding.fix}")
    if report.worksheet:
        lines += ["", "Worksheet: bullets with no measurable result. Answer with real numbers only.", ""]
        for where, bullet, question in report.worksheet:
            lines.append(f"  {where}")
            lines.append(f"    \"{bullet}\"")
            lines.append(f"    -> {question}")
    lines += ["", f"{report.count(ERROR)} error(s), {report.count(WARN)} warning(s), {report.count(INFO)} note(s)."]
    text = "\n".join(lines)
    return text if not markdown else "```text\n" + text + "\n```"


def main(path: str | None = None, language: str | None = None, markdown: bool = False) -> int:
    """CLI entry: audit ``path`` or the configured master resume. Exit code 1 on errors."""
    from jobhunter.config.settings import RESUME_SOURCE_DIR

    target = path or str(RESUME_SOURCE_DIR / ("master_resume_fr.txt" if language == "fr" else "master_resume.txt"))
    try:
        with open(target, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        print(f"Cannot read {target}: {exc}")
        return 1
    report = audit_resume(text, language)
    print(format_report(report, markdown))
    return 1 if report.has_errors else 0
