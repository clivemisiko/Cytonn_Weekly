"""Bond maturities, from the "Issues of Treasury Bonds" table on CBK's treasury-bonds page.

CBK prints a bond redemption only in the results of a bond auction that settles the same day
(fixed_income/net_borrowing.py).  A bond that matures on a day with no bond auction is therefore
on no result file, and the net domestic borrowing log would pass over it.  First case seen:
IFB1/2014/12 matures on 12 October 2026 (face at issue 15,420.55 mn; how much is still
outstanding is not printed anywhere the tool reads) and no bond auction settles that day.

This module reads the table only to know *when* something matures, so the log can ask about it.
It never supplies a redemption amount.

What the table is (read 2026-10-12):

* It sits in the page's third tab, under the heading "Issues of Treasury Bonds": one row per
  issue or reopening, with Issue Date, Issue No, ISIN Number, Tenor, Face Value (Kshs
  Millions), Maturity Date, Coupon Rate, Redemption Yield.  The whole table is in the page's
  HTML (no further request), so it comes with the listing the bond results are already fetched
  from: no extra request is made for it.
* **It is incomplete**: 333 rows, and its issue dates stop at 6 April 2026.  Reopenings and tap
  sales are missing for some bonds, so the face value summed per bond and maturity date is a
  **floor**, not the amount issued (FXD1/2016/10, maturing 17-08-2026, adds to 103,380.70 mn here
  while the results of that day print 118,137.00 mn of redemptions).  And it is face at issue,
  not the amount outstanding at maturity, which the team reads on the NSE Implied Yields sheet
  (IFB1/2014/12: 15,420.55 mn here, 16,631.48 mn outstanding there).  Hence the wording "CBK's
  table shows <face> mn, the face value at issue, which is only a floor".
* **Some rows are wrong.**  ``KNOWN_WRONG_ROWS`` below lists each one found, with the reason; a
  row on it never raises the maturity question.  Nothing else is ever hidden.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

HEADING = "Issues of Treasury Bonds"
SOURCE_NAME = "CBK, Issues of Treasury Bonds"
CACHE_FILE = "bond_issues.json"

# Rows of CBK's table that are known to be wrong, by (Issue No, Maturity Date as printed) -> why.
# Keep this short and documented: a row goes here only when another CBK source shows it is wrong.
KNOWN_WRONG_ROWS: dict[tuple[str, str], str] = {
    ("IFB1/2023/007", "15/07/2026"): (
        "the table gives this row a maturity of 15/07/2026, three years into a seven-year bond issued on 19/06/2023; "
        "the outstanding bond stock in the CBK Weekly Bulletin did not fall that week, and no result file carries a "
        "redemption for it"),
}

_TAG = re.compile(r"<[^>]+>")
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_DMY = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


class IssuesTableError(LookupError):
    """The table could not be found or read on the page."""


def table_html(page: str) -> str:
    """The table's own HTML: the first <table> after the "Issues of Treasury Bonds" heading."""
    heading = re.search(r"<h\d[^>]*>\s*" + re.escape(HEADING) + r"\s*</h\d>", page, re.I)
    if heading is None:
        raise IssuesTableError(f"the heading '{HEADING}' is not on the page")
    start = page.find("<table", heading.end())
    end = page.find("</table>", start)
    if start < 0 or end < 0:
        raise IssuesTableError(f"no table follows the heading '{HEADING}'")
    return page[start:end + len("</table>")]


