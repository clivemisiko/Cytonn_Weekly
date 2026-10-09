"""The approved weekly report as one Word file, in the real issue's order.

Allowed only when **every** weekly section of the week is approved: the tool never
publishes anything a coordinator has not signed off, and a half-approved report is not a
report.  The file is for whoever lays the issue out and loads it into the CMS; nothing
here sends or publishes it (publishing to the CMS is still a blocked stub).

What it holds, read from Cytonn Weekly #38.2026 (cytonnreport.com issue 891):

* the six sections under the issue's own headings, in its order;
* every table as a Word table, with its source line and footnotes;
* each chart the real issue carries as "[Chart to add: <caption>]", where the issue puts it
  (the tool draws no charts);
* text carried forward from the previous issue marked as such, and a part the coordinator
  approved as missing named as missing, so neither can pass for finished copy;
* a final part, "Section summaries for the CMS": each section's summary, which the website
  builds its Executive Summary from.

A dev-mode draft (any piece drafted by the local model) is exported with a DEV MODE
watermark and banner on every page, and ``refuse_to_send`` blocks any path that would send
it, by the same test the Word summary's email path uses.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Optional, Union

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.shared import Pt, RGBColor

from cytonn_weekly import paths
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.digital_payments.coordinator_review import APPROVED, CoordinatorReview
from cytonn_weekly.digital_payments.delivery import DevModeDeliveryBlocked, is_dev_mode_review
from cytonn_weekly.digital_payments.fetcher import format_table_rows
from cytonn_weekly.digital_payments.summary import (
    TABLE_COLUMNS,
    TABLE_TITLE,
    _average_row,
    _shade,
    _small,
    _style_document,
    footnote_links,
)
from cytonn_weekly.report_sections import SECTIONS, SectionSpec, is_current, latest_runs
from cytonn_weekly.report_types import WEEKLY, week_ending_of
from cytonn_weekly.weekly.summaries import section_summary
from cytonn_weekly.weekly.week import ordinal

DEV_LABEL = "DEV MODE DRAFT (local model): NOT FOR PUBLICATION OR CIRCULATION"
WATERMARK = "DEV MODE DRAFT"
SUMMARIES_HEADING = "Section summaries for the CMS"
CARRIED_NOTE = "[Carried forward from the previous issue: edit before publishing]"

# The issue's own section headings (#38.2026).
HEADINGS = {"company_updates": "Company Updates", "fixed_income": "Fixed Income", "equities": "Equities",
            "real_estate": "Real Estate", "digital_payments": "Digital Payments Weekly Highlights", "focus": "Focus of the Week"}

_RED = RGBColor(0xC0, 0x00, 0x00)
_INK = RGBColor(0x1F, 0x2A, 0x44)


class ExportNotAllowed(ValueError):
    """The weekly report cannot be exported yet; the message names each section that is not approved."""


# ---------------------------------------------------------------------------
# Which reviews make the week's report
# ---------------------------------------------------------------------------

def weekly_reviews(db_path: Optional[Union[Path, str]], period: str, today: Optional[date] = None
                   ) -> list[tuple[SectionSpec, Optional[CoordinatorReview]]]:
    """Each weekly section with its newest review of this period, or None if it has none (or an old unlabelled one)."""
    runs = latest_runs(db_path, WEEKLY, period)
    out = []
    for spec in SECTIONS:
        run = runs.get(spec.slug)
        review = None
        if run is not None and is_current(WEEKLY, period, run["run_date"], today):
            review = review_store.load_review(run["run_id"], db_path=db_path)
        out.append((spec, review))
    return out


def _state(review: Optional[CoordinatorReview]) -> str:
    if review is None:
        return "not_drafted"
    return review.decision or "in_review"


def export_status(db_path: Optional[Union[Path, str]], period: str, today: Optional[date] = None) -> dict[str, Any]:
    """Whether the week's report can be exported, and each section's state."""
    reviews = weekly_reviews(db_path, period, today)
    sections = [{"slug": spec.slug, "title": HEADINGS.get(spec.slug, spec.title), "state": _state(review),
                 "run_id": review.run_id if review else None} for spec, review in reviews]
    dev = [HEADINGS.get(spec.slug, spec.title) for spec, review in reviews if review is not None and is_dev_mode_review(review)]
    return {"period": period, "ready": all(s["state"] == APPROVED for s in sections), "sections": sections,
            "is_dev_draft": bool(dev), "dev_sections": dev, "dev_mode_label": DEV_LABEL if dev else None,
            "can_send": not dev, "file_name": file_name(period)}


def require_all_approved(reviews: list[tuple[SectionSpec, Optional[CoordinatorReview]]]) -> list[tuple[SectionSpec, CoordinatorReview]]:
    wording = {"not_drafted": "not drafted", "in_review": "still in review", "rejected": "rejected"}
    missing = [f"{HEADINGS.get(spec.slug, spec.title)} ({wording[_state(review)]})" for spec, review in reviews
               if _state(review) != APPROVED]
    if missing:
        raise ExportNotAllowed("The weekly report can be exported only when every section is approved. Not yet: "
                               + "; ".join(missing) + ".")
    return [(spec, review) for spec, review in reviews if review is not None]


def refuse_to_send(reviews: list[tuple[SectionSpec, CoordinatorReview]]) -> None:
    """Raise if any section was drafted by the local (dev-only) model: such a report never reaches a recipient."""
    dev = [HEADINGS.get(spec.slug, spec.title) for spec, review in reviews if is_dev_mode_review(review)]
    if dev:
        raise DevModeDeliveryBlocked("This weekly report is a DEV MODE draft (local model) and must not be sent or "
                                     f"published: {', '.join(dev)} hold pieces drafted by the local model.")


# ---------------------------------------------------------------------------
# Document pieces
# ---------------------------------------------------------------------------

_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _plain(text: str) -> str:
    return _BOLD.sub(r"\1", text).replace("*", "")


def _add_text(doc, body_md: str) -> None:
    """Paragraphs and "- " bullets of a block's text; inline links become numbered sources listed after it."""
    text, sources = footnote_links(body_md or "")
    for para in re.split(r"\n\s*\n", text.strip()):
        lines = [line for line in para.splitlines() if line.strip()]
        if lines and all(line.lstrip().startswith("- ") for line in lines):
            for line in lines:
                doc.add_paragraph(_plain(line.lstrip()[2:]), style="List Bullet")
        elif lines:
            head = [line for line in lines if not line.lstrip().startswith("- ")]
            doc.add_paragraph(_plain(" ".join(line.strip() for line in head)))
            for line in lines:
                if line.lstrip().startswith("- "):
                    doc.add_paragraph(_plain(line.lstrip()[2:]), style="List Bullet")
    if sources:
        p = _small(doc, "Sources:")
        for n, anchor, url in sources:
            p.add_run().add_break()
            p.add_run(f"[{n}] {anchor}: {url}").font.size = Pt(9)


