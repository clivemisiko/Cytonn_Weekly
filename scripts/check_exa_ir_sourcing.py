"""TEMPORARY, THROWAWAY sourcing check - not part of the permanent pipeline.

Purpose: eyeball whether an "investor-relations site first, general search as
fallback" design actually finds usable recent news per company, using Exa.
No drafting, no LLM calls, no citation logic - it only prints what Exa returns.
Delete this file once the sourcing question is settled.

Requirements: plain `requests` only (already installed as a transitive
dependency of the project; no changes to pyproject.toml).  If you'd rather use
the SDK instead, `pip install exa-py` would work, but is not needed here.

Run from the repo root, with your key in the environment:
    EXA_API_KEY=... python scripts/check_exa_ir_sourcing.py [days]
`days` is the look-back window (default 8, i.e. within the 7-10 day range).
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import requests

EXA_URL = "https://api.exa.ai/search"
NUM_RESULTS = 5
EXCERPT_CHARS = 300

# Priority order matches the highlights drafter.
COMPANIES = [
    ("Visa", "investor.visa.com"),
    ("Mastercard", "investor.mastercard.com"),
    ("American Express", "ir.americanexpress.com"),
    ("PayPal", "investor.pypl.com"),
    ("Circle", "investor.circle.com"),
]


def exa_search(api_key, query, start_date, include_domains=None):
    body = {
        "query": query,
        "numResults": NUM_RESULTS,
        "startPublishedDate": start_date,
        "contents": {"text": {"maxCharacters": EXCERPT_CHARS}},
    }
    if include_domains:
        body["includeDomains"] = include_domains
    resp = requests.post(
        EXA_URL,
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def print_results(results):
    for i, r in enumerate(results, 1):
        excerpt = " ".join((r.get("text") or "").split())[:EXCERPT_CHARS]
        print(f"  {i}. {r.get('title') or '(no title)'}")
        print(f"     {r.get('url')}")
        print(f"     published: {r.get('publishedDate') or 'n/a'}")
        if excerpt:
            print(f"     excerpt: {excerpt}")


def main():
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        sys.exit("EXA_API_KEY is not set.")
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00.000Z")
    print(f"Exa sourcing check - published on/after {start} ({days}-day window)\n")

    summary = []
    for name, domain in COMPANIES:
        print("=" * 72)
        print(f"{name}  (IR domain: {domain})")
        try:
            ir = exa_search(api_key, f"{name} news announcement", start, [domain])
            source = "IR domain"
            results = ir
            if not ir:
                print("  IR-domain search: 0 results -> running general fallback search")
                results = exa_search(api_key, f"{name} recent news", start)
                source = "general fallback" if results else "nothing found"
            print(f"  RESULT SOURCE: {source} ({len(results)} results)")
            print_results(results)
        except Exception as exc:  # throwaway script: report and keep going
            source = f"ERROR: {exc}"
            print(f"  {source}")
        summary.append((name, source))
        print()

    print("=" * 72)
    print("Summary")
    for name, source in summary:
        print(f"  {name:<18}{source}")


if __name__ == "__main__":
    main()
