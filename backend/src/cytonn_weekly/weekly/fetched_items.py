from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from decimal import Decimal

from cytonn_weekly.common.http import http_get
from cytonn_weekly.weekly import cbk_eurobond_opens, cbk_kesonia, cbk_remittances
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


def eurobond_yields(week: Week, today: date, get: Any = http_get) -> Fetched:
    seen: dict[str, bytes] = {}

    def once(url: str) -> bytes:   # the year's and the month's opening are often in the same issue
        if url not in seen:
            seen[url] = get(url)
        return seen[url]

    picks = [("year_open", week.as_at.year, 1, 8), ("month_open", week.thursday.year, week.thursday.month, 7)]
    rows, urls, shas = [], [], []
    for row, year, month, cap in picks:
        try:
            day, yields, url, sha = cbk_eurobond_opens.opening(year, month, cap, week.ending, once)
        except LookupError as exc:
            raise LookupError(f"the {'year' if row == 'year_open' else 'month'}'s first day: {exc}") from None
        rows.append({"row": row, "date": day.isoformat(), **yields})
        urls += [url] * (url not in urls)
        shas += [sha] * (sha not in shas)
    return rows, _note(cbk_eurobond_opens.SOURCE_NAME, " and ".join(urls), today, " and ".join(shas))


FETCHERS = {"interbank": interbank, "remittances": remittances, "eurobond_yields": eurobond_yields}


def fetch(key: str, week: Week, today: Optional[date] = None) -> Fetched:
    return FETCHERS[key](week, today or date.today())
