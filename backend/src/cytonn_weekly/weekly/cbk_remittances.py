from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional

from cytonn_weekly.common.http import http_get

SOURCE_NAME = "Central Bank of Kenya, diaspora remittances"
PAGE = "https://www.centralbank.go.ke/diaspora-remittances/"
TOTAL = "Total Remittances (USD '000)"   # the unit is part of the header: a page that changes it is refused, not converted

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.S)


def _text(cell: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", "", cell).replace("&#039;", "'").replace("&amp;", "&").split())


def parse_months(html: str) -> dict[str, tuple[Decimal, Decimal]]:
    """The page's table -> {"2026-08": (North America, total), ...}, both in USD thousands as CBK prints them.

    A page without the table, with other columns or another unit, or with a cell that is not a number raises ValueError.
    """
    try:
        head = html[html.index("<thead"):html.index("</thead>")]
        columns = [_text(c) for c in _CELL.findall(_ROW.search(head).group(1))]
        at = {name: columns.index(name) for name in ("Year", "Month", "North America", TOTAL)}
        body = html[html.index("<tbody"):html.index("</tbody>")]
        out: dict[str, tuple[Decimal, Decimal]] = {}
        for row in _ROW.findall(body):
            cells = [_text(c) for c in _CELL.findall(row)]
            money = [Decimal(cells[at[k]].replace(",", "")) for k in ("North America", TOTAL)]
            out[f"{int(cells[at['Year']]):04d}-{int(cells[at['Month']]):02d}"] = (money[0], money[1])
    except (ValueError, AttributeError, IndexError, InvalidOperation):
        raise ValueError("CBK's diaspora remittances page is not in the shape this tool reads") from None
    if not out:
        raise ValueError("CBK's diaspora remittances page has no months")
    return out


def fetch_months(get: Optional[Callable[[str], bytes]] = None) -> tuple[dict[str, tuple[Decimal, Decimal]], str]:
    """Every month CBK lists, and the sha256 of the page they were read from."""
    body = (get or http_get)(PAGE)
    return parse_months(body.decode("utf-8", errors="replace")), hashlib.sha256(body).hexdigest()
