"""This week's inputs: the files a coordinator uploads for one report week, and where they are kept.

Each Friday the analysts send their workbooks and the KCB IB reports; the coordinator
uploads them on the start screen.  They are kept under the data directory, never in the
repository tree::

    <CYTONN_DATA_DIR>/inputs/weekly/<week-ending date>/
        equities_workbook.xlsx   fi_workbook.xlsx
        kcb_daily_<date>.pdf     (one per trading day, named by the date printed in it)
        kcb_weekly.pdf           cbk_bulletin.pdf        nse_yield_curve.pdf
        manifest.json            (what each stored file is and the date read from it)
        notes.json               (what the coordinator typed: the bidding range, the previous issue)

An upload is checked before it is stored: its size, that it is the kind of file its slot
takes (a PDF or an Excel workbook, by its first bytes, not its name), and that it reads as
the document the slot is for.  The date is read from the file itself; a KCB daily report
is filed under the date printed in it, and one for a day outside the week is refused.
Nothing about a file is guessed from its name.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from cytonn_weekly import paths
from cytonn_weekly.weekly import cbk_bulletin, equities_workbook, fi_workbook, kcb, nse_yield_curve
from cytonn_weekly.weekly.week import Week
from cytonn_weekly.weekly.workbook import Workbook, WorkbookError

MAX_BYTES = 30 * 1024 * 1024
PDF_MAGIC = b"%PDF"
XLSX_MAGIC = b"PK\x03\x04"

EQUITIES_WORKBOOK = "equities_workbook"
FI_WORKBOOK = "fi_workbook"
KCB_DAILY = "kcb_daily"
KCB_WEEKLY = "kcb_weekly"
CBK_BULLETIN = "cbk_bulletin"
NSE_YIELD_CURVE = "nse_yield_curve"

NOTE_KEYS = ("bidding_range", "previous_issue")
MAX_NOTE = 2000


class InputError(ValueError):
    """An upload that is refused, with the reason shown to the coordinator."""


@dataclass(frozen=True)
class Slot:
    slug: str
    title: str
    kind: str            # "xlsx" | "pdf"
    optional: bool
    per_day: bool        # one file per trading day
    fetchable: bool      # the tool can fetch it itself
    help: str


SLOTS: tuple[Slot, ...] = (
    Slot(EQUITIES_WORKBOOK, "Equities workbook", "xlsx", False, False, False,
         "The equities team's workbook, updated for the Friday (index levels, turnover, foreign flows, "
         "market P/E, Universe of Coverage)."),
    Slot(FI_WORKBOOK, "Fixed income workbook", "xlsx", False, False, False,
         "The fixed income mastersheet, updated for the week's auction (T-bills, money market funds, Eurobonds, "
         "government borrowing)."),
    Slot(KCB_DAILY, "KCB IB daily trading reports", "pdf", False, True, False,
         "One per trading day, Monday to Friday. Each is filed under the date printed in it."),
    Slot(KCB_WEEKLY, "KCB IB weekly trading report", "pdf", False, False, False,
         "The Friday's weekly report: week-on-week moves and the daily foreign flows."),
    Slot(CBK_BULLETIN, "CBK Weekly Bulletin", "pdf", False, False, True,
         "The Friday's bulletin. It can be fetched from centralbank.go.ke, or uploaded."),
    Slot(NSE_YIELD_CURVE, "NSE yield curve", "pdf", True, False, False,
         "Optional. Shown beside the T-bond bidding range as context only."),
)
BY_SLUG = {s.slug: s for s in SLOTS}

# Set by tests (conftest redirects it), so nothing is ever written under the real data directory.
_DEFAULT_ROOT: Optional[Path] = None


def inputs_root(root: Optional[Path] = None) -> Path:
    return Path(root) if root is not None else (_DEFAULT_ROOT or paths.DATA_DIR / "inputs" / "weekly")


def week_dir(week: Week, root: Optional[Path] = None) -> Path:
    return inputs_root(root) / week.ending.isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _manifest_path(week: Week, root: Optional[Path]) -> Path:
    return week_dir(week, root) / "manifest.json"


def read_manifest(week: Week, root: Optional[Path] = None) -> dict[str, Any]:
    path = _manifest_path(week, root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_manifest(week: Week, root: Optional[Path], manifest: dict[str, Any]) -> None:
    path = _manifest_path(week, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Identifying an upload
# ---------------------------------------------------------------------------

def _check_bytes(slot: Slot, data: bytes) -> None:
    if not data:
        raise InputError(f"{slot.title}: the file is empty")
    if len(data) > MAX_BYTES:
        raise InputError(f"{slot.title}: the file is {len(data) / 1_048_576:.1f} MB; the limit is "
                         f"{MAX_BYTES // 1_048_576} MB")
    if slot.kind == "pdf" and not data.startswith(PDF_MAGIC):
        raise InputError(f"{slot.title}: this is not a PDF file")
    if slot.kind == "xlsx" and not data.startswith(XLSX_MAGIC):
        raise InputError(f"{slot.title}: this is not an Excel workbook (.xlsx); an older .xls file must be saved as .xlsx")


def equities_workbook_date(book: Workbook) -> Optional[date]:
    """The newest Friday the workbook's P/E series has a row for."""
    sheet = book.sheet(equities_workbook.VALUATION_SHEET)
    for r in range(1, min(sheet.max_row, 40) + 1):
        c = sheet.cell(r, 1)
        if c.day is not None and sheet.cell(r, 2).number is not None:
            return c.day
    return None


