"""Manual sanity check: run the real Digital Payments fetcher against live Yahoo data.

Not part of pytest.  Run from the repo root:
    python scripts/check_digital_payments_live.py
"""

from cytonn_weekly.fetchers.digital_payments import fetch_digital_payments

rows = fetch_digital_payments()
print(f"{'Company':<24}{'Ticker':<8}{'Price':>10}{'Prior':>10}{'YTD open':>10}{'w/w %':>9}{'YTD %':>9}")
for r in rows:
    if r["error"]:
        print(f"{r['company']:<24}{r['ticker']:<8}FAILED: {r['error']}")
        continue
    print(
        f"{r['company']:<24}{r['ticker']:<8}{r['current_price']:>10.2f}"
        f"{r['prior_close']:>10.2f}{r['ytd_open']:>10.2f}"
        f"{r['wow_pct']:>+9.2f}{r['ytd_pct']:>+9.2f}"
    )
    print(
        f"{'':<32}dates: price {r['current_price_date']}, "
        f"prior {r['prior_close_date']}, ytd open {r['ytd_open_date']}"
    )
