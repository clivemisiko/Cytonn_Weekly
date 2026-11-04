"""The published report's look, from one theme module: the charts' colours, fonts and axes, and the Word tables' fills,
text colours and borders.  Invented series and invented table rows only."""

import io
import re

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


def test_tables_have_thin_black_borders_and_calibri_text():
    for table in tables():
        borders = table._tbl.tblPr.xml
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            assert re.search(rf'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="000000"/>', borders), side
        for row in table.rows:
            for cell in row.cells:
                for run in cell.paragraphs[0].runs:
                    assert run.font.name == "Calibri"
