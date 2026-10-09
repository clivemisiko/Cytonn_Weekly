"""CBK's daily indicative exchange rate for the US dollar, fetched from centralbank.go.ke.

The Forex page (``/forex/``) shows "Daily KES Exchange Rates" from a server-side data table
(wpDataTables, table id 193) that answers a plain form POST with JSON rows of
``[dd/mm/yyyy, currency, mean]``.  Checked 2026-10-09: it is current to the day and holds
the US dollar back to early 2024, and its 2 October 2026 (129.76), 25 September 2026
(129.62) and 2 January 2026 (129.05) rates equal the fixed income workbook's.

The older table on ``/rates/forex-exchange-rates/`` (id 32) and the "historical data" CSV
both stop in January 2024, so they are not used.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Callable, Optional

import httpx

from cytonn_weekly.common.http import TIMEOUT, USER_AGENT

SOURCE_NAME = "Central Bank of Kenya, Daily KES Exchange Rates"
URL = "https://www.centralbank.go.ke/wp-admin/admin-ajax.php?action=get_wdtable&table_id=193"
PAGE = "https://www.centralbank.go.ke/forex/"
CURRENCY = "US DOLLAR"
ROWS = 520   # about two years of trading days: this year's first rate and last year's first and last

Poster = Callable[[str, dict[str, str]], bytes]


def _post(url: str, data: dict[str, str]) -> bytes:
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=True) as client:
        resp = client.post(url, data=data)
        resp.raise_for_status()
        return resp.content


def _form(rows: int) -> dict[str, str]:
    form = {"draw": "1", "start": "0", "length": str(rows), "order[0][column]": "0", "order[0][dir]": "desc"}
    for n in range(3):
        form[f"columns[{n}][data]"] = str(n)
        form[f"columns[{n}][searchable]"] = "true"
        form[f"columns[{n}][orderable]"] = "true"
    form["columns[1][search][value]"] = CURRENCY
    return form


def parse_rates(payload: bytes) -> dict[date, float]:
    """The table's JSON answer -> {day: KSh per USD}.  Rows of any other currency raise."""
    data = json.loads(payload.decode("utf-8"))
    out: dict[date, float] = {}
    for row in data.get("data") or []:
        day, currency, mean = row[0], row[1], row[2]
        if currency.strip().upper() != CURRENCY:
            raise ValueError(f"CBK's rate table returned {currency!r} where {CURRENCY!r} was asked for")
        out[datetime.strptime(day, "%d/%m/%Y").date()] = float(mean)
    if not out:
        raise ValueError("CBK's rate table returned no US dollar rows")
    return out


def fetch_usd_rates(post: Optional[Poster] = None, rows: int = ROWS) -> dict[date, float]:
    """Every US dollar rate CBK lists, newest first, back about two years."""
    return parse_rates((post or _post)(URL, _form(rows)))
