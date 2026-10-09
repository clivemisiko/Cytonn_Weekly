"""The weekly Equities section, in the real issue's order.

Read from #38.2026 (cytonnreport.com id 891) and the Q3'2026 review's weekly paragraphs
(id 892), 2026-10-09.  The real weekly prints no indices table and no top gainers/losers
table; it is:

1. "Market Performance": the four indices' week (ordered by the size of the move) and year
   to date; the large-cap movers; the Banking Sector index; turnover in USD; foreign
   investors' net position in USD; the market's P/E, dividend yield and PEG.
2. "Universe of Coverage": the 13-company table.
3. "Weekly highlights": cited narrative.
4. The outlook paragraph, carried forward from the previous issue.

Where each figure comes from:

* NASI, NSE 20, NSE 25: KCB IB's weekly report (last Friday and this Friday).
* NSE 10 and the Banking Sector index: the NSE daily price list, read by OCR (it is the only
  public source of either).  An OCR'd level is clean only when a published second source
  confirms it: afx.kwayisi.org's own week and year changes, when afx's page is for that
  Friday.  When only the analysts' typed level agrees with it, it is not auto-verified;
  with nothing to compare, or a disagreement, it is flagged.
* Year opens: the year's first trading day, from that day's NSE price list (OCR), compared
  with the workbook's typed "Year Open" cells.
* Turnover and foreign flows: each day's KES figure divided by that day's CBK rate.  A
  day's equities turnover is KCB's daily "Trading stats > Equities turnover" (not the
  "Equities TO" indicator, which includes ETFs on the weekly report), else the CBK
  bulletin's Table 6, else the NSE price list (OCR).  Foreign net flows by weekday are in
  KCB's weekly report.
* The year-to-date totals, the P/E and dividend yield series and every Universe of Coverage
  input: the equities workbook, typed by the analysts (analyst input, never clean).

Week windows: Monday to Friday throughout.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Optional

from cytonn_weekly.common.computed import ANALYST, PLAIN, PLAIN_PCT, POINTS, computed_block, evaluate, pct_change
from cytonn_weekly.common.formatting import MULTIPLE, PCT, PRICE, TEXT
from cytonn_weekly.common.http import http_get
from cytonn_weekly.common.review import (
    build_review,
    check_section,
    narrative_block,
    numbered,
    table_block,
    unavailable_block,
)
from cytonn_weekly.common.run_events import Observer, report_blocks
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.equities import fetcher as afx
from cytonn_weekly.equities.review_run import BRIEFS
from cytonn_weekly.fixed_income.weekly import _carried
from cytonn_weekly.narrative.base import NarrativeProvider
from cytonn_weekly.narrative.drafter import draft_pieces
from cytonn_weekly.weekly import cbk_bulletin, cbk_rates, equities_workbook, fi_workbook, kcb, nse_price_list, previous_issue
from cytonn_weekly.weekly.inputs import WeeklyInputs
from cytonn_weekly.weekly.prose import (
    Figures,
    direction,
    join_names,
    published,
    scanned,
    second_reading,
    try_fetch,
    typed,
    typed_second,
)
from cytonn_weekly.weekly.week import Week, week_for
from cytonn_weekly.weekly.workbook import WorkbookError

SECTION = "equities"
TITLE = "Equities"
N_HIGHLIGHTS = 3
WB = equities_workbook.SOURCE_NAME

SUBSECTIONS = ("Market Performance:", "Universe of Coverage:", "Weekly highlights")
CHARTS = ("The charts below indicate the historical P/E and dividend yields of the market (P/E chart)",
          "The charts below indicate the historical P/E and dividend yields of the market (dividend yield chart)")
CHART_REFERENCE = "Cytonn Weekly #38.2026"
CHART_AFTER = {"valuation": list(CHARTS)}   # both charts follow the valuation paragraph in #38.2026

UPLOAD = "Upload it under \"This week's inputs\" on the start screen and draft again."
NEED_WORKBOOK = (f"The {WB.lower()} for this week is not among this week's inputs.", f"The analysts' {WB.lower()}. {UPLOAD}")
NEED_KCB_WEEKLY = ("KCB IB's weekly trading report for this week is not among this week's inputs.",
                   f"KCB IB's weekly report for the Friday. {UPLOAD}")

INDEX_NAMES = {"nse_10": "NSE 10", "nse_25": "NSE 25", "nse_20": "NSE 20", "nasi": "NASI"}
FOOTNOTES = ("*Target Price as per Cytonn Analyst estimates", "**Upside/ (Downside) is adjusted for Dividend Yield",
             "***Dividend Yield is calculated using FY’2025 Dividends")

# The workbook's large-cap names and the tickers KCB's report lists them under.
LARGE_CAP_TICKERS = {"safaricom": "SCOM", "equity group": "EQTY", "kcb": "KCB", "co-operative": "COOP", "absa bank": "ABSA",
                     "standard chartered": "SCBK", "i&m holdings": "IMH", "stanbic": "SBIC", "dtbk": "DTK", "ncba": "NCBA",
                     "hfcb group": "HFCK"}
LARGE_CAP_FLAG = ("check the names: this sentence names the biggest movers among the workbook's large-cap list, which is the "
                  "equities team's stated rule, but the published issues have not always followed it (they have named EABL, "
                  "which is not on the list, and passed over bigger movers)")
PE_FLAG = "typed from Bloomberg's NASI P/E, which the tool cannot read (login pending)"

PEG_TEXT = ("A PEG ratio greater than 1.0x indicates the market may be overvalued while a PEG ratio less than 1.0x indicates "
            "that the market is undervalued.")


@dataclass
class Fetchers:
    """Every network call the section makes, so tests can replace each one."""

    usd_rates: Callable[[], dict[date, float]] = cbk_rates.fetch_usd_rates
    price_list: Callable[[date], bytes] = nse_price_list.fetch_price_list
    read_box: Callable[..., nse_price_list.IndexBox] = nse_price_list.read_index_box_cached
    afx_page: Callable[[], bytes] = lambda: http_get(afx.BASE)
    bulletin: Callable[[date], tuple[bytes, str]] = cbk_bulletin.fetch_bulletin
    previous_issue: Callable[[date, Optional[str]], previous_issue.Issue] = (
        lambda day, ref: previous_issue.find_previous_issue(day, reference=ref))


# ---------------------------------------------------------------------------
# Sources gathered once
# ---------------------------------------------------------------------------

@dataclass
class Market:
    week: Week
    inputs: WeeklyInputs
    bulletin: Optional[cbk_bulletin.Bulletin]
    rates: dict[date, dict[str, Any]]                # day -> an input (the CBK rate, with where it was read)
    boxes: dict[date, nse_price_list.IndexBox]       # OCR'd price lists, by day
    year_open_day: Optional[date]
    afx: Optional[dict[str, dict[str, float]]]       # afx's own week and year changes, only when its page is for the Friday
    typed_indices: Optional[dict[str, dict[str, Any]]]


def _box(fetchers: Fetchers, inputs: WeeklyInputs, day: date, on_event: Optional[Observer], problems: list[str]
         ) -> Optional[nse_price_list.IndexBox]:
    def read() -> nse_price_list.IndexBox:
        return fetchers.read_box(fetchers.price_list(day), inputs.cache_dir)

    box = try_fetch(on_event, f"NSE daily price list, {day.isoformat()} (OCR)", read, problems=problems)
    if box is not None and box.list_date is not None and box.list_date != day:
        problems.append(f"NSE daily price list for {day.isoformat()}: the list itself is dated {box.list_date.isoformat()}; not used")
        return None
    return box


def _year_open(fetchers: Fetchers, inputs: WeeklyInputs, year: int, on_event: Optional[Observer], problems: list[str]
               ) -> tuple[Optional[date], Optional[nse_price_list.IndexBox]]:
    """The year's first trading day and its price list: the first of 2 to 8 January that NSE has a list for."""
    for n in range(2, 9):
        day = date(year, 1, n)
        if day.weekday() >= 5:
            continue
        try:
            pdf = fetchers.price_list(day)
        except LookupError:
            continue
        except Exception as exc:  # noqa: BLE001 - NSE not answering is a named problem, not a failed draft
            problems.append(f"NSE daily price list, {day.isoformat()}: {type(exc).__name__}: {exc}"[:300])
            return None, None
        box = try_fetch(on_event, f"NSE daily price list, {day.isoformat()} (OCR, the year's first trading day)",
                        lambda: fetchers.read_box(pdf, inputs.cache_dir), problems=problems)
        return (day, box) if box is not None else (None, None)
    return None, None


