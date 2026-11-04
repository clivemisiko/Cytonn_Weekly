"""Drawing one chart as a PNG from a read series.  Nothing here reads a workbook or decides a figure.

matplotlib's ``Figure`` and its Agg canvas are used directly, never pyplot: pyplot keeps global
state, and drafts run in worker threads.  No global setting (rcParams) is changed; the font is
named on every text: Calibri, else Carlito, else DejaVu Sans, which ships inside matplotlib.
Colours, widths and sizes come from ``common/report_theme.py``.  A float is used only to place a
point on the picture; every number printed on it (the average and end labels) is the series' own
Decimal display.
"""

from __future__ import annotations

import io
import logging
from bisect import bisect_right
from datetime import date
from functools import cache
from typing import Optional

from matplotlib import font_manager
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.dates import date2num
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from cytonn_weekly.charts.series import Average, ChartSeries, average, window_start, windowed
from cytonn_weekly.common import report_theme as theme
from cytonn_weekly.common.formatting import MULTIPLE, PCT, fmt_value

log = logging.getLogger(__name__)
FALLBACK_FONT = "DejaVu Sans"      # bundled with matplotlib
WIDTH_IN, HEIGHT_IN, DPI = 6.0, 3.0, 200    # 1200 x 600 pixels, placed at 6.0 in in the Word export


@cache
def chart_font() -> str:
    """The first of the theme's chart fonts installed here, else the font bundled with matplotlib (said once)."""
    installed = {f.name for f in font_manager.fontManager.ttflist}
    found = next((name for name in theme.CHART_FONTS if name in installed), None)
    if found is None:
        log.warning("Charts: neither %s is installed; drawing in %s", " nor ".join(theme.CHART_FONTS), FALLBACK_FONT)
    return found or FALLBACK_FONT


def _fmt(spec_unit: str) -> str:
    return PCT if spec_unit == "pct" else MULTIPLE


