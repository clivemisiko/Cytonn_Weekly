"""The government's net domestic borrowing for the fiscal year, built from CBK's own auction results.

The weekly Fixed Income section closes with "The government is at X% of its pro-rated net
domestic borrowing target of Kshs Y bn, with a net borrowing position of Kshs Z bn (inclusive of
T-bills)."  The net position used to be read from the borrowing log the fixed income team keeps
in its workbook.  Every row of that log is a figure CBK publishes, so the log is built here from
CBK's result files and the workbook's log, when one is uploaded, is only its second reading.

What CBK prints (read from the results of 1 July to 7 October 2026, 2026-10-12):

* **T-bill results**, section A: "Total Amount Accepted" and "Rollover / Redemptions" per tenor
  and in TOTAL.  Section C, the next auction: "Redemptions", which is next week's section A total
  announced a week ahead (it was not the same figure once in fourteen weeks: 31,874.00 announced
  for 24-08-2026, 31,874.15 printed that week).
* **Primary T-bond results**: "Amount Accepted" per issue, and "Redemptions" under "Purpose/
  Application of funds" in the total column ("-" is zero).  The printed total accepted is rounded
  to a whole million when there are several issues, so the accepted amount is the sum of the
  per-issue cells (17-08-2026: 312,027.34, printed 312,027).
* **Switch results** state no redemptions: holders exchange maturing paper for a longer bond.
* "New Borrowing/Net Repayment" is printed unsigned in both and is never used.

The rules:

* **Net = accepted minus redemptions**, release by release, from the fiscal year's first day
  (1 July) to the latest release settling by the end of the week's value-date window.
* **A switch auction never counts** (the investments team's rule, settled 2026-10-12): holders
  exchange paper they already hold, so a switch is not new debt.  Every switch found is listed
  for information, with CBK's amount, and adds nothing to the net.  When an uploaded workbook's
  log counts one (it holds the 26-08-2026 switch at 22,510.90), that row is flagged "workbook log
  counts a switch the rule excludes": the workbook against the rule, not an error of CBK's.
* **Nothing is a tolerance.**  Each row is CBK's printed figures.  Second readings are the
  previous release's section C against a T-bill release's redemptions, and the uploaded
  workbook's log row by row; a difference is a "sources disagree" flag on that row.
* **The files are kept and re-checked** (``ResultsCache``): each downloaded PDF is stored under
  the data folder with its sha256.  On every run a cached file is checked against that hash and
  against CBK's current size and modification time; a file CBK has replaced is downloaded again
  and the change is reported, never silently used.  Revisions happen: CBK restated the 26-08-2026
  switch results after release, as "... Final.pdf" (22,510.93 mn accepted in the original,
  21,816.46 in the file it serves now).
* **A bond redemption CBK prints on no result file is typed** (``typed_redemptions``).  CBK prints
  a bond redemption only in the results of a bond auction settling that day, so a bond that
  matures on a day with no bond auction is on no file (first case: IFB1/2014/12, 12-10-2026).
  The analysts type it under "Other bond redemptions" on the weekly form; each row counts as a
  redemption on its value date, is labelled "typed, not on a release" and is analyst input.
* **A maturity nobody accounted for is asked about, never filled in** (``maturities``, from
  fixed_income/bond_issues.py).  A maturity date inside the log's window with no redemption on
  a bond result of that day and no typed row for that day gets a row of its own, flagged.  The
  face value it names is a floor at issue, not the amount redeemed, and is never subtracted.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional

from cytonn_weekly.checkers.digital_payments import MISSING
from cytonn_weekly.common.computed import ANALYST, SOURCE, an_input
from cytonn_weekly.common.formatting import NUMBER, TEXT
from cytonn_weekly.common.http import http_get, http_head
from cytonn_weekly.common.review import table_block
from cytonn_weekly.fixed_income import bond_issues, cbk_auctions

SOURCE_NAME = "CBK Treasury bill and bond auction results"
TBILL, PRIMARY, TAP, SWITCH = "tbill", "primary", "tap", "switch"
KINDS = {TBILL: "T-bills", PRIMARY: "T-bonds", TAP: "T-bond tap sale", SWITCH: "T-bond switch"}
ORDER = list(KINDS)
TYPED, MATURITY = "typed_redemption", "maturity"      # rows of the log that are not a CBK release
TYPED_LABEL = "typed, not on a release"
TYPED_KIND = f"Bond redemption ({TYPED_LABEL})"
MATURITY_KIND = "Bond maturity (no redemption found)"

GET_DELAY = 1.0     # seconds between two downloads from centralbank.go.ke
PROBE_DELAY = 0.5   # seconds between two size-and-date checks of files already held
MAX_GAP_DAYS = 9    # T-bills settle weekly (a Monday, or the Tuesday after a holiday); more than this is a missing week
# The advisory stock check (stock_check_block): a week's change in CBK's outstanding bond stock less the net of the bond
# results settling in it.  From 1 July to 25 September 2026 that residual ran from 0.00 to +3.77 bn, so a fall of more
# than 1.0 bn that no result explains is worth a look.  A threshold for a prompt, never a tolerance on a figure.
STOCK_RESIDUAL_FLOOR_BN = Decimal("-1.0")

Getter = Callable[[str], bytes]
Probe = Callable[[str], dict[str, str]]


# ---------------------------------------------------------------------------
# The kept files
# ---------------------------------------------------------------------------

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_name(url: str) -> str:
    return re.sub(r"[^A-Za-z0-9 ._()&,-]", "_", url.rsplit("/", 1)[-1].replace("%20", " "))


class ResultsCache:
    """CBK's result PDFs as downloaded, each with its sha256, and a ``get`` that reads through them.

    ``get`` is a drop-in for the fetchers' getter: a listing page is always fetched; a PDF is
    downloaded once and then served from the folder.  Before a kept PDF is served it is
    re-checked: its bytes against the recorded hash, and (``probe``) CBK's current size and
    modification time against those recorded at download.  If either differs the file is
    downloaded again; if its content really changed, the earlier copy is kept beside it and
    ``changes`` says so.  ``downloaded`` lists what was fetched this run.
    """

    def __init__(self, folder: Path, get: Getter = http_get, probe: Optional[Probe] = http_head,
                 sleep: Callable[[float], None] = time.sleep):
        self.folder = Path(folder)
        self._get, self._probe, self._sleep = get, probe, sleep
        self._asked = False
        self.changes: list[str] = []
        self.unchecked: list[str] = []
        self.downloaded: list[str] = []
        self.pages: dict[str, bytes] = {}     # the listing pages fetched this run, as served
        self.index: dict[str, dict[str, Any]] = {}
        path = self.folder / "index.json"
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                self.index = loaded if isinstance(loaded, dict) else {}
            except ValueError:
                self.index = {}

    def _pace(self, seconds: float) -> None:
        if self._asked:
            self._sleep(seconds)
        self._asked = True

    def _headers(self, url: str) -> Optional[dict[str, str]]:
        if self._probe is None:
            return None
        self._pace(PROBE_DELAY)
        head = self._probe(url)
        return {k: head[k] for k in ("content-length", "last-modified") if head.get(k)}

    def _download(self, url: str) -> bytes:
        self._pace(GET_DELAY)
        return self._get(url)

    def _store(self, url: str, data: bytes, headers: Optional[dict[str, str]]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        name = _file_name(url)
        (self.folder / name).write_bytes(data)
        self.index[url] = {"file": name, "sha256": sha256(data), "bytes": len(data), "headers": headers or {},
                           "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        (self.folder / "index.json").write_text(json.dumps(self.index, indent=1, sort_keys=True), encoding="utf-8")
        self.downloaded.append(name)

    def info(self, url: str) -> dict[str, Any]:
        return self.index.get(url) or {}

    def get(self, url: str) -> bytes:
        if not url.lower().split("?")[0].endswith(".pdf"):
            self.pages[url] = self._download(url)
            return self.pages[url]
        entry = self.index.get(url)
        path = self.folder / entry["file"] if entry else None
        if entry is None or path is None or not path.is_file():
            data = self._download(url)
            self._store(url, data, None)
            return data
        held = path.read_bytes()
        damaged = sha256(held) != entry["sha256"]
        headers: Optional[dict[str, str]] = None
        try:
            headers = self._headers(url)
        except Exception as exc:  # noqa: BLE001 - the kept copy is still the file that was downloaded
            self.unchecked.append(f"{entry['file']} ({type(exc).__name__})")
        recorded = entry.get("headers") or {}
        moved = bool(headers) and bool(recorded) and any(recorded.get(k) not in (None, headers.get(k)) for k in recorded)
        if not damaged and not moved:
            if headers and not recorded:   # first re-check: remember what CBK reports for the file as held
                entry["headers"] = headers
                (self.folder / "index.json").write_text(json.dumps(self.index, indent=1, sort_keys=True), encoding="utf-8")
            return held
        data = self._download(url)
        new, old = sha256(data), entry["sha256"]
        if new != old:
            kept = f"{path.stem}.replaced-{old[:8]}{path.suffix}"
            if not damaged:
                (self.folder / kept).write_bytes(held)
            why = ("the kept copy no longer matched the hash recorded when it was downloaded" if damaged else
                   f"CBK's file changed after it was downloaded on {str(entry.get('fetched_at', ''))[:10]} "
                   f"(sha256 {old[:12]} then, {new[:12]} now); the earlier copy is kept as {kept}")
            self.changes.append(f"{entry['file']}: {why}. The file as CBK serves it now is used: check the figures it changes.")
        elif damaged:
            self.changes.append(f"{entry['file']}: the kept copy no longer matched the hash recorded when it was downloaded; "
                                "it was downloaded again and is unchanged at CBK.")
        self._store(url, data, headers)
        return data


# ---------------------------------------------------------------------------
# Fetch: every release of the fiscal year so far
# ---------------------------------------------------------------------------

def _mn_of_bn(bn: Optional[float]) -> Optional[float]:
    return None if bn is None else float(Decimal(repr(bn)) * 1000)


def tbill_release(auction: dict[str, Any]) -> dict[str, Any]:
    """One T-bill auction (cbk_auctions.fetch_period_tbills) as a release of the log."""
    accepted, redeemed = auction.get("accepted_kes_m") or {}, auction.get("redemptions_kes_m") or {}
    parts = [{"label": t, "kes_m": accepted.get(t)} for t in cbk_auctions.TENORS]
    out = {"value_date": auction["value_date"], "kind": TBILL, "url": auction.get("url"), "error": auction.get("error"),
           "accepted_parts": parts, "accepted_kes_m": cbk_auctions._total([p["kes_m"] for p in parts]),
           "accepted_printed_kes_m": accepted.get("total"), "redemptions_kes_m": redeemed.get("total"),
           "redemptions_parts": [{"label": t, "kes_m": redeemed.get(t)} for t in cbk_auctions.TENORS],
           "next_week_redemptions_kes_m": auction.get("next_week_redemptions_kes_m"),
           "next_value_date": auction.get("next_value_date")}
    if out["error"] is None and out["accepted_kes_m"] is None:
        out["error"] = "an accepted amount was not found in the results PDF"
    elif out["error"] is None and out["redemptions_kes_m"] is None:
        out["error"] = "'Rollover / Redemptions' was not found in the results PDF"
    return out


def tbond_release(auction: dict[str, Any]) -> dict[str, Any]:
    """One T-bond auction (cbk_auctions.fetch_period_tbonds) as a release of the log."""
    parts = [{"label": r["issue"], "kes_m": _mn_of_bn(r.get("accepted_kes_bn"))} for r in auction.get("rows") or []]
    out = {"value_date": auction["value_date"], "kind": auction.get("kind") or PRIMARY, "url": auction.get("url"),
           "error": auction.get("error"), "accepted_parts": parts,
           "accepted_kes_m": cbk_auctions._total([p["kes_m"] for p in parts]),
           "redemptions_kes_m": auction.get("redemptions_kes_m")}
    if out["error"] is None and out["accepted_kes_m"] is None:
        out["error"] = "an accepted amount was not found in the results PDF"
    elif out["error"] is None and out["kind"] == PRIMARY and out["redemptions_kes_m"] is None:
        out["error"] = "'Redemptions' was not found in the results PDF"
    return out


def release_key(release: dict[str, Any]) -> tuple[str, int]:
    return release["value_date"], ORDER.index(release["kind"]) if release["kind"] in ORDER else len(ORDER)


def fetch_releases(start: date, end: date, cache_dir: Path, get: Getter = http_get, probe: Optional[Probe] = http_head,
                   sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Every T-bill and T-bond result with a value date in ``start``..``end``, oldest first.

    {"start", "end", "releases": [...], "maturities": [...], "warnings": [...]}: each release is
    its value date, kind (tbill, primary, tap, switch), accepted amount and its parts, redemptions
    (None where the results state none), the file's name and sha256, and an ``error`` if it could
    not be read.  The first run of a fiscal year downloads every file since 1 July; later runs
    download only what is new (one T-bill file a week, and any bond result) and re-check the rest.

    ``maturities`` is the bond maturities of CBK's "Issues of Treasury Bonds" table
    (bond_issues.read_maturities), or None if it could not be read.  The table is in the bond
    listing page this fetch already downloads, so it costs no further request.
    """
    cache = ResultsCache(cache_dir, get, probe, sleep)
    bills = cbk_auctions.fetch_period_tbills(start, end, get=cache.get)
    bonds = cbk_auctions.fetch_period_tbonds(start, end, get=cache.get)
    releases = [tbill_release(a) for a in bills["auctions"]] + [tbond_release(a) for a in bonds["auctions"]]
    for r in releases:
        info = cache.info(r["url"])
        r["file"], r["sha256"] = info.get("file") or _file_name(r["url"]), info.get("sha256")
    releases.sort(key=release_key)
    warnings = [f"CBK auction results: {c}" for c in cache.changes]
    if cache.unchecked:
        warnings.append(f"CBK auction results: {len(cache.unchecked)} kept file(s) could not be re-checked against "
                        f"centralbank.go.ke this run and are used as downloaded: {', '.join(cache.unchecked[:5])}"
                        f"{', ...' if len(cache.unchecked) > 5 else ''}.")
    issues = bond_issues.read_maturities(cache.pages.get(cbk_auctions.TBOND_LISTING), cache.folder)
    warnings += issues["warnings"]
    return {"start": start.isoformat(), "end": end.isoformat(), "releases": releases, "warnings": warnings,
            "maturities": issues["maturities"], "issues_sha256": issues["sha256"],
            "downloaded": list(cache.downloaded), "listings": [cbk_auctions.TBILL_LISTING, cbk_auctions.TBOND_LISTING]}