def _afx_changes(fetchers: Fetchers, week: Week, today: date, on_event: Optional[Observer]) -> Optional[dict[str, dict[str, float]]]:
    """afx's one-week and year-to-date changes, only while its page is still the Friday's close."""
    if not week.ending <= today <= week.ending + timedelta(days=2):
        return None   # afx shows the latest close only; by Monday's close it is no longer this week's
    page = try_fetch(on_event, afx.SOURCE_NAME, fetchers.afx_page)
    if page is None:
        return None
    html = page.decode("utf-8", errors="replace")
    as_of = afx.parse_as_of(html)
    if not as_of or as_of[:10] != week.ending.isoformat():
        return None
    keys = {"NASI": "nasi", "NSE25": "nse_25", "NSE20": "nse_20", "NSE10": "nse_10", "BANKING": "banking"}
    out = {}
    for row in afx.parse_indices(html):
        key = keys.get(str(row["index"]).upper().replace(" ", "").replace("_", ""))
        if key and row.get("wow_pct") is not None:
            out[key] = {"wow": row["wow_pct"], "ytd": row.get("ytd_pct")}
    return out or None


def _rates(fetchers: Fetchers, inputs: WeeklyInputs, bulletin: Optional[cbk_bulletin.Bulletin], on_event: Optional[Observer],
           problems: list[str]) -> dict[date, dict[str, Any]]:
    fetched = try_fetch(on_event, cbk_rates.SOURCE_NAME, fetchers.usd_rates, problems=problems) or {}
    typed_rates = {}
    if inputs.fi_book is not None:
        try:
            typed_rates = fi_workbook.read_exchange_rates(inputs.fi_book)
        except WorkbookError:
            typed_rates = {}
    out: dict[date, dict[str, Any]] = {}
    for day, value in fetched.items():
        out[day] = published(value, cbk_rates.SOURCE_NAME, second=typed_second(typed_rates.get(day), fi_workbook.SOURCE_NAME), decimals=2)
    for day, value in (bulletin.exchange_rates if bulletin else {}).items():
        out.setdefault(day, published(value, f"{cbk_bulletin.SOURCE_NAME}, Table 1"))
    for day, cell in typed_rates.items():
        out.setdefault(day, typed(cell, fi_workbook.SOURCE_NAME))
    return out


# ---------------------------------------------------------------------------
# 1. Indices
# ---------------------------------------------------------------------------

