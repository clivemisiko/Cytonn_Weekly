"""Streamlit coordinator-review screen for the Digital Payments section (backlog task 9).

Run from anywhere (the package is installed editable):
    streamlit run src/cytonn_weekly/ui/digital_payments_review.py

The screen operates on ONE CoordinatorReview per browser session, held in
``st.session_state["review"]`` and saved to SQLite (review_store) when the draft
lands, on every resolution change, and on the decision.  A page refresh starts a
new session, so on start the screen offers to resume today's saved review rather
than running the pipeline again (which spends API budget in Anthropic mode).  With
nothing to resume it offers a button that runs the real pipeline
(review_run.build_digital_payments_review).

The tool never approves anything; this screen only records what the coordinator
decides.  The ReviewItem objects are the source of truth: every widget writes
through ReviewItem.resolve() in its callback, so the status panel, which renders
before the items, is always current.
"""

from __future__ import annotations

import os
from datetime import date

import pandas as pd
import streamlit as st

from cytonn_weekly.env import load_env
from cytonn_weekly.digital_payments.coordinator_review import (
    ACCEPT, APPROVED, CLEAN, FIX_NEEDED, FLAGGED, NOT_AUTO_VERIFIED, REJECTED,
    CoordinatorReview, ReviewItem,
)
from cytonn_weekly.digital_payments.fetcher import format_table_rows
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.digital_payments.provider_factory import ENV_VAR as PROVIDER_ENV_VAR
from cytonn_weekly.digital_payments.review_run import build_digital_payments_review

load_env(quiet=True)  # an entrypoint loads .env before anything reads os.environ

RESOLUTION_LABELS = {None: "Unresolved", ACCEPT: "Accept", FIX_NEEDED: "Fix needed"}
LABEL_TO_RESOLUTION = {label: value for value, label in RESOLUTION_LABELS.items()}
GROUPS = [
    (FLAGGED, "Flagged by the checker"),
    (NOT_AUTO_VERIFIED, "Not automatically verified"),
    (CLEAN, "Clean"),
]
TABLE_COLUMNS = {
    "company": "Company", "ticker": "Ticker", "current_price": "Price",
    "prior_close": "Price 7 days ago", "ytd_open": "YTD open",
    "wow_pct": "w/w %", "ytd_pct": "YTD %", "forward_pe": "Forward P/E",
}


def md(text: object) -> str:
    """Escape ``$`` so figures like "$1.2bn ... $3m" are not rendered as LaTeX."""
    return str(text).replace("$", r"\$")


# ---------------------------------------------------------------------------
# State and callbacks (callbacks run before the script body on the next rerun)
# ---------------------------------------------------------------------------

def _key_prefix() -> str:
    return f"r{st.session_state.get('review_nonce', 0)}"


def _persist(review: CoordinatorReview) -> None:
    """Save the review; a failure is shown on screen (never swallowed, never fatal)."""
    try:
        review_store.save_review(review)
        st.session_state.pop("save_error", None)
    except Exception as exc:  # noqa: BLE001 - surfaced in the status panel
        st.session_state["save_error"] = f"{type(exc).__name__}: {exc}"


def _set_review(review: CoordinatorReview, *, save: bool) -> None:
    st.session_state["review"] = review
    st.session_state["review_nonce"] = st.session_state.get("review_nonce", 0) + 1
    st.session_state.pop("decision_error", None)
    st.session_state.pop("save_error", None)
    if save:  # a fresh draft is saved at once, so a refresh right after it does not lose a paid run
        _persist(review)


def _resume(review: CoordinatorReview) -> None:
    _set_review(review, save=False)  # it came from the database


def _discard_review() -> None:
    st.session_state.pop("review", None)
    st.session_state.pop("decision_error", None)


def _on_resolution(review: CoordinatorReview, item: ReviewItem, res_key: str, note_key: str) -> None:
    item.resolve(LABEL_TO_RESOLUTION[st.session_state[res_key]], st.session_state[note_key].strip() or None)
    _persist(review)


def _accept_clean(review: CoordinatorReview) -> None:
    review.accept_all_clean()
    _persist(review)


def _decide(review: CoordinatorReview, decision: str) -> None:
    try:
        review.decide(decision)
        st.session_state.pop("decision_error", None)
    except ValueError as exc:  # e.g. approvability changed under the coordinator
        st.session_state["decision_error"] = str(exc)
        return
    _persist(review)


# ---------------------------------------------------------------------------
# Drafted content, for context
# ---------------------------------------------------------------------------

