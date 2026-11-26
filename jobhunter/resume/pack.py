from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from docx.shared import RGBColor
from reportlab.lib import colors

from jobhunter.config.settings import (
    OUTPUT_DIR,
    RESUME_INCLUDE_STREET_ADDRESS,
    RESUME_LAYOUT,
    RESUME_SOURCE_DIR,
    USER_PROFILE,
)
from jobhunter.matching.requirements import analyze_posting, candidate_inventory
from jobhunter.matching.skills import expand_inventory, get_matcher
from jobhunter.resume.layout import clean_location, parse_resume
from jobhunter.resume.letter import build_cover_letter
from jobhunter.resume.render import (
    DocxResumeExporter,
    PdfResumeExporter,
    build_letter_docx,
    choose_density,
)
from jobhunter.resume.selection import (
    DATE_LINE_PATTERN,
    SECTION_HEADERS,
    strip_tags,
    strip_tags_from_text,
    tailor_resume_text,
)
from jobhunter.resume.selection import SUMMARY_HEADERS as SUMMARY_SECTION_HEADERS
from jobhunter.resume.verify import verify_letter, verify_resume
from jobhunter.textutils import detect_language, mentions_bilingual

# Short factual lines (not prose, not a "Company - Title" heading) that should
# render as plain text rather than a bold entry heading.
PLAIN_TEXT_SECTION_HEADERS = SUMMARY_SECTION_HEADERS | {"LANGUAGES", "LANGUES"}
ACCENT_COLOR = RGBColor(31, 78, 121)
ACCENT_HEX = "1F4E79"
PDF_ACCENT_COLOR = colors.HexColor("#1F4E79")


def _language_suffix(language: str) -> str:
    if language not in {"en", "fr"}:
        raise ValueError("language must be 'en' or 'fr'")
    return "_fr" if language == "fr" else ""