def _level(m: Market, key: str, when: str) -> Optional[dict[str, Any]]:
    """One index level as an input: ``when`` is "today", "last_week" or "year_open"."""
    week = m.week
    day = {"today": week.ending, "last_week": week.previous_friday, "year_open": m.year_open_day}[when]
    cell = (m.typed_indices or {}).get(key, {}).get(when)
    typed_reading = typed_second(cell, WB)
    kcb_weekly = m.inputs.kcb_weekly
    if when != "year_open" and kcb_weekly is not None and key in kcb_weekly.indicators and kcb_weekly.report_date == week.ending \
            and kcb_weekly.previous_date == week.previous_friday:
        value = kcb_weekly.indicators[key]["current" if when == "today" else "previous"]
        return published(value, f"{kcb.SOURCE_NAME} weekly report, {week.ending.isoformat()}", second=typed_reading, decimals=2)
    daily = m.inputs.kcb_daily.get(day) if day else None
    if when != "year_open" and daily is not None and key in daily.indicators:
        return published(daily.indicators[key]["current"], f"{kcb.SOURCE_NAME} daily report, {day.isoformat()}",
                         second=typed_reading, decimals=2)
    row = next((r for r in (m.bulletin.market if m.bulletin else []) if r["date"] == day), None)
    if row is not None and row.get(key) is not None:
        return published(row[key], f"{cbk_bulletin.SOURCE_NAME}, Table 6", second=typed_reading, decimals=2)
    box = m.boxes.get(day) if day else None
    if box is not None and key in box.values:
        return scanned(box.values[key], f"NSE daily price list of {day.isoformat()}", second=typed_reading, decimals=2)
    if cell is not None and cell.number is not None:
        return typed(cell, WB)
    return None


def _afx_second(m: Market, key: str, which: str) -> Optional[dict[str, Any]]:
    value = ((m.afx or {}).get(key) or {}).get(which)
    return None if value is None else {"value": value, "source": afx.SOURCE_NAME, "decimals": 1}


def indices_block(m: Market) -> dict[str, Any]:
    title = "Market Performance"
    figs = Figures()
    moves, ytds, missing = [], [], []
    for key, name in INDEX_NAMES.items():
        today, last, opened = _level(m, key, "today"), _level(m, key, "last_week"), _level(m, key, "year_open")
        if today is None or last is None:
            missing.append(name)
            continue
        w = figs.add(f"{key}_wow", f"{name} week-on-week change", PLAIN_PCT, 1, {"today": today, "last_week": last},
                     pct_change("today", "last_week"))
        figs.items[-1]["second"] = _afx_second(m, key, "wow")
        moves.append((figs.value(f"{key}_wow"), name, w))
        if opened is not None:
            y = figs.add(f"{key}_ytd", f"{name} year-to-date change", PLAIN_PCT, 1, {"today": today, "year_open": opened},
                         pct_change("today", "year_open"),
                         note=f"Year open: the close of {m.year_open_day.isoformat() if m.year_open_day else 'the year open in the workbook'}.")
            figs.items[-1]["second"] = _afx_second(m, key, "ytd")
            ytds.append((figs.value(f"{key}_ytd"), name, y))
    if not moves:
        return unavailable_block("indices", title, "No index levels for this Friday and the previous one were found: KCB IB's "
                                 "weekly report is not among this week's inputs, and neither the CBK bulletin, the NSE price list "
                                 "nor the equities workbook has them.", f"KCB IB's weekly report for the Friday. {UPLOAD}")
    moves.sort(key=lambda x: -abs(x[0]))
    ups = sum(1 for v, _, _ in moves if v > 0)
    downs = sum(1 for v, _, _ in moves if v < 0)
    names = join_names([n for _, n, _ in moves])
    values = join_names([d for _, _, d in moves])
    if ups == len(moves) or downs == len(moves):
        text = (f"During the week, the equities market was on {'an upward' if ups else 'a downward'} trajectory, with {names} "
                f"{'gaining' if ups else 'losing'} by {values}{', respectively' if len(moves) > 1 else ''}")
    else:
        each = join_names([f"{n} {direction(v, 'gaining', 'losing', 'unchanged')}"
                           + (f" by {d}" if v else "") for v, n, d in moves])
        text = f"During the week, the equities market recorded a mixed performance, with {each}"
    if ytds:
        ytds.sort(key=lambda x: -x[0])
        all_up, all_down = all(v > 0 for v, _, _ in ytds), all(v < 0 for v, _, _ in ytds)
        if all_up or all_down:
            text += (f", taking the YTD performance to {'gains' if all_up else 'losses'} of {join_names([d for _, _, d in ytds])} for "
                     f"{join_names([n for _, n, _ in ytds])}{' respectively' if len(ytds) > 1 else ''}")
        else:
            text += ", taking the YTD performance to " + join_names(
                [f"a {direction(v, 'gain', 'loss', 'change')} of {d} for {n}" for v, n, d in ytds])
    text += "."
    notes = []
    if missing:
        notes.append(f"Left out, because no level for both Fridays was found: {join_names(missing)}.")
    if m.afx is None:
        notes.append("afx.kwayisi.org shows only the latest close, so it confirms the OCR'd indices only when the section is "
                     "drafted on the Friday or over the weekend.")
    return computed_block("indices", title, text, figs.items,
                          sources=[{"name": f"{kcb.SOURCE_NAME} weekly report"}, {"name": nse_price_list.SOURCE_NAME, "url": nse_price_list.BASE},
                                   {"name": WB}], notes=notes)


def banking_block(m: Market) -> dict[str, Any]:
    title = "Market Performance: Banking Sector index"
    today, last = _level(m, "banking", "today"), _level(m, "banking", "last_week")
    if today is None or last is None:
        return unavailable_block("banking", title, "The Banking Sector index for this Friday and the previous one was not found: "
                                 "the NSE daily price lists could not be read and the equities workbook is not among this "
                                 "week's inputs.", f"nse.co.ke answering, or the {WB.lower()}. {UPLOAD}")
    figs = Figures()
    change = figs.add("banking_wow", "Banking Sector index week-on-week change", PLAIN_PCT, 1, {"today": today, "last_week": last},
                      pct_change("today", "last_week"))
    figs.items[-1]["second"] = _afx_second(m, "banking", "wow")
    now = figs.add("banking_level", "Banking Sector index, Friday", PLAIN, 1, {"today": today})
    was = figs.add("banking_previous", "Banking Sector index, previous Friday", PLAIN, 1, {"last_week": last})
    moved = figs.value("banking_wow")
    text = (f"During the week, the banking sector index {direction(moved, 'increased', 'decreased', 'was unchanged')} by {change} to "
            f"{now} from {was} recorded the previous week.")
    return computed_block("banking", title, text, figs.items,
                          sources=[{"name": nse_price_list.SOURCE_NAME, "url": nse_price_list.BASE}, {"name": WB}])


