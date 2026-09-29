"""Manual review: run the real Digital Payments highlights drafter against live data.

Not part of pytest.  Calls the live Anthropic API (web search + tokens, a few
cents) and Yahoo Finance.  Needs ANTHROPIC_API_KEY set.  Run from the repo root:
    PYTHONPATH=src python scripts/check_digital_payments_highlights_live.py
"""

from cytonn_weekly.drafters.digital_payments_highlights import (
    compose_section,
    draft_highlights,
    draft_outlook,
)
from cytonn_weekly.fetchers.digital_payments import fetch_digital_payments

draft = draft_highlights()
table = fetch_digital_payments()
outlook = draft_outlook(draft, table)
section = compose_section(draft, table, outlook)

print(f"Report week: {section['week_start']} to {section['week_end']}")
print(f"Shortfall: {section['shortfall']}\n")

for item in section["items"]:
    if item["kind"] == "highlight":
        print(f"{item['numeral']}. {item['headline_md']}")
        print(f"  company: {item['company']}  |  source: {item['search_scope']} ({item['ir_domain']})\n")
        print(item["body_md"], "\n")
        print(f"  [{len(item['body'].split())} words] links:")
        for l in item["links"]:
            print(f"    - '{l['anchor']}' -> {l['url']} ({l.get('page_age')})")
        print("  claims (span -> exact source):")
        for c in item["claims"]:
            print(f"    - \"{c['text'][:110]}...\"\n      {c['url']}\n      cited: \"{c['cited_text'][:110]}\"")
        for w in item["warnings"]:
            print(f"  ! {w}")
    else:
        print(f"{item['numeral']}. Stock table")
        for r in item["rows"]:
            if r["error"]:
                print(f"    {r['ticker']}: FAILED {r['error']}")
            else:
                print(f"    {r['ticker']:<6}{r['current_price']:>9.2f}  w/w {r['wow_pct']:+.2f}%  YTD {r['ytd_pct']:+.2f}%")
    print("\n" + "-" * 70 + "\n")

print(section["outlook"]["text_md"])
print(f"\n  [{len(section['outlook']['text'].split())} words]  stats: {section['outlook']['stats']}")
if section["warnings"]:
    print("\nSection warnings:")
    for w in section["warnings"]:
        print(f"  ! {w}")