def _iso(text: str) -> Optional[str]:
    m = _DMY.match(text)
    if m is None:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def parse_issues(page: str) -> list[dict[str, Any]]:
    """Every row of the table: {issue_date, issue, isin, face_kes_m, maturity_date, maturity_printed}.

    Columns are found by their printed headings, never by position.  A row whose maturity date
    or face value cannot be read is left out (the table is only ever a prompt to look).
    """
    rows = [[html.unescape(_TAG.sub("", c)).strip() for c in _CELL.findall(r)] for r in _ROW.findall(table_html(page))]
    head = next((r for r in rows if any(c.lower().startswith("maturity date") for c in r)), None)
    if head is None:
        raise IssuesTableError(f"'{HEADING}' has no 'Maturity Date' column")

    def col(*names: str) -> int:
        for n, cell in enumerate(head):
            if cell.lower().startswith(names):
                return n
        raise IssuesTableError(f"'{HEADING}' has no '{names[0].title()}' column")

    issue, face, maturity, isin, issued = col("issue no"), col("face value"), col("maturity date"), col("isin"), col("issue date")
    out = []
    for r in rows:
        if r == head or len(r) != len(head):
            continue
        day = _iso(r[maturity])
        try:
            amount = float(Decimal(r[face].replace(",", "")))
        except ArithmeticError:
            continue
        if day is None or not r[issue]:
            continue
        out.append({"issue_date": _iso(r[issued]), "issue": r[issue], "isin": r[isin], "face_kes_m": amount,
                    "maturity_date": day, "maturity_printed": r[maturity]})
    if not out:
        raise IssuesTableError(f"'{HEADING}' has no readable row")
    return out


def _name(issue: str) -> str:
    """"FXD1/2010/10(R1)" is a reopening of FXD1/2010/10."""
    return re.sub(r"\s*\(.*\)\s*$", "", issue).strip()


def maturities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Face value summed per bond and maturity date, oldest first: [{date, bond, face_kes_m, issues}].

    A bond is its ISIN (the table writes one bond as FXD1/2016/10 and as FXD1/2016/010); it is
    named as its first row names it.  Rows on ``KNOWN_WRONG_ROWS`` are left out.  **The total is a
    floor** (see the module's note): the table lacks rows.
    """
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        if (r["issue"], r["maturity_printed"]) in KNOWN_WRONG_ROWS or (_name(r["issue"]), r["maturity_printed"]) in KNOWN_WRONG_ROWS:
            continue
        key = (r["maturity_date"], r["isin"] or _name(r["issue"]))
        found = grouped.setdefault(key, {"date": r["maturity_date"], "bond": _name(r["issue"]), "face": Decimal(0), "issues": 0})
        found["face"] += Decimal(repr(r["face_kes_m"]))
        found["issues"] += 1
    return [{"date": g["date"], "bond": g["bond"], "face_kes_m": float(g["face"]), "issues": g["issues"]}
            for _, g in sorted(grouped.items())]


def read_maturities(page: Optional[bytes], folder: Path) -> dict[str, Any]:
    """The maturities from the page just fetched, kept under ``folder`` with the table's sha256.

    {"maturities": [...] or None, "sha256", "fetched_at", "warnings": [...]}.  The table as read
    is kept in ``bond_issues.json``; when this run's page has no readable table (or there is no
    page), the kept reading is used and a warning says from when.  With neither, ``maturities``
    is None and the warning says the maturity check was not made.
    """
    path = Path(folder) / CACHE_FILE
    problem = "CBK's treasury-bonds page was not fetched"
    if page is not None:
        try:
            text = page.decode("utf-8", errors="replace")
            digest = hashlib.sha256(table_html(text).encode("utf-8")).hexdigest()
            rows = parse_issues(text)
            kept = {"sha256": digest, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": rows}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(kept, indent=1, sort_keys=True), encoding="utf-8")
            return {"maturities": maturities(rows), "sha256": digest, "fetched_at": kept["fetched_at"], "warnings": []}
        except IssuesTableError as exc:
            problem = str(exc)
    if path.is_file():
        try:
            kept = json.loads(path.read_text(encoding="utf-8"))
            return {"maturities": maturities(kept["rows"]), "sha256": kept.get("sha256"), "fetched_at": kept.get("fetched_at"),
                    "warnings": [f"{SOURCE_NAME}: {problem} this run; the table as read on "
                                 f"{str(kept.get('fetched_at', ''))[:10]} is used for the bond maturity check."]}
        except (ValueError, KeyError, TypeError):
            pass
    return {"maturities": None, "sha256": None, "fetched_at": None,
            "warnings": [f"{SOURCE_NAME}: {problem}, so bond maturities with no redemption on a result file were not "
                         "looked for this run."]}
