from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Pt, RGBColor

from cytonn_weekly.common import report_theme as theme

# The look of the published issue #41.2026 (its PDF, checked 2026-10-28): Calibri, black, justified body; headings and
# chart titles bold and underlined; table colours from the theme.
BLACK = RGBColor.from_string(theme.BLACK.lstrip("#"))
DARK_GREY = RGBColor(0x59, 0x59, 0x59)
WHITE = RGBColor.from_string(theme.WHITE.lstrip("#"))
HEADER_FILL = theme.HEADER_FILL.lstrip("#")
FONT = theme.TABLE_FONT
LINK_BLUE = RGBColor(0x05, 0x63, 0xC1)
HYPERLINK_STYLE = "Hyperlink"

_MARKER = re.compile(r"\[(\d+)\]")
_BARE_URL = re.compile(r"https?://[^\s<>\"]+")
_TRAILING = ".,;:!?)]}'\""


def _plain_font(style) -> None:
    """Drop the theme font attributes, which would win over the font set on the style."""
    rfonts = style.element.get_or_add_rPr().get_or_add_rFonts()
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        rfonts.attrib.pop(qn(attr), None)
    style.font.name = FONT
    rfonts.set(qn("w:eastAsia"), FONT)


def apply_report_look(doc) -> None:
    """Body justified and black in Calibri, Heading 1 to 3 black, bold and underlined, a page number in every footer."""
    normal = doc.styles["Normal"]
    _plain_font(normal)
    normal.font.color.rgb = BLACK
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    for name in ("Heading 1", "Heading 2", "Heading 3"):   # Heading 3: a Real Estate story under its group
        heading = doc.styles[name]
        _plain_font(heading)
        heading.font.color.rgb, heading.font.bold, heading.font.underline = BLACK, True, True
    doc.styles["Heading 1"].font.size = Pt(16)
    hyperlink_style(doc)
    for n, section in enumerate(doc.sections):
        if n and section.footer.is_linked_to_previous:
            continue   # it shows the footer before it, which already has the number
        para =section.footer.paragraphs[0] if section.footer.paragraphs else section.footer.add_paragraph()
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
    """A source line, footnote or note under a table or paragraph: 9 pt, left-aligned (never stretched like the body)."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = p.add_run(text)
    r.font.size, r.font.color.rgb, r.italic, r.bold = Pt(9), color, italic, bold
    p.paragraph_format.space_after = Pt(3)
    return p


def shade(cell, fill: str, text: str, bold: Optional[bool] = None) -> None:
    """Fill a cell and colour its runs ("#RRGGBB"); ``bold`` None leaves each run's weight as it is."""
    tc_pr = cell._tc.get_or_add_tcPr()
    for old in tc_pr.findall(qn("w:shd")):
        tc_pr.remove(old)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill.lstrip("#"))
    tc_pr.append(shd)
    for para in cell.paragraphs:
        for run in para.runs:
            run.font.color.rgb = RGBColor.from_string(text.lstrip("#"))
            if bold is not None:
                run.bold = bold


def shade_header(cell) -> None:
    """The green header band, its text white and bold."""
    shade(cell, theme.HEADER_FILL, theme.HEADER_TEXT, bold=True)


def _cell_text(cell, text: str, bold: bool, centred: bool):
    cell.text = text    # one paragraph holding one run
    para = cell.paragraphs[0]
    run = para.runs[0]
    run.font.size, run.bold, run.font.name = Pt(theme.TABLE_TEXT_PT), bold, theme.TABLE_FONT
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER if centred else WD_ALIGN_PARAGRAPH.LEFT
    para.paragraph_format.space_after = Pt(0)
    return para


def _row_look(values: list) -> Optional[tuple[str, str]]:
    """(fill, text colour) of a body row, or None for a row with the header look."""
    label = str(values[0] or "")
    if label in theme.HEADER_LOOK_ROWS:
        return None
    if label in theme.CHANGE_ROWS:
        return theme.SUMMARY_FILL, theme.CHANGE_TEXT
    if label in theme.SUMMARY_ROWS or any(str(v or "").startswith(theme.CYTONN_ROW_PREFIX) for v in values):
        return theme.SUMMARY_FILL, theme.SUMMARY_TEXT
    return theme.BODY_FILL, theme.BODY_TEXT


def _hold(row, keep_with_next: bool) -> None:
    """A row never splits across pages; with ``keep_with_next`` it stays on the page of what follows it."""
    row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
    for cell in row.cells:
        for para in cell.paragraphs:
            para.paragraph_format.keep_with_next = keep_with_next


def report_table(doc, grid: list[list], header_rows: int = 1, title: Optional[str] = None, keep_last: bool = False):
    """A table in the published look: the title as one merged row, then ``grid``, its first ``header_rows`` rows the header.

    Every row stays whole and on the page of the row after it, so a table that fits a page is never split; the last
    row is kept with what follows only with ``keep_last`` (a source line under the table)."""
    table = doc.add_table(rows=0, cols=len(grid[0]))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    thin_borders(table)
    if title:
        cells = table.add_row().cells
        merged = cells[0].merge(cells[-1]) if len(cells) > 1 else cells[0]
        _cell_text(merged, title, bold=True, centred=True)
        shade_header(merged)
    heads = [str(h) for h in grid[header_rows - 1]] if header_rows else []
    names = {c for c, head in enumerate(heads) if head in theme.NAME_COLUMNS}
    rating = {c for c, head in enumerate(heads) if any(word in head.lower() for word in theme.RATING_COLUMNS)}
    for r, values in enumerate(grid):
        cells = table.add_row().cells
        look = _row_look(values) if r >= header_rows else None
        for c, value in enumerate(values):
            text = "" if value is None else str(value)
            _cell_text(cells[c], text, bold=look is None, centred=look is None or c not in names)
            if look is None:
                shade_header(cells[c])
            elif look[0] == theme.BODY_FILL and text in theme.RECOMMENDATION_FILLS:
                shade(cells[c], theme.RECOMMENDATION_FILLS[text], theme.RECOMMENDATION_TEXT)
            elif look[0] == theme.BODY_FILL and c in rating:
                shade(cells[c], theme.RATING_FILL, theme.BODY_TEXT)
            else:
                shade(cells[c], *look)
    rows = table.rows
    for n, row in enumerate(rows):
        _hold(row, keep_with_next=keep_last or n < len(rows) - 1)
    return table