def _add_grid(doc, grid: list[list[str]], header_rows: int = 1, numeric_from: int = 1) -> None:
    table = doc.add_table(rows=0, cols=len(grid[0]))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for r, values in enumerate(grid):
        cells = table.add_row().cells
        for c, value in enumerate(values):
            cells[c].text = ""
            para = cells[c].paragraphs[0]
            run = para.add_run("" if value is None else str(value))
            run.font.size, run.bold = Pt(8), r < header_rows
            para.alignment = WD_ALIGN_PARAGRAPH.RIGHT if c >= numeric_from and r >= header_rows else WD_ALIGN_PARAGRAPH.LEFT
            para.paragraph_format.space_after = Pt(0)
            if r < header_rows:
                _shade(cells[c], "E7EAF0")


def _source_line(doc, source: dict[str, Any]) -> None:
    if source and source.get("name"):
        _small(doc, f"Source: {source['name']}")


def _add_table_block(doc, block: dict[str, Any]) -> None:
    doc.add_paragraph().add_run(block["title"]).bold = True
    if block.get("export_grid"):
        _add_grid(doc, block["export_grid"], header_rows=2)
    else:
        columns = block["columns"]
        numeric = next((n for n, c in enumerate(columns) if c.get("fmt", "text") != "text"), len(columns))
        grid = [[c["label"] for c in columns]] + [[row.get(c["key"], "") for c in columns] for row in block.get("rows", [])]
        _add_grid(doc, grid, numeric_from=numeric)
    for note in block.get("footnotes") or []:
        _small(doc, note)
    for note in block.get("notes") or []:
        _small(doc, note, italic=True)
    _source_line(doc, block.get("source") or {})
    failed = [r for r in block.get("source_rows", []) if r.get("error")]
    for r in failed:
        _small(doc, f"{r.get(block['key_field'])}: {r['error']}", color=_RED, italic=True)


