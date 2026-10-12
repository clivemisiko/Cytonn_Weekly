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
* **A switch is listed, never counted on the tool's own judgment.**  The team has not said which
  switches count (its log holds the 26-08-2026 one, at 22,510.90 where CBK's results print
  21,816.46, and not the others).  A switch counts only when the analyst has chosen it; it then
  adds CBK's accepted amount and no redemptions, unless the analyst typed another amount, which
  is an analyst input and is compared with CBK's.
* **Nothing is a tolerance.**  Each row is CBK's printed figures.  Second readings are the
  previous release's section C against a T-bill release's redemptions, and the uploaded
  workbook's log row by row; a difference is a "sources disagree" flag on that row.
* **The files are kept and re-checked** (``ResultsCache``): each downloaded PDF is stored under
  the data folder with its sha256.  On every run a cached file is checked against that hash and
  against CBK's current size and modification time; a file CBK has replaced is downloaded again
  and the change is reported, never silently used (CBK re-issued the 26-08-2026 switch results
  as "... Final.pdf" three weeks after the auction).
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

from cytonn_weekly.common.computed import ANALYST, SOURCE, an_input
from cytonn_weekly.common.formatting import NUMBER, TEXT
from cytonn_weekly.common.http import http_get, http_head
from cytonn_weekly.common.review import table_block
from cytonn_weekly.fixed_income import cbk_auctions

SOURCE_NAME = "CBK Treasury bill and bond auction results"
TBILL, PRIMARY, TAP, SWITCH = "tbill", "primary", "tap", "switch"
KINDS = {TBILL: "T-bills", PRIMARY: "T-bonds", TAP: "T-bond tap sale", SWITCH: "T-bond switch"}
ORDER = list(KINDS)

GET_DELAY = 1.0     # seconds between two downloads from centralbank.go.ke
PROBE_DELAY = 0.5   # seconds between two size-and-date checks of files already held
MAX_GAP_DAYS = 9    # T-bills settle weekly (a Monday, or the Tuesday after a holiday); more than this is a missing week

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
            return self._download(url)
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

    {"start", "end", "releases": [...], "warnings": [...]}: each release is its value date, kind
    (tbill, primary, tap, switch), accepted amount and its parts, redemptions (None where the
    results state none), the file's name and sha256, and an ``error`` if it could not be read.
    The first run of a fiscal year downloads every file since 1 July; later runs download only
    what is new (one T-bill file a week, and any bond result) and re-check the rest.
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
    return {"start": start.isoformat(), "end": end.isoformat(), "releases": releases, "warnings": warnings,
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
    return f"{release['value_date']} {KINDS.get(release['kind'], release['kind'])}"


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
    uncounted_switches: list[dict[str, Any]] = field(default_factory=list)
    counted_switches: list[dict[str, Any]] = field(default_factory=list)
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
        ours = [n for n, r in enumerate(releases) if r["value_date"] == day]
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
              switches: Optional[dict[str, dict[str, Any]]] = None,
              workbook_log: Optional[list[dict[str, Any]]] = None,
              cell_source: Callable[[Any], str] = lambda cell: getattr(cell, "source", None) or str(cell.ref)) -> Log:
    """The log from ``fy_start`` to ``limit``: one row per release, the running net, and the net figure's inputs.

    ``switches`` is the analyst's choice per switch, by value date: {"2026-08-26": {"count": True,
    "override": cell or None}}.  No entry, or ``count`` false, and the switch is listed but not
    counted.  ``workbook_log`` is the uploaded workbook's log ([{date, accepted, redemptions}],
    cells, redemptions negative), used only as each row's second reading.
    """
    log = Log(fy_start, limit)
    switches = switches or {}
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

    pairs, left = _match_workbook(kept, [w for w in (workbook_log or []) if fy_start <= w["date"] <= limit])
    running = Decimal(0)
    previous_bill: Optional[dict[str, Any]] = None
    bill_days: list[date] = []
    rounded: list[str] = []
    for n, r in enumerate(kept):
        key, src, when = row_key(r), release_source(r), date.fromisoformat(r["value_date"])
        choice = switches.get(r["value_date"]) or {}
        is_switch = r["kind"] == SWITCH
        counts = bool(choice.get("count")) if is_switch else True
        override = choice.get("override") if is_switch and counts else None
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
        if theirs is not None:
            log.second_sources.append({"row": key, "column": "accepted_kes_m", "source": cell_source(theirs["accepted"]),
                                       "value": theirs["accepted"].number})
            red = theirs["redemptions"].number
            if red is not None and not (r.get("redemptions_kes_m") is None and red == 0):
                log.second_sources.append({"row": key, "column": "redemptions_kes_m", "source": cell_source(theirs["redemptions"]),
                                           "value": abs(red)})
        if not counts:
            log.uncounted_switches.append(r)
            continue

        accepted = _d(r["accepted_kes_m"])
        if override is not None and override.number is not None:
            # The analyst's own amount for a switch: an analyst input, with CBK's printed amount as its second reading.
            name = f"accepted {r['value_date']} switch (typed)"
            log.inputs[name] = an_input(override.number, ANALYST, cell_source(override), decimals=2,
                                        second={"value": r["accepted_kes_m"], "source": src, "origin": SOURCE})
            log.accepted.append(name)
            accepted = _d(override.number)
            row.update(accepted_kes_m=override.number, _origin=ANALYST,
                       _note=(f"Not auto-verified: the amount is an {cell_source(override)}, typed over CBK's printed "
                              f"{_mn(r['accepted_kes_m'])}."))
            row["_derived"].pop("accepted_kes_m")
            log.second_sources = [s for s in log.second_sources if not (s["row"] == key and s["column"] == "accepted_kes_m")]
            log.second_sources.append({"row": key, "column": "accepted_kes_m", "source": src, "value": r["accepted_kes_m"]})
            if theirs is not None:
                log.second_sources.append({"row": key, "column": "accepted_kes_m", "source": cell_source(theirs["accepted"]),
                                           "value": theirs["accepted"].number})
        else:
            for p in r["accepted_parts"]:
                name = f"accepted {r['value_date']} {p['label']}"
                log.inputs[name] = an_input(p["kes_m"], SOURCE, f"{src}, {p['label']}")
                log.accepted.append(name)
        redeemed = r.get("redemptions_kes_m")
        if redeemed is None:
            if not is_switch:
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
        if is_switch:
            log.counted_switches.append(r)
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
        missing = [row_key(r) for n, r in enumerate(kept) if n not in pairs and r["kind"] != SWITCH
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
        "A switch auction is counted only when it is chosen under \"Weekly analyst inputs\".",
    ]
    return block


def switches_listed(switches: list[dict[str, Any]]) -> str:
    """"15-07-2026 (Kshs 7,954.71 mn), 26-08-2026 (Kshs 21,816.46 mn)"."""
    return ", ".join(f"{_day(s['value_date'])} (Kshs {_mn(s['accepted_kes_m'])} mn)" if s.get("accepted_kes_m") is not None
                     else f"{_day(s['value_date'])} (amount not read)" for s in switches)
