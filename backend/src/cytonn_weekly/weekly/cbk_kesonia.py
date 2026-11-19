from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from cytonn_weekly.weekly.cbk_rates import Poster, _post

SOURCE_NAME = "Central Bank of Kenya, KESONIA"
PAGE = "https://www.centralbank.go.ke/kesonia/"
URL = "https://www.centralbank.go.ke/wp-admin/admin-ajax.php?action=get_wdtable&table_id=194"
ROWS = 60   # newest first: the two weeks the Liquidity paragraph compares, with room for holidays


def _form(rows: int) -> dict[str, str]:
    form = {"draw": "1", "start": "0", "length": str(rows), "order[0][column]": "0", "order[0][dir]": "desc"}
    for n in range(2):
        form[f"columns[{n}][data]"] = str(n)
        form[f"columns[{n}][searchable]"] = "true"
        form[f"columns[{n}][orderable]"] = "true"
    return form


def parse_rates(payload: bytes) -> dict[date, str]:
    """The table's JSON answer -> {day: rate as CBK prints it, percent}.  Any other shape raises ValueError."""
    try:
        rows = json.loads(payload.decode("utf-8"))["data"]
        out = {datetime.strptime(day, "%d/%m/%Y").date(): str(Decimal(str(rate).strip())) for day, rate in rows}
    except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
        raise ValueError(f"CBK's KESONIA table is not in the shape this tool reads ({type(exc).__name__})") from None
    if not out:
        raise ValueError("CBK's KESONIA table returned no rows")
    return out


def fetch_rates(post: Optional[Poster] = None, rows: int = ROWS) -> tuple[dict[date, str], str]:
    """The newest KESONIA rates and the sha256 of the answer they were read from."""
    body = (post or _post)(URL, _form(rows))
    return parse_rates(body), hashlib.sha256(body).hexdigest()