def _render_table(rows: list[dict]) -> None:
    shown = format_table_rows(rows)  # the section holds raw fetcher rows, not display strings
    st.dataframe(
        pd.DataFrame(shown)[list(TABLE_COLUMNS)].rename(columns=TABLE_COLUMNS),
        hide_index=True, use_container_width=True,
    )
    for r in rows:
        if r.get("error"):
            st.caption(f":red[{md(r['ticker'])} failed to fetch: {md(r['error'])}]")


def _render_draft(review: CoordinatorReview) -> None:
    sec = review.section
    st.subheader(f"Drafted section: {sec['week_start']} to {sec['week_end']}")
    drafted_by = {i.get("drafted_by") for i in sec["items"] if i.get("kind") == "highlight"}
    drafted_by.add(sec["outlook"].get("drafted_by"))
    if any(str(d).startswith("local:") for d in drafted_by):
        st.error("DEV MODE draft (local model): NOT FOR PUBLICATION.")
    if sec.get("shortfall"):
        st.warning(f"Only {4 - sec['shortfall']} of 4 highlights were found this week.")
    for w in sec.get("warnings", []):
        st.warning(md(w))

    for it in sec["items"]:
        if it["kind"] == "highlight":
            st.markdown(f"**{it['numeral']}.** {md(it['headline_md'])}")
            st.markdown(md(it["body_md"]))
            st.caption(
                f"{it.get('company')} · {it.get('search_scope')} ({it.get('ir_domain')}) · "
                f"drafted by {it.get('drafted_by')}"
            )
            for w in it.get("warnings", []):
                st.caption(f":orange[{md(w)}]")
        else:
            st.markdown(f"**{it['numeral']}.** **Digital Payments NYSE and LSE Stock Performance**")
            _render_table(it["rows"])

    outlook = sec["outlook"]
    st.markdown(md(outlook["text_md"]))
    st.dataframe(
        pd.DataFrame({"Stat": list(outlook["stats"]), "Value": [str(v) for v in outlook["stats"].values()]}),
        hide_index=True,
    )
    for w in outlook.get("warnings", []):
        st.caption(f":orange[{md(w)}]")


# ---------------------------------------------------------------------------
# Review items
# ---------------------------------------------------------------------------

def _render_flag(f) -> None:
    st.markdown(f":red[**{f.kind}**] · {md(f.message)}")
    if f.drafted is not None or f.expected is not None:
        st.caption(f"Drafted: {md(repr(f.drafted))} · Expected (normalized source): {md(f.expected)} · "
                   f"Source value: {md(repr(f.source_value))}")
    for s in f.sources:
        st.caption(f"- {md(s['source'])}: {md(s['value'])} (normalized {md(s['normalized'])})")


def _render_detail(item: ReviewItem) -> None:
    if item.status == FLAGGED:
        for f in item.detail:
            _render_flag(f)
    if item.context:
        c = item.context
        if c.get("text"):
            st.markdown(f"> {md(c['text'])}")
        if str(c.get("url", "")).startswith(("http://", "https://")):
            st.markdown(f"Source: [{md(c.get('title') or c['url'])}]({c['url']})")
        if c.get("cited_text"):
            st.caption(f"Cited text: “{md(c['cited_text'])}”")
    if item.status == NOT_AUTO_VERIFIED:
        st.caption(md(item.detail))


def _render_controls(review: CoordinatorReview, item: ReviewItem, idx: int, locked: bool) -> None:
    res_key, note_key = f"{_key_prefix()}_res_{idx}", f"{_key_prefix()}_note_{idx}"
    # The model is the source of truth: re-seed the widgets from it on every run.
    st.session_state[res_key] = RESOLUTION_LABELS[item.resolution]
    st.session_state[note_key] = item.resolution_note or ""
    on_change = dict(on_change=_on_resolution, args=(review, item, res_key, note_key))
    st.radio("Resolution", list(LABEL_TO_RESOLUTION), key=res_key, horizontal=True, disabled=locked, **on_change)
    st.text_input("Note (optional)", key=note_key, disabled=locked, **on_change)


def _render_item(review: CoordinatorReview, item: ReviewItem, idx: int, locked: bool) -> None:
    with st.container(border=True):
        st.markdown(f"**{md(item.ref)}**")
        _render_detail(item)
        _render_controls(review, item, idx, locked)


def _render_items(review: CoordinatorReview, locked: bool) -> None:
    st.subheader("Review items")
    indexed = list(enumerate(review.review_items))
    for status, title in GROUPS:
        group = [(i, it) for i, it in indexed if it.status == status]
        if status == CLEAN:
            unresolved = sum(1 for _, it in group if it.resolution is None)
            st.markdown(f"#### {title} ({len(group)})")
            st.caption("Checked with no flag. Listed so you can see full coverage.")
            st.button(
                f"Mark all clean as accepted ({unresolved} unresolved)",
                key=f"{_key_prefix()}_accept_clean", type="primary",
                disabled=locked or unresolved == 0, on_click=_accept_clean, args=(review,),
            )
            with st.expander(f"Show the {len(group)} clean items"):
                for i, it in group:
                    _render_item(review, it, i, locked)
        else:
            st.markdown(f"#### {title} ({len(group)})")
            if not group:
                st.caption("None.")
            for i, it in group:
                _render_item(review, it, i, locked)


