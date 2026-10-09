"""Small helpers the weekly section builders share: figures for a paragraph, source wording, safe fetches.

Wording rules read from the published issues (#38.2026 and the Q3'2026 review's weekly
paragraphs): percentages and bps to 1 dp, "Kshs" for shillings, "Kshs X.X bn", "USD X.X mn";
prose states a move's size and names its direction in words ("decreased by 0.9 bps"), while
tables print negatives in brackets.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, TypeVar

from cytonn_weekly.common.computed import ANALYST, OCR, SOURCE, Expr, a_figure, an_input
from cytonn_weekly.common.run_events import Observer, fetch_source
from cytonn_weekly.weekly.workbook import Cell

T = TypeVar("T")


class Figures:
    """The figures of one computed paragraph, collected as the sentence is built."""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, key: str, label: str, fmt: str, decimals: int, inputs: dict[str, dict[str, Any]],
            expr: Optional[Expr] = None, *, in_text: bool = True, note: str = "", flag: str = "") -> str:
        """Record one figure and return its display string for the sentence."""
        fig = a_figure(key, label, fmt, decimals, inputs, expr, in_text=in_text, note=note)
        if flag:
            fig["flag"] = flag
        self.items.append(fig)
        return fig["display"]

    def hide(self, key: str) -> None:
        """A figure that is worked out and checked but not printed (an unchanged yield's 0.0 bps)."""
        next(f for f in self.items if f["key"] == key)["in_text"] = False

    def value(self, key: str) -> float:
        return next(f["value"] for f in self.items if f["key"] == key)


def published(value: Any, source: str, *, second: Optional[dict[str, Any]] = None,
              decimals: Optional[int] = None) -> dict[str, Any]:
    """An input read from a published document."""
    return an_input(value, SOURCE, source, second=second, decimals=decimals)


def typed(cell: Cell, workbook: str, *, scale: float = 1.0, second: Optional[dict[str, Any]] = None,
          decimals: Optional[int] = None) -> dict[str, Any]:
    """An input read from a typed workbook cell: "analyst input from <workbook> <sheet>!<cell>"."""
    value = cell.number * scale if cell.number is not None else cell.value
    return an_input(value, ANALYST, f"analyst input from {workbook} {cell.ref}", second=second, decimals=decimals)


def scanned(value: Any, source: str, *, second: Optional[dict[str, Any]] = None,
            decimals: Optional[int] = None) -> dict[str, Any]:
    """An input read by OCR; it needs ``second`` to be anything but flagged."""
    return an_input(value, OCR, source, second=second, decimals=decimals)


def second_reading(value: Any, source: str, origin: str = SOURCE) -> dict[str, Any]:
    return {"value": value, "source": source, "origin": origin}


def typed_second(cell: Optional[Cell], workbook: str, scale: float = 1.0) -> Optional[dict[str, Any]]:
    if cell is None or cell.number is None:
        return None
    return second_reading(cell.number * scale, f"analyst input from {workbook} {cell.ref}", ANALYST)


def direction(change: float, up: str, down: str, flat: str = "remained unchanged") -> str:
    return up if change > 0 else down if change < 0 else flat


def try_fetch(on_event: Optional[Observer], label: str, fetch: Callable[..., T], *args: Any,
              problems: Optional[list[str]] = None) -> Optional[T]:
    """One named fetch that must not fail the draft: None, with the reason recorded, if it raises."""
    try:
        return fetch_source(on_event, label, fetch, *args)
    except Exception as exc:  # noqa: BLE001 - a source being down becomes a named unavailable part
        if problems is not None:
            problems.append(f"{label}: {type(exc).__name__}: {' '.join(str(exc).split())}"[:300])
        return None


def join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]
