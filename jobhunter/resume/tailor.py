from __future__ import annotations

import re
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from hashlib import sha256
from html import escape
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate

try:
    from jobhunter.config.settings import OUTPUT_DIR, USER_PROFILE
    from jobhunter.matching.requirements import analyze_posting, candidate_inventory
    from jobhunter.matching.skills import expand_inventory, get_matcher
    from jobhunter.resume.letter import build_cover_letter
    from jobhunter.resume.tailoring import (
        DATE_LINE_PATTERN,
        SECTION_HEADERS,
        strip_tags,
        strip_tags_from_text,
        tailor_resume_text,
    )
    from jobhunter.resume.tailoring import SUMMARY_HEADERS as SUMMARY_SECTION_HEADERS
    from jobhunter.resume.verify import verify_letter, verify_resume
    from jobhunter.textutils import detect_language, mentions_bilingual
except ModuleNotFoundError:  # pragma: no cover
    from config.settings import OUTPUT_DIR, USER_PROFILE
    from matching.requirements import analyze_posting, candidate_inventory
    from matching.skills import expand_inventory, get_matcher
    from resume.letter import build_cover_letter
    from resume.tailoring import (
        DATE_LINE_PATTERN,
        SECTION_HEADERS,
        strip_tags,
        strip_tags_from_text,
        tailor_resume_text,
    )
    from resume.tailoring import SUMMARY_HEADERS as SUMMARY_SECTION_HEADERS
    from resume.verify import verify_letter, verify_resume
    from textutils import detect_language, mentions_bilingual

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


class IResumeExporter(ABC):
    """Abstract strategy for exporting resume documents in various file formats."""

    @abstractmethod
    def export(self, parsed: ParsedResume, output_path: Path) -> str:
        pass


class TxtResumeExporter(IResumeExporter):
    def export(self, parsed: ParsedResume, output_path: Path) -> str:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(parsed.raw_text, encoding="utf-8")
        return str(output_path)


def _add_docx_hyperlink(
    paragraph, url: str, text: str, font_size_pt: float = 9, color_hex: str = ACCENT_HEX
) -> None:
    """Insert a clickable hyperlink run into a python-docx paragraph.

    python-docx has no built-in hyperlink API, so this builds the required
    <w:hyperlink> XML directly. The run's font size/color are set here (not via
    paragraph.runs) because python-docx's `.runs` accessor only sees runs that
    are direct children of the paragraph, and a hyperlink run is nested one
    level deeper.
    """
    part = paragraph.part
    r_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)

    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")

    color = OxmlElement("w:color")
    color.set(qn("w:val"), color_hex)
    rpr.append(color)

    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    rpr.append(underline)

    size = OxmlElement("w:sz")
    size.set(qn("w:val"), str(int(font_size_pt * 2)))  # half-points
    rpr.append(size)

    run.append(rpr)
    text_el = OxmlElement("w:t")
    text_el.text = text
    run.append(text_el)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _add_contact_line_docx(document: Document, contacts: list[str], font_size_pt: float = 9) -> None:
    """Render the contact line, hyperlinking anything that looks like an email
    or a URL while leaving plain text (address, phone) as-is."""
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for index, item in enumerate(contacts):
        if index > 0:
            separator = paragraph.add_run("  |  ")
            separator.font.size = Pt(font_size_pt)
        if "@" in item:
            _add_docx_hyperlink(paragraph, f"mailto:{item}", item, font_size_pt=font_size_pt)
        elif item.lower().startswith(("http://", "https://")):
            _add_docx_hyperlink(paragraph, item, item, font_size_pt=font_size_pt)
        else:
            run = paragraph.add_run(item)
            run.font.size = Pt(font_size_pt)
    paragraph.paragraph_format.space_after = Pt(8)


