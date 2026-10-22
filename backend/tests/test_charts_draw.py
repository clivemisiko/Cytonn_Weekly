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

from cytonn_weekly.charts.draw import FONT, alt_text, average_label, render_png, subtitle
from cytonn_weekly.charts.series import average, read_series, windowed
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
    assert sum(1 for p in px if p == NAVY_RGB) > 500                   # the series and average lines, and the label
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
    assert NASI_PE.window_years == 5 and shown[-1].day == FRIDAY
    assert date(2021, 10, 2) <= shown[0].day < date(2021, 10, 9)        # five years back from the newest point


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

    from cytonn_weekly.charts.draw import NAVY, SKY, figure

    s = series(weeks=931, stated=(12.95, 0.05295))
    shown, a = windowed(s), average(s)
    fig = figure(s)
    ax = fig.axes[0]
    left, right = (num2date(x).date() for x in ax.get_xlim())
    assert (left, right) == (shown[0].day, shown[-1].day)                    # five years, not every point read
    line, level = ax.get_lines()
    assert to_hex(line.get_color()) == NAVY.lower() and len(line.get_xdata()) == len(shown)
    assert to_hex(level.get_color()) == NAVY.lower() and level.get_linestyle() == "--"
    assert float(level.get_ydata()[0]) == float(a.value)                      # the line sits at the average since 2009
    fills = [c for c in ax.collections if isinstance(c, PolyCollection)]
    assert len(fills) == 1 and to_hex(fills[0].get_facecolor()[0], keep_alpha=False) == SKY.lower()
    texts = [t.get_text().strip() for t in ax.texts + fig.texts]
    assert average_label(s, a) in texts and subtitle(a) in texts