def _charts(doc, captions: list[str]) -> None:
    for caption in captions:
        p = doc.add_paragraph()
        r = p.add_run(f"[Chart to add: {caption}]")
        r.italic, r.font.color.rgb = True, _INK


def _add_blocks(doc, section: dict[str, Any]) -> None:
    chart_after: dict[str, list[str]] = section.get("chart_after") or {}
    placed: set[str] = set()
    for block in section.get("blocks", []):
        kind = block["kind"]
        if block.get("export") is False:
            continue   # shown on the review screen only; its content is inside another block's table
        if kind == "table":
            _add_table_block(doc, block)
        elif kind == "narrative":
            doc.add_heading(block.get("headline") or block.get("topic") or "", level=2)
            _add_text(doc, block.get("body_md") or "")
        elif kind == "computed":
            doc.add_heading(block["title"], level=2)
            _add_text(doc, block["body_md"])
            names = [s["name"] for s in block.get("sources") or [] if s.get("name")]
            if names:
                _small(doc, "Source: " + "; ".join(names))
        elif kind == "carried":
            doc.add_heading(block["title"], level=2)
            note = doc.add_paragraph().add_run(CARRIED_NOTE)
            note.bold, note.font.color.rgb = True, _RED
            _add_text(doc, block["body_md"])
        elif kind == "supplied":
            if len(section.get("blocks", [])) > 1:
                doc.add_heading(block["title"], level=2)
            _add_text(doc, block["body_md"])
        elif kind == "unavailable":
            p = doc.add_paragraph()
            r = p.add_run(f"[Not included: {block['title']}. {block['reason']}]")
            r.italic, r.font.color.rgb = True, _RED
        captions = chart_after.get(block["id"]) or []
        _charts(doc, captions)
        placed.update(captions)
    _charts(doc, [c for c in section.get("chart_notes") or [] if c not in placed])


def _add_digital_payments(doc, section: dict[str, Any]) -> None:
    """The weekly Digital Payments shape: highlights and the stock table as items, then the outlook."""
    outlook = section.get("outlook") or {}
    for item in section.get("items", []):
        if item.get("kind") == "highlight":
            doc.add_heading(f"{item.get('numeral', '')}. {item.get('headline', '')}".strip(". "), level=2)
            _add_text(doc, item.get("body_md") or item.get("body") or "")
        elif item.get("kind") == "stock_table":
            doc.add_paragraph().add_run(f"{item.get('numeral', '')}. {TABLE_TITLE}".strip(". ")).bold = True
            rows = item.get("rows", [])
            grid = [[label for _, label, _ in TABLE_COLUMNS]] + [[r[k] for k, _, _ in TABLE_COLUMNS] for r in format_table_rows(rows)]
            average = _average_row(outlook.get("stats") or {})
            if average:
                grid.append(average)
            _add_grid(doc, grid, numeric_from=2)
            _small(doc, "Source: Yahoo Finance. Forward P/E is based on analyst consensus forward earnings estimates.")
    text = outlook.get("text") or (outlook.get("text_md") or "").strip("*")
    if text:
        doc.add_heading("Outlook", level=2)
        doc.add_paragraph(_plain(text))