# ---------------------------------------------------------------------------
# Large caps
# ---------------------------------------------------------------------------

def large_caps_block(m: Market) -> dict[str, Any]:
    title = "Market Performance: large-cap movers"
    report = m.inputs.kcb_weekly
    if report is None:
        return unavailable_block("large_caps", title, *NEED_KCB_WEEKLY)
    book = m.inputs.equities_book
    if book is None:
        return unavailable_block("large_caps", title, "The large-cap list is read from the equities workbook, which is not among "
                                 "this week's inputs.", f"The analysts' {WB.lower()}. {UPLOAD}")
    try:
        names = equities_workbook.read_large_caps(book)
    except WorkbookError as exc:
        return unavailable_block("large_caps", title, str(exc), f"The {WB.lower()} with its large-cap list. {UPLOAD}")
    src = f"{kcb.SOURCE_NAME} weekly report, {report.report_date.isoformat()}"
    movers, unknown = [], []
    for cell in names:
        name = " ".join(str(cell.value).split())
        ticker = LARGE_CAP_TICKERS.get(name.lower())
        stock = report.securities.get(ticker) if ticker else None
        if stock is None:
            unknown.append(name)
            continue
        movers.append((stock["change_pct"], name, ticker))
    losers = sorted((x for x in movers if x[0] < 0), key=lambda x: x[0])[:3]
    gainers = sorted((x for x in movers if x[0] > 0), key=lambda x: -x[0])[:3]
    if not losers and not gainers:
        return unavailable_block("large_caps", title, "None of the workbook's large caps moved over the week in KCB IB's weekly "
                                 "report, or none could be matched to a ticker.", "Check the workbook's large-cap list.")
    figs = Figures()

    def listed(group: list[tuple[float, str, str]]) -> tuple[str, str]:
        shown = [figs.add(f"move_{t}", f"{n} week-on-week change", PLAIN_PCT, 1, {"change": published(v, src)},
                          flag=LARGE_CAP_FLAG if not figs.items else "") for v, n, t in group]
        return join_names([n for _, n, _ in group]), join_names(shown) + (" respectively" if len(group) > 1 else "")

    nasi = next((f["value"] for f in (indices_block(m).get("figures") or []) if f["key"] == "nasi_wow"), None)
    down = (nasi < 0) if nasi is not None else len(losers) >= len(gainers)
    lead, other = (losers, gainers[:2]) if down else (gainers, losers[:2])
    lead_word, other_word = ("losses", "gains") if down else ("gains", "losses")
    if not lead:
        lead, other, lead_word, other_word = other, [], other_word, lead_word
    a, b = listed(lead)
    text = (f"The equities market performance was mainly driven by {lead_word} recorded by large-cap stocks such as {a} of {b}.")
    if other:
        c, d = listed(other)
        text += (f" However, the performance was {'supported' if down else 'weighed down'} by {other_word} recorded by "
                 f"large-cap stocks such as {c} of {d}.")
    notes = ["The large-cap list is read from the equities workbook ('Market PE & Dividend Yield')."]
    if unknown:
        notes.append(f"Not matched to a ticker in KCB's report and left out: {join_names(unknown)}.")
    return computed_block("large_caps", title, text, figs.items, sources=[{"name": src}, {"name": WB}], notes=notes)


# ---------------------------------------------------------------------------
# Turnover and foreign flows
# ---------------------------------------------------------------------------

def _day_turnover(m: Market, day: date) -> Optional[dict[str, Any]]:
    """One day's equities turnover in KES as an input: KCB's daily report, else the bulletin, else the price list."""
    daily = m.inputs.kcb_daily.get(day)
    row = next((r for r in (m.bulletin.market if m.bulletin else []) if r["date"] == day), None)
    bulletin_kes = row["equity_turnover_mn"] * 1_000_000 if row and row.get("equity_turnover_mn") is not None else None
    box = m.boxes.get(day)
    ocr_kes = box.values.get("equity_turnover") if box is not None else None
    if daily is not None and daily.equities_turnover is not None:
        second = second_reading(bulletin_kes, f"{cbk_bulletin.SOURCE_NAME}, Table 6") if bulletin_kes is not None else (
            second_reading(ocr_kes, nse_price_list.SOURCE_NAME) if ocr_kes is not None else None)
        return published(daily.equities_turnover, f"{kcb.SOURCE_NAME} daily report, {day.isoformat()}, trading stats",
                         second=second, decimals=-4 if second and bulletin_kes is not None else 0)
    if bulletin_kes is not None:
        return published(bulletin_kes, f"{cbk_bulletin.SOURCE_NAME}, Table 6",
                         second=second_reading(ocr_kes, nse_price_list.SOURCE_NAME) if ocr_kes is not None else None, decimals=-4)
    if ocr_kes is not None:
        return scanned(ocr_kes, f"NSE daily price list of {day.isoformat()}")
    return None


def _usd_week(m: Market, week: Week, kes_for: Callable[[date], Optional[dict[str, Any]]], prefix: str
              ) -> tuple[Optional[dict[str, dict]], Optional[list], list[date]]:
    """(inputs, the expression for the week's USD mn total, the days with no figure) for one week."""
    inputs: dict[str, dict] = {}
    terms, missing = [], []
    for n, day in enumerate(week.trading_days):
        kes, rate = kes_for(day), m.rates.get(day)
        if kes is None or rate is None:
            missing.append(day)
            continue
        inputs[f"{prefix}kes_{n}"], inputs[f"{prefix}rate_{n}"] = kes, rate
        terms.append(["div", f"{prefix}kes_{n}", f"{prefix}rate_{n}"])
    if missing or not terms:
        return None, None, missing
    return inputs, ["div", ["sum", *terms], 1_000_000], missing