def _day(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def average_label(series: ChartSeries, avg: Average) -> str:
    """"Average = 10.0x" (or a percentage), from the average's own display figure."""
    return f"Average = {fmt_value(avg.display, _fmt(series.spec.unit), series.spec.decimals)}"


def chart_title(series: ChartSeries) -> str:
    return f"{theme.CHART_TITLE_PREFIX}{series.spec.name}"


def y_axis(series: ChartSeries, high: float) -> tuple[int, list[int]]:
    """(top, ticks): from 0, a tick every ``y_step``; the spec's top, or the next multiple of the step above ``high``."""
    step, top = series.spec.y_step, series.spec.y_top
    if top is None or high >= top:   # never cut off the data
        top = (int(high // step) + 1) * step
    return top, list(range(0, top + 1 if top % step == 0 else top, step))


def alt_text(series: ChartSeries, avg: Optional[Average]) -> str:
    """What the picture shows, in words: the caption, the window and the figures printed on it."""
    shown = windowed(series)
    last = series.points[-1]
    unit = _fmt(series.spec.unit)
    text = (f"{series.spec.caption}. Line chart of {len(shown)} weekly points from {_day(shown[0].day)} to "
            f"{_day(shown[-1].day)}; the latest is {fmt_value(last.value, unit, series.spec.decimals)} on {_day(last.day)}.")
    if avg is not None:
        text += f" A dashed line marks the {average_label(series, avg)}, over {avg.count} weekly points since {_day(avg.first)}."
    return text


def ticks(series: ChartSeries) -> list[date]:
    """The first of the window-start month, then every third month, up to the report month (as the published chart)."""
    day, last = window_start(series), series.week_ending.replace(day=1)
    out = []
    while day <= last:
        out.append(day)
        month = day.month + 2
        day = day.replace(year=day.year + month // 12, month=month % 12 + 1)
    return out


LABEL_GAP_PT = 2    # between the average line and its label


def _place_average_label(fig, ax, label, xs: list[date], ys: list[float], level: float) -> None:
    """Put the label where, across its own width, the series is furthest from the average line, on the series' side.

    Every start point is tried; the points just outside the label's width are counted too, so a segment entering
    its width is never missed."""
    # ponytail: O(n * width) scan over about 365 weekly points; fine for weekly charts, a sliding window if series grow.
    renderer = fig.canvas.get_renderer()
    width = label.get_window_extent(renderer).width
    pts = [tuple(map(float, p)) for p in ax.transData.transform(list(zip(date2num(xs), ys)))]
    px = [p[0] for p in pts]
    line = float(ax.transData.transform((0, level))[1])
    right = ax.get_window_extent(renderer).x1
    best = None
    for i, x0 in enumerate(px):
        if x0 + width > right:
            break
        span = [p[1] for p in pts[max(i - 1, 0):bisect_right(px, x0 + width) + 1]]
        above, below = min(span) - line, line - max(span)
        gap, side = (above, "above") if above >= below else (below, "below")
        if best is None or gap > best[0]:
            best = (gap, i, side)
    if best is None:
        return
    _, i, side = best
    label.xy = (xs[i], level)
    label.xyann = (0, LABEL_GAP_PT if side == "above" else -LABEL_GAP_PT)
    label.set_va("bottom" if side == "above" else "top")


def render_png(series: ChartSeries) -> bytes:
    """The chart as PNG bytes.  Only a drawn series (``series.drawn``) is rendered."""
    out = io.BytesIO()
    figure(series).savefig(out, format="png", dpi=DPI, metadata={"Software": None})
    return out.getvalue()


def figure(series: ChartSeries) -> Figure:
    """The chart as a matplotlib Figure on an Agg canvas: the title, the spec's window, the line, the average, the end value."""
    if not series.drawn or not series.points:
        raise ValueError(f"{series.spec.id} is not drawn; it has blocking defects")
    shown = windowed(series)
    avg = average(series)
    xs = [p.day for p in shown]
    ys = [float(p.value) for p in shown]
    level = float(avg.value) if avg is not None else None
    top, y_marks = y_axis(series, max(ys + ([level] if level is not None else [])))
    font = chart_font()
    text = {"fontfamily": font, "fontsize": theme.CHART_TEXT_PT, "fontweight": "bold", "color": theme.CHART_TEXT}

    fig = Figure(figsize=(WIDTH_IN, HEIGHT_IN), dpi=DPI)
    canvas = FigureCanvasAgg(fig)
    fig.subplots_adjust(left=0.09, right=0.91, top=0.88, bottom=0.2)
    heading = fig.text(0.5, 0.975, chart_title(series), ha="center", va="top", fontfamily=font, fontsize=theme.CHART_TITLE_PT,
                       fontweight="bold", color=theme.CHART_TEXT)
    box = heading.get_window_extent(canvas.get_renderer())    # matplotlib has no underlined text: a line under it
    y = (box.y0 - 1.5) / fig.bbox.height
    fig.add_artist(Line2D([box.x0 / fig.bbox.width, box.x1 / fig.bbox.width], [y, y], transform=fig.transFigure,
                          color=theme.CHART_TEXT, linewidth=0.8, gid="title-underline"))

    ax = fig.add_subplot()
    ax.set_ylim(0, top)
    marks = ticks(series)
    ax.set_xlim(marks[0] if series.points[0].day < marks[0] else xs[0], xs[-1])   # the axis opens on the first tick when the series reaches back to it
    ax.grid(False)
    ax.plot(xs, ys, color=theme.CHART_LINE, linewidth=theme.CHART_LINE_PT)
    if avg is not None:
        ax.axhline(level, color=theme.AVERAGE_LINE, linewidth=theme.AVERAGE_LINE_PT, linestyle=(0, (5, 3)))
        label = ax.annotate(" " + average_label(series, avg), (xs[0], level), xytext=(0, LABEL_GAP_PT),
                            textcoords="offset points", va="bottom", ha="left", **text)
        _place_average_label(fig, ax, label, xs, ys, level)
    unit = _fmt(series.spec.unit)
    last = series.points[-1]
    ax.annotate(fmt_value(last.value, unit, series.spec.decimals), (xs[-1], ys[-1]), xytext=(4, 0), textcoords="offset points",
                ha="left", va="center", annotation_clip=False, gid="end-label", **text)

    suffix = "%" if series.spec.unit == "pct" else "x"
    ax.set_xticks(marks, labels=[f"{d:%b-%y}" for d in marks], rotation=90, **text)
    ax.set_yticks(y_marks, labels=[f"{v:.1f}{suffix}" for v in y_marks], **text)
    ax.tick_params(color=theme.CHART_AXIS_LINE)    # the tick marks only; the labels stay black
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme.CHART_AXIS_LINE)
    return fig
