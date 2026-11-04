"""Drawing a chart: the picture's size and colours, its labels, its window and its alt text (invented series only).

There is no golden image or hash: the PNG is checked through Pillow for its size, that it is not
blank, and where its colours are, so a matplotlib upgrade that moves a pixel does not fail a test.
"""

import io
from datetime import date

import pytest
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties
from PIL import Image

from cytonn_weekly.charts.draw import FONT, alt_text, average_label, render_png, subtitle, ticks
from cytonn_weekly.charts.series import ChartSeries, average, read_series, windowed
from cytonn_weekly.charts.specs import NASI_PE, NASI_YIELD
from tests.chart_helpers import FRIDAY, book, day

NAVY_RGB, SKY_RGB = (1, 54, 96), (111, 195, 255)
FILL_RGB = (205, 234, 255)     # the light blue at the drawn opacity over white


def series(spec=NASI_PE, **kw):
    return read_series(book(**kw), spec, FRIDAY)


def pixels(png: bytes):
    img = Image.open(io.BytesIO(png)).convert("RGB")
    return img, list(img.getdata())


def near(rgb, target, tol=3):
    return all(abs(a - b) <= tol for a, b in zip(rgb, target))


def test_the_picture_is_6_by_3_inches_at_200_dpi_and_not_blank():
    for spec in (NASI_PE, NASI_YIELD):
        img, px = pixels(render_png(series(spec, weeks=400)))
        assert img.size == (1200, 600)
        assert sum(1 for p in px if p != (255, 255, 255)) > 0.03 * len(px)


def test_navy_draws_the_line_and_light_blue_only_fills_under_it():
    _, px = pixels(render_png(series(weeks=400)))
    assert sum(1 for p in px if p == NAVY_RGB) > 500                   # the series line and the average label
    assert sum(1 for p in px if near(p, FILL_RGB)) > 10_000            # the area under the line
    assert not any(near(p, SKY_RGB, tol=2) for p in px)                # never at full strength: no light blue text or line


def test_the_same_series_draws_the_same_bytes():
    s = series(weeks=400)
    assert render_png(s) == render_png(s)


def test_a_chart_that_is_not_drawn_is_never_rendered():
    with pytest.raises(ValueError, match="not drawn"):
        render_png(series(newest=day(1)))


def test_the_font_is_the_one_bundled_with_matplotlib():
    path = font_manager.findfont(FontProperties(family=FONT), fallback_to_default=False)
    assert "mpl-data" in path.replace("\\", "/") and FONT == "DejaVu Sans"


def test_the_average_label_and_subtitle_print_the_average_from_2009_not_only_the_window():
    s = series(weeks=931, stated=(12.95, 0.05295))
    a = average(s)
    assert average_label(s, a) == f"Average = {a.display}x"
    assert subtitle(a) == f"Average of {a.count} weekly points, 2 Jan 2009 to 2 Oct 2026"     # no leading zero on the day
    assert a.count > len(windowed(s))
    y = series(NASI_YIELD, weeks=60)
    assert average_label(y, average(y)) == "Average = 5.3%"


def test_the_window_comes_from_the_spec():
    s = series(weeks=931)
    shown = windowed(s)
    assert NASI_PE.window_years == 7 and shown[-1].day == FRIDAY
    assert date(2019, 10, 1) <= shown[0].day < date(2019, 10, 8)        # the first of the week's month, seven years back


def test_the_alt_text_is_built_from_the_caption_and_says_what_is_shown():
    s = series(weeks=931)
    shown, a = windowed(s), average(s)
    text = alt_text(s, a)
    assert text.startswith(NASI_PE.caption + ". Line chart of ")
    assert f"{len(shown)} weekly points" in text and "the latest is 10.0x on 2 Oct 2026" in text
    assert average_label(s, a) in text and f"over {a.count} weekly points since 2 Jan 2009" in text


def test_the_figure_shows_the_specs_window_the_line_the_fill_and_the_average():
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import to_hex
    from matplotlib.dates import num2date

    from cytonn_weekly.charts.draw import AVERAGE_RED, NAVY, SKY, figure

    s = series(weeks=931, stated=(12.95, 0.05295))
    shown, a = windowed(s), average(s)
    fig = figure(s)
    ax = fig.axes[0]
    left, right = (num2date(x).date() for x in ax.get_xlim())
    assert (left, right) == (date(2019, 10, 1), shown[-1].day)               # opens on the first tick, not every point read
    assert left < shown[0].day < date(2019, 10, 8)
    line, level = ax.get_lines()
    assert to_hex(line.get_color()) == NAVY.lower() and len(line.get_xdata()) == len(shown)
    assert to_hex(level.get_color()) == AVERAGE_RED.lower() == "#ff0000" and level.get_linestyle() == "--"
    label = next(t for t in ax.texts if t.get_text().strip() == average_label(s, a))
    assert to_hex(label.get_color()) == NAVY.lower() != AVERAGE_RED.lower()  # only the dashed line is red
    assert float(level.get_ydata()[0]) == float(a.value)                      # the line sits at the average since 2009
    fills = [c for c in ax.collections if isinstance(c, PolyCollection)]
    assert len(fills) == 1 and to_hex(fills[0].get_facecolor()[0], keep_alpha=False) == SKY.lower()
    texts = [t.get_text().strip() for t in ax.texts + fig.texts]
    assert average_label(s, a) in texts and subtitle(a) in texts


def tick_labels(week_ending):
    return [f"{d:%b-%y}" for d in ticks(ChartSeries(NASI_PE, week_ending, "B", (), (), None))]


def test_the_ticks_run_every_third_month_from_the_window_start_month_to_the_report_month():
    labels = tick_labels(date(2026, 10, 23))
    assert (labels[0], labels[1], labels[2], labels[-1], len(labels)) == ("Oct-19", "Jan-20", "Apr-20", "Oct-26", 29)
    assert all(label[:3] in ("Jan", "Apr", "Jul", "Oct") for label in labels)
    assert tick_labels(date(2026, 10, 30)) == labels                   # the same for every week of the month
    nov = tick_labels(date(2026, 11, 6))
    assert (nov[0], nov[1], nov[-1], len(nov)) == ("Nov-19", "Feb-20", "Nov-26", 29)
    jan = tick_labels(date(2027, 1, 8))
    assert (jan[0], jan[1], jan[-1], len(jan)) == ("Jan-20", "Apr-20", "Jan-27", 29)


def test_the_figure_prints_the_ticks_vertically_and_none_overlaps_or_runs_off_the_picture():
    from cytonn_weekly.charts.draw import figure

    fig = figure(series(weeks=931))
    ax = fig.axes[0]
    fig.canvas.draw()
    shown = [t for t in ax.get_xticklabels() if t.get_text()]
    assert [t.get_text() for t in shown] == tick_labels(FRIDAY) and len(shown) == 29
    assert all(t.get_rotation() == 90 for t in shown)
    boxes = [t.get_window_extent(fig.canvas.get_renderer()) for t in shown]
    assert all(a.x1 <= b.x0 for a, b in zip(boxes, boxes[1:]))
    assert min(b.y0 for b in boxes) >= 0 and min(b.x0 for b in boxes) >= 0 and max(b.x1 for b in boxes) <= fig.bbox.width