def _slugify(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or fallback


def _filename_component(value: str, fallback: str = "company") -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", (value or "").lower()).strip("._-") or fallback


def _application_pack_directory(job: dict, output_dir: str | Path | None = None) -> Path:
    """Return a stable folder for one specific company, role, and posting URL."""
    target_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR / "resumes"
    company_slug = _slugify(str(job.get("company") or ""), "company")
    role_slug = _slugify(str(job.get("title") or ""), "role")
    url = str(job.get("url") or "").strip().lower()
    posting_id = sha256(url.encode("utf-8")).hexdigest()[:8] if url else "manual"
    return target_dir / f"{company_slug}__{role_slug}__{posting_id}"


@dataclass
class ResumeBlock:
    kind: str  # "header", "section", "summary", "entry", "date", "bullet"
    value: Any


@dataclass
class ParsedResume:
    header_name: str = ""
    contact_lines: list[str] = field(default_factory=list)
    blocks: list[ResumeBlock] = field(default_factory=list)
    raw_text: str = ""


class ResumeParser:
    """Parses plain text master resume into typed document blocks."""

    @staticmethod
    def parse(resume_text: str) -> ParsedResume:
        lines = [line.strip() for line in resume_text.splitlines()]
        first_section = next(
            (index for index, line in enumerate(lines) if line in SECTION_HEADERS), len(lines)
        )
        contact_lines_raw = [line for line in lines[1:first_section] if line]
        # Some master-resume files put phone/email/github each on its own line;
        # others combine them on one line separated by "|" (seen in the French
        # master resume). Normalize both into one flat list of individual items
        # so header rendering (and hyperlinking) works the same either way.
        contact_lines: list[str] = []
        for raw_line in contact_lines_raw:
            parts = [part.strip() for part in raw_line.split("|") if part.strip()]
            contact_lines.extend(parts or [raw_line])
        header_name = lines[0] if lines else ""

        blocks: list[ResumeBlock] = [ResumeBlock("header", (header_name, contact_lines))]
        index = first_section
        current_section = None

        while index < len(lines):
            line = lines[index]
            if not line:
                index += 1
                continue
            if line in SECTION_HEADERS:
                blocks.append(ResumeBlock("section", line.title()))
                current_section = line
                index += 1
                continue
            if line.startswith("-"):
                blocks.append(ResumeBlock("bullet", strip_tags(line[1:]).strip()))
                index += 1
                continue
            if current_section not in SUMMARY_SECTION_HEADERS and DATE_LINE_PATTERN.search(line):
                blocks.append(ResumeBlock("date", line))
                index += 1
                continue
            # A plain line under Professional Summary or Languages is either
            # prose or a short fact ("French - Fluent"), not a job/education
            # heading, so it must not render bold the way an entry line does.
            if current_section in PLAIN_TEXT_SECTION_HEADERS:
                blocks.append(ResumeBlock("summary", line))
            else:
                blocks.append(ResumeBlock("entry", line))
            index += 1

        return ParsedResume(
            header_name=header_name,
            contact_lines=contact_lines,
            blocks=blocks,
            raw_text=resume_text,
        )


class TxtResumeExporter:
    def export(self, parsed: ParsedResume, output_path: Path) -> str:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(parsed.raw_text, encoding="utf-8")
        return str(output_path)


def build_master_resume(language: str = "en") -> str:
    """Load the English or French user-maintained master resume, falling back to
    a generic template ONLY if the real master file is missing.

    That fallback template is NOT reviewed per-application the way the master
    resume is -- if it ever gets used, warn loudly rather than silently sending
    out a generic/placeholder resume.
    """
    suffix = _language_suffix(language)
    master_resume_path = Path(RESUME_SOURCE_DIR) / f"master_resume{suffix}.txt"
    if master_resume_path.exists():
        return master_resume_path.read_text(encoding="utf-8")

    template_path = Path(__file__).parent / f"master_resume{suffix}.template.txt"
    if template_path.exists():
        warnings.warn(
            f"master_resume{suffix}.txt not found -- falling back to "
            f"master_resume{suffix}.template.txt. That template may contain "
            "placeholder/generic content (e.g. fake company names) and should "
            "NOT be sent to a real employer. Restore your real master resume "
            "file before generating any more application packs.",
            stacklevel=2,
        )
        return template_path.read_text(encoding="utf-8")

    return f"{USER_PROFILE.get('name', 'Your Name')}\n{USER_PROFILE.get('location', 'Your City, Region')}"


def tailor_resume_for_job(
    job_title: str, company_name: str, language: str = "en", job_description: str = ""
) -> str:
    """Select and order verified master-resume content for a specific posting.

    Only ordering and selection change - bullets inside each entry are ranked by how
    well they evidence what the posting asks for, the most relevant projects are
    chosen, and skill groups are reordered. No text is rewritten or added. If you
    keep ``summary_variants.json``, one of *your own* summaries is chosen by role
    family; otherwise the PROFESSIONAL SUMMARY stays exactly as authored.
    """
    return tailor_resume_text(build_master_resume(language), job_title, job_description, language)


def prepare_resume_text(
    job_title: str, company_name: str, language: str = "en", job_description: str = ""
) -> str:
    """The tailored resume text that gets exported (and verified).

    On top of :func:`tailor_resume_for_job` this applies ``RESUME_LAYOUT`` (section order)
    and uses the page well: three projects when they fit on one page at a readable size
    (9.5 pt or larger), otherwise two. Only existing master-resume lines are used.
    """
    master = build_master_resume(language)
    text = ""
    for projects in (3, 2):
        text = tailor_resume_text(
            master, job_title, job_description, language, max_projects=projects, layout=RESUME_LAYOUT
        )
        density, pages = choose_density(parse_resume(text, RESUME_INCLUDE_STREET_ADDRESS))
        if pages <= 1 and density.body >= 9.5:
            break
    return text


_RESUME_EXPORTERS = {
    "txt": TxtResumeExporter,
    "docx": DocxResumeExporter,
    "pdf": PdfResumeExporter,
}


def _resume_output_path(
    prefix: str, extension: str, company_name: str, language: str, output_dir: str | Path | None
) -> Path:
    target_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR / "resumes"
    suffix = _language_suffix(language)
    company_slug = _filename_component(company_name)
    return target_dir / f"{prefix}_{company_slug}{suffix}.{extension}"


def export_resume_docx(
    job_title: str,
    company_name: str,
    output_dir: str | Path | None = None,
    language: str = "en",
    job_description: str = "",
) -> str:
    """Export a clean, ATS-friendly resume based on Harvard's bullet template."""
    return export_resume_files(
        job_title, company_name, formats=["docx"], output_dir=output_dir,
        language=language, job_description=job_description,
    )["docx"]


def export_resume_pdf(
    job_title: str,
    company_name: str,
    output_dir: str | Path | None = None,
    language: str = "en",
    job_description: str = "",
) -> str:
    """Export the same conservative, scan-friendly template as a PDF."""
    return export_resume_files(
        job_title, company_name, formats=["pdf"], output_dir=output_dir,
        language=language, job_description=job_description,
    )["pdf"]


def export_resume_files(
    job_title: str,
    company_name: str,
    formats=None,
    output_dir: str | Path | None = None,
    language: str = "en",
    job_description: str = "",
    resume_text: str | None = None,
):
    target_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR / "resumes"
    target_dir.mkdir(parents=True, exist_ok=True)
    wanted_formats = formats or ["txt", "docx", "pdf"]
    if resume_text is None:
        resume_text = prepare_resume_text(job_title, company_name, language, job_description)
    parsed = ResumeParser.parse(resume_text)

    result = {}
    for fmt in wanted_formats:
        file_path = _resume_output_path("resume", fmt, company_name, language, target_dir)
        result[fmt] = _RESUME_EXPORTERS[fmt]().export(parsed, file_path)
    return result


def _letter_for(
    job_title: str,
    company_name: str,
    job_description: str,
    language: str,
    company_hook: str = "",
    mention_gaps: bool = True,
) -> str:
    return build_cover_letter(
        job_title,
        company_name,
        job_description,
        strip_tags_from_text(build_master_resume(language)),
        language=language,
        user_name=USER_PROFILE["name"],
        user_location=clean_location(USER_PROFILE["location"]),
        company_hook=company_hook,
        mention_gaps=mention_gaps,
    )


def generate_cover_letter(
    job_title: str,
    company_name: str,
    job_description: str = "",
    company_hook: str = "",
    mention_gaps: bool = True,
) -> str:
    """English cover letter built only from master-resume bullets that match the posting.

    ``company_hook`` is an optional sentence *you* write about why this company; it is
    inserted verbatim. Nothing company-specific is ever generated for you.
    """
    return _letter_for(job_title, company_name, job_description, "en", company_hook, mention_gaps)


def generate_cover_letter_french(
    job_title: str,
    company_name: str,
    job_description: str = "",
    company_hook: str = "",
    mention_gaps: bool = True,
) -> str:
    """French cover letter built only from master-resume bullets that match the posting."""
    return _letter_for(job_title, company_name, job_description, "fr", company_hook, mention_gaps)


def export_cover_letter(
    job_title: str,
    company_name: str,
    job_description: str = "",
    output_dir: str | Path | None = None,
    language: str = "en",
    company_hook: str = "",
) -> str:
    target_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR / "resumes"
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = _resume_output_path("cover_letter", "docx", company_name, language, target_dir)
    letter = (
        generate_cover_letter_french(job_title, company_name, job_description, company_hook)
        if language == "fr"
        else generate_cover_letter(job_title, company_name, job_description, company_hook)
    )
    letterhead = parse_resume(build_master_resume(language), RESUME_INCLUDE_STREET_ADDRESS)
    build_letter_docx(letter, letterhead).save(str(file_path))
    return str(file_path)


def suggest_languages(job: dict) -> tuple[str, ...]:
    """Document languages worth generating for a posting.

    A French posting gets French documents, an English one English; bilingual or
    ambiguous postings get both. Saves review time and avoids sending the wrong language.
    """
    text = f"{job.get('title', '')}. {job.get('description', '')}"
    language = detect_language(text)
    if mentions_bilingual(text) or language == "unknown":
        return ("en", "fr")
    return (language,)


def _pack_file_names(company_slug: str, language: str) -> dict[str, str]:
    suffix = _language_suffix(language)
    return {
        f"{language}_resume_pdf": f"resume_{company_slug}{suffix}.pdf",
        f"{language}_resume_docx": f"resume_{company_slug}{suffix}.docx",
        f"{language}_cover_letter_docx": f"cover_letter_{company_slug}{suffix}.docx",
    }


def generate_application_pack(
    job: dict,
    output_dir: str | Path | None = None,
    languages: tuple[str, ...] | list[str] | None = None,
    company_hook: str | None = None,
) -> dict[str, str]:
    """Generate tailored resume (PDF, DOCX) and cover letter (DOCX) files for a posting.

    ``languages`` defaults to both English and French; pass ``suggest_languages(job)``
    to generate only what the posting calls for. ``company_hook`` is an optional
    company-specific sentence you wrote (it can also come from ``job["company_hook"]``).

    The returned dict maps names to file paths. Every generated document is also
    checked against the master resume: anything that is not a reordering of your own
    content (or a number/skill in a letter found in neither resume nor posting) is
    written to ``verification_report.txt`` in the pack folder, and the dict gains a
    ``verification_report`` key pointing to it (read it with
    ``read_verification_warnings``). No such key means the pack verified clean.
    """
    job_title = job.get("title", "Software Engineer")
    company_name = job.get("company", "Company")
    description = job.get("description", "")
    hook = company_hook if company_hook is not None else str(job.get("company_hook") or "")
    wanted = tuple(languages) if languages else ("en", "fr")
    pack_dir = _application_pack_directory(job, output_dir)

    result: dict[str, str] = {
        f"{lang}_{kind}": ""
        for lang in ("en", "fr")
        for kind in ("resume_docx", "resume_pdf", "cover_letter_docx")
    }
    warnings_found: list[str] = []
    for language in wanted:
        tailored = prepare_resume_text(job_title, company_name, language, description)
        files = export_resume_files(
            job_title,
            company_name,
            formats=["docx", "pdf"],
            output_dir=pack_dir,
            language=language,
            job_description=description,
            resume_text=tailored,
        )
        cover = export_cover_letter(
            job_title,
            company_name,
            job_description=description,
            output_dir=pack_dir,
            language=language,
            company_hook=hook,
        )
        result[f"{language}_resume_docx"] = files.get("docx", "")
        result[f"{language}_resume_pdf"] = files.get("pdf", "")
        result[f"{language}_cover_letter_docx"] = cover

        master = build_master_resume(language)
        # Summary variants are user-authored; anything else off-master is flagged.
        from_variants = _summary_variant_lines(language)
        for issue in verify_resume(tailored, master, allowed_extra_lines=from_variants):
            warnings_found.append(f"[{language}] {issue}")
        letter_text = _letter_for(job_title, company_name, description, language, hook)
        for issue in verify_letter(
            letter_text,
            strip_tags_from_text(master),
            f"{job_title}\n{description}",
            allowed_text=[company_name, hook, USER_PROFILE["name"], USER_PROFILE["location"]],
        ):
            warnings_found.append(f"[{language}] {issue}")

    report = pack_dir / "verification_report.txt"
    if warnings_found:
        report.write_text(
            "Items to review before sending (generated text that is not directly from your "
            "master resume or the posting):\n" + "\n".join(f"- {w}" for w in warnings_found),
            encoding="utf-8",
        )
        result["verification_report"] = str(report)
    elif report.exists():
        report.unlink()
    return result


def read_verification_warnings(report_path: str | Path | None) -> list[str]:
    """Warnings listed in a pack's ``verification_report.txt`` (empty list if none)."""
    if not report_path:
        return []
    path = Path(report_path)
    if not path.exists():
        return []
    return [
        line[2:].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("- ")
    ]


def _summary_variant_lines(language: str) -> list[str]:
    from jobhunter.resume.selection import load_summary_variants

    return list(load_summary_variants(language).values())


def get_application_pack_files(
    job: dict,
    output_dir: str | Path | None = None,
    languages: tuple[str, ...] | list[str] | None = None,
) -> dict[str, str | bool]:
    """
    Inspect which resume and cover letter files exist on disk for a job. Does NOT
    generate files. `exists` means at least one file is available; `complete`
    means every expected file (for ``languages``, default both) was generated.
    """
    target_dir = _application_pack_directory(job, output_dir)
    company_slug = _filename_component(str(job.get("company") or ""))
    wanted = tuple(languages) if languages else ("en", "fr")

    paths: dict[str, Path] = {}
    for language in ("en", "fr"):
        for key, name in _pack_file_names(company_slug, language).items():
            paths[key] = target_dir / name

    expected_files = [path for key, path in paths.items() if key[:2] in wanted]
    complete = all(path.exists() for path in expected_files)
    exists = any(path.exists() for path in paths.values())
    report = target_dir / "verification_report.txt"

    files: dict[str, str | bool] = {"exists": exists, "complete": complete}
    for key, path in paths.items():
        files[key] = str(path) if path.exists() else ""
    files["verification_report"] = str(report) if report.exists() else ""
    return files


_ATS_STOP_WORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "but",
    "by",
    "can",
    "candidate",
    "company",
    "for",
    "from",
    "have",
    "has",
    "in",
    "into",
    "is",
    "it",
    "its",
    "job",
    "of",
    "on",
    "or",
    "our",
    "role",
    "that",
    "the",
    "their",
    "team",
    "this",
    "to",
    "we",
    "with",
    "you",
    "your",
}


