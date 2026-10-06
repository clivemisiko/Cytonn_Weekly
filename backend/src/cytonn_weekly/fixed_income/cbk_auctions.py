"""CBK primary-auction results for Treasury bills and bonds (public, free).

Free-standing: not wired into a Fixed Income weekly run, which waits on the KCB
email samples (see kcb_email.py).  Once that run exists, these results are the
independent second source for the auction figures the KCB emails report, which
is exactly what the checker's ``extra_sources`` / sources-disagree path is for.

Where the results live (checked 2026-10-02):

* T-bills: centralbank.go.ke/bills-bonds/treasury-bills/ links one PDF per weekly
  auction under /uploads/91_day_historical_treasury_bill_results/, newest first.
* T-bonds: centralbank.go.ke/bills-bonds/treasury-bonds/ links one PDF per
  auction under /uploads/historical_treasury_bond_results/, newest first
  (switch and tap-sale results are listed too, and skipped here).

Both PDFs have a text layer; pdfplumber's table extraction kerns digits apart
("1 6,546.14"), repaired by clean_pdf_number.  Rows are matched on their printed
labels, never on position alone, and a label that is not found leaves that
figure None rather than shifting the rest.
"""

from __future__ import annotations

import io
import re
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Optional
from urllib.parse import urljoin

import pdfplumber

from cytonn_weekly.common.formatting import NUMBER, PCT, TEXT, clean_pdf_number
from cytonn_weekly.common.http import http_get

CBK = "https://www.centralbank.go.ke"
TBILL_LISTING = f"{CBK}/bills-bonds/treasury-bills/"
TBOND_LISTING = f"{CBK}/bills-bonds/treasury-bonds/"

Getter = Callable[[str], bytes]

# Units and precision follow Cytonn Weekly #38.2026 (published 2026-09-27, still the newest
# issue on 2026-10-02), which reports this very auction (cbk_tbill_2026-09-28.pdf) in prose:
#   amounts in KES bn, 1 dp: "bids of Kshs 17.7 bn against the offered Kshs 8.0 bn" (CBK:
#     17,739.93 / 8,000.00 m); "accepted a total of Kshs 33.4 bn worth of bids out of Kshs
#     41.7 bn bids received" (CBK: 33,350.22 / 41,724.28 m).  CBK prints KES m; the parser
#     converts, so the stored value is already in the displayed unit.
#   subscription 1 dp: "translating to a subscription rate of 221.7%".  That is bids/offered
#     unrounded (221.749%), NOT CBK's printed performance rate (221.75, which half-up rounds
#     to 221.8%): rounding CBK's already-rounded figure double-rounds.  So subscription is
#     derived from the bids and the offer, never read from the performance-rate row.
#   yields 2 dp: "the yields on the 182-day decreased the most by 1.5 bps to 8.89% from 8.91%"
#     (CBK: 8.8949 / 8.9099).  NOTE, deliberate: the source itself varies.  The same issue
#     gives the 91-day "from 8.78%" in the auction paragraph and "from 8.8%" in the money
#     market paragraph.  That is the report's own inconsistency, not a bug here; 2 dp is
#     used throughout because it is never wrong to show the precision the source sometimes
#     drops.  Don't "fix" this to 1 dp.
#   coupons 1 dp: "FXD1/2019/020 has a fixed coupon rate of 12.9%" (CBK: 12.8730), and
#     "FXD3/2019/015 has a fixed coupon rate of 12.3%"; the offer: "seeking to raise Kshs
#     50.0 bn".  The issue prints no bond-auction results, so bond amounts and yields follow
#     the T-bill conventions above.
TBILL_COLUMNS = [
    {"key": "tenor", "label": "Tenor", "fmt": TEXT},
    {"key": "offered_kes_bn", "label": "Offered (KES bn)", "fmt": NUMBER, "decimals": 1},
    {"key": "bids_kes_bn", "label": "Bids (KES bn)", "fmt": NUMBER, "decimals": 1},
    {"key": "subscription_pct", "label": "Subscription", "fmt": PCT, "decimals": 1},
    {"key": "accepted_kes_bn", "label": "Accepted (KES bn)", "fmt": NUMBER, "decimals": 1},
    {"key": "avg_rate_pct", "label": "Average rate", "fmt": PCT, "decimals": 2},
    {"key": "prior_avg_rate_pct", "label": "Last auction", "fmt": PCT, "decimals": 2},
]