# ---------------------------------------------------------------------------
# The log
# ---------------------------------------------------------------------------

def _d(value: Any) -> Decimal:
    return Decimal(repr(value)) if isinstance(value, float) else Decimal(str(value))


def _mn(value: Any) -> str:
    return f"{_d(value):,.2f}"


def _day(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d-%m-%Y")


def row_key(release: dict[str, Any]) -> str:
    if release["kind"] == TYPED:
        return f"{release['value_date']} {release['bond']} redemption ({TYPED_LABEL})"
    if release["kind"] == MATURITY:
        return f"{release['value_date']} {release['bond']} maturity"
    return f"{release['value_date']} {KINDS.get(release['kind'], release['kind'])}"


def maturity_message(day: str, bond: str, face_kes_m: Any) -> str:
    return (f"bond maturity on {_day(day)} ({bond}, up to {_mn(face_kes_m)} mn at face, outstanding may be lower): "
            "no redemption on any release and none typed")


def release_source(release: dict[str, Any]) -> str:
    what = {TBILL: "Treasury bill auction results", PRIMARY: "Treasury bond auction results",
            TAP: "Treasury bond tap sale results", SWITCH: "Treasury bond switch auction results"}[release["kind"]]
    return f"CBK {what}, value date {release['value_date']}"


@dataclass
class Log:
    """The fiscal year's log up to one week, and what the closing sentence's figures are made from."""

    fy_start: date
    limit: date
    rows: list[dict[str, Any]] = field(default_factory=list)            # the table's source rows, oldest first
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)      # the net figure's inputs
    accepted: list[str] = field(default_factory=list)                    # input names that add
    redeemed: list[str] = field(default_factory=list)                    # input names that subtract
    net_kes_m: Decimal = Decimal(0)
    as_at: Optional[date] = None                                          # the latest counted release's value date
    counted: int = 0
    switches: list[dict[str, Any]] = field(default_factory=list)         # found, and excluded by rule
    typed: int = 0                                                        # typed bond redemptions counted
    unaccounted: list[str] = field(default_factory=list)                 # maturities nobody accounted for (the messages)
    workbook_net_kes_m: Optional[Decimal] = None                          # the uploaded workbook's own log, same window
    workbook_as_at: Optional[date] = None
    second_sources: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)   # the log cannot be used: a release that could not be read
    flags: list[str] = field(default_factory=list)      # the net needs a human call (a missing week, unstated redemptions)
    warnings: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not self.problems and self.as_at is not None

    @property
    def days(self) -> Optional[int]:
        return None if self.as_at is None else (self.as_at - self.fy_start).days

    @property
    def net_bn(self) -> Decimal:
        return self.net_kes_m / 1000

    @property
    def net_expr(self) -> list:
        gross: list = ["sum", *self.accepted]
        return ["div", ["sub", gross, ["sum", *self.redeemed]] if self.redeemed else gross, 1000]

    def prorated_bn(self, target_bn: Any) -> Decimal:
        """The full-year target pro-rated by the days from the fiscal year's start to ``as_at``, over a 364-day year."""
        return _d(target_bn) / 364 * (self.days or 0)

    def share_pct(self, target_bn: Any) -> Decimal:
        """Net borrowing as a percentage OF the pro-rated target (never "ahead of" it)."""
        return self.net_bn / self.prorated_bn(target_bn) * 100

    def workbook_difference(self) -> Optional[str]:
        """The workbook's own log beside the rule's net, when the two differ: old against new, for the warnings."""
        if self.workbook_net_kes_m is None or not self.usable or self.workbook_as_at != self.as_at:
            return None
        gap = self.workbook_net_kes_m - self.net_kes_m
        if gap == 0:
            return None
        theirs = [_d(s["workbook_kes_m"]) for s in self.switches if s.get("workbook_kes_m") is not None]
        rest = gap - sum(theirs, Decimal(0))
        why = [f"the switch auction{'' if len(theirs) == 1 else 's'} it counts ({_mn(sum(theirs, Decimal(0)))} mn)"] if theirs else []
        if rest:
            why.append(f"{_mn(rest)} mn in other rows (each is flagged in the log)")
        return (f"Net domestic borrowing: the uploaded workbook's own log adds to Kshs {self.workbook_net_kes_m / 1000:,.3f} bn "
                f"to {self.as_at.isoformat()}, against Kshs {self.net_bn:,.3f} bn from CBK's results with no switch counted. "
                f"The difference of {_mn(gap)} mn is {' and '.join(why)}. The figure from CBK's results is used.")