def keep_together(paragraphs: list) -> None:
    """Lines under a table: each stays on the page of the next; the last lets go."""
    for n, para in enumerate(paragraphs):
        para.paragraph_format.keep_with_next = n < len(paragraphs) - 1


def thin_borders(table) -> None:
    """Thin single black lines round and inside the table."""
    tbl_pr = table._tbl.tblPr
    for old in tbl_pr.findall(qn("w:tblBorders")):
        tbl_pr.remove(old)
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        edge = OxmlElement(f"w:{side}")
        edge.set(qn("w:val"), "single")
        edge.set(qn("w:sz"), str(theme.BORDER_EIGHTHS_PT))
        edge.set(qn("w:space"), "0")
        edge.set(qn("w:color"), theme.BORDER.lstrip("#"))
        borders.append(edge)
    # The schema orders tblPr's children; tblBorders comes before these.
    after = next((c for c in tbl_pr if c.tag in {qn(t) for t in ("w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook")}), None)
    if after is None:
        tbl_pr.append(borders)
    else:
        after.addprevious(borders)


def executive_summary(doc, heading: str, items: list[tuple[str, str]]) -> None:
    """``heading`` as a Heading 1, then one paragraph per (section name, plain summary text), the name in bold.

    A section whose text is empty is left out.
    """
    doc.add_heading(heading, level=1)
    for name, text in items:
        if text.strip():
            p = doc.add_paragraph()
            p.add_run(f"{name}:").bold = True
            add_linked_text(p, f" {text.strip()}")


def hyperlink_style(doc):
    """The "Hyperlink" character style (blue, underlined), added if the document lacks it."""
    try:
        return doc.styles[HYPERLINK_STYLE]
    except KeyError:
        style = doc.styles.add_style(HYPERLINK_STYLE, WD_STYLE_TYPE.CHARACTER)
        style.font.color.rgb, style.font.underline = LINK_BLUE, True
        return style


def safe_url(url) -> Optional[str]:
    """``url`` if it is an http or https address with a host and no whitespace or control character, else None."""
    if not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 for c in url):
        return None
    try:
        parsed = urlparse(url)
        host = parsed.hostname
    except ValueError:
        return None
    return url if parsed.scheme in ("http", "https") and host else None


def add_hyperlink(paragraph, text: str, url: str):
    """Append ``text`` as a real external link to ``url`` and return its run; a refused URL gives a plain run.

    The text goes through python-docx's run and the address through the part's relationships, so both are escaped
    by the library; no XML is built from either string."""
    if safe_url(url) is None:
        return paragraph.add_run(text)
    run = paragraph.add_run(text, style=hyperlink_style(paragraph.part.document))
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True))
    link.set(qn("w:history"), "1")
    paragraph._p.append(link)
    link.append(run._r)   # moves the run inside the link
    return run


def _with_urls(paragraph, text: str) -> list:
    """Plain runs, with each bare http(s) address a link showing itself (trailing punctuation left outside it)."""
    runs, pos = [], 0
    for m in _BARE_URL.finditer(text):
        url = m.group(0).rstrip(_TRAILING)
        if pos < m.start():
            runs.append(paragraph.add_run(text[pos:m.start()]))
        runs.append(add_hyperlink(paragraph, url, url))
        pos = m.start() + len(url)
    if pos < len(text):
        runs.append(paragraph.add_run(text[pos:]))
    return runs


def add_linked_text(paragraph, text: str, sources: Optional[dict[int, tuple[str, str]]] = None) -> list:
    """Write ``text`` into ``paragraph`` with its "[n]" markers turned into links; return the runs written.

    ``sources`` maps n to (phrase, url).  When the text just before "[n]" ends with the phrase (whitespace
    normalised, case-sensitive), the phrase becomes the link and the marker, with the space before it, is removed;
    otherwise the marker "[n]" itself is the link, so no link is lost.  A marker with no source is left as text.
    Any other bare http(s) address becomes a link showing itself.  No other wording changes."""
    sources = sources or {}
    runs, pos = [], 0
    for m in _MARKER.finditer(text):
        n = int(m.group(1))
        if n not in sources:
            continue
        phrase, url = sources[n]
        before = text[pos:m.start()]
        words = phrase.split()
        found = re.search(r"\s+".join(map(re.escape, words)) + r"\s*$", before) if words else None
        if found:
            runs += _with_urls(paragraph, before[:found.start()])
            runs.append(add_hyperlink(paragraph, before[found.start():].rstrip(), url))
        else:
            runs += _with_urls(paragraph, before)
            runs.append(add_hyperlink(paragraph, m.group(0), url))
        pos = m.end()
    runs += _with_urls(paragraph, text[pos:])
    return runs
