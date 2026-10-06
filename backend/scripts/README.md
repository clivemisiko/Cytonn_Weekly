# scripts/

Manual, run-by-hand scripts against live services: diagnostics, plus the summary-email entrypoint. None runs automatically. Run each from `backend/` after `pip install -e .`.

| Script | What it does | Cost | When to run it |
| --- | --- | --- | --- |
| `check_digital_payments_live.py` | Fetches the 7 Digital Payments stock rows from Yahoo Finance and prints price, prior close, Year Open (the first trading day's close), w/w %, YTD %, forward EPS and forward P/E with their source dates. Fetch only: no drafting, no checking. | Free | After touching `digital_payments/fetcher.py`, or to compare the P/E column against Yahoo's quote pages. |
| `check_digital_payments_highlights_live.py` | Runs the real highlights drafter, the table fetch and the outlook drafter, then prints the composed section (headlines, bodies, links, cited claims, warnings). | Spends Anthropic budget by default; free with `CYTONN_LLM_PROVIDER=local` (Ollama + Exa, dev only, not for publication) | To eyeball a real draft, or to check citation spans after changing `highlights.py` or a provider. |
| `send_weekly_summary.py` | Previews, and with `--yes` sends, the latest approved Word summary of a section (default `digital_payments`, the only one with a summary today) to `CYTONN_SUMMARY_RECIPIENTS`. Prints section, run, approval status, `drafted_by`, recipients and SMTP host first. Refuses (non-zero exit, nothing sent) for a missing/undecided/rejected review, missing SMTP config, or any `local:` (dev-mode) draft. | Sends **real email** with `--yes` once SMTP is configured | Once a week, after the coordinator approves the section and before publish. |
| `check_exa_ir_sourcing.py` | Queries Exa for each of the 5 highlight companies, IR domain first and general web as fallback, and prints what comes back. No LLM involved. Temporary diagnostic, not a dependency of the drafter. | Exa API only (`EXA_API_KEY`) | To see whether a company's IR site has news this week before blaming the drafter. |

Keys and `CYTONN_LLM_PROVIDER` are read from the repo-root `.env`. The `PYTHONPATH=src` prefix shown in the scripts' docstrings is not needed once the package is installed with `pip install -e .`.
