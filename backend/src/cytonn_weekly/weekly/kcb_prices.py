from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

# KCB ticker -> the row's name in column A of 'Market PE & Dividend Yield', in the sheet's order (13 Nov 2026 workbook).
# One explicit entry per security, matched exactly after spaces are collapsed.  The sheet's 'NSE' and 'Mumias' rows have no
# KCB ticker (KCB's report does not list them), so they have no entry and are flagged blank every week.
MARKET_PE = {
    "SCOM": "Safaricom", "EQTY": "Equity Group", "KCB": "KCB", "EABL": "EABL", "COOP": "Co-operative", "ABSA": "ABSA Bank",
    "SCBK": "Standard Chartered", "BAT": "BAT", "IMH": "I&M Holdings", "SBIC": "Stanbic", "KEGN": "KenGen", "DTK": "DTBK",
    "BAMB": "Bamburi", "JUB": "Jubilee", "NCBA": "NCBA", "BRIT": "Britam", "CTUM": "Centum", "BKG": "BK Group",
    "KQ": "Kenya Airways", "KNRE": "Kenya Re", "SCAN": "WPP Scangroup", "CIC": "CIC", "NMG": "NMG", "KUKZ": "Kakuzi",
    "KPLC": "KPLC", "LBTY": "Liberty", "TOTL": "Total Energies", "CRWN": "Crown Berger Paint", "SASN": "Sasini",
    "TPSE": "TPS Eastern Africa", "SLAM": "Sanlam Allianz", "UNGA": "Unga", "WTK": "Williamson Tea", "HFCK": "HFCB Group",
    "CARB": "Carbacid", "SGL": "Standard Group", "LKL": "Longhorn Publishers", "PORT": "E.A Portland Cement", "BOC": "BOC Kenya",
    "LIMT": "Limuru Tea", "CGEN": "Car and General", "TCL": "Trans-Century", "SMER": "Sameer", "CABL": "EA Cables",
    "KAPC": "Kapchorua Tea", "EGAD": "Eaagads", "EVRD": "Eveready", "HAFR": "Home Afrika", "XPRS": "Express Ltd",
    "AMAC": "Africa Mega Agricorp", "KURV": "Kurwitu", "UCHM": "Uchumi", "OCH": "Olympia", "FTGH": "Flame Tree",
    "NBV": "Nrb Bsn Ventures", "HBE": "HomeBoyz Africa", "UMME": "Umeme Ltd", "SKL": "Shri Krishana Overseas Plc", "KPC": "KPC",
    "FMLY": "Family Bank",
}

# KCB ticker -> the ticker in column P of 'Gainers & Losers', in the sheet's order.  Two differ from KCB's.
LARGE_CAPS = {"SCOM": "SCOM", "EABL": "EABL", "EQTY": "EQTY", "KCB": "KCB", "COOP": "COOP", "BAT": "BAT", "BAMB": "BAMB",
              "ABSA": "ABSA", "SCBK": "SCBK", "DTK": "DTBK", "NCBA": "NCBA", "SBIC": "STANBIC"}


def _norm(name: Any) -> str:
    return " ".join(str(name).split())


def fill(rows: Optional[list[str]], prices: dict[str, Any], mapping: dict[str, str], name_unused: bool = False) -> tuple[list[list[Any]], list[str]]:
    """[[row name, price or None]] in `rows`' order (the map's own order when None), and one flag per row left blank or KCB name unused.

    `prices` is {KCB ticker: price} for one day.  Nothing is guessed: a row with no entry, two entries or no price stays blank."""
    by_row: dict[str, list[str]] = defaultdict(list)
    for ticker, row in mapping.items():
        by_row[_norm(row)].append(ticker)
    out, flags = [], []
    for row in (list(mapping.values()) if rows is None else rows):
        tickers, price = by_row.get(_norm(row), []), None
        if not tickers:
            flags.append(f"{_norm(row)}: no KCB ticker is mapped to this row, left blank")
        elif len(tickers) > 1:
            flags.append(f"{_norm(row)}: {len(tickers)} KCB tickers ({', '.join(tickers)}) map to this row, left blank")
        elif (price := prices.get(tickers[0])) is None:
            flags.append(f"{_norm(row)}: KCB's report has no price for {tickers[0]}, left blank")
        out.append([_norm(row), price])
    unused = sorted(set(prices) - set(mapping))
    if unused and name_unused:
        flags.append(f"KCB tickers with no row in the map: {', '.join(unused)}")
    return out, flags