def _watermark(doc) -> None:
    """A diagonal DEV MODE watermark behind every page, and the full label at the top of every page."""
    for sec in doc.sections:
        header = sec.header
        para = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
        run = para.add_run(DEV_LABEL)
        run.bold, run.font.color.rgb, run.font.size = True, _RED, Pt(9)
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pict = parse_xml(
            '<w:pict xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">'
            '<v:shape id="DevModeWatermark" o:spid="_x0000_s2049" type="#_x0000_t136" '
            'style="position:absolute;margin-left:0;margin-top:0;width:468pt;height:117pt;rotation:315;z-index:-251658752;'
            'mso-position-horizontal:center;mso-position-horizontal-relative:margin;'
            'mso-position-vertical:center;mso-position-vertical-relative:margin" '
            'o:allowincell="f" fillcolor="#c00000" stroked="f">'
            '<v:fill opacity=".25"/>'
            f'<v:textpath style="font-family:&quot;Calibri&quot;;font-size:1pt" string="{WATERMARK}"/>'
            "</v:shape></w:pict>")
        para.add_run()._r.append(pict)


def report_title(period: str) -> str:
    week = week_ending_of(period)
    if week is not None:
        return f"Cytonn Weekly: week ending {ordinal(week)}"
    return f"Cytonn Weekly: {period}" if period else "Cytonn Weekly"


def build_weekly_document(reviews: list[tuple[SectionSpec, CoordinatorReview]], period: str):
    """The python-docx Document of an approved week (the caller has already required every section approved)."""
    doc = Document()
    _style_document(doc)
    heading1 = doc.styles["Heading 1"]
    heading1.font.name, heading1.font.size, heading1.font.bold = "Calibri", Pt(16), True
    heading1.font.color.rgb = _INK
    doc.core_properties.title = report_title(period)
    doc.core_properties.author = "Cytonn Weekly tool"
    dev = any(is_dev_mode_review(review) for _, review in reviews)
    if dev:
        _watermark(doc)
        banner = doc.add_paragraph().add_run(DEV_LABEL)
        banner.bold, banner.font.color.rgb = True, _RED

    title = doc.add_paragraph().add_run(report_title(period))
    title.bold, title.font.size, title.font.color.rgb = True, Pt(22), _INK
    decided = max((review.decided_at or "" for _, review in reviews), default="")
    _small(doc, f"Every section checked and approved by the coordinator{f' (last on {decided[:10]})' if decided else ''}. "
                "Charts are added by hand where marked; text marked as carried forward must be edited before publishing.")

    for spec, review in reviews:
        doc.add_heading(HEADINGS.get(spec.slug, spec.title), level=1)
        section = review.section
        if "blocks" in section:
            _add_blocks(doc, section)
        else:
            _add_digital_payments(doc, section)

    doc.add_page_break()
    doc.add_heading(SUMMARIES_HEADING, level=1)
    _small(doc, "One per section, composed from the section's own lead paragraphs. The website builds the issue's "
                "Executive Summary from these.")
    for spec, review in reviews:
        doc.add_heading(HEADINGS.get(spec.slug, spec.title), level=2)
        summary = section_summary(review.section)
        if summary:
            _add_text(doc, summary)
        else:
            _small(doc, "No summary: the published issue's section has none.", italic=True)
    return doc


# ---------------------------------------------------------------------------
# Writing the file
# ---------------------------------------------------------------------------

def _label(period: str) -> str:
    week = week_ending_of(period)
    if week is not None:
        return week.isoformat()
    return re.sub(r"[^A-Za-z0-9]+", "-", period).strip("-") or "unlabelled"


def file_name(period: str) -> str:
    return f"Cytonn-Weekly-{_label(period)}.docx"


def export_dir(root: Optional[Union[Path, str]] = None) -> Path:
    return Path(root) if root is not None else paths.DATA_DIR / "exports" / "weekly"


def write_weekly_report(db_path: Optional[Union[Path, str]], period: str, out_dir: Optional[Union[Path, str]] = None,
                        today: Optional[date] = None) -> Path:
    """Write the week's approved report and return its path.  ExportNotAllowed unless every section is approved."""
    reviews = require_all_approved(weekly_reviews(db_path, period, today))
    folder = export_dir(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / file_name(period)
    build_weekly_document(reviews, period).save(str(path))
    return path