def fi_workbook_date(book: Workbook) -> Optional[date]:
    """The date the workbook's money market fund table is "as published on"."""
    sheet = book.sheet(fi_workbook.MMF_SHEET)
    for c in sheet.find_all(lambda s: s.startswith("money market fund yield for fund managers as published on")):
        m = fi_workbook._PUBLISHED.search(" ".join(str(c.value).split()).lower())
        if m:
            try:
                return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y").date()
            except ValueError:
                return None
    return None


def identify(slot: Slot, data: bytes, week: Week) -> dict[str, Any]:
    """Read the upload as its slot's document: {read_date, matches, stored_name, note}.  InputError if it is not one."""
    _check_bytes(slot, data)
    try:
        if slot.slug == EQUITIES_WORKBOOK:
            read = equities_workbook_date(equities_workbook.open_equities_workbook(data, slot.title))
            return _found(read, read == week.ending, "equities_workbook.xlsx",
                          "The newest Friday its P/E series has a row for.")
        if slot.slug == FI_WORKBOOK:
            read = fi_workbook_date(fi_workbook.open_fi_workbook(data, slot.title))
            return _found(read, read == week.ending, "fi_workbook.xlsx",
                          "The date its money market fund table is published on.")
        if slot.slug in (KCB_DAILY, KCB_WEEKLY):
            report = kcb.parse_kcb_pdf(data)
            wanted = kcb.DAILY if slot.slug == KCB_DAILY else kcb.WEEKLY
            if report.kind != wanted:
                raise InputError(f"{slot.title}: this is KCB's {report.kind} report, dated "
                                 f"{report.report_date.isoformat()}, not a {wanted} one")
            if slot.slug == KCB_DAILY:
                if report.report_date not in week.trading_days:
                    raise InputError(f"{slot.title}: this report is dated {report.report_date.isoformat()}, which is "
                                     f"not in the week {week.monday.isoformat()} to {week.ending.isoformat()}")
                return _found(report.report_date, True, f"kcb_daily_{report.report_date.isoformat()}.pdf",
                              "; ".join(report.problems))
            return _found(report.report_date, report.report_date == week.ending, "kcb_weekly.pdf",
                          "; ".join(report.problems))
        if slot.slug == CBK_BULLETIN:
            bulletin = cbk_bulletin.parse_bulletin(data)
            return _found(bulletin.issue_date, bulletin.issue_date == week.ending, "cbk_bulletin.pdf",
                          "; ".join(bulletin.problems))
        if slot.slug == NSE_YIELD_CURVE:
            curve = nse_yield_curve.parse_yield_curve(data)
            return _found(curve.curve_date, week.monday <= curve.curve_date <= week.ending, "nse_yield_curve.pdf", "")
    except InputError:
        raise
    except (WorkbookError, kcb.KcbParseError, cbk_bulletin.BulletinParseError,
            nse_yield_curve.YieldCurveParseError) as exc:
        raise InputError(f"{slot.title}: {exc}")
    except Exception as exc:  # noqa: BLE001 - a file the parser chokes on is refused, never half-read
        raise InputError(f"{slot.title}: the file could not be read ({type(exc).__name__}: {exc})")
    raise InputError(f"unknown input {slot.slug!r}")


