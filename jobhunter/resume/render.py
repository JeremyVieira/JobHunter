"""DOCX and PDF resume renderers.

Design goals (modelled on resumes professional recruiters write):

* one clean, ATS-friendly column: real text, real bullets, tab-aligned dates (no tables or
  text boxes in the DOCX);
* a clear hierarchy: accent-coloured company/project names, the role on its own italic
  line, dates right-aligned, numbers in bullets in bold, section headings with a rule;
* a centred header with a single tidy contact line (no street address, short link labels);
* everything fits one page when it reasonably can: the renderer tries progressively tighter
  spacing and font sizes before it ever spills to a second page.

The renderers only decide how existing text is shown (see ``layout.py``).
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from jobhunter.config.settings import RESUME_INCLUDE_STREET_ADDRESS
from jobhunter.resume.layout import (
    Contact,
    Entry,
    Link,
    ResumeDoc,
    emphasize_metrics,
    parse_resume,
)

ACCENT_HEX = "#1D4F91"
DARK_HEX = "#111827"
MUTED_HEX = "#4B5563"
PAGE_WIDTH_IN = 8.5


@dataclass(frozen=True)
class Density:
    """Size/spacing preset. Renderers use the largest one that keeps the resume on one page."""

    name: str
    body: float  # base font size, pt
    leading: float  # line-height ratio
    name_size: float
    section_gap: float  # space above a section heading, pt
    entry_gap: float  # space above an entry, pt
    bullet_gap: float  # space after a bullet, pt
    margin: float  # left/right margin, inches
    margin_y: float  # top/bottom margin, inches


PRESETS: tuple[Density, ...] = (
    Density("comfortable", 10.5, 1.24, 22, 9, 5, 1.4, 0.75, 0.6),
    Density("standard", 10.0, 1.22, 21, 8, 4, 1.0, 0.7, 0.55),
    Density("compact", 9.5, 1.20, 20, 7, 3.5, 0.8, 0.65, 0.5),
    Density("tight", 9.0, 1.18, 19, 6, 3, 0.6, 0.6, 0.45),
)


# --------------------------------------------------------------------------
# Fonts (PDF)
# --------------------------------------------------------------------------
_FONT_FAMILIES: tuple[tuple[str, tuple[str, str, str, str]], ...] = (
    ("Calibri", ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf")),
    ("Arial", ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf")),
    (
        "LiberationSans",
        (
            "LiberationSans-Regular.ttf",
            "LiberationSans-Bold.ttf",
            "LiberationSans-Italic.ttf",
            "LiberationSans-BoldItalic.ttf",
        ),
    ),
)
_FONT_DIRS = (
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
    Path("/System/Library/Fonts/Supplemental"),
    Path("/Library/Fonts"),
    Path("/usr/share/fonts/truetype/liberation"),
    Path("/usr/share/fonts/truetype/msttcorefonts"),
)
_registered: tuple[str, str, str, str] | None = None


def resume_fonts() -> tuple[str, str, str, str]:
    """(regular, bold, italic, bold-italic) font names; Helvetica (base-14) as a fallback."""
    global _registered
    if _registered is not None:
        return _registered
    for family, files in _FONT_FAMILIES:
        for directory in _FONT_DIRS:
            paths = [directory / name for name in files]
            if all(path.exists() for path in paths):
                names = tuple(f"Resume-{family}-{i}" for i in range(4))
                for font_name, path in zip(names, paths, strict=True):
                    pdfmetrics.registerFont(TTFont(font_name, str(path)))
                pdfmetrics.registerFontFamily(
                    names[0], normal=names[0], bold=names[1], italic=names[2], boldItalic=names[3]
                )
                _registered = names  # type: ignore[assignment]
                return _registered  # type: ignore[return-value]
    _registered = ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique")
    return _registered


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------
def _contact_text_items(contact: Contact) -> list[tuple[str, str | None]]:
    """``(label, url-or-None)`` in display order: location, phone, email, links, extras."""
    items: list[tuple[str, str | None]] = []
    if contact.location:
        items.append((contact.location, None))
    if contact.phone:
        items.append((contact.phone, None))
    if contact.email:
        items.append((contact.email, f"mailto:{contact.email}"))
    items += [(link.label, link.url) for link in contact.links]
    items += [(extra, None) for extra in contact.extras]
    return items


def _summary_paragraphs(doc: ResumeDoc) -> list[str]:
    return [p for s in doc.sections if s.kind == "summary" for p in s.paragraphs]


def _entry_right_text(entry: Entry) -> tuple[str, list[Link]]:
    """What goes in the right-hand slot: dates when present, otherwise the entry's links."""
    if entry.dates:
        return entry.dates, []
    return "", entry.links