class DocxResumeExporter(IResumeExporter):
    def export(self, parsed: ParsedResume, output_path: Path) -> str:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        document = Document()
        _configure_docx(document)

        for block in parsed.blocks:
            kind, value = block.kind, block.value
            if kind == "header":
                name, contacts = value
                paragraph = document.add_paragraph()
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = paragraph.add_run(name.upper())
                run.bold = True
                run.font.name = "Aptos Display"
                run.font.size = Pt(17)
                run.font.color.rgb = ACCENT_COLOR
                _add_contact_line_docx(document, contacts)
            elif kind == "section":
                paragraph = document.add_paragraph()
                run = paragraph.add_run(value.upper())
                run.bold = True
                run.font.size = Pt(10.5)
                run.font.color.rgb = ACCENT_COLOR
                _set_cell_border_bottom(paragraph)
                paragraph.paragraph_format.space_before = Pt(5)
                paragraph.paragraph_format.space_after = Pt(1)
            elif kind == "summary":
                # Regular justified prose -- not bold. Previously this fell
                # through to the "entry" branch below and rendered as a bold
                # heading-style line, which is wrong for a paragraph of text.
                paragraph = document.add_paragraph()
                paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                run = paragraph.add_run(value)
                run.font.size = Pt(9)
                paragraph.paragraph_format.space_after = Pt(4)
            elif kind == "entry":
                paragraph = document.add_paragraph()
                run = paragraph.add_run(value)
                run.bold = True
                run.font.size = Pt(9.5)
                paragraph.paragraph_format.space_before = Pt(3)
            elif kind == "date":
                paragraph = document.add_paragraph(value)
                paragraph.paragraph_format.space_after = Pt(1)
                paragraph.runs[0].italic = True
                paragraph.runs[0].font.size = Pt(8.5)
            elif kind == "bullet":
                paragraph = document.add_paragraph(style="Normal")
                paragraph.paragraph_format.left_indent = Inches(0.2)
                paragraph.paragraph_format.first_line_indent = Inches(-0.14)
                paragraph.paragraph_format.space_after = Pt(1)
                run = paragraph.add_run("•  " + value)
                run.font.size = Pt(9)

        document.save(output_path)
        return str(output_path)


class PdfResumeExporter(IResumeExporter):
    def export(self, parsed: ParsedResume, output_path: Path) -> str:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        document = SimpleDocTemplate(
            str(output_path),
            pagesize=letter,
            topMargin=0.35 * inch,
            bottomMargin=0.35 * inch,
            leftMargin=0.65 * inch,
            rightMargin=0.65 * inch,
        )
        styles = _pdf_styles()
        story = []

        for block in parsed.blocks:
            kind, value = block.kind, block.value
            if kind == "header":
                name, contacts = value
                contact_markup = " | ".join(_pdf_contact_markup(item) for item in contacts)
                story.extend(
                    [
                        Paragraph(escape(name.upper()), styles["name"]),
                        Paragraph(contact_markup, styles["contact"]),
                        HRFlowable(
                            width="100%", thickness=0.9, color=PDF_ACCENT_COLOR, spaceAfter=2
                        ),
                    ]
                )
            elif kind == "section":
                story.extend(
                    [
                        Paragraph(escape(value.upper()), styles["section"]),
                        HRFlowable(
                            width="100%", thickness=0.5, color=PDF_ACCENT_COLOR, spaceAfter=1
                        ),
                    ]
                )
            elif kind == "summary":
                # Justified prose, not bold -- same fix as the DOCX exporter.
                story.append(Paragraph(escape(value), styles["summary"]))
            elif kind == "entry":
                story.append(Paragraph(escape(value), styles["entry"]))
            elif kind == "date":
                story.append(Paragraph(escape(value), styles["date"]))
            elif kind == "bullet":
                story.append(Paragraph("• " + escape(value), styles["bullet"]))

        document.build(story)
        return str(output_path)


def _pdf_contact_markup(item: str) -> str:
    """Return reportlab mini-markup for one contact item, hyperlinked if it's
    an email or URL, escaped either way so no stray text breaks the markup."""
    safe = escape(item)
    if "@" in item:
        return f'<link href="mailto:{safe}" color="#1F4E79"><u>{safe}</u></link>'
    if item.lower().startswith(("http://", "https://")):
        return f'<link href="{safe}" color="#1F4E79"><u>{safe}</u></link>'
    return safe


def build_master_resume(language: str = "en") -> str:
    """Load the English or French user-maintained master resume, falling back to
    a generic template ONLY if the real master file is missing.

    That fallback template is NOT reviewed per-application the way the master
    resume is -- if it ever gets used, warn loudly rather than silently sending
    out a generic/placeholder resume.
    """
    suffix = _language_suffix(language)
    resume_dir = Path(__file__).parent
    master_resume_path = resume_dir / f"master_resume{suffix}.txt"
    if master_resume_path.exists():
        return master_resume_path.read_text(encoding="utf-8")

    template_path = resume_dir / f"master_resume{suffix}.template.txt"
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
    return tailor_resume_text(
        build_master_resume(language), job_title, job_description, language
    )