def _found(read: Optional[date], matches: bool, stored_name: str, note: str) -> dict[str, Any]:
    return {"read_date": read.isoformat() if read else None, "matches": bool(matches), "stored_name": stored_name,
            "note": note}


# ---------------------------------------------------------------------------
# Storing and listing
# ---------------------------------------------------------------------------

_SAFE_NAME = re.compile(r"[^A-Za-z0-9 ._()'&,-]")


def store(week: Week, slug: str, data: bytes, filename: str = "", root: Optional[Path] = None,
          fetched_from: Optional[str] = None) -> dict[str, Any]:
    """Check and keep one upload; returns its manifest entry.  InputError (nothing stored) if it is refused."""
    slot = BY_SLUG.get(slug)
    if slot is None:
        raise InputError(f"unknown input {slug!r}")
    found = identify(slot, data, week)
    folder = week_dir(week, root)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / found["stored_name"]).write_bytes(data)
    entry = {
        "slot": slug, "stored_name": found["stored_name"], "read_date": found["read_date"], "matches": found["matches"],
        "note": found["note"], "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "original_name": _SAFE_NAME.sub("_", filename or "")[:160], "received_at": _now(),
        "fetched_from": fetched_from,
    }
    manifest = read_manifest(week, root)
    manifest[found["stored_name"]] = entry
    _write_manifest(week, root, manifest)
    return entry


def remove(week: Week, stored_name: str, root: Optional[Path] = None) -> bool:
    manifest = read_manifest(week, root)
    if stored_name not in manifest:
        return False
    path = week_dir(week, root) / stored_name
    if path.is_file():
        path.unlink()
    del manifest[stored_name]
    _write_manifest(week, root, manifest)
    return True


def read_notes(week: Week, root: Optional[Path] = None) -> dict[str, str]:
    path = week_dir(week, root) / "notes.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return {k: str(v) for k, v in data.items() if k in NOTE_KEYS and isinstance(v, str) and v.strip()}


def write_notes(week: Week, notes: dict[str, Optional[str]], root: Optional[Path] = None) -> dict[str, str]:
    kept = read_notes(week, root)
    for key, value in notes.items():
        if key not in NOTE_KEYS:
            raise InputError(f"unknown note {key!r}")
        text = " ".join((value or "").split())
        if len(text) > MAX_NOTE:
            raise InputError(f"{key.replace('_', ' ')} is {len(text)} characters; the limit is {MAX_NOTE}")
        if text:
            kept[key] = text
        else:
            kept.pop(key, None)
    folder = week_dir(week, root)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "notes.json").write_text(json.dumps(kept, indent=1, sort_keys=True), encoding="utf-8")
    return kept


def _file_view(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: entry.get(k) for k in ("stored_name", "read_date", "matches", "note", "size", "original_name",
                                      "received_at", "fetched_from")}