def education_one_line(entry: Entry, limit: int = 90) -> bool:
    """Education fits a single line (school | degree ... dates) when it is short enough."""
    return bool(entry.role) and len(entry.name) + len(entry.role) + 3 + len(entry.dates) <= limit


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def _markup(text: str) -> str:
    """Escape ``text`` for reportlab and bold its metrics."""
    return "".join(f"<b>{escape(part)}</b>" if bold else escape(part) for part, bold in emphasize_metrics(text))


def _link_markup(link: Link) -> str:
    return f'<a href="{escape(link.url, {chr(34): "&quot;"})}" color="{ACCENT_HEX}"><u>{escape(link.label)}</u></a>'


class _PdfStyles:
    def __init__(self, density: Density):
        regular, bold, italic, _ = resume_fonts()
        body, lead = density.body, density.body * density.leading
        self.regular, self.bold, self.italic = regular, bold, italic
        self.entry_gap = density.entry_gap
        self.body = body
        self.name = ParagraphStyle(
            "name", fontName=bold, fontSize=density.name_size, leading=density.name_size * 1.1,
            alignment=TA_CENTER, textColor=HexColor(DARK_HEX), spaceAfter=2,
        )
        self.contact = ParagraphStyle(
            "contact", fontName=regular, fontSize=body - 0.5, leading=(body - 0.5) * 1.3,
            alignment=TA_CENTER, textColor=HexColor(MUTED_HEX), spaceAfter=4,
        )
        self.summary = ParagraphStyle(
            "summary", fontName=regular, fontSize=body, leading=lead, alignment=TA_LEFT,
            textColor=HexColor(DARK_HEX), spaceBefore=3, spaceAfter=0,
        )
        self.section = ParagraphStyle(
            "section", fontName=bold, fontSize=body + 0.5, leading=(body + 0.5) * 1.15,
            textColor=HexColor(DARK_HEX), spaceBefore=density.section_gap, spaceAfter=1, keepWithNext=1,
        )
        self.entry = ParagraphStyle(
            "entry", fontName=regular, fontSize=body, leading=lead, textColor=HexColor(DARK_HEX),
        )
        self.right = ParagraphStyle(
            "right", parent=self.entry, alignment=TA_RIGHT, textColor=HexColor(MUTED_HEX),
        )
        self.role = ParagraphStyle(
            "role", fontName=italic, fontSize=body, leading=lead, textColor=HexColor(ACCENT_HEX),
        )
        self.bullet = ParagraphStyle(
            "bullet", fontName=regular, fontSize=body, leading=lead, textColor=HexColor(DARK_HEX),
            leftIndent=12, bulletIndent=3, bulletFontName=regular, bulletFontSize=body,
            spaceAfter=density.bullet_gap,
        )
        self.skill = ParagraphStyle(
            "skill", fontName=regular, fontSize=body, leading=lead, textColor=HexColor(DARK_HEX),
            spaceBefore=1,
        )


def _entry_header(entry: Entry, styles: _PdfStyles, width: float) -> tuple[list[Any], bool]:
    """Flowables for an entry heading. Returns ``(flowables, has_role_line)``."""
    left = f'<font color="{ACCENT_HEX}"><b>{escape(entry.name)}</b></font>'
    role_line = entry.role
    right_text, right_links = _entry_right_text(entry)
    if entry.kind == "education":
        if entry.role and education_one_line(entry):
            left += f" | {escape(entry.role)}"
            role_line = ""
    else:
        if entry.location:
            left += f" | {escape(entry.location)}"
        if entry.dates and entry.links:  # dates take the right slot; links follow the name
            left += " | " + " ".join(_link_markup(link) for link in entry.links)
    right_markup = escape(right_text) if right_text else " | ".join(_link_markup(link) for link in right_links)

    flowables: list[Any] = [Spacer(1, styles.entry_gap)]
    if right_markup:
        plain_width = stringWidth(right_text or " ", styles.regular, styles.body) if right_text else sum(
            stringWidth(link.label, styles.regular, styles.body) for link in right_links
        ) + 12 * max(0, len(right_links) - 1)
        right_width = min(plain_width + 8, width * 0.45)
        table = Table(
            [[Paragraph(left, styles.entry), Paragraph(right_markup, styles.right)]],
            colWidths=[width - right_width, right_width],
        )
        table.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        flowables.append(table)
    else:
        flowables.append(Paragraph(left, styles.entry))
    if role_line:
        flowables.append(Paragraph(escape(role_line), styles.role))
    for flowable in flowables:
        flowable.keepWithNext = 1  # heading stays with its role line and first bullet
    return flowables, bool(role_line)


