# Cytonn Weekly

Tooling to automate drafting, checking and publishing the Cytonn weekly report.

See [CLAUDE.md](CLAUDE.md) for full project context and the task backlog.

## Setup

```sh
python -m venv .venv
.venv\Scripts\activate        # Windows; use `source .venv/bin/activate` elsewhere
pip install -e .
playwright install chromium
```

## Coordinator review screen (Digital Payments)

```sh
streamlit run src/cytonn_weekly/ui/digital_payments_review.py
```

The screen's "Draft this week's section" button runs the real pipeline (price fetch, drafting, checks) and loads the result. That uses the drafting provider below, so the default Anthropic provider spends API budget; `CYTONN_LLM_PROVIDER=local` is the free dev option (output not for publication).

The review is saved to `data/app.db` (table `coordinator_reviews`, defined in `data/schema.sql`) when the draft lands, on every resolution change, and on the decision. After a refresh, the start screen offers to resume today's saved review instead of re-drafting; a decided review is frozen and can only be viewed. Code that needs the approved values reads them with `review_store.load_latest_review()`.

## Drafting provider (Digital Payments)

`CYTONN_LLM_PROVIDER` picks who drafts the Weekly Highlights and outlook: `anthropic` (default, production) or `local` (development only, prints a NOT FOR PUBLICATION warning).

Local mode uses Ollama for drafting and Exa (`EXA_API_KEY`) for search:

```sh
ollama pull phi4-mini                         # default model, ~2.5 GB
CYTONN_LLM_PROVIDER=local python scripts/check_digital_payments_highlights_live.py
```

To A/B another model on the same search results, set `CYTONN_LOCAL_MODEL`, e.g. `gemma4:26b-a4b-it-qat` (a ~15.6 GB pull; needs well over 16 GB of free RAM or a large GPU). The first run saves each company's Exa results to `data/exa_cache/<company>_<date>.json`, and later runs, whatever the model, reuse them. The cache is keyed by calendar day, so compare models on the same day. **To force a fresh Exa pull**, set `CYTONN_EXA_REFRESH=1`, or delete the file (or the whole `data/exa_cache/` directory).