TBOND_COLUMNS = [
    {"key": "issue", "label": "Issue", "fmt": TEXT},
    {"key": "tenor", "label": "Tenor", "fmt": TEXT},
    {"key": "bids_kes_bn", "label": "Bids (KES bn)", "fmt": NUMBER, "decimals": 1},
    {"key": "subscription_pct", "label": "Subscription", "fmt": PCT, "decimals": 1},
    {"key": "accepted_kes_bn", "label": "Accepted (KES bn)", "fmt": NUMBER, "decimals": 1},
    {"key": "avg_rate_pct", "label": "Average rate", "fmt": PCT, "decimals": 2},
    {"key": "coupon_pct", "label": "Coupon", "fmt": PCT, "decimals": 1},
]

TENORS = ("91-day", "182-day", "364-day")


def _key(label: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (label or "").lower())


def _labelled_rows(tables: list[list[list[Optional[str]]]]) -> dict[str, list[Optional[str]]]:
    """{normalized label: the cells after it} across every table (first occurrence wins)."""
    out: dict[str, list[Optional[str]]] = {}
    for table in tables:
        for row in table:
            cells = list(row or [])
            for i, cell in enumerate(cells[:2]):
                if cell and str(cell).strip():
                    out.setdefault(_key(str(cell)), cells[i + 1:])
                    break
    return out


def _find(rows: dict[str, list[Optional[str]]], *prefixes: str) -> list[Optional[str]]:
    for p in prefixes:
        for k, v in rows.items():
            if k.startswith(p):
                return v
    return []


def _num(cells: list[Optional[str]], i: int) -> Optional[float]:
    try:
        return clean_pdf_number(cells[i]) if i < len(cells) else None
    except ArithmeticError:
        return None


def _bn(kes_m: Optional[float]) -> Optional[float]:
    """KES m as CBK prints it -> KES bn (Decimal, so no float noise lands on a rounding boundary)."""
    return None if kes_m is None else float(Decimal(repr(kes_m)) / 1000)


def _subscription(bids_kes_m: Optional[float], offered_kes_m: Optional[float]) -> Optional[float]:
    """Bids as a % of the offer, unrounded (see the conventions comment above TBILL_COLUMNS)."""
    if bids_kes_m is None or not offered_kes_m:
        return None
    return float(Decimal(repr(bids_kes_m)) * 100 / Decimal(repr(offered_kes_m)))


def latest_pdf_links(listing_html: str, folder: str) -> list[str]:
    """Absolute URLs of result PDFs under ``folder`` in page order (newest first on CBK's pages)."""
    hrefs = re.findall(r'href=["\']([^"\']*' + re.escape(folder) + r'/[^"\']+\.pdf)["\']', listing_html, flags=re.I)
    seen, out = set(), []
    for h in hrefs:
        url = urljoin(CBK + "/", h.replace("//uploads", "/uploads"))
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _tables_and_text(pdf_bytes: bytes) -> tuple[list, str]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return [t for p in pdf.pages for t in p.extract_tables()], "\n".join(p.extract_text() or "" for p in pdf.pages)


