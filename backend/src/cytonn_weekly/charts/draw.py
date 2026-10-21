"""Drawing one chart as a PNG from a read series.  Nothing here reads a workbook or decides a figure.

matplotlib's ``Figure`` and its Agg canvas are used directly, never pyplot: pyplot keeps global
state, and drafts run in worker threads.  No global setting (rcParams) is changed; the font is
named on every text, and it is DejaVu Sans, which ships inside matplotlib, so the picture needs
no font installed on the machine.  A float is used only to place a point on the picture; every
number printed on it (the average label, the subtitle) is the series' own Decimal display.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Optional

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.dates import DateFormatter, MonthLocator
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from cytonn_weekly.charts.series import Average, ChartSeries, average, windowed
from cytonn_weekly.common.formatting import MULTIPLE, PCT, fmt_value

NAVY = "#013660"          # the series line, the average line and its label
SKY = "#6FC3FF"           # the area under the series only: never text, never a line that carries meaning
AXES = "#5B6B7A"          # axes, ticks, tick labels and the subtitle
FONT = "DejaVu Sans"      # bundled with matplotlib
WIDTH_IN, HEIGHT_IN, DPI = 6.0, 3.0, 200    # 1200 x 600 pixels, placed at 6.0 in in the Word export


def _fmt(spec_unit: str) -> str:
    return PCT if spec_unit == "pct" else MULTIPLE


def _day(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def average_label(series: ChartSeries, avg: Average) -> str:
    """"Average = 10.0x" (or a percentage), from the average's own display figure."""
    return f"Average = {fmt_value(avg.display, _fmt(series.spec.unit), series.spec.decimals)}"


def subtitle(avg: Average) -> str:
    return f"Average of {avg.count} weekly points, {_day(avg.first)} to {_day(avg.last)}"


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


def render_png(series: ChartSeries) -> bytes:
    """The chart as PNG bytes.  Only a drawn series (``series.drawn``) is rendered."""
    out = io.BytesIO()
    figure(series).savefig(out, format="png", dpi=DPI, metadata={"Software": None})
    return out.getvalue()


def figure(series: ChartSeries) -> Figure:
    """The chart as a matplotlib Figure on an Agg canvas: the spec's window, the area, the line and the average."""
    if not series.drawn or not series.points:
        raise ValueError(f"{series.spec.id} is not drawn; it has blocking defects")
    shown = windowed(series)
    avg = average(series)
    xs = [p.day for p in shown]
    ys = [float(p.value) for p in shown]
    level = float(avg.value) if avg is not None else None
    low, high = min(ys + ([level] if level is not None else [])), max(ys + ([level] if level is not None else []))
    pad = (high - low) * 0.08 or abs(high) * 0.05 or 1.0
    floor = low - pad

    fig = Figure(figsize=(WIDTH_IN, HEIGHT_IN), dpi=DPI)
    FigureCanvasAgg(fig)
    fig.subplots_adjust(left=0.09, right=0.98, top=0.86, bottom=0.13)
    ax = fig.add_subplot()
    ax.set_ylim(floor, high + pad)
    ax.set_xlim(xs[0], xs[-1])
    ax.fill_between(xs, ys, floor, color=SKY, alpha=0.35, linewidth=0)
    ax.plot(xs, ys, color=NAVY, linewidth=1.6)
    if avg is not None:
        ax.axhline(level, color=NAVY, linewidth=1.1, linestyle=(0, (5, 3)))
        ax.text(xs[0], level, " " + average_label(series, avg), color=NAVY, fontsize=8, fontfamily=FONT,
                va="bottom", ha="left")
        fig.text(0.09, 0.92, subtitle(avg), color=AXES, fontsize=8, fontfamily=FONT, ha="left", va="center")

    unit = series.spec.unit
    ax.xaxis.set_major_locator(MonthLocator(bymonth=(1, 7)))
    ax.xaxis.set_major_formatter(DateFormatter("%b-%y"))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.1f}{'%' if unit == 'pct' else 'x'}"))
    ax.tick_params(colors=AXES, labelcolor=AXES, labelsize=7, labelfontfamily=FONT)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXES)
    return fig