def _days(days: list[date]) -> str:
    return join_names([d.strftime("%A %d %B") for d in days])


def turnover_block(m: Market) -> dict[str, Any]:
    title = "Market Performance: equities turnover"
    week = m.week
    inputs, expr, missing = _usd_week(m, week, lambda d: _day_turnover(m, d), "")
    if inputs is None:
        need_rate = [d for d in missing if m.rates.get(d) is None and _day_turnover(m, d) is not None]
        why = (f"The CBK rate for {_days(need_rate)} was not found." if need_rate else
               f"No equities turnover was found for {_days(missing)}: KCB IB's daily report for the day is not among this week's "
               "inputs, the CBK bulletin's Table 6 does not cover it, and the NSE price list could not be read.")
        return unavailable_block("turnover", title, why, f"KCB IB's daily trading report for each missing day. {UPLOAD}")
    figs = Figures()
    book = m.inputs.equities_book
    series = None
    if book is not None:
        try:
            series = equities_workbook.read_turnover(book, week)
        except WorkbookError:
            series = None
    now = figs.add("turnover", "Equities turnover over the week (USD mn)", PLAIN, 1, inputs, expr)
    if series is not None and series.total is not None:
        figs.items[-1]["second"] = {"value": series.total.number, "source": f"analyst input from {WB} {series.total.ref}", "decimals": 1}
    text = f"During the week, equities turnover stood at USD {now} mn"
    p_inputs, p_expr, p_missing = _usd_week(m, week.previous, lambda d: _day_turnover(m, d), "last_")
    if p_inputs is None and series is not None and len(series.history) >= 2 and series.history[-2][0] == week.previous_friday:
        # The previous week's own days are not all in this week's inputs: its typed weekly row is used instead.
        row = equities_workbook.read_turnover(book, week.previous).total
        if row is not None:
            p_inputs, p_expr = {"last_week": typed(row, WB)}, "last_week"
    if p_inputs is not None:
        was = figs.add("previous_turnover", "Equities turnover, previous week (USD mn)", PLAIN, 1, p_inputs, p_expr)
        change = figs.add("turnover_change", "Equities turnover, change on the previous week", PLAIN_PCT, 1, {**inputs, **p_inputs},
                          ["mul", ["sub", ["div", expr, p_expr], 1], 100])
        moved = figs.value("turnover_change")
        text = (f"During the week, equities turnover {direction(moved, 'increased', 'decreased', 'was unchanged')} by {change} to USD "
                f"{now} mn from USD {was} mn recorded the previous week")
    if series is not None and series.ytd is not None:
        ytd = figs.add("turnover_ytd", "Year-to-date equities turnover (USD mn)", PLAIN, 1, {"ytd": typed(series.ytd, WB)})
        text += f", taking the YTD total turnover to USD {ytd} mn"
    text += "."
    notes = ["Each day's equities turnover in KES is divided by that day's CBK rate; Monday to Friday."]
    if series is None or series.ytd is None:
        notes.append(f"The year-to-date total is left out: it is the running total in the {WB.lower()}, which has no row for this week.")
    return computed_block("turnover", title, text, figs.items,
                          sources=[{"name": f"{kcb.SOURCE_NAME} daily reports"}, {"name": f"{cbk_bulletin.SOURCE_NAME}, Table 6"},
                                   {"name": cbk_rates.SOURCE_NAME, "url": cbk_rates.PAGE}, {"name": WB}], notes=notes)


def _day_flow(m: Market, day: date) -> Optional[dict[str, Any]]:
    report = m.inputs.kcb_weekly
    if report is not None and report.report_date == m.week.ending:
        flow = report.daily_foreign_flows.get(day.strftime("%A"))
        if flow is not None:
            daily = m.inputs.kcb_daily.get(day)
            second = None
            if daily is not None and "net_flows" in daily.indicators:
                second = second_reading(daily.indicators["net_flows"]["current"], f"{kcb.SOURCE_NAME} daily report, {day.isoformat()}")
            return published(flow["net"], f"{kcb.SOURCE_NAME} weekly report, daily foreign flows, {day.strftime('%A')}",
                             second=second, decimals=0)
    daily = m.inputs.kcb_daily.get(day)
    if daily is not None and "net_flows" in daily.indicators:
        return published(daily.indicators["net_flows"]["current"], f"{kcb.SOURCE_NAME} daily report, {day.isoformat()}")
    return None


def _position(value: float) -> str:
    return "net buying" if value > 0 else "net selling"


def _ordinal_word(n: int) -> str:
    words = ["", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "eleventh",
             "twelfth"]
    return words[n] if n < len(words) else f"{n}th"


def _count_word(n: int) -> str:
    words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]
    return words[n] if n < len(words) else str(n)