def _match_workbook(releases: list[dict[str, Any]], workbook_log: list[dict[str, Any]]) -> tuple[dict[int, dict], list[dict]]:
    """Pair each release with the workbook's row for it: same value date, the same accepted amount first, then in order.

    Returns ({index of the release: the workbook row}, the workbook rows no release pairs with).
    """
    pairs: dict[int, dict] = {}
    left: list[dict] = []
    by_day: dict[str, list[dict]] = {}
    for row in workbook_log:
        by_day.setdefault(row["date"].isoformat(), []).append(row)
    for day, theirs in by_day.items():
        ours = [n for n, r in enumerate(releases) if r["value_date"] == day and r["kind"] in KINDS]
        for n in list(ours):
            got = releases[n].get("accepted_kes_m")
            same = next((t for t in theirs if got is not None and t["accepted"].number is not None
                         and round(_d(t["accepted"].number), 2) == round(_d(got), 2)), None)
            if same is not None:
                pairs[n] = same
                theirs = [t for t in theirs if t is not same]
                ours.remove(n)
        for n, t in zip(ours, theirs):
            pairs[n] = t
        left += theirs[len(ours):]
    return pairs, left


def build_log(releases: list[dict[str, Any]], fy_start: date, limit: date,
              workbook_log: Optional[list[dict[str, Any]]] = None,
              cell_source: Callable[[Any], str] = lambda cell: getattr(cell, "source", None) or str(cell.ref),
              typed_redemptions: Optional[list[dict[str, Any]]] = None,
              maturities: Optional[list[dict[str, Any]]] = None) -> Log:
    """The log from ``fy_start`` to ``limit``: one row per release, the running net, and the net figure's inputs.

    A switch auction is listed and never counted.  ``workbook_log`` is the uploaded workbook's log
    ([{date, accepted, redemptions}], cells, redemptions negative), used only as each row's second
    reading; a row of it that counts a switch is flagged on that switch's row.

    ``typed_redemptions`` ([{date, bond, kes_m, source}], the form's "Other bond redemptions") are
    bond redemptions CBK prints on no result file: each in the window is a row of its own that
    subtracts its amount on its value date, as analyst input.  ``maturities`` ([{date, bond,
    face_kes_m}], bond_issues.maturities) are only a question: one in the window with no
    redemption on a bond result of that day and no typed row for that day is a flagged row that
    adds nothing to the net.
    """
    log = Log(fy_start, limit)
    seen_bills: set[str] = set()
    kept: list[dict[str, Any]] = []
    for r in sorted(releases, key=release_key):
        if not fy_start.isoformat() <= r["value_date"] <= limit.isoformat():
            continue
        if r["kind"] == TBILL:
            if r["value_date"] in seen_bills:
                log.warnings.append(f"CBK lists two Treasury bill results with value date {r['value_date']}; the first "
                                    f"listed is used and {r.get('file') or r.get('url')} is left out.")
                continue
            seen_bills.add(r["value_date"])
        kept.append(r)
    extra: list[dict[str, Any]] = []      # rows that are not a CBK release; they never pair with the workbook's log
    days_typed: set[str] = set()
    for t in typed_redemptions or []:
        day = t["date"].isoformat() if isinstance(t["date"], date) else str(t["date"])
        if fy_start.isoformat() <= day <= limit.isoformat():
            days_typed.add(day)
            extra.append({"value_date": day, "kind": TYPED, "bond": t["bond"], "kes_m": t["kes_m"], "source": t["source"]})
    # A bond result prints its day's redemptions in one total, so a maturity is carried by any bond result of the
    # day that states redemptions; a Treasury bill result's redemptions are bills and never carry a bond.
    days_redeemed = {r["value_date"] for r in kept if r["kind"] in (PRIMARY, TAP) and (r.get("redemptions_kes_m") or 0) > 0}
    for m in maturities or []:
        if fy_start.isoformat() <= m["date"] <= limit.isoformat() and m["date"] not in days_redeemed | days_typed:
            extra.append({"value_date": m["date"], "kind": MATURITY, "bond": m["bond"], "face_kes_m": m["face_kes_m"]})
    kept = sorted(kept + extra, key=release_key)

    in_window = [w for w in (workbook_log or []) if fy_start <= w["date"] <= limit]
    pairs, left = _match_workbook(kept, in_window)
    if in_window:
        log.workbook_net_kes_m = sum((_d(w["accepted"].number or 0) - abs(_d(w["redemptions"].number or 0))
                                      for w in in_window), Decimal(0))
        log.workbook_as_at = max(w["date"] for w in in_window)
    running = Decimal(0)
    previous_bill: Optional[dict[str, Any]] = None
    bill_days: list[date] = []
    rounded: list[str] = []
    for n, r in enumerate(kept):
        if r["kind"] == MATURITY:
            message = maturity_message(r["value_date"], r["bond"], r["face_kes_m"])
            log.rows.append({"key": row_key(r), "value_date": r["value_date"], "kind": MATURITY_KIND, "accepted_kes_m": None,
                             "redemptions_kes_m": None, "net_kes_m": None, "counted": "No", "running_bn": float(running / 1000),
                             "file": None, "sha256": None, "error": None, "_derived": {},
                             "_flags": [{"kind": MISSING, "field": "redemptions_kes_m", "message": message,
                                         "sources": [{"source": f"{bond_issues.SOURCE_NAME}, face value at issue (a floor: the "
                                                                "table lacks rows)",
                                                      "value": r["face_kes_m"], "normalized": _mn(r["face_kes_m"])}]}]})
            log.unaccounted.append(message)
            continue
        if r["kind"] == TYPED:
            name, amount = f"redemptions {r['value_date']} {r['bond']} ({TYPED_LABEL})", _d(r["kes_m"])
            log.inputs[name] = an_input(r["kes_m"], ANALYST, r["source"])
            log.redeemed.append(name)
            before, running = running, running - amount
            log.rows.append({"key": row_key(r), "value_date": r["value_date"], "kind": TYPED_KIND, "accepted_kes_m": None,
                             "redemptions_kes_m": r["kes_m"], "net_kes_m": float(-amount), "counted": "Yes",
                             "running_bn": float(running / 1000), "file": None, "sha256": None, "error": None,
                             "_origin": ANALYST, "_note": f"{TYPED_LABEL}: {r['source']}",
                             "_derived": {"net_kes_m": {"expr": ["neg", "redemptions"], "inputs": {"redemptions": r["kes_m"]}},
                                          "running_bn": {"expr": ["add", "before", ["div", "net", 1000]],
                                                         "inputs": {"before": float(before / 1000), "net": float(-amount)}}}})
            log.typed += 1
            continue
        key, src, when = row_key(r), release_source(r), date.fromisoformat(r["value_date"])
        counts = r["kind"] != SWITCH          # a switch is not new debt: listed, never counted
        row: dict[str, Any] = {"key": key, "value_date": r["value_date"], "kind": KINDS.get(r["kind"], r["kind"]),
                               "accepted_kes_m": r.get("accepted_kes_m"), "redemptions_kes_m": r.get("redemptions_kes_m"),
                               "net_kes_m": None, "counted": "Yes" if counts else "No", "running_bn": float(running / 1000),
                               "file": r.get("file"), "sha256": r.get("sha256"), "error": None, "_derived": {}}
        log.rows.append(row)
        if r.get("error") or r.get("accepted_kes_m") is None:
            row["error"] = r.get("error") or "an accepted amount was not found in the results PDF"
            if counts:
                log.problems.append(f"CBK's {KINDS.get(r['kind'], r['kind']).lower()} results with value date "
                                    f"{r['value_date']} could not be read ({row['error']})")
            continue
        parts = {f"{p['label']} accepted": p["kes_m"] for p in r["accepted_parts"]}
        row["_derived"]["accepted_kes_m"] = {"expr": ["sum", *parts], "inputs": parts}
        if r["kind"] == TBILL:
            bill_days.append(when)
            printed = r.get("accepted_printed_kes_m")
            if printed is not None and _d(printed) != _d(r["accepted_kes_m"]):
                rounded.append(f"{_day(r['value_date'])} ({_mn(r['accepted_kes_m'])} against {_mn(printed)})")
            tenors = cbk_auctions._total([p["kes_m"] for p in r.get("redemptions_parts") or []])
            if tenors is not None and _d(tenors) != _d(r["redemptions_kes_m"]):
                log.warnings.append(f"T-bills of {_day(r['value_date'])}: the three tenors' redemptions add to {_mn(tenors)} "
                                    f"and CBK prints a total of {_mn(r['redemptions_kes_m'])}; the printed total is used.")
            if previous_bill is not None and previous_bill.get("next_week_redemptions_kes_m") is not None \
                    and previous_bill.get("next_value_date") in (None, r["value_date"]):
                log.second_sources.append({"row": key, "column": "redemptions_kes_m",
                                           "source": f"{release_source(previous_bill)}, section C (the next auction's redemptions)",
                                           "value": previous_bill["next_week_redemptions_kes_m"]})
            previous_bill = r
        theirs = pairs.get(n)
        if not counts:
            found = dict(r)
            if theirs is not None and theirs["accepted"].number:
                # The workbook against the rule, not against CBK: whatever amount it holds, the row should not be there.
                amount = theirs["accepted"].number
                found["workbook_kes_m"] = amount
                row["_flags"] = [{"field": "accepted_kes_m",
                                  "message": (f"workbook log counts a switch the rule excludes ({_day(r['value_date'])}, "
                                              f"{_mn(amount)} mn)"),
                                  "sources": [{"source": src, "value": r["accepted_kes_m"], "normalized": _mn(r["accepted_kes_m"])},
                                              {"source": cell_source(theirs["accepted"]), "value": amount,
                                               "normalized": _mn(amount)}]}]
            log.switches.append(found)
            continue
        if theirs is not None:
            log.second_sources.append({"row": key, "column": "accepted_kes_m", "source": cell_source(theirs["accepted"]),
                                       "value": theirs["accepted"].number})
            red = theirs["redemptions"].number
            if red is not None and not (r.get("redemptions_kes_m") is None and red == 0):
                log.second_sources.append({"row": key, "column": "redemptions_kes_m", "source": cell_source(theirs["redemptions"]),
                                           "value": abs(red)})

        accepted = _d(r["accepted_kes_m"])
        for p in r["accepted_parts"]:
            name = f"accepted {r['value_date']} {p['label']}"
            log.inputs[name] = an_input(p["kes_m"], SOURCE, f"{src}, {p['label']}")
            log.accepted.append(name)
        redeemed = r.get("redemptions_kes_m")
        if redeemed is None:
            log.flags.append(f"CBK's {KINDS[r['kind']].lower()} results of {_day(r['value_date'])} state no redemptions; "
                             "none is subtracted for it")
            net = accepted
            row["_derived"]["net_kes_m"] = {"expr": "accepted", "inputs": {"accepted": float(accepted)}}
        else:
            name = f"redemptions {r['value_date']} {KINDS[r['kind']]}"
            log.inputs[name] = an_input(redeemed, SOURCE, f"{src}, redemptions")
            log.redeemed.append(name)
            net = accepted - _d(redeemed)
            row["_derived"]["net_kes_m"] = {"expr": ["sub", "accepted", "redemptions"],
                                            "inputs": {"accepted": float(accepted), "redemptions": redeemed}}
        row["_derived"]["running_bn"] = {"expr": ["add", "before", ["div", "net", 1000]],
                                         "inputs": {"before": float(running / 1000), "net": float(net)}}
        running += net
        row.update(net_kes_m=float(net), running_bn=float(running / 1000))
        log.counted += 1
        log.as_at = when if log.as_at is None else max(log.as_at, when)
    log.net_kes_m = running
    if rounded:
        log.warnings.append("Net domestic borrowing: a Treasury bill auction's accepted amount is the sum of its three tenors, "
                            f"which is not CBK's printed total for {', '.join(rounded)}.")

    edges = [fy_start - timedelta(days=1), *bill_days]
    for a, b in zip(edges, edges[1:]):
        if (b - a).days > MAX_GAP_DAYS:
            log.flags.append(f"no Treasury bill results were found with a value date between {a.isoformat()} and "
                             f"{b.isoformat()}; a week may be missing from the log")
    for w in left:
        log.warnings.append(f"The uploaded workbook's log has a row dated {w['date'].isoformat()} (accepted "
                            f"{_mn(w['accepted'].number or 0)}, redemptions {_mn(abs(w['redemptions'].number or 0))}) that no "
                            "CBK result matches; it is not in the net borrowing.")
    if workbook_log:
        latest = max(w["date"] for w in workbook_log)
        missing = [row_key(r) for n, r in enumerate(kept) if n not in pairs and r["kind"] in (TBILL, PRIMARY, TAP)
                   and date.fromisoformat(r["value_date"]) <= latest]
        if missing:
            log.warnings.append(f"The uploaded workbook's log has no row for {', '.join(missing)}, which CBK's results list.")
    return log