def _pdf_story(doc: ResumeDoc, density: Density, width: float) -> list[Any]:
    styles = _PdfStyles(density)
    story: list[Any] = [Paragraph(escape(doc.name), styles.name)]
    parts = []
    for label, url in _contact_text_items(doc.contact):
        parts.append(
            f'<a href="{escape(url)}" color="{ACCENT_HEX}">{escape(label)}</a>' if url else escape(label)
        )
    if parts:
        story.append(Paragraph("  |  ".join(parts), styles.contact))

    for paragraph in _summary_paragraphs(doc):
        story.append(Paragraph(_markup(paragraph), styles.summary))

    for section in doc.sections:
        if section.kind == "summary":
            continue
        rule = HRFlowable(width="100%", thickness=0.6, color=HexColor(DARK_HEX), spaceBefore=0, spaceAfter=2)
        rule.keepWithNext = 1
        story.extend([Paragraph(escape(section.title.upper()), styles.section), rule])
        for entry in section.entries:
            header, _ = _entry_header(entry, styles, width)
            story.extend(header)
            story.extend(Paragraph(_markup(b), styles.bullet, bulletText="•") for b in entry.bullets)
        for group in section.skills:
            label = f"<b>{escape(group.label)}:</b> " if group.label else ""
            story.append(Paragraph(f"{label}{escape(group.items)}", styles.skill))
        if section.paragraphs and section.kind in {"languages", "other"}:
            story.append(Paragraph(" · ".join(escape(p) for p in section.paragraphs), styles.skill))
    return story


def build_pdf(doc: ResumeDoc, target: str | Path | io.BytesIO, density: Density) -> int:
    """Render ``doc`` to ``target`` and return the page count."""
    template = SimpleDocTemplate(
        str(target) if isinstance(target, Path) else target,
        pagesize=letter,
        leftMargin=density.margin * inch,
        rightMargin=density.margin * inch,
        topMargin=density.margin_y * inch,
        bottomMargin=density.margin_y * inch,
        title=f"{doc.name} - Resume" if doc.name else "Resume",
        author=doc.name,
        subject="Resume",
        creator="JobHunter",
    )
    # ReportLab frames pad 6pt on each side; tables must fit inside that, not the raw margins.
    width = template.width - 12
    template.build(_pdf_story(doc, density, width))
    return int(template.page)


def choose_density(doc: ResumeDoc) -> tuple[Density, int]:
    """Largest preset that keeps the resume on one page (else the tightest one, and its pages)."""
    pages = 0
    for preset in PRESETS:
        pages = build_pdf(doc, io.BytesIO(), preset)
        if pages <= 1:
            return preset, pages
    return PRESETS[-1], pages


class PdfResumeExporter:
    """PDF export: one column, selectable text, hyperlinks, document metadata."""

    def export(self, parsed: Any, output_path: str | Path) -> str:
        doc = parse_resume(parsed.raw_text, RESUME_INCLUDE_STREET_ADDRESS)
        density, _ = choose_density(doc)
        path = Path(output_path)
        build_pdf(doc, path, density)
        return str(path)


# --------------------------------------------------------------------------
# DOCX
# --------------------------------------------------------------------------
def _rgb(hex_color: str) -> RGBColor:
    return RGBColor(int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))


def _set_font(run: Any, name: str = "Calibri") -> None:
    run.font.name = name
    properties = run._element.get_or_add_rPr()
    fonts = properties.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        properties.append(fonts)
    for attribute in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attribute), name)


def _run(paragraph: Any, text: str, size: float, *, bold=False, italic=False, color: str | None = None) -> Any:
    run = paragraph.add_run(text)
    _set_font(run)
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color:
        run.font.color.rgb = _rgb(color)
    return run