def foreign_block(m: Market) -> dict[str, Any]:
    title = "Market Performance: foreign investors"
    week = m.week
    inputs, expr, missing = _usd_week(m, week, lambda d: _day_flow(m, d), "")
    if inputs is None:
        need_rate = [d for d in missing if m.rates.get(d) is None and _day_flow(m, d) is not None]
        why = (f"The CBK rate for {_days(need_rate)} was not found." if need_rate else
               f"No foreign net flow was found for {_days(missing)}: KCB IB's weekly report (which lists each weekday) is not among "
               "this week's inputs, and neither is that day's daily report.")
        return unavailable_block("foreign", title, why, f"KCB IB's weekly report, or the daily report for each missing day. {UPLOAD}")
    figs = Figures()
    book = m.inputs.equities_book
    series = None
    if book is not None:
        try:
            series = equities_workbook.read_foreign_flows(book, week)
        except WorkbookError:
            series = None
    net = figs.add("net_flow", "Foreign investors' net position over the week (USD mn)", PLAIN, 1, inputs, expr)
    if series is not None and series.total is not None:
        figs.items[-1]["second"] = {"value": series.total.number, "source": f"analyst input from {WB} {series.total.ref}", "decimals": 1}
    value = figs.value("net_flow")
    notes = ["Each day's net foreign flow in KES is divided by that day's CBK rate; Monday to Friday."]
    earlier = [(d, t, c) for d, t, _, c in (series.history if series else []) if d < week.monday]
    previous = earlier[-1] if earlier and earlier[-1][0] == week.previous_friday else None
    if previous is None:
        text = f"During the week, foreign investors recorded a {_position(value)} position of USD {net} mn"
        notes.append(f"The previous week and the streak are left out: they come from the weekly sums in the {WB.lower()}.")
    else:
        # The previous week's sum is in the row left of its running total.
        prev_cell = book.sheet(equities_workbook.FOREIGN_SHEET).cell(previous[2].row, 2) if previous[2] is not None else None
        prev_in = {"last_week": typed(prev_cell, WB)} if prev_cell is not None else {"last_week": {"value": previous[1], "origin": ANALYST,
                                                                                               "source": f"analyst input from {WB} '{equities_workbook.FOREIGN_SHEET}' weekly sum"}}
        was = figs.add("previous_net_flow", "Foreign investors' net position, previous week (USD mn)", PLAIN, 1, prev_in)
        same = (previous[1] > 0) == (value > 0)
        if same:
            streak = 1
            for _, total, _ in reversed(earlier):
                if (total > 0) != (value > 0):
                    break
                streak += 1
            lead = f"Foreign investors remained {_position(value)[:-3]}ers for the {_ordinal_word(streak)} consecutive week"
            notes.append(f"Streak: {streak} consecutive weeks of {_position(value)}, counted from the weekly sums in the {WB.lower()}.")
        else:
            gap = 1
            for _, total, _ in reversed(earlier):
                if (total > 0) == (value > 0):
                    break
                gap += 1
            lead = f"Foreign investors became {_position(value)[:-3]}ers for the first time in {_count_word(gap)} weeks"
            notes.append(f"The last week of {_position(value)} before this one was {gap} weeks ago, counted from the weekly sums in "
                         f"the {WB.lower()}.")
        text = (f"{lead} with a {_position(value)} position of USD {net} mn, from a {_position(previous[1])} position of USD {was} mn "
                "recorded the previous week")
    if series is not None and series.ytd is not None:
        ytd = figs.add("net_flow_ytd", "Year-to-date foreign net position (USD mn)", PLAIN, 1, {"ytd": typed(series.ytd, WB)})
        text += f", taking the YTD foreign {_position(series.ytd.number)} position to USD {ytd} mn"
        prior = equities_workbook.prior_year_total(series, week.ending.year)
        if prior is not None:
            was_year = figs.add("net_flow_prior_year", f"Foreign net position recorded in {week.ending.year - 1} (USD mn)", PLAIN, 1,
                                {"prior_year": typed(prior, WB)},
                                note="The running total on the last weekly row before the workbook's count restarted for this year.")
            text += f", compared to a {_position(prior.number)} position of USD {was_year} mn recorded in {week.ending.year - 1}"
    text += "."
    return computed_block("foreign", title, text, figs.items,
                          sources=[{"name": f"{kcb.SOURCE_NAME} weekly report"}, {"name": cbk_rates.SOURCE_NAME, "url": cbk_rates.PAGE},
                                   {"name": WB}], notes=notes)


# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------

def valuation_block(m: Market) -> dict[str, Any]:
    title = "Market Performance: valuation"
    book = m.inputs.equities_book
    if book is None:
        return unavailable_block("valuation", title, *NEED_WORKBOOK)
    try:
        v = equities_workbook.read_valuation(book, m.week)
    except WorkbookError as exc:
        return unavailable_block("valuation", title, str(exc), f"The {WB.lower()} updated for this week. {UPLOAD}")

    def average(key: str, scale: float = 1.0) -> dict[str, Any]:
        worked = v.get(f"{key}_recomputed")
        second = None
        if worked is not None:
            second = second_reading(worked[0] * scale, f"the average of {worked[1]} figures in {worked[2]}, worked out by the tool", ANALYST)
        return typed(v[key], WB, scale=scale, second=second, decimals=6)

    figs = Figures()
    pe_in = {"pe": typed(v["pe"], WB)}
    pe_avg_in = {"pe_average": average("pe_average")}
    dy_in = {"dividend_yield": typed(v["dividend_yield"], WB, scale=100)}
    dy_avg_in = {"dividend_yield_average": average("dividend_yield_average", 100)}
    pe = figs.add("pe", "Market P/E", MULTIPLE, 1, pe_in, note=PE_FLAG)
    gap = figs.add("pe_vs_average", "P/E against its historical average", PLAIN_PCT, 1, {**pe_in, **pe_avg_in}, pct_change("pe", "pe_average"))
    pe_avg = figs.add("pe_average", "Historical average P/E", MULTIPLE, 1, pe_avg_in)
    dy = figs.add("dividend_yield", "Market dividend yield", PLAIN_PCT, 1, dy_in)
    dy_gap = figs.add("dividend_yield_vs_average", "Dividend yield against its historical average", POINTS, 1, {**dy_in, **dy_avg_in},
                      ["sub", "dividend_yield", "dividend_yield_average"])
    dy_avg = figs.add("dividend_yield_average", "Historical average dividend yield", PLAIN_PCT, 1, dy_avg_in)
    peg = figs.add("peg", "NASI PEG ratio", MULTIPLE, 1, dict(pe_in), ["div", "pe", equities_workbook.PEG_GROWTH],
                   note=f"The P/E divided by a fixed {equities_workbook.PEG_GROWTH} (the equities team's rule).")
    if v.get("peg_sheet") is not None and v["peg_sheet"].number is not None:
        figs.items[-1]["second"] = {"value": v["peg_sheet"].number, "source": f"analyst input from {WB} {v['peg_sheet'].ref}", "decimals": 4}
    text = (f"The market is currently trading at a price to earnings ratio (P/E) of {pe}, {gap} "
            f"{direction(figs.value('pe_vs_average'), 'above', 'below', 'in line with')} the historical average of {pe_avg}, and a "
            f"dividend yield of {dy}, {dy_gap} {direction(figs.value('dividend_yield_vs_average'), 'above', 'below', 'in line with')} "
            f"the historical average of {dy_avg}. Key to note, NASI’s PEG ratio currently stands at {peg}. {PEG_TEXT}")
    return computed_block("valuation", title, text, figs.items, sources=[{"name": WB}])