def _dated(text: str) -> Optional[str]:
    m = re.search(r"DATED\s+(\d{2})/(\d{2})/(\d{4})", text or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def parse_tbill_results(tables: list, text: str = "") -> dict[str, Any]:
    """One row per tenor (91/182/364-day) from a T-bill results PDF's tables."""
    rows = _labelled_rows(tables)
    offered = _find(rows, "amountoffered")
    bids = _find(rows, "bidsreceived")
    accepted = _find(rows, "totalamountaccepted")
    avg = _find(rows, "weightedaverageinterestrateofaccepted")
    comparative = {t: _find(rows, t.replace("-", "")) for t in ("91day", "182day", "364day")}
    out = []
    for i, tenor in enumerate(TENORS):
        comp = comparative[("91day", "182day", "364day")[i]]
        row = {
            "tenor": tenor, "offered_kes_bn": _bn(_num(offered, i)), "bids_kes_bn": _bn(_num(bids, i)),
            "subscription_pct": _subscription(_num(bids, i), _num(offered, i)), "accepted_kes_bn": _bn(_num(accepted, i)),
            "avg_rate_pct": _num(avg, i), "prior_avg_rate_pct": _num(comp, 1), "error": None,
        }
        if row["avg_rate_pct"] is None:
            row["error"] = f"{tenor} average rate not found in the results PDF"
        out.append(row)
    return {"auction_date": _dated(text), "rows": out}


_BOND_CODE = re.compile(r"^[A-Z]{2,4}\d?/\d{4}/\d{2,3}$")
_TO_MATURITY = re.compile(r"\(([\d.]+)\s*years?\s+to\s+maturity\)", re.I)


def _years_to_maturity(tenor: Optional[str]) -> Optional[float]:
    """CBK prints a reopened bond's remaining life in its tenor cell: "Twenty (12.6 years to maturity)"."""
    m = _TO_MATURITY.search(tenor or "")
    return float(m.group(1)) if m else None


def parse_tbond_results(tables: list, text: str = "") -> dict[str, Any]:
    """One row per bond issue from a T-bond results PDF's tables, plus the auction totals.

    Three layouts are in use: most results print an ISSUE NUMBER row and a TENOR row
    ("Twenty (12.6 years to maturity)"); some (13-07-2026) print the issue numbers in the
    TENOR row and no remaining life; tap sales (25-08-2025) print the issue numbers in a
    Tenor row too, and label the offer "Total Advertised Amount", the accepted amount "Total
    Bids Accepted at Cost" and the rate "Allocated average rate".  ``years_to_maturity`` is None
    there rather than derived from the due date (CBK's own figure is not the plain date gap:
    FXD1/2026/030 is "29.6 years to maturity" on 21-09-2026 though it falls due 13-Mar-2056).
    """
    rows = _labelled_rows(tables)
    issues = [c for c in _find(rows, "issuenumber") if c and str(c).strip()]
    tenors = _find(rows, "tenor")
    if not issues:
        coded = [c for c in tenors if c and _BOND_CODE.match(" ".join(str(c).split()))]
        if coded:
            issues, tenors = coded, []
    bids = _find(rows, "totalbidsreceived")
    accepted = _find(rows, "amountaccepted", "totalbidsacceptedatcost")
    avg = _find(rows, "weightedaveragerateofaccepted", "allocatedaveragerate")
    coupon = _find(rows, "couponrate")
    # One offer covers every issue in the auction (printed once, in the total column), and
    # CBK's per-issue performance rate is that issue's bids over it (43,803.82 / 60,000.00
    # = 73.006%, printed 73.01); derived here unrounded for the same double-rounding reason.
    offered = [c for c in _find(rows, "totalamountoffered", "totaladvertisedamount") if c and str(c).strip()]
    total_offered = clean_pdf_number(offered[-1]) if offered else None
    out = []
    for i, issue in enumerate(issues):
        tenor = " ".join(str(tenors[i]).split()) if i < len(tenors) and tenors[i] else None
        row = {
            "issue": " ".join(str(issue).split()), "tenor": tenor,
            "bids_kes_bn": _bn(_num(bids, i)), "subscription_pct": _subscription(_num(bids, i), total_offered),
            "accepted_kes_bn": _bn(_num(accepted, i)), "avg_rate_pct": _num(avg, i), "coupon_pct": _num(coupon, i),
            "years_to_maturity": _years_to_maturity(tenor), "acceptance_pct": _subscription(_num(accepted, i), _num(bids, i)),
            "error": None,
        }
        if row["avg_rate_pct"] is None:
            row["error"] = f"{row['issue']} average rate not found in the results PDF"
        out.append(row)
    return {
        "auction_date": _dated(text) or _dated(text.replace("\n", " ")),
        "total_offered_kes_bn": _bn(total_offered),
        "total_subscription_pct": _subscription(_num(bids, len(issues)), total_offered),
        "rows": out,
    }


_LINK_DATE = re.compile(r"DATED\s+(\d{2})-(\d{2})-(\d{4})", re.I)


def link_value_date(url: str) -> Optional[date]:
    """The value date CBK puts in a results PDF's file name ("... DATED 21-09-2026.pdf")."""
    m = _LINK_DATE.search(url.replace("%20", " "))
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def link_kind(url: str) -> str:
    """``switch``, ``tap`` (a tap sale) or ``primary``, from the results PDF's file name."""
    name = url.rsplit("/", 1)[-1].upper()
    return "switch" if "SWITCH" in name else "tap" if "TAP" in name.replace(" ", "") else "primary"


def fetch_period_tbonds(start: date, end: date, get: Getter = http_get) -> dict[str, Any]:
    """Every T-bond auction (primary, tap sale or switch) with a value date in ``start``..``end``, newest first.

    This is what the Markets Reviews' "Bond Issuances in <period>" table reports (checked
    against Q1'2026, H1'2026 and Q3'2026; periodic/fixed_income.py says which kinds each
    part of the table counts).  Each auction is the parsed PDF plus ``url``, ``kind`` and
    ``value_date``; one whose PDF cannot be read keeps its place with an ``error`` instead
    of vanishing.
    """
    links = latest_pdf_links(get(TBOND_LISTING).decode("utf-8", errors="replace"), "historical_treasury_bond_results")
    auctions: list[dict[str, Any]] = []
    for url in links:
        when, kind = link_value_date(url), link_kind(url)
        if when is None or not start <= when <= end:
            continue
        auction: dict[str, Any] = {"url": url, "kind": kind, "value_date": when.isoformat()}
        try:
            tables, text = _tables_and_text(get(url))
            auction.update(parse_tbond_results(tables, text), error=None)
            if not auction["rows"]:
                auction["error"] = "no bond rows recognised in the results PDF"
        except Exception as exc:  # noqa: BLE001 - one unreadable PDF must not hide the others
            auction.update(rows=[], total_offered_kes_bn=None, error=f"{type(exc).__name__}: {exc}")
        auctions.append(auction)
    auctions.sort(key=lambda a: a["value_date"], reverse=True)
    return {"listing_url": TBOND_LISTING, "start": start.isoformat(), "end": end.isoformat(), "auctions": auctions}


def fetch_latest_tbill_results(get: Getter = http_get) -> dict[str, Any]:
    """The newest T-bill auction's results.  Raises LookupError if the listing links no results PDF."""
    links = latest_pdf_links(get(TBILL_LISTING).decode("utf-8", errors="replace"), "91_day_historical_treasury_bill_results")
    if not links:
        raise LookupError(f"no T-bill results PDF linked from {TBILL_LISTING}")
    tables, text = _tables_and_text(get(links[0]))
    return {"source_url": links[0], **parse_tbill_results(tables, text)}


def fetch_latest_tbond_results(get: Getter = http_get) -> dict[str, Any]:
    """The newest primary T-bond auction's results (switch and tap-sale results skipped)."""
    links = [u for u in latest_pdf_links(get(TBOND_LISTING).decode("utf-8", errors="replace"), "historical_treasury_bond_results")
             if not re.search(r"SWITCH|TAP", u, re.I)]
    if not links:
        raise LookupError(f"no T-bond results PDF linked from {TBOND_LISTING}")
    tables, text = _tables_and_text(get(links[0]))
    return {"source_url": links[0], **parse_tbond_results(tables, text)}
