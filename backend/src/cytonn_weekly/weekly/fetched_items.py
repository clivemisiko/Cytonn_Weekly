from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from decimal import Decimal

from cytonn_weekly.weekly import cbk_kesonia, cbk_remittances
from cytonn_weekly.weekly.week import Week, closures

Fetched = tuple[list[dict[str, str]], str]   # the form table's rows, and the note kept with them: source, address, day, sha256


def _note(source: str, url: str, today: date, sha: str) -> str:
    return f"{source}, {url}, fetched {today.isoformat()}, sha256 {sha}"


def interbank(week: Week, today: date, post: Optional[Any] = None) -> Fetched:
    first = week.previous.previous_friday   # the two weeks the Liquidity paragraph compares, Friday to Thursday
    days = [d for n in range((week.thursday - first).days + 1) if (d := first + timedelta(n)).weekday() < 5 and d not in closures()]
    rates, sha = cbk_kesonia.fetch_rates(post)
    missing = [d for d in days if d not in rates]
    if missing:
        raise LookupError(f"CBK's KESONIA table has no rate yet for {', '.join(d.isoformat() for d in missing)}")
    return [{"date": d.isoformat(), "rate": rates[d]} for d in days], _note(cbk_kesonia.SOURCE_NAME, cbk_kesonia.PAGE, today, sha)


def _mn(thousands: Decimal) -> str:
    return format((thousands / 1000).normalize(), "f")   # exact: USD thousands to USD million, no rounding


def remittances(week: Week, today: date, get: Optional[Any] = None) -> Fetched:
    months, sha = cbk_remittances.fetch_months(get)
    keys = sorted((m for m in months if m <= week.ending.strftime("%Y-%m")), reverse=True)[:24]
    index = [int(m[:4]) * 12 + int(m[5:]) for m in keys]
    if len(keys) < 24 or any(a - b != 1 for a, b in zip(index, index[1:])):
        raise ValueError("CBK's diaspora remittances page does not list 24 months in a row up to this week")
    rows = [{"month": m, "total": _mn(months[m][1]), **({"north_america": _mn(months[m][0])} if months[m][0] else {})} for m in keys]
    return rows, _note(cbk_remittances.SOURCE_NAME, cbk_remittances.PAGE, today, sha)


FETCHERS = {"interbank": interbank, "remittances": remittances}


def fetch(key: str, week: Week, today: Optional[date] = None) -> Fetched:
    return FETCHERS[key](week, today or date.today())
