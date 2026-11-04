"""The published report's look, from one theme module: the charts' colours, fonts and axes, and the Word tables' fills,
text colours and borders.  Invented series and invented table rows only."""

import io
import re
from datetime import date

import pytest
from docx import Document
from matplotlib.colors import to_hex
from PIL import Image

from cytonn_weekly.charts import draw
from cytonn_weekly.charts.series import read_series
from cytonn_weekly.charts.specs import NASI_PE, NASI_YIELD
from cytonn_weekly.common import word_layout as wl
from cytonn_weekly.weekly import export
from tests.chart_helpers import FRIDAY, book

GREEN_RGB = (0x00, 0x6C, 0x5B)
OLD_FILL_RGB = (205, 234, 255)     # the light blue area the chart used to draw
OLD_SKY_RGB = (111, 195, 255)


def series(spec=NASI_YIELD, weeks=400):
    return read_series(book(weeks=weeks), spec, FRIDAY)


def near(rgb, target, tol=12):
    return all(abs(a - b) <= tol for a, b in zip(rgb, target))


def drawn(fig):
    fig.canvas.draw()
    return fig


# --- the theme module is the one place the values live ----------------------------------------------------------

def test_the_theme_holds_the_published_values():
    from cytonn_weekly.common import report_theme as theme

    assert theme.GREEN == "#006C5B" and theme.YELLOW == "#FFFF00" and theme.RED == "#FF0000"
    assert (theme.CHART_LINE, theme.CHART_LINE_PT) == (theme.GREEN, 2.25)
    assert (theme.AVERAGE_LINE, theme.AVERAGE_LINE_PT) == (theme.RED, 1.5)
    assert (theme.CHART_FONTS[:2], theme.CHART_TEXT_PT) == (("Calibri", "Carlito"), 9)
    assert theme.RECOMMENDATION_FILLS == {"Buy": "#00FF00", "Accumulate": "#ED7D31", "Hold": "#A6A6A6",
                                          "Lighten": "#0070C0", "Sell": "#FF0000"}
    assert theme.RATING_FILL == "#F5F5F5" and theme.TABLE_FONT == "Calibri"
    # constants only, for the charts not built yet
    assert (theme.BAR, theme.BAR_CYTONN) == (theme.GREEN, theme.YELLOW)
    assert theme.TBILL_LINES == {"91-day": theme.GREEN, "182-day": theme.YELLOW, "364-day": theme.RED}
    assert theme.LEGEND_LOC == "lower center"


def test_the_chart_and_the_word_tables_take_their_colours_from_the_theme():
    from cytonn_weekly.common import report_theme as theme

    assert wl.HEADER_FILL == theme.GREEN.lstrip("#")
    src = open(draw.__file__, encoding="utf-8").read()
    assert not re.search(r"#[0-9A-Fa-f]{6}", src), "a colour is written in draw.py instead of the theme"


# --- the chart -----------------------------------------------------------------------------------------------------

def test_the_dividend_yield_chart_draws_a_green_line_with_no_fill():
    img = Image.open(io.BytesIO(draw.render_png(series()))).convert("RGB")
    px = list(img.getdata())
    assert sum(1 for p in px if near(p, GREEN_RGB)) > 1500
    assert not any(near(p, OLD_FILL_RGB, tol=3) or near(p, OLD_SKY_RGB, tol=3) for p in px)
    fig = draw.figure(series())
    ax = fig.axes[0]
    assert not ax.collections                                           # no area under the line
    assert not any(g.get_visible() for g in ax.get_xgridlines() + ax.get_ygridlines())
    line, level = ax.get_lines()
    assert to_hex(line.get_color()) == "#006c5b" and line.get_linewidth() == 2.25
    assert to_hex(level.get_color()) == "#ff0000" and level.get_linewidth() == 1.5 and level.get_linestyle() == "--"