def _hyperlink(paragraph: Any, url: str, text: str, size: float) -> None:
    relationship = paragraph.part.relate_to(
        url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True
    )
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), relationship)
    run = OxmlElement("w:r")
    props = OxmlElement("w:rPr")
    fonts = OxmlElement("w:rFonts")
    for attribute in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attribute), "Calibri")
    props.append(fonts)
    color = OxmlElement("w:color")
    color.set(qn("w:val"), ACCENT_HEX[1:])
    props.append(color)
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    props.append(underline)
    size_el = OxmlElement("w:sz")
    size_el.set(qn("w:val"), str(int(size * 2)))
    props.append(size_el)
    run.append(props)
    text_el = OxmlElement("w:t")
    text_el.text = text
    text_el.set(qn("xml:space"), "preserve")
    run.append(text_el)
    link.append(run)
    paragraph._p.append(link)


def _bottom_border(paragraph: Any) -> None:
    properties = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for key, value in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", DARK_HEX[1:])):
        bottom.set(qn(key), value)
    borders.append(bottom)
    properties.append(borders)


def _paragraph(document: Any, *, align=None, before=0.0, after=0.0, keep_next=False, style=None) -> Any:
    paragraph = document.add_paragraph(style=style)
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(before)
    fmt.space_after = Pt(after)
    fmt.line_spacing = 1.0
    fmt.keep_with_next = keep_next
    if align is not None:
        paragraph.alignment = align
    return paragraph


def _metric_runs(paragraph: Any, text: str, size: float) -> None:
    for part, bold in emphasize_metrics(text):
        _run(paragraph, part, size, bold=bold, color=DARK_HEX)


def _docx_entry_header(document: Any, entry: Entry, density: Density, content_width: float) -> None:
    size = density.body
    paragraph = _paragraph(document, before=density.entry_gap, keep_next=True)
    paragraph.paragraph_format.tab_stops.add_tab_stop(Inches(content_width), WD_TAB_ALIGNMENT.RIGHT)
    _run(paragraph, entry.name, size, bold=True, color=ACCENT_HEX)

    role_line = entry.role
    if entry.kind == "education":
        if entry.role and education_one_line(entry):
            _run(paragraph, f" | {entry.role}", size, color=DARK_HEX)
            role_line = ""
    elif entry.location:
        _run(paragraph, f" | {entry.location}", size, color=DARK_HEX)

    if entry.kind != "education" and entry.dates and entry.links:
        _run(paragraph, " | ", size, color=DARK_HEX)
        for index, link in enumerate(entry.links):
            if index:
                _run(paragraph, " ", size)
            _hyperlink(paragraph, link.url, link.label, size)
    if entry.dates:
        _run(paragraph, "\t", size)
        _run(paragraph, entry.dates, size - 0.5, color=MUTED_HEX)
    elif entry.links:
        _run(paragraph, "\t", size)
        for index, link in enumerate(entry.links):
            if index:
                _run(paragraph, " | ", size, color=MUTED_HEX)
            _hyperlink(paragraph, link.url, link.label, size)
    if role_line:
        role = _paragraph(document, keep_next=bool(entry.bullets))
        _run(role, role_line, size, italic=True, color=ACCENT_HEX)