# ---------------------------------------------------------------------------
# What the review shows
# ---------------------------------------------------------------------------

# Amounts in Kshs mn to 2 dp, as CBK prints them; the running net in Kshs bn to 1 dp, as the issue prints the
# position ("a net borrowing position of Kshs 530.0 bn", Cytonn Weekly #38.2026, Fixed Income, closing paragraph).
LOG_COLUMNS = [
    {"key": "value_date", "label": "Value date", "fmt": TEXT},
    {"key": "kind", "label": "Auction", "fmt": TEXT},
    {"key": "accepted_kes_m", "label": "Accepted (Kshs mn)", "fmt": NUMBER, "decimals": 2},
    {"key": "redemptions_kes_m", "label": "Redemptions (Kshs mn)", "fmt": NUMBER, "decimals": 2},
    {"key": "net_kes_m", "label": "Net (Kshs mn)", "fmt": NUMBER, "decimals": 2},
    {"key": "counted", "label": "Counted", "fmt": TEXT},
    {"key": "running_bn", "label": "Running net (Kshs bn)", "fmt": NUMBER, "decimals": 1},
]
LOG_TITLE = "Net domestic borrowing log"


def log_block(log: Log) -> dict[str, Any]:
    """The log as a table for the review screen only (the issue prints the sentence, not the log)."""
    block = table_block("borrowing_log", LOG_TITLE, LOG_COLUMNS, log.rows, "key", "key",
                        {"name": SOURCE_NAME, "url": cbk_auctions.TBILL_LISTING,
                         "as_of": log.as_at.isoformat() if log.as_at else None})
    block["export"] = False
    block["second_sources"] = log.second_sources
    block["notes"] = [
        f"One row per CBK result with a value date from {log.fy_start.isoformat()} to {log.limit.isoformat()}. Net is accepted "
        "minus redemptions; CBK's \"New Borrowing/Net Repayment\" is printed unsigned and is not used. A T-bond's accepted "
        "amount is the sum of its issues' accepted amounts. A switch auction's results state no redemptions.",
        "A switch auction is not new debt and is never counted (the investments team's rule).",
        "CBK prints a bond redemption only in the results of a bond auction settling that day. A bond that matures on a day "
        f"with no bond auction is typed under \"Other bond redemptions\" on the weekly form and shown here as \"{TYPED_LABEL}\". "
        f"A maturity listed in {bond_issues.SOURCE_NAME} with neither is a flagged row that adds nothing to the net; the face "
        "value it names is a floor at issue (the table lacks rows), not the amount redeemed.",
    ]
    if log.switches:
        block["notes"].append(switches_note(log.switches))
    return block