def _resume_blocks(resume_text: str) -> list[tuple[str, object]]:
    """Convert the simple master-resume format into typed document blocks."""
    parsed = ResumeParser.parse(resume_text)
    return [(b.kind, b.value) for b in parsed.blocks]


def _set_cell_border_bottom(paragraph) -> None:
    paragraph_format = paragraph.paragraph_format
    paragraph_format.space_after = Pt(5)
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "12")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), ACCENT_HEX)
    borders.append(bottom)
    paragraph._p.get_or_add_pPr().append(borders)


def _configure_docx(document: Document) -> None:
    section = document.sections[0]
    section.top_margin = Inches(0.4)
    section.bottom_margin = Inches(0.4)
    section.left_margin = Inches(0.65)
    section.right_margin = Inches(0.65)

    normal = document.styles["Normal"]
    normal.font.name = "Aptos"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Aptos")
    normal.font.size = Pt(9.5)
    normal.paragraph_format.space_after = Pt(1.5)
    normal.paragraph_format.line_spacing = 1.0


def export_resume_docx(
    job_title: str,
    company_name: str,
    output_dir: str | Path | None = None,
    language: str = "en",
    job_description: str = "",
) -> str:
    """Export a clean, ATS-friendly resume based on Harvard's bullet template."""
    target_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR / "resumes"
    suffix = _language_suffix(language)
    company_slug = _filename_component(company_name)
    file_path = target_dir / f"resume_{company_slug}{suffix}.docx"
    resume_text = tailor_resume_for_job(job_title, company_name, language, job_description)
    parsed = ResumeParser.parse(resume_text)
    return DocxResumeExporter().export(parsed, file_path)


def _register_pdf_fonts() -> None:
    """Register a Unicode-capable font for PDF output on Windows."""
    fonts = {
        "ResumeArial": "C:\\Windows\\Fonts\\arial.ttf",
        "ResumeArial-Bold": "C:\\Windows\\Fonts\\arialbd.ttf",
        "ResumeArial-Italic": "C:\\Windows\\Fonts\\ariali.ttf",
        "ResumeArial-BoldItalic": "C:\\Windows\\Fonts\\arialbi.ttf",
    }
    for name, path in fonts.items():
        if name not in pdfmetrics.getRegisteredFontNames() and Path(path).exists():
            pdfmetrics.registerFont(TTFont(name, path))


def _pdf_styles() -> dict[str, ParagraphStyle]:
    _register_pdf_fonts()
    font_regular = "ResumeArial" if "ResumeArial" in pdfmetrics.getRegisteredFontNames() else "Helvetica"
    font_bold = (
        "ResumeArial-Bold"
        if "ResumeArial-Bold" in pdfmetrics.getRegisteredFontNames()
        else "Helvetica-Bold"
    )
    font_italic = (
        "ResumeArial-Italic"
        if "ResumeArial-Italic" in pdfmetrics.getRegisteredFontNames()
        else "Helvetica-Oblique"
    )
    base = getSampleStyleSheet()
    return {
        "name": ParagraphStyle(
            "resume-name",
            parent=base["Normal"],
            fontName=font_bold,
            fontSize=18,
            leading=21,
            textColor=PDF_ACCENT_COLOR,
            alignment=TA_CENTER,
            spaceAfter=2,
        ),
        "contact": ParagraphStyle(
            "resume-contact",
            parent=base["Normal"],
            fontName=font_regular,
            fontSize=8.5,
            leading=10,
            textColor=colors.HexColor("#404040"),
            alignment=TA_CENTER,
            spaceAfter=5,
        ),
        "section": ParagraphStyle(
            "resume-section",
            parent=base["Normal"],
            fontName=font_bold,
            fontSize=10.5,
            leading=12.5,
            textColor=PDF_ACCENT_COLOR,
            spaceBefore=6,
            spaceAfter=2,
        ),
        "summary": ParagraphStyle(
            "resume-summary",
            parent=base["Normal"],
            fontName=font_regular,
            fontSize=9,
            leading=11.5,
            alignment=TA_JUSTIFY,
            spaceAfter=4,
        ),
        "entry": ParagraphStyle(
            "resume-entry",
            parent=base["Normal"],
            fontName=font_bold,
            fontSize=9.8,
            leading=11.5,
            spaceBefore=3,
            spaceAfter=1,
        ),
        "date": ParagraphStyle(
            "resume-date",
            parent=base["Normal"],
            fontName=font_italic,
            fontSize=8.3,
            leading=9.5,
            textColor=colors.HexColor("#555555"),
            spaceAfter=0.5,
        ),
        "bullet": ParagraphStyle(
            "resume-bullet",
            parent=base["Normal"],
            fontName=font_regular,
            fontSize=9,
            leading=10.5,
            leftIndent=12,
            firstLineIndent=-8,
            spaceAfter=1,
        ),
        "body": ParagraphStyle(
            "resume-body",
            parent=base["Normal"],
            fontName=font_regular,
            fontSize=9,
            leading=10.5,
            spaceAfter=1.5,
        ),
    }