def status(week: Week, root: Optional[Path] = None) -> dict[str, Any]:
    """What the panel shows: per slot, what was received, the date read from it, and whether it is this week's."""
    manifest = read_manifest(week, root)
    folder = week_dir(week, root)
    present = {name: e for name, e in manifest.items() if (folder / name).is_file()}
    slots = []
    for slot in SLOTS:
        files = sorted((e for e in present.values() if e.get("slot") == slot.slug), key=lambda e: e["stored_name"])
        view: dict[str, Any] = {"slug": slot.slug, "title": slot.title, "kind": slot.kind, "optional": slot.optional,
                                "per_day": slot.per_day, "fetchable": slot.fetchable, "help": slot.help}
        if slot.per_day:
            by_day = {e["read_date"]: e for e in files}
            view["days"] = [{"date": d.isoformat(), "weekday": d.strftime("%A"), "received": d.isoformat() in by_day,
                             "file": _file_view(by_day[d.isoformat()]) if d.isoformat() in by_day else None}
                            for d in week.trading_days]
            view["received"] = bool(files)
            view["complete"] = all(d["received"] for d in view["days"])
        else:
            view["file"] = _file_view(files[0]) if files else None
            view["received"] = bool(files)
            view["complete"] = bool(files) and bool(files[0].get("matches"))
        slots.append(view)
    return {"week_ending": week.ending.isoformat(), "monday": week.monday.isoformat(),
            "previous_friday": week.previous_friday.isoformat(), "slots": slots, "notes": read_notes(week, root),
            "max_bytes": MAX_BYTES}


# ---------------------------------------------------------------------------
# Reading the stored inputs back, for the section builders
# ---------------------------------------------------------------------------

class WeeklyInputs:
    """One week's stored inputs, parsed on first use.  A missing input is None, never an error."""

    def __init__(self, week: Week, root: Optional[Path] = None):
        self.week = week
        self.root = root
        self._cache: dict[str, Any] = {}

    def _path(self, name: str) -> Optional[Path]:
        path = week_dir(self.week, self.root) / name
        return path if path.is_file() else None

    def _once(self, key: str, load: Callable[[], Any]) -> Any:
        if key not in self._cache:
            self._cache[key] = load()
        return self._cache[key]

    def _parsed(self, key: str, name: str, parse: Callable[[bytes], Any]) -> Any:
        def load() -> Any:
            path = self._path(name)
            return parse(path.read_bytes()) if path else None

        return self._once(key, load)

    @property
    def equities_book(self) -> Optional[Workbook]:
        return self._parsed("eq", "equities_workbook.xlsx", lambda b: equities_workbook.open_equities_workbook(b))

    @property
    def fi_book(self) -> Optional[Workbook]:
        return self._parsed("fi", "fi_workbook.xlsx", lambda b: fi_workbook.open_fi_workbook(b))

    @property
    def kcb_weekly(self) -> Optional[kcb.KcbReport]:
        return self._parsed("kcbw", "kcb_weekly.pdf", kcb.parse_kcb_pdf)

    @property
    def kcb_daily(self) -> dict[date, kcb.KcbReport]:
        def load() -> dict[date, kcb.KcbReport]:
            out = {}
            for day in self.week.trading_days:
                path = self._path(f"kcb_daily_{day.isoformat()}.pdf")
                if path:
                    out[day] = kcb.parse_kcb_pdf(path.read_bytes())
            return out

        return self._once("kcbd", load)

    @property
    def bulletin(self) -> Optional[cbk_bulletin.Bulletin]:
        return self._parsed("bulletin", "cbk_bulletin.pdf", cbk_bulletin.parse_bulletin)

    @property
    def yield_curve(self) -> Optional[nse_yield_curve.YieldCurve]:
        return self._parsed("curve", "nse_yield_curve.pdf", nse_yield_curve.parse_yield_curve)

    @property
    def notes(self) -> dict[str, str]:
        return self._once("notes", lambda: read_notes(self.week, self.root))

    def matches(self, stored_name: str) -> Optional[bool]:
        """Whether a stored file's own date is this week's (None if it is not stored)."""
        entry = read_manifest(self.week, self.root).get(stored_name)
        return None if entry is None else bool(entry.get("matches"))

    @property
    def cache_dir(self) -> Path:
        """Where slow readings (OCR) of fetched documents are remembered, beside the weekly inputs."""
        return inputs_root(self.root).parent / "ocr_cache"