def _ats_terms(text: str) -> set[str]:
    plain_text = re.sub(r"<[^>]+>", " ", text or "").lower()
    return {
        token.strip("./-")
        for token in re.findall(r"[a-z][a-z0-9+#./-]*", plain_text)
        if len(token.strip("./-")) > 1 and token.strip("./-") not in _ATS_STOP_WORDS
    }


def ats_analysis(resume_text: str, job_description: str) -> dict:
    """Keyword coverage plus an honest skills gap report; not an ATS prediction.

    * ``missing_skills``  - skills the posting names that you *do* have (per your profile
      keywords) but this resume does not show: safe to add.
    * ``skill_gaps``      - skills the posting names that you have no record of: do NOT
      claim them; learn them or address them honestly.
    """
    resume_text = strip_tags_from_text(resume_text or "")
    resume_keywords = _ats_terms(resume_text)
    jd_tokens = _ats_terms(job_description)
    missing_keywords = sorted(jd_tokens - resume_keywords)
    matched_count = len(jd_tokens & resume_keywords)
    ats_score = round(100 * matched_count / len(jd_tokens)) if jd_tokens else 0

    keywords = tuple(USER_PROFILE.get("keywords", []) or [])
    matcher = get_matcher(keywords)
    profile_skills = set(candidate_inventory(keywords, None, matcher)) | expand_inventory(
        USER_PROFILE.get("resume_skills", []) or []
    )
    resume_skills = set(matcher.extract(resume_text))
    posting_skills = set(analyze_posting("", job_description, matcher).skills)
    missing_skills = [
        matcher.label(skill) for skill in sorted(posting_skills & profile_skills - resume_skills)
    ]
    skill_gaps = [
        matcher.label(skill) for skill in sorted(posting_skills - profile_skills - resume_skills)
    ]

    improvements: list[str] = []
    if missing_skills:
        improvements.append(
            "Show these skills you already have (they are in your profile but not on this resume): "
            + ", ".join(missing_skills[:6])
            + "."
        )
    if skill_gaps:
        improvements.append(
            "The posting also names skills you have no record of - do not claim them: "
            + ", ".join(skill_gaps[:6])
            + ". Consider learning the ones that recur across your target roles."
        )
    if not improvements:
        improvements.append("Your resume already covers the skills this posting names.")

    return {
        "ats_score": ats_score,
        "score_type": "keyword coverage estimate",
        "missing_keywords": missing_keywords[:15],
        "missing_skills": missing_skills[:10],
        "skill_gaps": skill_gaps[:10],
        "improvements": improvements,
    }