# ---------------------------------------------------------------------------
# Status and decision
# ---------------------------------------------------------------------------

def _render_status(review: CoordinatorReview) -> None:
    items = review.review_items
    resolved = sum(1 for i in items if i.resolution is not None)
    fixes = sum(1 for i in items if i.resolution == FIX_NEEDED)
    st.progress(resolved / len(items) if items else 0.0, text=f"{resolved} of {len(items)} items resolved")
    if review.decision:
        st.info(f"Decision recorded: **{review.decision}**.")
    elif review.is_approvable:
        st.success("Approvable: every item is resolved and none needs a fix.")
    else:
        st.warning(f"Not approvable yet: {len(items) - resolved} unresolved, {fixes} marked fix needed.")
    if st.session_state.get("save_error"):
        st.error(
            f"NOT SAVED: {md(st.session_state['save_error'])}. Your work is only in this browser "
            "session right now; a refresh would lose it."
        )
    else:
        st.caption(f"Saved as run {review.run_id}.")


def _render_decision(review: CoordinatorReview) -> None:
    st.subheader("Decision")
    decided = review.decision is not None
    left, right, _ = st.columns([1, 1, 4])
    left.button(
        "Approve", key=f"{_key_prefix()}_approve", type="primary",
        disabled=decided or not review.is_approvable, on_click=_decide, args=(review, APPROVED),
    )
    right.button(
        "Reject", key=f"{_key_prefix()}_reject",
        disabled=decided, on_click=_decide, args=(review, REJECTED),
    )
    if st.session_state.get("decision_error"):
        st.error(st.session_state["decision_error"])
    if decided:
        st.success(f"Review {review.decision}.")
        st.button("Close this review", on_click=_discard_review)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def _todays_saved_review() -> CoordinatorReview | None:
    try:
        return review_store.load_latest_review(run_date=date.today())
    except Exception as exc:  # noqa: BLE001 - the screen still works without saved reviews
        st.warning(f"Could not read saved reviews: {type(exc).__name__}: {exc}")
        return None


def _render_saved_review(saved: CoordinatorReview) -> None:
    items = saved.review_items
    resolved = sum(1 for i in items if i.resolution is not None)
    sec = saved.section
    if saved.decision is None:
        st.info(
            f"A review from today is in progress (run {saved.run_id}, report week {sec['week_start']} to "
            f"{sec['week_end']}): {resolved} of {len(items)} items resolved. Resuming it does not re-run the draft."
        )
        st.button("Resume this review", key="resume", type="primary", on_click=_resume, args=(saved,))
    else:
        st.info(f"Today's review (run {saved.run_id}) was {saved.decision} at {saved.decided_at}.")
        st.button("View it", key="resume", on_click=_resume, args=(saved,))


def _render_start() -> None:
    saved = _todays_saved_review()
    if saved is not None:
        _render_saved_review(saved)
        st.divider()
    provider = (os.environ.get(PROVIDER_ENV_VAR) or "anthropic").strip().lower()
    if saved is None:
        st.write("No review is loaded. Draft this week's Digital Payments section, check it, and review it here.")
    else:
        st.write("Or start over with a new draft. The saved review stays in the database either way.")
    if provider == "local":
        st.error("CYTONN_LLM_PROVIDER=local: DEV MODE. Drafts from the local model are NOT FOR PUBLICATION.")
    else:
        st.caption(f"Drafting provider: {provider}. A run spends real API budget (web search and tokens).")
    if st.button("Draft this week's section", type="primary" if saved is None else "secondary"):
        try:
            with st.spinner("Fetching prices, searching for highlights and drafting. This takes a few minutes."):
                review = build_digital_payments_review()
        except Exception as exc:  # noqa: BLE001 - shown to the coordinator, not swallowed
            st.error(f"The draft run failed: {type(exc).__name__}: {exc}")
        else:
            _set_review(review, save=True)
            st.rerun()


def main() -> None:
    st.set_page_config(page_title="Digital Payments review", layout="wide")
    st.title("Digital Payments: coordinator review")
    review: CoordinatorReview | None = st.session_state.get("review")
    if review is None:
        _render_start()
        return
    locked = review.decision is not None
    with st.sidebar:
        st.header("Review status")
        _render_status(review)
    _render_draft(review)
    _render_items(review, locked)
    _render_decision(review)


main()
