"""Manual sanity check: run the real Digital Payments fetcher against live Yahoo data.

Not part of pytest.  Run from backend/:
    PYTHONPATH=src python scripts/check_digital_payments_live.py
Forward P/E is Yahoo's forwardPE (consensus basis), fetched fresh every run.
Compare the column against the "Forward P/E" shown on each ticker's Yahoo Finance
quote/statistics page.
"""

from cytonn_weekly.digital_payments.fetcher import average_forward_pe, fetch_digital_payments

rows = fetch_digital_payments()
print(f"{'Company':<24}{'Ticker':<8}{'Price':>10}{'Prior':>10}{'Year Open':>10}{'w/w %':>9}{'YTD %':>9}{'Fwd EPS':>9}{'Fwd P/E':>9}")
for r in rows:
    if r["error"]:
        print(f"{r['company']:<24}{r['ticker']:<8}FAILED: {r['error']}")
        continue
    eps = f"{r['forward_eps']:.2f}" if r["forward_eps"] is not None else "-"
    pe = f"{r['forward_pe']:.2f}" if r["forward_pe"] is not None else "-"
    print(
        f"{r['company']:<24}{r['ticker']:<8}{r['current_price']:>10.2f}"
        f"{r['prior_close']:>10.2f}{r['ytd_open']:>10.2f}"
        f"{r['wow_pct']:>+9.2f}{r['ytd_pct']:>+9.2f}{eps:>9}{pe:>9}"
    )
    print(
        f"{'':<32}dates: price {r['current_price_date']}, "
        f"prior {r['prior_close_date']}, year open {r['ytd_open_date']}, "
        f"P/E source {r['forward_pe_source']}"
    )
    if r["forward_pe_note"]:
        print(f"{'':<32}P/E note: {r['forward_pe_note']}")

avg = average_forward_pe(rows)
n = sum(1 for r in rows if r["forward_pe"] is not None)
print(f"\nAverage forward P/E: {avg} (over {n} of {len(rows)} companies)")