# ---------------------------------------------------------------------------
# 2. Universe of Coverage
# ---------------------------------------------------------------------------

def recommendation(upside_pct: float) -> Optional[str]:
    """The workbook's rule.  It returns nothing for an upside between 0% and 0.1%; neither does this."""
    if upside_pct >= 20:
        return "Buy"
    if upside_pct >= 10:
        return "Accumulate"
    if upside_pct >= 5:
        return "Hold"
    if upside_pct >= 0.1:
        return "Lighten"
    if upside_pct <= 0:
        return "Sell"
    return None


_UPSIDE = ["mul", ["add", ["div", "dps", "price"], ["sub", ["div", "target", "price"], 1]], 100]


def universe_block(m: Market, warnings: list[str]) -> dict[str, Any]:
    title = "Cytonn Report: Equities Universe of Coverage"
    book = m.inputs.equities_book
    if book is None:
        return unavailable_block("universe_of_coverage", title, *NEED_WORKBOOK)
    try:
        data = equities_workbook.read_universe(book, m.week)
    except WorkbookError as exc:
        return unavailable_block("universe_of_coverage", title, str(exc), f"The {WB.lower()} updated for this week. {UPLOAD}")
    week = m.week
    columns = [
        {"key": "company", "label": "Company", "fmt": TEXT},
        {"key": "last_price", "label": f"Price as at {week.previous_friday.strftime('%d/%m/%Y')}", "fmt": PRICE, "decimals": 1},
        {"key": "price", "label": f"Price as at {week.ending.strftime('%d/%m/%Y')}", "fmt": PRICE, "decimals": 1},
        {"key": "wow", "label": "w/w change", "fmt": PCT, "decimals": 1, "expr": pct_change("price", "last_price")},
        {"key": "mom", "label": "m/m change", "fmt": PCT, "decimals": 1, "expr": pct_change("price", "month_end_price")},
        {"key": "ytd", "label": "YTD Change", "fmt": PCT, "decimals": 1, "expr": pct_change("price", "year_open")},
        {"key": "year_open", "label": f"Year Open {week.ending.year}", "fmt": PRICE, "decimals": 1},
        {"key": "target", "label": "Target Price*", "fmt": PRICE, "decimals": 1},
        {"key": "dividend_yield", "label": "Dividend Yield***", "fmt": PCT, "decimals": 1, "expr": ["mul", ["div", "dps", "price"], 100]},
        {"key": "upside", "label": "Upside/ Downside**", "fmt": PCT, "decimals": 1, "expr": _UPSIDE},
        {"key": "ptbv", "label": "P/TBv Multiple", "fmt": MULTIPLE, "decimals": 1, "expr": ["div", "price", ["div", "tbv_bn", "shares_bn"]]},
        {"key": "recommendation", "label": "Recommendation", "fmt": TEXT},
    ]
    rows = []
    for c in data["companies"]:
        raw = {k: c[k].number for k in ("price", "last_price", "month_end_price", "year_open", "target", "dps", "shares_bn", "tbv_bn")}
        name = " ".join(str(c["company"].value).split())
        gaps = [k for k, v in raw.items() if v is None or (k in ("price", "last_price", "month_end_price", "year_open", "shares_bn", "tbv_bn") and not v)]
        if gaps:
            rows.append({"company": name, "error": f"the workbook has no usable {', '.join(gaps)} for {name} (row {c['price'].row})"})
            continue
        row: dict[str, Any] = {"company": name, **raw}
        # Worked out exactly (decimal arithmetic), as the checker does, so a figure on a rounding
        # boundary (399.0 against 400.0 is -0.25%) rounds the same way in both.
        for col in columns:
            if col.get("expr") is not None:
                row[col["key"]] = float(evaluate(col["expr"], raw))
        rec = recommendation(row["upside"])
        row["recommendation"] = rec or ""
        if rec is None:
            row["incomplete"] = {"recommendation": "the workbook's rule gives no recommendation for an upside between 0% and 0.1%; "
                                                   "the analysts must give one"}
        row["_note"] = (f"Not auto-verified: analyst input from {WB} '{equities_workbook.UNIVERSE_SHEET}' row {c['price'].row} "
                        f"(prices {c['last_price'].a1} and {c['price'].a1}, month-end {c['month_end_price'].a1}, Year Open "
                        f"{c['year_open'].a1}, target {c['target'].a1}, DPS {c['dps'].a1}, tangible book {c['tbv_bn'].a1}, shares "
                        f"{c['shares_bn'].a1}). The changes, yield, upside and multiple are worked out again from them; the typed "
                        "values are not checked.")
        rows.append(row)
    rows.sort(key=lambda r: -(r.get("upside") if r.get("upside") is not None else float("-inf")))
    block = table_block("universe_of_coverage", title, columns, rows, "company", "company",
                        {"name": f"{WB}, '{equities_workbook.UNIVERSE_SHEET}'", "url": None, "as_of": week.ending.isoformat()})
    block["row_origin"] = ANALYST
    block["footnotes"] = list(FOOTNOTES)
    block["notes"] = [f"m/m change is against the close of {data['month_end'].strftime('%d/%m/%Y')}, the previous month's last "
                      "price column in the workbook."]
    if (week.ending.replace(day=1) - data["month_end"]).days > 5:
        warnings.append(f"Universe of Coverage: the m/m base is the workbook's {data['month_end'].isoformat()} column, which is "
                        "not the previous month's last trading day; check the m/m column.")
    return block


