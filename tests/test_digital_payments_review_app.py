"""Tests for the Streamlit coordinator-review screen (task 9) and review_run.

The screen is driven with streamlit.testing.v1.AppTest, which executes the real
script headlessly and lets the test set widget values and click buttons.  The
review is injected through st.session_state["review"]; the pipeline behind the
"Draft this week's section" button is faked at its edges (provider, price fetch).
No network, no LLM, no browser.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import cytonn_weekly.env as env
from cytonn_weekly.digital_payments import coordinator_review as cr
from cytonn_weekly.digital_payments import fetcher, review_run, review_store

from review_helpers import ROWS, TODAY, FakeProvider, LocalFakeProvider, make_review

APP = str(Path(__file__).parents[1] / "src" / "cytonn_weekly" / "ui" / "digital_payments_review.py")


@pytest.fixture(autouse=True)
def hermetic_env(monkeypatch, tmp_path):
    """The app loads .env like any entrypoint; keep a real one out of the test process."""
    monkeypatch.setattr(env, "ENV_FILE", tmp_path / "no.env")
    monkeypatch.delenv("CYTONN_LLM_PROVIDER", raising=False)


def app_with(review=None):
    at = AppTest.from_file(APP, default_timeout=30)
    if review is not None:
        at.session_state["review"] = review
    return at.run()


def idx_of(review, fragment):
    (i,) = [n for n, it in enumerate(review.review_items) if fragment in it.ref]
    return i


def pre(at):
    """Widget-key prefix: a drafted or resumed review bumps the nonce, an injected one does not."""
    return f"r{at.session_state['review_nonce']}" if "review_nonce" in at.session_state else "r0"


def pick(at, review, fragment, label, note=None):
    i = idx_of(review, fragment)
    at.radio(key=f"{pre(at)}_res_{i}").set_value(label)
    if note is not None:
        at.text_input(key=f"{pre(at)}_note_{i}").set_value(note)
    return at.run()


def accept_everything(at, review):
    at.button(key=f"{pre(at)}_accept_clean").click()
    at = at.run()
    for n, item in enumerate(review.review_items):
        if item.resolution is None:
            at.radio(key=f"{pre(at)}_res_{n}").set_value("Accept")
    return at.run()


def texts(elements):
    return [e.value for e in elements]


# ---------------------------------------------------------------------------
# review_run: the wiring that produces the CoordinatorReview
# ---------------------------------------------------------------------------

def test_build_digital_payments_review_runs_the_pipeline_into_a_review():
    review = review_run.build_digital_payments_review(
        provider=FakeProvider(), today=TODAY, fetch_table=lambda today: ROWS,
    )
    assert isinstance(review, cr.CoordinatorReview)
    kinds = [i.kind for i in review.review_items]
    assert kinds.count(cr.TABLE_ROW) == 3 and kinds.count(cr.HIGHLIGHT_CLAIM) == 4
    # the checker compared formatted rows to the source rows: a faithful draft is all clean
    assert not review.by_status(cr.FLAGGED)
    assert {i.status for i in review.review_items if i.kind != cr.HIGHLIGHT_CLAIM} == {cr.CLEAN}
    assert review.section["week_end"] == TODAY.isoformat()


# ---------------------------------------------------------------------------
# Domain additions the screen relies on
# ---------------------------------------------------------------------------

def test_accept_all_clean_resolves_only_unresolved_clean_items():
    review = make_review(tamper=True)
    mine = review.review_items[idx_of(review, "Visa (V)")]
    mine.resolve(cr.FIX_NEEDED, "I disagree")

    n = review.accept_all_clean()

    clean = review.by_status(cr.CLEAN)
    assert n == len(clean) - 1
    assert all(i.resolution == cr.ACCEPT for i in clean if i is not mine)
    assert mine.resolution == cr.FIX_NEEDED and mine.resolution_note == "I disagree"  # not overwritten
    others = review.by_status(cr.FLAGGED) + review.by_status(cr.NOT_AUTO_VERIFIED)
    assert others and all(i.resolution is None for i in others)
    assert review.accept_all_clean() == 0


def test_claim_items_carry_their_source_for_hand_checking():
    review = make_review()
    claim = next(i for i in review.review_items if i.kind == cr.HIGHLIGHT_CLAIM)
    assert claim.context["url"].startswith("https://") and claim.context["cited_text"]
    assert next(i for i in review.review_items if i.kind == cr.TABLE_ROW).context == {}


# ---------------------------------------------------------------------------
# Getting a review into the screen
# ---------------------------------------------------------------------------

def test_without_a_review_the_screen_offers_to_draft(monkeypatch):
    at = app_with()
    assert not at.exception
    assert [b.label for b in at.button] == ["Draft this week's section"]
    assert "Drafting provider: anthropic" in at.caption[0].value  # the default, and says it costs money


def test_local_provider_start_screen_warns_dev_mode(monkeypatch):
    monkeypatch.setenv("CYTONN_LLM_PROVIDER", "local")
    at = app_with()
    assert any("NOT FOR PUBLICATION" in e.value for e in at.error)


def test_draft_button_runs_the_builder_and_shows_the_review(monkeypatch):
    review = make_review()
    monkeypatch.setattr(review_run, "build_digital_payments_review", lambda: review)
    at = app_with()
    at.button[0].click()
    at.run()
    assert not at.exception
    assert at.session_state["review"] is review
    assert any("Mastercard announces a thing" in m.value for m in at.markdown)


def test_draft_run_failure_is_shown_not_swallowed(monkeypatch):
    def boom():
        raise RuntimeError("no API key")

    monkeypatch.setattr(review_run, "build_digital_payments_review", boom)
    at = app_with()
    at.button[0].click()
    at.run()
    assert not at.exception
    assert any("RuntimeError: no API key" in e.value for e in at.error)
    assert "review" not in at.session_state


# ---------------------------------------------------------------------------
# Rendering the drafted content
# ---------------------------------------------------------------------------

def test_table_is_display_formatted_by_calling_format_table_rows(monkeypatch):
    calls = []
    real = fetcher.format_table_rows

    def spy(rows):
        calls.append(rows)
        return real(rows)

    monkeypatch.setattr(fetcher, "format_table_rows", spy)  # the script re-imports it on each run
    review = make_review()
    at = app_with(review)

    assert not at.exception
    assert calls and calls[0] == ROWS  # called on the section's raw fetcher rows
    table = next(d.value for d in at.dataframe if "Ticker" in d.value.columns)
    mc = table[table["Ticker"] == "MA"].iloc[0]
    assert (mc["Price"], mc["w/w %"], mc["Forward P/E"]) == ("100.0", "(1.5%)", "20.0x")  # not 100.0 / -1.5


def test_highlights_outlook_and_stats_are_rendered_and_dollar_signs_escaped():
    at = app_with(make_review())
    md = texts(at.markdown)
    assert sum("announces a thing" in m for m in md) == 4
    assert any(r"paid \$5 million" in m for m in md)  # unescaped $...$ would render as LaTeX
    assert any(r"gained \$2 billion" in m for m in md)
    stats = next(d.value for d in at.dataframe if "Stat" in d.value.columns)
    assert "avg_wow_pct" in set(stats["Stat"])


def test_local_drafted_section_carries_a_dev_mode_banner():
    at = app_with(make_review(provider=LocalFakeProvider()))
    assert any("NOT FOR PUBLICATION" in e.value for e in at.error)
    assert not any("NOT FOR PUBLICATION" in e.value for e in app_with(make_review()).error)


# ---------------------------------------------------------------------------
# Review items
# ---------------------------------------------------------------------------

def test_items_are_grouped_flagged_then_unverified_then_clean():
    review = make_review(tamper=True)
    at = app_with(review)
    heads = [m.value for m in at.markdown if m.value.startswith("#### ")]
    n = {s: len(review.by_status(s)) for s in (cr.FLAGGED, cr.NOT_AUTO_VERIFIED, cr.CLEAN)}
    assert heads == [
        f"#### Flagged by the checker ({n[cr.FLAGGED]})",
        f"#### Not automatically verified ({n[cr.NOT_AUTO_VERIFIED]})",
        f"#### Clean ({n[cr.CLEAN]})",
    ]
    assert n[cr.FLAGGED] == 2 and n[cr.NOT_AUTO_VERIFIED] == 4


def test_flag_detail_and_claim_source_are_shown():
    at = app_with(make_review(tamper=True))
    assert any("mismatch" in m.value and "current_price" in m.value for m in at.markdown)
    assert any("Source: [Visa news](https://investor.visa.com/news)" in m.value for m in at.markdown)


def test_setting_a_resolution_writes_through_to_the_item_and_the_status_updates():
    review = make_review(tamper=True)
    at = app_with(review)
    assert "Not approvable yet" in at.sidebar.warning[0].value

    at = pick(at, review, "Mastercard (MA)", "Fix needed", note="price is off")

    item = review.review_items[idx_of(review, "Mastercard (MA)")]
    assert (item.resolution, item.resolution_note) == (cr.FIX_NEEDED, "price is off")
    assert "1 marked fix needed" in at.sidebar.warning[0].value
    assert at.radio(key=f"r0_res_{idx_of(review, 'Mastercard (MA)')}").value == "Fix needed"  # persists across runs

    at = pick(at, review, "Mastercard (MA)", "Unresolved")
    assert item.resolution is None


def test_bulk_accept_resolves_only_the_clean_items():
    review = make_review(tamper=True)
    at = app_with(review)
    at.button(key="r0_accept_clean").click()
    at.run()

    assert not at.exception
    assert review.by_status(cr.CLEAN) and all(i.resolution == cr.ACCEPT for i in review.by_status(cr.CLEAN))
    untouched = review.by_status(cr.FLAGGED) + review.by_status(cr.NOT_AUTO_VERIFIED)
    assert untouched and all(i.resolution is None for i in untouched)
    assert at.button(key="r0_accept_clean").disabled  # nothing left to bulk-accept
    # and the clean items' radios reflect it
    assert at.radio(key=f"r0_res_{idx_of(review, 'Visa (V)')}").value == "Accept"


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

def test_approve_is_disabled_until_approvable_and_reject_is_always_enabled():
    review = make_review()
    at = app_with(review)
    assert at.button(key="r0_approve").disabled and not at.button(key="r0_reject").disabled

    at = accept_everything(at, review)
    assert review.is_approvable
    assert not at.button(key="r0_approve").disabled
    assert "Approvable" in at.sidebar.success[0].value

    at = pick(at, review, "Visa (V)", "Fix needed")
    assert at.button(key="r0_approve").disabled and not at.button(key="r0_reject").disabled


def test_approve_calls_decide_and_locks_the_screen():
    review = make_review()
    at = accept_everything(app_with(review), review)
    at.button(key="r0_approve").click()
    at.run()

    assert not at.exception
    assert review.decision == cr.APPROVED
    assert at.button(key="r0_approve").disabled and at.button(key="r0_reject").disabled
    assert all(r.disabled for r in at.radio)
    assert review_store.load_review(review.run_id).decision == cr.APPROVED  # the decision was saved
    assert at.button[-1].label == "Close this review"


def test_reject_works_with_items_unresolved_or_fix_needed():
    review = make_review(tamper=True)
    at = pick(app_with(review), review, "Mastercard (MA)", "Fix needed")
    at.button(key="r0_reject").click()
    at.run()
    assert review.decision == cr.REJECTED and not at.exception


def test_closing_a_decided_review_returns_to_the_start_screen():
    review = make_review()
    at = app_with(review)
    at.button(key="r0_reject").click()
    at.run()
    at.button[-1].click()
    at.run()
    assert "review" not in at.session_state
    # the decided review is still in the database, so it can be viewed again
    assert [b.label for b in at.button] == ["View it", "Draft this week's section"]


# ---------------------------------------------------------------------------
# Persistence and resume (the DB is a per-test temp file; see conftest.py)
# ---------------------------------------------------------------------------

def saved():
    return review_store.load_latest_review(run_date=date.today())


def test_a_fresh_draft_is_saved_immediately(monkeypatch):
    review = make_review()
    monkeypatch.setattr(review_run, "build_digital_payments_review", lambda: review)
    assert saved() is None
    at = app_with()
    at.button[0].click()
    at.run()

    assert review.run_id is not None and saved() == review
    assert f"Saved as run {review.run_id}." in [c.value for c in at.sidebar.caption]


def test_every_resolution_change_and_the_decision_are_saved():
    review = make_review()
    at = app_with(review)
    visa = idx_of(review, "Visa (V)")

    at = pick(at, review, "Visa (V)", "Accept", note="checked on Yahoo")
    from_db = saved()
    assert from_db is not review
    assert (from_db.review_items[visa].resolution, from_db.review_items[visa].resolution_note) == (
        cr.ACCEPT, "checked on Yahoo")

    at = pick(at, review, "Visa (V)", "Unresolved")
    assert saved().review_items[visa].resolution is None  # clearing is saved too

    at.button(key=f"{pre(at)}_accept_clean").click()
    at.run()
    assert saved() == review and saved().by_status(cr.CLEAN)[0].resolution == cr.ACCEPT  # bulk accept saved

    at = accept_everything(at, review)
    at.button(key=f"{pre(at)}_approve").click()
    at.run()
    assert saved() == review and saved().decision == cr.APPROVED and saved().decided_at


def test_refresh_mid_review_offers_resume_and_resuming_restores_the_work_without_redrafting(monkeypatch):
    # Session 1: draft (the builder runs once), resolve a few items, then "refresh".
    review = make_review(tamper=True)
    monkeypatch.setattr(review_run, "build_digital_payments_review", lambda: review)
    at = app_with()
    at.button[0].click()
    at.run()
    at = pick(at, review, "Mastercard (MA)", "Fix needed", note="price is off")
    at = pick(at, review, "Visa (V)", "Accept")

    # Session 2 = a new AppTest: no session state, same database.  The builder must not run again.
    def must_not_run():
        raise AssertionError("resume must not re-run the (paid) draft")

    monkeypatch.setattr(review_run, "build_digital_payments_review", must_not_run)
    at2 = app_with()
    assert not at2.exception
    assert "review" not in at2.session_state
    assert any("in progress" in i.value and "2 of" in i.value for i in at2.info)
    labels = [b.label for b in at2.button]
    assert labels[0] == "Resume this review" and "Draft this week's section" in labels

    at2.button(key="resume").click()
    at2.run()
    resumed = at2.session_state["review"]
    assert resumed == review and resumed is not review
    key = pre(at2)
    ma, visa = idx_of(resumed, "Mastercard (MA)"), idx_of(resumed, "Visa (V)")
    assert at2.radio(key=f"{key}_res_{ma}").value == "Fix needed"
    assert at2.text_input(key=f"{key}_note_{ma}").value == "price is off"
    assert at2.radio(key=f"{key}_res_{visa}").value == "Accept"
    assert "Not approvable yet" in at2.sidebar.warning[0].value

    # the resumed session keeps saving to the same row
    at2 = pick(at2, resumed, "Mastercard (MA)", "Accept")
    assert saved().run_id == review.run_id
    assert saved().review_items[ma].resolution == cr.ACCEPT


def test_decided_review_is_offered_for_viewing_after_a_refresh_and_is_locked():
    review = make_review()
    at = accept_everything(app_with(review), review)
    at.button(key=f"{pre(at)}_approve").click()
    at.run()

    at2 = app_with()  # refresh
    assert any("was approved" in i.value for i in at2.info)
    assert [b.label for b in at2.button][0] == "View it"
    at2.button(key="resume").click()
    at2.run()

    assert not at2.exception
    assert at2.session_state["review"].decision == cr.APPROVED
    assert all(r.disabled for r in at2.radio)
    assert at2.button(key=f"{pre(at2)}_approve").disabled and at2.button(key=f"{pre(at2)}_reject").disabled


def test_yesterdays_review_is_not_offered_for_resume():
    review_store.save_review(make_review(), run_date=date.today() - timedelta(days=1))
    at = app_with()
    assert not any("in progress" in i.value for i in at.info)
    assert [b.label for b in at.button] == ["Draft this week's section"]


def test_save_failure_is_shown_loudly_and_the_screen_keeps_working(monkeypatch):
    review = make_review()
    at = app_with(review)

    def broken(*a, **k):
        raise OSError("disk is full")

    monkeypatch.setattr(review_store, "save_review", broken)
    at = pick(at, review, "Visa (V)", "Accept")

    assert not at.exception
    assert review.review_items[idx_of(review, "Visa (V)")].resolution == cr.ACCEPT  # in-memory work is kept
    assert any("NOT SAVED" in e.value and "disk is full" in e.value for e in at.sidebar.error)


def test_a_stale_session_cannot_edit_a_review_decided_elsewhere():
    review = make_review()
    tab_b = app_with(review)  # tab B has the review open and undecided
    twin = review_store.load_review(review_store.save_review(review))  # tab A's copy of the same run
    twin.decide("rejected")
    review_store.save_review(twin)

    tab_b = pick(tab_b, review, "Visa (V)", "Accept")
    assert any("NOT SAVED" in e.value and "already rejected" in e.value for e in tab_b.sidebar.error)
    assert saved().decision == cr.REJECTED
    assert saved().review_items[idx_of(review, "Visa (V)")].resolution is None


def test_unreadable_saved_reviews_do_not_block_drafting(monkeypatch):
    def broken(*a, **k):
        raise OSError("db locked")

    monkeypatch.setattr(review_store, "load_latest_review", broken)
    at = app_with()
    assert not at.exception
    assert any("Could not read saved reviews" in w.value for w in at.warning)
    assert [b.label for b in at.button] == ["Draft this week's section"]
