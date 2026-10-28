from __future__ import annotations

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Pt, RGBColor

# The look of the published issue #41.2026 (its PDF, checked 2026-10-28): Calibri, black, justified body; headings and
# table titles bold and underlined; table headers on the green band sampled from its tables (006C5B) in white.
BLACK = RGBColor(0x00, 0x00, 0x00)
DARK_GREY = RGBColor(0x59, 0x59, 0x59)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
HEADER_FILL = "006C5B"
FONT = "Calibri"


def _plain_font(style) -> None:
    """Drop the theme font attributes, which would win over the font set on the style."""
    rfonts = style.element.get_or_add_rPr().get_or_add_rFonts()
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        rfonts.attrib.pop(qn(attr), None)
    style.font.name = FONT
    rfonts.set(qn("w:eastAsia"), FONT)


def apply_report_look(doc) -> None:
    """Body justified and black in Calibri, Heading 1 and 2 black, bold and underlined, a page number in every footer."""
    normal = doc.styles["Normal"]
    _plain_font(normal)
    normal.font.color.rgb = BLACK
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    for name in ("Heading 1", "Heading 2"):
        heading = doc.styles[name]
        _plain_font(heading)
        heading.font.color.rgb, heading.font.bold, heading.font.underline = BLACK, True, True
    doc.styles["Heading 1"].font.size = Pt(16)
    for section in doc.sections:
        para = section.footer.paragraphs[0] if section.footer.paragraphs else section.footer.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para._p.append(parse_xml(f'<w:fldSimple {nsdecls("w")} w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>'))


def title(doc, text: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(text)
    r.bold, r.underline, r.font.size, r.font.color.rgb = True, True, Pt(16), BLACK
    return p


def title_line(doc, text: str):
    """A table's or chart's own title line."""
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold, r.underline = True, True
    p.paragraph_format.keep_with_next = True
    return p


def small_line(doc, text: str, *, color: RGBColor = DARK_GREY, italic: bool = False, bold: bool = False):
    """A source line, footnote or note under a table or paragraph: 9 pt."""
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.font.size, r.font.color.rgb, r.italic, r.bold = Pt(9), color, italic, bold
    p.paragraph_format.space_after = Pt(3)
    return p


def shade_header(cell) -> None:
    """The green header band, its text white and bold."""
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), HEADER_FILL)
    cell._tc.get_or_add_tcPr().append(shd)
    for para in cell.paragraphs:
        for run in para.runs:
            run.bold, run.font.color.rgb = True, WHITE


def executive_summary(doc, heading: str, items: list[tuple[str, str]]) -> None:
    """``heading`` as a Heading 1, then one paragraph per (section name, plain summary text), the name in bold.

    A section whose text is empty is left out.
    """
    doc.add_heading(heading, level=1)
    for name, text in items:
        if text.strip():
            p = doc.add_paragraph()
            p.add_run(f"{name}:").bold = True
            p.add_run(f" {text.strip()}")