def build_docx(doc: ResumeDoc, density: Density) -> Any:
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.left_margin = section.right_margin = Inches(density.margin)
    section.top_margin = section.bottom_margin = Inches(density.margin_y)
    content_width = PAGE_WIDTH_IN - 2 * density.margin
    size = density.body

    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(size)
    bullet_style = document.styles["List Bullet"]
    bullet_style.font.name = "Calibri"
    bullet_style.font.size = Pt(size)

    properties = document.core_properties
    properties.title = f"{doc.name} - Resume" if doc.name else "Resume"
    properties.author = doc.name
    properties.last_modified_by = doc.name
    properties.subject = "Resume"
    properties.comments = "Generated by JobHunter"

    header = _paragraph(document, align=WD_ALIGN_PARAGRAPH.CENTER, after=2)
    _run(header, doc.name, density.name_size, bold=True, color=DARK_HEX)

    items = _contact_text_items(doc.contact)
    if items:
        contact = _paragraph(document, align=WD_ALIGN_PARAGRAPH.CENTER, after=4)
        for index, (label, url) in enumerate(items):
            if index:
                _run(contact, "  |  ", size - 0.5, color=MUTED_HEX)
            if url:
                _hyperlink(contact, url, label, size - 0.5)
            else:
                _run(contact, label, size - 0.5, color=MUTED_HEX)

    for text in _summary_paragraphs(doc):
        paragraph = _paragraph(document, align=WD_ALIGN_PARAGRAPH.LEFT, before=3)
        _metric_runs(paragraph, text, size)

    for sec in doc.sections:
        if sec.kind == "summary":
            continue
        heading = _paragraph(document, before=density.section_gap, after=1, keep_next=True)
        _run(heading, sec.title.upper(), size + 0.5, bold=True, color=DARK_HEX)
        _bottom_border(heading)
        for entry in sec.entries:
            _docx_entry_header(document, entry, density, content_width)
            for index, bullet in enumerate(entry.bullets):
                paragraph = _paragraph(
                    document, after=density.bullet_gap, style="List Bullet", keep_next=index == 0 and len(entry.bullets) > 1
                )
                paragraph.paragraph_format.left_indent = Inches(0.2)
                paragraph.paragraph_format.first_line_indent = Inches(-0.15)
                _metric_runs(paragraph, bullet, size)
        for group in sec.skills:
            paragraph = _paragraph(document, before=1)
            if group.label:
                _run(paragraph, f"{group.label}: ", size, bold=True, color=DARK_HEX)
            _run(paragraph, group.items, size, color=DARK_HEX)
        if sec.paragraphs and sec.kind in {"languages", "other"}:
            paragraph = _paragraph(document, before=1)
            _run(paragraph, " · ".join(sec.paragraphs), size, color=DARK_HEX)
    return document


class DocxResumeExporter:
    """DOCX export: real bullets, tab-aligned dates, hyperlinks; no tables or text boxes."""

    def export(self, parsed: Any, output_path: str | Path) -> str:
        doc = parse_resume(parsed.raw_text, RESUME_INCLUDE_STREET_ADDRESS)
        density, _ = choose_density(doc)  # same size/spacing the PDF uses
        path = Path(output_path)
        build_docx(doc, density).save(str(path))
        return str(path)


# --------------------------------------------------------------------------
# Cover letter DOCX (same header and typography as the resume)
# --------------------------------------------------------------------------
LETTER_DENSITY = Density("letter", 10.5, 1.3, 20, 0, 0, 0, 0.85, 0.9)


def build_letter_docx(letter: str, doc: ResumeDoc, density: Density = LETTER_DENSITY) -> Any:
    """A cover letter on the resume's letterhead: name, one contact line, rule, then the text."""
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.left_margin = section.right_margin = Inches(density.margin)
    section.top_margin = section.bottom_margin = Inches(density.margin_y)
    size = density.body
    document.styles["Normal"].font.name = "Calibri"
    document.styles["Normal"].font.size = Pt(size)

    properties = document.core_properties
    properties.title = f"{doc.name} - Cover Letter" if doc.name else "Cover Letter"
    properties.author = doc.name
    properties.last_modified_by = doc.name
    properties.subject = "Cover letter"
    properties.comments = "Generated by JobHunter"

    header = _paragraph(document, align=WD_ALIGN_PARAGRAPH.CENTER, after=2)
    _run(header, doc.name, density.name_size, bold=True, color=DARK_HEX)
    items = _contact_text_items(doc.contact)
    if items:
        contact = _paragraph(document, align=WD_ALIGN_PARAGRAPH.CENTER, after=10)
        _bottom_border(contact)
        for index, (label, url) in enumerate(items):
            if index:
                _run(contact, " | ", size - 1.5, color=MUTED_HEX)
            if url:
                _hyperlink(contact, url, label, size - 1.5)
            else:
                _run(contact, label, size - 1.5, color=MUTED_HEX)

    for block in letter.split("\n\n"):
        paragraph = _paragraph(document, align=WD_ALIGN_PARAGRAPH.LEFT, after=9)
        paragraph.paragraph_format.line_spacing = 1.12
        for index, line in enumerate(block.split("\n")):
            if index:
                paragraph.add_run().add_break()
            _run(paragraph, line, size, color=DARK_HEX)
    return document