def test_the_y_axis_starts_at_zero_and_steps_by_two():
    s = series()
    fig = drawn(draw.figure(s))
    ax = fig.axes[0]
    top = max(float(p.value) for p in draw.windowed(s))
    assert ax.get_ylim()[0] == 0 and ax.get_ylim()[1] == (int(top // 2) + 1) * 2   # the next multiple of 2 above the data
    labels = [t.get_text() for t in ax.get_yticklabels() if t.get_text()]
    assert labels[0] == "0.0%" and "6.0%" in labels
    pe = drawn(draw.figure(read_series(book(weeks=60), NASI_PE, FRIDAY)))     # an invented P/E that stays under 19
    pax = pe.axes[0]
    assert pax.get_ylim() == (0, 19) and list(pax.get_yticks()) == list(range(0, 19, 2))
    assert [t.get_text() for t in pax.get_yticklabels()][:2] == ["0.0x", "2.0x"] and "12.0x" in [t.get_text() for t in pax.get_yticklabels()]


def test_the_title_end_label_and_tick_labels_are_bold_black_calibri():
    s = series()
    fig = drawn(draw.figure(s))
    ax = fig.axes[0]
    title = next(t for t in fig.texts if t.get_text() == "Cytonn Report: NASI Dividend Yield")
    assert title.get_ha() == "center" and title.get_weight() == "bold" and to_hex(title.get_color()) == "#000000"
    [under] = fig.findobj(lambda a: a.get_gid() == "title-underline")       # matplotlib has no underlined text
    box = title.get_window_extent()
    xs = [x * fig.bbox.width for x in under.get_xdata()]
    assert abs(xs[0] - box.x0) < 2 and abs(xs[1] - box.x1) < 2 and to_hex(under.get_color()) == "#000000"
    assert not any("weekly points" in t.get_text() for t in fig.texts + ax.texts)          # the grey caption sentence is gone
    end = next(t for t in ax.texts if t.get_gid() == "end-label")
    assert end.get_text() == "5.0%" and end.get_weight() == "bold" and to_hex(end.get_color()) == "#000000"
    avg = next(t for t in ax.texts if t.get_text().strip().startswith("Average = "))
    assert avg.get_weight() == "bold" and to_hex(avg.get_color()) == "#000000" and avg.get_fontsize() == 9
    for t in ax.get_xticklabels() + ax.get_yticklabels() + [end, title]:
        assert t.get_fontfamily()[0] in ("Calibri", "Carlito", "DejaVu Sans")
    for t in ax.get_xticklabels() + ax.get_yticklabels():
        assert t.get_fontsize() == 9 and t.get_weight() == "bold" and to_hex(t.get_color()) == "#000000"
    pe = drawn(draw.figure(read_series(book(weeks=60), NASI_PE, FRIDAY)))
    assert any(t.get_text() == "Cytonn Report: NASI P/E" for t in pe.texts)
    assert next(t for t in pe.axes[0].texts if t.get_gid() == "end-label").get_text() == "10.0x"


# --- the Word tables -------------------------------------------------------------------------------------------------

def table_block():
    columns = [{"key": "name", "label": "Company", "fmt": "text"}, {"key": "price", "label": "Price", "fmt": "price"},
               {"key": "rec", "label": "Recommendation", "fmt": "text"}, {"key": "outlook", "label": "Outlook", "fmt": "text"}]
    rows = [{"name": "Invented Bank", "price": "10.0", "rec": rec, "outlook": "Neutral"}
            for rec in ("Buy", "Accumulate", "Hold", "Lighten", "Sell")]
    rows += [{"name": "Cytonn Money Market Fund", "price": "11.0", "rec": "", "outlook": ""},
             {"name": "Average", "price": "10.0", "rec": "", "outlook": ""}]
    return {"kind": "table", "title": "Cytonn Report: Invented Table", "columns": columns, "rows": rows, "source": {"name": "Invented"}}


def grid_block():
    grid = [["", "2018"], ["Tenor", "10-year issue"], ["01-Oct-26", "7.6%"], ["Weekly Change", "(0.1%)"], ["YTD Change", "1.2%"]]
    return {"kind": "table", "title": "Cytonn Report: Invented Grid", "columns": [], "rows": [], "export_grid": grid}


def cell_look(cell):
    xml = cell._tc.xml
    fill = re.search(r'w:fill="([0-9A-Fa-f]{6})"', xml)
    colours = frozenset(re.findall(r'<w:color w:val="([0-9A-Fa-f]{6})"', xml))
    return (fill.group(1).upper() if fill else None), colours, "<w:b/>" in xml


def tables():
    doc = Document()
    wl.apply_report_look(doc)
    export._add_table_block(doc, table_block())
    export._add_table_block(doc, grid_block())
    return doc.tables


def test_title_and_header_rows_are_green_with_white_bold_text():
    plain, grid = tables()
    for table, header_rows in ((plain, 2), (grid, 3)):        # the title row, then the table's own header rows
        for row in table.rows[:header_rows]:
            for cell in row.cells:
                assert cell_look(cell) == ("006C5B", {"FFFFFF"}, True), cell.text
    assert plain.rows[0].cells[0].text == "Cytonn Report: Invented Table"   # the title, unchanged, in the title row
    assert len({c._tc for c in plain.rows[0].cells}) == 1                    # one merged cell across the table


def test_summary_and_cytonn_rows_are_yellow_and_body_rows_white_with_black_text():
    plain, grid = tables()
    by_name = {r.cells[0].text: r for r in plain.rows[2:]}
    for name in ("Average", "Cytonn Money Market Fund"):
        assert {cell_look(c)[:2] for c in by_name[name].cells} == {("FFFF00", frozenset({"000000"}))}
    body = by_name["Invented Bank"].cells
    assert cell_look(body[0])[:2] == ("FFFFFF", {"000000"}) and cell_look(body[1])[:2] == ("FFFFFF", {"000000"})
    by_label = {r.cells[0].text: r for r in grid.rows[3:]}
    assert cell_look(by_label["01-Oct-26"].cells[1])[:2] == ("FFFFFF", {"000000"})
    for label in ("Weekly Change", "YTD Change"):     # the published Eurobond change rows: yellow, red text
        assert {cell_look(c)[:2] for c in by_label[label].cells} == {("FFFF00", frozenset({"FF0000"}))}


def test_recommendation_and_outlook_cells_carry_the_published_fills():
    plain, _ = tables()
    recs = {r.cells[2].text: cell_look(r.cells[2])[:2] for r in plain.rows[2:7]}
    assert recs == {"Buy": ("00FF00", {"000000"}), "Accumulate": ("ED7D31", {"000000"}), "Hold": ("A6A6A6", {"000000"}),
                    "Lighten": ("0070C0", {"000000"}), "Sell": ("FF0000", {"000000"})}
    assert {cell_look(r.cells[3])[0] for r in plain.rows[2:7]} == {"F5F5F5"}


CENTER, LEFT = 1, 0     # WD_ALIGN_PARAGRAPH.CENTER, .LEFT


def mmf_block():
    columns = [{"key": "rank", "label": "Rank", "fmt": "text"}, {"key": "fund", "label": "Fund Manager", "fmt": "text"},
               {"key": "rate", "label": "Effective Annual Rate", "fmt": "pct"}]
    rows = [{"rank": "1", "fund": "Cytonn Money Market Fund", "rate": "11.0%"}, {"rank": "2", "fund": "Invented Fund", "rate": "10.0%"}]
    return {"kind": "table", "title": "Money Market Fund Yield for Fund Managers", "columns": columns, "rows": rows,
            "source": {"name": "Daily Nation"}}


def euro_block():
    grid = [["", "2018", "2024"], ["Tenor", "10-year issue", "7-year issue"], ["Amount Issued (USD)", "1.0 bn", "1.5 bn"],
            ["Years to Maturity", "1.3", "4.3"], ["Yields at Issue", "7.3%", "10.4%"], ["01-Oct-26", "7.6%", "8.3%"],
            ["Weekly Change", "(0.1%)", "(0.3%)"]]
    return {"kind": "table", "title": "Cytonn Report: Kenya Eurobonds Performance", "columns": [], "rows": [],
            "export_grid": grid, "notes": ["Changes are in percentage points."], "source": {"name": "CBK"}}


def exported(*blocks):
    doc = Document()
    wl.apply_report_look(doc)
    for b in blocks:
        export._add_table_block(doc, b)
    return doc


def align(cell):
    return cell.paragraphs[0].alignment


def test_titles_headers_and_values_are_centred_and_only_names_stay_left():
    plain, mmf, euro = exported(table_block(), mmf_block(), euro_block()).tables
    for table, headers in ((plain, 2), (mmf, 2), (euro, 6)):     # title + header rows (and the Eurobond's fixed rows)
        for row in table.rows[:headers]:
            assert {align(c) for c in row.cells} == {CENTER}, row.cells[0].text
    for row in plain.rows[2:]:
        assert align(row.cells[0]) == LEFT and {align(c) for c in row.cells[1:]} == {CENTER}   # Company stays left
    for row in mmf.rows[2:]:
        assert [align(c) for c in row.cells] == [CENTER, LEFT, CENTER]       # Rank and the rate centred, the fund left
    for row in euro.rows[6:]:
        assert {align(c) for c in row.cells} == {CENTER}                     # the date column and the values


def test_the_eurobond_fixed_rows_take_the_header_look():
    euro = exported(euro_block()).tables[0]
    by_label = {r.cells[0].text: r for r in euro.rows}
    for label in ("Amount Issued (USD)", "Years to Maturity", "Yields at Issue"):
        assert {cell_look(c) for c in by_label[label].cells} == {("006C5B", frozenset({"FFFFFF"}), True)}, label
    assert cell_look(by_label["01-Oct-26"].cells[1])[:2] == ("FFFFFF", frozenset({"000000"}))
    assert cell_look(by_label["Weekly Change"].cells[1])[:2] == ("FFFF00", frozenset({"FF0000"}))


def test_table_text_is_9_pt_with_bold_titles_and_headers():
    for table in exported(table_block(), mmf_block(), euro_block()).tables:
        sizes = {run.font.size.pt for row in table.rows for c in row.cells for run in c.paragraphs[0].runs}
        assert sizes == {9.0}
        assert all(run.bold for c in table.rows[0].cells for run in c.paragraphs[0].runs)


def keeps(table):
    return [all(p.paragraph_format.keep_with_next for c in row.cells for p in c.paragraphs) for row in table.rows]


def test_every_row_stays_whole_and_the_table_stays_with_its_source_line():
    doc = exported(mmf_block(), euro_block())
    for table in doc.tables:
        assert all("<w:cantSplit/>" in row._tr.xml for row in table.rows)
        assert all(keeps(table))       # every row, the last too: a source line follows, and it keeps with the table
    lines = [p for p in doc.paragraphs if p.text]
    notes = [p for p in lines if p.text in ("Changes are in percentage points.", "Source: CBK")]
    assert [p.paragraph_format.keep_with_next for p in notes] == [True, False]   # the last line under a table lets go
    alone = Document()
    wl.report_table(alone, [["Company", "Price"], ["A", "1.0"], ["B", "2.0"]])  # nothing under it
    assert keeps(alone.tables[0]) == [True, True, False]


def test_the_digital_payments_summary_table_uses_the_theme():
    from review_helpers import make_review

    from cytonn_weekly.digital_payments import summary as sm

    review = make_review()
    item = next(it for it in review.section["items"] if it["kind"] == "stock_table")
    doc = Document()
    sm._add_table(doc, item["rows"], review.section["outlook"].get("stats") or {})
    table = doc.tables[0]
    assert {cell_look(c) for c in table.rows[0].cells} == {("006C5B", frozenset({"FFFFFF"}), True)}
    assert {align(c) for c in table.rows[0].cells} == {CENTER}
    average = table.rows[-1]
    assert average.cells[0].text == "Average" and {cell_look(c)[:2] for c in average.cells} == {("FFFF00", frozenset({"000000"}))}
    body = table.rows[1]
    assert cell_look(body.cells[0])[:2] == ("FFFFFF", frozenset({"000000"}))
    assert align(body.cells[0]) == LEFT and {align(c) for c in body.cells[1:]} == {CENTER}
    assert {run.font.size.pt for row in table.rows for c in row.cells for run in c.paragraphs[0].runs} == {9.0}
    assert re.search(r'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/>', table._tbl.tblPr.xml)
    assert all("<w:cantSplit/>" in row._tr.xml for row in table.rows)


# --- the average label never sits on the line ------------------------------------------------------------------

def label_clearance(fig):
    """Pixels between the "Average = ..." label's box and the series line nearest it (the line's own width taken off)."""
    import numpy as np
    from matplotlib.dates import date2num

    fig.canvas.draw()
    ax = fig.axes[0]
    label = next(t for t in ax.texts if t.get_text().strip().startswith("Average = "))
    box = label.get_window_extent(fig.canvas.get_renderer())
    line = ax.get_lines()[0]
    xs = np.asarray(date2num(line.get_xdata()), dtype=float)
    ys = np.asarray(line.get_ydata(), dtype=float)
    dense_x = np.linspace(xs[0], xs[-1], 20_000)
    pts = ax.transData.transform(np.column_stack([dense_x, np.interp(dense_x, xs, ys)]))
    inside = pts[(pts[:, 0] >= box.x0) & (pts[:, 0] <= box.x1)]
    half = line.get_linewidth() * fig.dpi / 72 / 2
    gaps = np.where(inside[:, 1] > box.y1, inside[:, 1] - box.y1,
                    np.where(inside[:, 1] < box.y0, box.y0 - inside[:, 1], -1.0))
    return float(gaps.min()) - half


@pytest.mark.parametrize("spec", [NASI_YIELD, NASI_PE])
def test_the_average_label_is_clear_of_the_line_on_the_real_30_october_series(spec):
    from cytonn_weekly.weekly.workbook import Workbook
    from tests.weekly_helpers import sample

    s = read_series(Workbook(sample("Equities Workbook 30.10.2026.vf (1).xlsx"), "Equities workbook"), spec, date(2026, 10, 30))
    assert s.drawn
    assert label_clearance(draw.figure(s)) > 0


def test_the_average_label_is_clear_of_an_invented_line_that_crosses_it():
    assert label_clearance(draw.figure(series())) > 0


# --- the image the API runs in ------------------------------------------------------------------------------------

def test_the_image_installs_carlito_beside_the_opencv_libraries():
    from cytonn_weekly import paths

    docker = (paths.BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")
    line = next(ln for ln in docker.splitlines() if "apt-get install" in ln)
    assert "--no-install-recommends" in line and {"libgl1", "libglib2.0-0", "fonts-crosextra-carlito"} <= set(line.split())


def test_tables_have_thin_black_borders_and_calibri_text():
    for table in tables():
        borders = table._tbl.tblPr.xml
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            assert re.search(rf'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="000000"/>', borders), side
        for row in table.rows:
            for cell in row.cells:
                for run in cell.paragraphs[0].runs:
                    assert run.font.name == "Calibri"