def export_resume_pdf(
    job_title: str,
    company_name: str,
    output_dir: str | Path | None = None,
    language: str = "en",
    job_description: str = "",
) -> str:
    """Export the same conservative, scan-friendly template as a PDF."""
    target_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR / "resumes"
    suffix = _language_suffix(language)
    company_slug = _filename_component(company_name)
    file_path = target_dir / f"resume_{company_slug}{suffix}.pdf"
    resume_text = tailor_resume_for_job(job_title, company_name, language, job_description)
    parsed = ResumeParser.parse(resume_text)
    return PdfResumeExporter().export(parsed, file_path)


def export_resume_files(
    job_title: str,
    company_name: str,
    formats=None,
    output_dir: str | Path | None = None,
    language: str = "en",
    job_description: str = "",
):
    target_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR / "resumes"
    target_dir.mkdir(parents=True, exist_ok=True)
    wanted_formats = formats or ["txt", "docx", "pdf"]
    result = {}
    suffix = _language_suffix(language)
    company_slug = _filename_component(company_name)
    resume_text = tailor_resume_for_job(job_title, company_name, language, job_description)
    parsed = ResumeParser.parse(resume_text)

    if "txt" in wanted_formats:
        txt_file = target_dir / f"resume_{company_slug}{suffix}.txt"
        result["txt"] = TxtResumeExporter().export(parsed, txt_file)
    if "docx" in wanted_formats:
        docx_file = target_dir / f"resume_{company_slug}{suffix}.docx"
        result["docx"] = DocxResumeExporter().export(parsed, docx_file)
    if "pdf" in wanted_formats:
        pdf_file = target_dir / f"resume_{company_slug}{suffix}.pdf"
        result["pdf"] = PdfResumeExporter().export(parsed, pdf_file)
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
        user_location=USER_PROFILE["location"],
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
    suffix = _language_suffix(language)
    company_slug = _filename_component(company_name)
    file_path = target_dir / f"cover_letter_{company_slug}{suffix}.docx"
    document = Document()
    _configure_docx(document)

    letter = (
        generate_cover_letter_french(job_title, company_name, job_description, company_hook)
        if language == "fr"
        else generate_cover_letter(job_title, company_name, job_description, company_hook)
    )
    for text in letter.split("\n\n"):
        paragraph = document.add_paragraph(text)
        paragraph.paragraph_format.space_after = Pt(9)
        paragraph.paragraph_format.line_spacing = 1.08

    document.save(file_path)
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
        files = export_resume_files(
            job_title,
            company_name,
            formats=["docx", "pdf"],
            output_dir=pack_dir,
            language=language,
            job_description=description,
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
        tailored = tailor_resume_for_job(job_title, company_name, language, description)
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
    try:
        from jobhunter.resume.tailoring import load_summary_variants
    except ModuleNotFoundError:  # pragma: no cover
        from resume.tailoring import load_summary_variants
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

    expected_files = [paths[key] for language in wanted for key in _pack_file_names(company_slug, language)]
    complete = all(path.exists() for path in expected_files)
    exists = any(path.exists() for path in paths.values())
    report = target_dir / "verification_report.txt"

    files: dict[str, str | bool] = {"exists": exists, "complete": complete}
    for key, path in paths.items():
        files[key] = str(path) if path.exists() else ""
    files["verification_report"] = str(report) if report.exists() else ""
    return files


_ATS_STOP_WORDS = {
    "about", "after", "also", "and", "are", "as", "at", "be", "been", "but", "by",
    "can", "candidate", "company", "for", "from", "have", "has", "in", "into", "is",
    "it", "its", "job", "of", "on", "or", "our", "role", "that", "the", "their",
    "team", "this", "to", "we", "with", "you", "your",
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