# ---------------------------------------------------------------------------
# Advisory: the bond stock against the log
# ---------------------------------------------------------------------------

STOCK_TITLE = "Treasury bond stock against the log (advisory)"
STOCK_SOURCE = "CBK Weekly Bulletin, Government Domestic Debt"
STOCK_COLUMNS = [
    {"key": "from", "label": "From", "fmt": TEXT},
    {"key": "to", "label": "To", "fmt": TEXT},
    {"key": "stock_from_bn", "label": "Bond stock, from (Kshs bn)", "fmt": NUMBER, "decimals": 2},
    {"key": "stock_to_bn", "label": "Bond stock, to (Kshs bn)", "fmt": NUMBER, "decimals": 2},
    {"key": "change_bn", "label": "Change (Kshs bn)", "fmt": NUMBER, "decimals": 2},
    {"key": "net_bonds_bn", "label": "Net of bond rows in the log (Kshs bn)", "fmt": NUMBER, "decimals": 2},
    {"key": "residual_bn", "label": "Residual (Kshs bn)", "fmt": NUMBER, "decimals": 2},
]
_BOND_ROWS = (KINDS[PRIMARY], KINDS[TAP], TYPED_KIND)


def stock_check_block(log: Log, bond_stock: dict[date, float], as_of: Optional[date] = None) -> Optional[dict[str, Any]]:
    """An advisory table: for each pair of consecutive Fridays the bulletin prints, the change in the outstanding
    Treasury bond stock less the net of the log's bond rows settling after the first Friday and by the second.

    It is a prompt to look, not an exact match: the stock is CBK's own count and moves for reasons
    no auction result prints.  A residual below ``STOCK_RESIDUAL_FLOOR_BN`` is flagged "possible
    unprinted bond redemption".  A week with a switch auction is left out (the results do not
    print how the exchanged paper splits, so the week's change cannot be set against them), and
    so is a week holding a result that could not be read.  None when the bulletin gives no such
    pair inside the log's window.
    """
    days = sorted(bond_stock)
    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    for a, b in zip(days, days[1:]):
        if (b - a).days != 7 or a.weekday() != 4 or a < log.fy_start or b > log.limit:
            continue
        inside = [r for r in log.rows if a.isoformat() < r["value_date"] <= b.isoformat()]
        if any(r["kind"] == KINDS[SWITCH] or r.get("error") for r in inside):
            skipped.append(f"{a.isoformat()} to {b.isoformat()}")
            continue
        bonds = {r["key"]: r["net_kes_m"] for r in inside if r["kind"] in _BOND_ROWS and r["net_kes_m"] is not None}
        change = _d(bond_stock[b]) - _d(bond_stock[a])
        net = sum((_d(v) for v in bonds.values()), Decimal(0)) / 1000
        residual = change - net
        row: dict[str, Any] = {
            "key": f"{a.isoformat()} to {b.isoformat()}", "from": a.isoformat(), "to": b.isoformat(),
            "stock_from_bn": bond_stock[a], "stock_to_bn": bond_stock[b], "change_bn": float(change),
            "net_bonds_bn": float(net), "residual_bn": float(residual),
            "_derived": {"change_bn": {"expr": ["sub", "to", "from"], "inputs": {"to": bond_stock[b], "from": bond_stock[a]}},
                         "residual_bn": {"expr": ["sub", "change", "net"], "inputs": {"change": float(change), "net": float(net)}}}}
        if bonds:
            row["_derived"]["net_bonds_bn"] = {"expr": ["div", ["sum", *bonds], 1000], "inputs": bonds}
        if residual < STOCK_RESIDUAL_FLOOR_BN:
            row["_flags"] = [{"field": "residual_bn", "message": (
                f"possible unprinted bond redemption: the Treasury bond stock changed by {change:,.2f} bn from "
                f"{_day(a.isoformat())} to {_day(b.isoformat())}, {-residual:,.2f} bn less than the net of the bond results "
                "settling between them (advisory, not an exact match)"),
                "sources": [{"source": STOCK_SOURCE, "value": float(change), "normalized": f"{change:,.2f}"},
                            {"source": SOURCE_NAME, "value": float(net), "normalized": f"{net:,.2f}"}]}]
        rows.append(row)
    if not rows:
        return None
    block = table_block("bond_stock_check", STOCK_TITLE, STOCK_COLUMNS, rows, "key", "key",
                        {"name": f"{STOCK_SOURCE}; {SOURCE_NAME}", "url": cbk_auctions.TBOND_LISTING,
                         "as_of": as_of.isoformat() if as_of else None})
    block["export"] = False
    block["notes"] = [
        "Advisory, not an exact match. For each pair of consecutive Fridays the bulletin prints: the change in the outstanding "
        "Treasury bond stock, less the net (accepted less redemptions, typed redemptions included) of the log's bond rows "
        "settling after the first Friday and by the second. A residual below "
        f"{STOCK_RESIDUAL_FLOOR_BN} bn is flagged as a possible bond redemption that no result prints; from 1 July to "
        "25 September 2026 the residual ran from 0.00 to +3.77 bn. The bulletin prints the stock a week behind, so this "
        "looks at the weeks before this one."]
    if skipped:
        block["notes"].append(f"Left out, because a switch auction settled in the week or a result could not be read: "
                              f"{', '.join(skipped)}.")
    return block


def switches_note(switches: list[dict[str, Any]]) -> str:
    """For information only: what was found and left out.  A note, never a review flag."""
    return f"Switch auctions found, excluded by rule: {switches_listed(switches)}."


def switches_listed(switches: list[dict[str, Any]]) -> str:
    """"15-07-2026 (Kshs 7,954.71 mn), 26-08-2026 (Kshs 21,816.46 mn)"."""
    return ", ".join(f"{_day(s['value_date'])} (Kshs {_mn(s['accepted_kes_m'])} mn)" if s.get("accepted_kes_m") is not None
                     else f"{_day(s['value_date'])} (amount not read)" for s in switches)
