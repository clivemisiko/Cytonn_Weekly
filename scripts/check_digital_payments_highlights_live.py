"""Manual review: run the real Weekly Highlights drafter against the live Anthropic API.

Not part of pytest.  Costs a few cents (web search + tokens).  Needs
ANTHROPIC_API_KEY set.  Run from the repo root:
    PYTHONPATH=src python scripts/check_digital_payments_highlights_live.py
"""

from cytonn_weekly.drafters.digital_payments_highlights import draft_weekly_highlights

highlights = draft_weekly_highlights()
print(f"{len(highlights)} highlights\n")
for i, h in enumerate(highlights, 1):
    print(f"[{i}] {h['title']}\n")
    print(h["body"], "\n")
    print(f"  {len(h['citations'])} citation(s):")
    for c in h["citations"]:
        print(f"  - {c['title']}\n    {c['url']}\n    \"{c['cited_text']}\"")
    print("\n" + "-" * 70 + "\n")