# ---------------------------------------------------------------------------
# The section
# ---------------------------------------------------------------------------

def equities_outlook_text(paragraphs: list[str]) -> Optional[str]:
    """The previous issue's closing outlook: its last paragraph, when it opens "We maintain" or "We are"."""
    for p in reversed(paragraphs[-4:]):
        if p.lower().startswith(("we maintain", "we are ", "we remain")):
            return p
    return None


def compose_summary(blocks: list[dict[str, Any]], limit: int = 3000) -> str:
    lead = [b["body_md"] for b in blocks if b["kind"] == "computed" and b["id"] in ("indices", "large_caps", "banking")]
    first_piece = next((b for b in blocks if b["kind"] == "narrative"), None)
    if first_piece is not None:
        lead.append(first_piece.get("body_md", "").split("\n\n")[0])
    out: list[str] = []
    for p in lead:
        if p and sum(len(x) for x in out) + len(p) <= limit:
            out.append(p)
    return " ".join(out)


def build_equities_weekly_review(
    week_ending: Optional[date] = None,
    provider: Optional[NarrativeProvider] = None,
    today: Optional[date] = None,
    inputs: Optional[WeeklyInputs] = None,
    fetchers: Optional[Fetchers] = None,
    on_event: Optional[Observer] = None,
    draft: Optional[Callable[..., dict[str, Any]]] = None,
    inputs_root: Optional[Any] = None,
) -> CoordinatorReview:
    """Read the week's inputs, fetch what is published, work out the section, draft its highlights, check it.

    A missing input or a source that does not answer never fails the draft: the part that
    needed it is an ``unavailable`` block naming it.  Provider errors propagate.
    """
    today = today or date.today()
    week = week_for(week_ending, today)
    inputs = inputs or WeeklyInputs(week, inputs_root)
    fetchers = fetchers or Fetchers()
    problems: list[str] = []
    warnings: list[str] = []

    bulletin = inputs.bulletin
    if bulletin is None:
        fetched = try_fetch(on_event, "CBK Weekly Bulletin", fetchers.bulletin, week.ending, problems=problems)
        if fetched is not None:
            try:
                bulletin = cbk_bulletin.parse_bulletin(fetched[0])
            except Exception as exc:  # noqa: BLE001
                problems.append(f"CBK Weekly Bulletin: {exc}")
    typed_indices = None
    if inputs.equities_book is not None:
        try:
            typed_indices = equities_workbook.read_indices(inputs.equities_book, week.ending.year)
        except WorkbookError as exc:
            warnings.append(f"Index levels in the workbook were not read: {exc}")
    boxes: dict[date, nse_price_list.IndexBox] = {}
    for day in (week.ending, week.previous_friday):
        box = _box(fetchers, inputs, day, on_event, problems)
        if box is not None:
            boxes[day] = box
            warnings += [f"NSE daily price list of {day.isoformat()}: {p}" for p in box.problems]
    year_open_day, year_box = _year_open(fetchers, inputs, week.ending.year, on_event, problems)
    if year_open_day is not None and year_box is not None:
        boxes[year_open_day] = year_box
    market = Market(week=week, inputs=inputs, bulletin=bulletin,
                    rates=_rates(fetchers, inputs, bulletin, on_event, problems), boxes=boxes, year_open_day=year_open_day,
                    afx=_afx_changes(fetchers, week, today, on_event), typed_indices=typed_indices)
    # A day with neither a KCB daily report nor a bulletin row is read from that day's price list.
    for wk in (week, week.previous):
        for day in wk.trading_days:
            if day not in boxes and day not in inputs.kcb_daily and not any(r["date"] == day for r in (bulletin.market if bulletin else [])):
                box = _box(fetchers, inputs, day, on_event, problems)
                if box is not None:
                    boxes[day] = box
    issue = try_fetch(on_event, "Previous issue on cytonnreport.com", fetchers.previous_issue, week.ending,
                      inputs.notes.get("previous_issue"), problems=problems)

    blocks: list[dict[str, Any]] = [indices_block(market), large_caps_block(market), banking_block(market),
                                    turnover_block(market), foreign_block(market), valuation_block(market),
                                    universe_block(market, warnings)]
    drafted = (draft or draft_pieces)(BRIEFS, N_HIGHLIGHTS, provider=provider, today=today,
                                      window=(week.ending - timedelta(days=6), week.ending), on_event=on_event)
    blocks += [narrative_block(f"highlight_{p['brief_id']}", p) for p in drafted["pieces"]]
    blocks.append(_carried(issue, "outlook", "Equities outlook (closing paragraph)", equities_outlook_text, ("equities",)))

    content = {
        "section": SECTION, "title": TITLE, "week_ending": week.ending.isoformat(),
        "week_start": drafted["week_start"], "week_end": drafted["week_end"],
        "blocks": numbered(blocks), "pieces_found": len(drafted["pieces"]), "pieces_expected": N_HIGHLIGHTS,
        "shortfall": drafted["shortfall"], "warnings": list(drafted["warnings"]) + warnings + problems,
        "chart_notes": list(CHARTS), "chart_reference": CHART_REFERENCE, "chart_after": CHART_AFTER,
        "summary": compose_summary(blocks),
    }
    report_blocks(on_event, content)
    return build_review(content, check_section(content, on_event))
