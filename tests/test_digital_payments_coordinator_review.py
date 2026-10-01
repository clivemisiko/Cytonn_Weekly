"""Unit tests for cytonn_weekly.digital_payments.coordinator_review (backlog task 8).

compose_section() output is mocked; the CheckReport is the real checker's, run
on small source/drafted rows with deliberate errors, so these tests also pin
the CheckReport shape the review is built on.  No network, no LLM.
"""

import copy

import pytest

from cytonn_weekly.checkers import digital_payments as ck
from cytonn_weekly.checkers.digital_payments import CheckReport, Flag
from cytonn_weekly.digital_payments import coordinator_review as cr
from cytonn_weekly.digital_payments.fetcher import format_table_rows
from cytonn_weekly.digital_payments.highlights import table_stats


def src(ticker, company, price=100.0, wow=2.0, ytd=10.0, pe=20.0):
    return {"company": company, "ticker": ticker, "error": None, "current_price": price,
            "prior_close": 98.0, "ytd_open": 90.0, "wow_pct": wow, "ytd_pct": ytd, "forward_pe": pe}


ROWS = [src("V", "Visa"), src("MA", "Mastercard", wow=-1.5), src("AXP", "American Express", pe=18.0)]


def highlight(numeral, company, headline, claim_texts):
    return {
        "numeral": numeral, "kind": "highlight", "headline": headline, "company": company,
        "claims": [{"text": t, "url": f"https://example.com/{i}", "title": "t", "cited_text": "c"}
                   for i, t in enumerate(claim_texts)],
    }


def compose(rows=ROWS, stats=None, highlights=None):
    highlights = highlights if highlights is not None else [
        highlight("I", "Visa", "Visa does a thing", ["Visa launched X.", "Visa expanded to Y."]),
        highlight("II", "Mastercard", "Mastercard does another", ["Mastercard partnered with Z."]),
    ]
    return {
        "week_start": "2026-09-24", "week_end": "2026-09-30",
        "items": [*highlights, {"numeral": "III", "kind": "stock_table", "rows": rows}],
        "outlook": {"text": "...", "stats": table_stats(rows) if stats is None else stats, "warnings": []},
        "shortfall": 2, "warnings": [],
    }


def run_checker(section, drafted_rows=None):
    drafted = format_table_rows(ROWS) if drafted_rows is None else drafted_rows
    return ck.check_digital_payments(
        source_rows=ROWS,
        drafted_rows=drafted,
        drafted_outlook_stats=section["outlook"]["stats"],
        highlights=[i for i in section["items"] if i["kind"] == "highlight"],
    )


def mixed():
    """V clean; MA has a wrong price; AXP is absent from the draft; one outlook stat is wrong."""
    stats = {**table_stats(ROWS), "avg_wow_pct": 99.9}
    section = compose(stats=stats)
    drafted = [r for r in format_table_rows(ROWS) if r["ticker"] != "AXP"]
    next(r for r in drafted if r["ticker"] == "MA")["current_price"] = "101.0"
    return section, run_checker(section, drafted)


def approvable_review():
    section = compose()
    review = cr.build_coordinator_review(section, run_checker(section))
    return review


def resolve_all(review, resolution="accept"):
    for item in review.review_items:
        item.resolve(resolution)


def by_ref(review, fragment):
    (item,) = [i for i in review.review_items if fragment in i.ref]
    return item


# ---------------------------------------------------------------------------
# Building the items
# ---------------------------------------------------------------------------

def test_items_cover_every_row_stat_and_claim_with_mixed_statuses():
    section, report = mixed()
    review = cr.build_coordinator_review(section, report)

    kinds = [i.kind for i in review.review_items]
    assert kinds.count(cr.TABLE_ROW) == 3
    assert kinds.count(cr.OUTLOOK_STAT) == len(table_stats(ROWS))
    assert kinds.count(cr.HIGHLIGHT_CLAIM) == 3  # 2 + 1 claims

    assert by_ref(review, "Visa (V)").status == cr.CLEAN
    assert by_ref(review, "Mastercard (MA)").status == cr.FLAGGED
    assert by_ref(review, "American Express (AXP)").status == cr.FLAGGED
    assert by_ref(review, "avg_wow_pct").status == cr.FLAGGED
    assert by_ref(review, "avg_ytd_pct").status == cr.CLEAN


def test_flagged_row_carries_the_checkers_flag_objects_and_clean_has_no_detail():
    section, report = mixed()
    review = cr.build_coordinator_review(section, report)

    ma = by_ref(review, "(MA)")
    assert [f.kind for f in ma.detail] == [ck.MISMATCH]
    assert ma.detail[0] in report.flags  # the same object, not a copy
    assert ma.detail[0].field == "current_price"
    assert [f.kind for f in by_ref(review, "(AXP)").detail] == [ck.MISSING]
    assert by_ref(review, "(V)").detail is None


def test_row_with_several_flagged_figures_gets_all_of_them():
    section = compose()
    drafted = format_table_rows(ROWS)
    drafted[0]["current_price"] = "1.0"
    drafted[0]["wow_pct"] = "9.9%"
    review = cr.build_coordinator_review(section, run_checker(section, drafted))
    assert sorted(f.field for f in by_ref(review, "(V)").detail) == ["current_price", "wow_pct"]


def test_every_highlight_claim_is_not_auto_verified_with_the_fixed_note():
    section, report = mixed()
    review = cr.build_coordinator_review(section, report)
    claims = [i for i in review.review_items if i.kind == cr.HIGHLIGHT_CLAIM]
    assert {i.status for i in claims} == {cr.NOT_AUTO_VERIFIED}
    assert {i.detail for i in claims} == {cr.NOT_AUTO_VERIFIED_NOTE}
    assert "not a flag" in cr.NOT_AUTO_VERIFIED_NOTE


def test_not_implemented_placeholder_flags_do_not_become_flagged_items():
    section, report = mixed()
    assert report.by_kind(ck.NOT_IMPLEMENTED)  # the checker does emit them, per highlight
    review = cr.build_coordinator_review(section, report)
    assert not [i for i in review.by_status(cr.FLAGGED) if i.kind == cr.HIGHLIGHT_CLAIM]


def test_claim_ref_names_the_highlight_and_truncates_long_claim_text():
    long_claim = "word " * 60
    section = compose(highlights=[highlight("I", "Visa", "H", [long_claim])])
    review = cr.build_coordinator_review(section, run_checker(section))
    ref = by_ref(review, "Highlight I (Visa)").ref
    assert ref.endswith("…") and len(ref) < 120


def test_highlight_without_claims_is_still_listed_once():
    section = compose(highlights=[highlight("I", "Visa", "H", [])])
    review = cr.build_coordinator_review(section, run_checker(section))
    (item,) = [i for i in review.review_items if i.kind == cr.HIGHLIGHT_CLAIM]
    assert item.status == cr.NOT_AUTO_VERIFIED


def test_stat_missing_from_the_draft_still_gets_an_item():
    stats = table_stats(ROWS)
    del stats["avg_forward_pe"]
    section = compose(stats=stats)
    review = cr.build_coordinator_review(section, run_checker(section))
    item = by_ref(review, "avg_forward_pe")
    assert item.status == cr.FLAGGED and item.detail[0].kind == ck.MISSING


def test_no_flag_is_dropped_even_when_it_points_outside_the_section():
    section = compose()
    drafted = [*format_table_rows(ROWS), {**format_table_rows([src("ZZ", "Zed")])[0]}]  # drafted row, no source
    report = run_checker(section, drafted)
    stray = Flag(kind=ck.MISMATCH, scope="highlight", subject="No such headline", field=None, message="x")
    report.flags.append(stray)

    review = cr.build_coordinator_review(section, report)
    expected = [f for f in report.flags if f.kind != ck.NOT_IMPLEMENTED]
    landed = [f for i in review.review_items if i.status == cr.FLAGGED for f in i.detail]
    assert len(expected) == len(landed) == 2
    assert all(any(f is g for g in landed) for f in expected)


def test_future_highlight_flag_marks_that_highlights_claims_flagged():
    section = compose()
    report = run_checker(section)
    flag = Flag(kind=ck.MISMATCH, scope="highlight", subject="Visa does a thing", field=None, message="x")
    report.flags.append(flag)
    review = cr.build_coordinator_review(section, report)
    visa = [i for i in review.review_items if i.ref.startswith("Highlight I (")]
    assert len(visa) == 2 and all(i.status == cr.FLAGGED and i.detail == [flag] for i in visa)
    assert by_ref(review, "Highlight II").status == cr.NOT_AUTO_VERIFIED


def test_unrecognised_flag_scope_raises_rather_than_dropping_it():
    section = compose()
    report = run_checker(section)
    report.flags.append(Flag(kind=ck.MISMATCH, scope="weird", subject="s", field=None, message="x"))
    with pytest.raises(ValueError, match="unrecognised scope"):
        cr.build_coordinator_review(section, report)


def test_report_that_compared_nothing_is_rejected_instead_of_reading_all_clean():
    with pytest.raises(ValueError, match="compared no figures"):
        cr.build_coordinator_review(compose(), CheckReport())


def test_compose_output_is_wrapped_unchanged():
    section, report = mixed()
    before = copy.deepcopy(section)
    review = cr.build_coordinator_review(section, report)
    assert review.section is section
    assert section == before


# ---------------------------------------------------------------------------
# is_approvable
# ---------------------------------------------------------------------------

def test_not_approvable_until_every_item_is_resolved():
    review = approvable_review()
    assert review.review_items and not review.is_approvable  # nothing resolved yet
    items = review.review_items
    for item in items[:-1]:
        item.resolve(cr.ACCEPT)
        assert not review.is_approvable
    items[-1].resolve(cr.ACCEPT)
    assert review.is_approvable


def test_clean_and_unverified_items_need_a_resolution_too():
    review = approvable_review()
    assert {i.status for i in review.review_items} == {cr.CLEAN, cr.NOT_AUTO_VERIFIED}
    resolve_all(review)
    review.review_items[0].resolve(None)
    assert not review.is_approvable


def test_not_approvable_if_any_item_is_fix_needed():
    review = approvable_review()
    resolve_all(review)
    review.review_items[3].resolve(cr.FIX_NEEDED, "figure looks wrong")
    assert not review.is_approvable
    assert review.review_items[3].resolution_note == "figure looks wrong"
    review.review_items[3].resolve(cr.ACCEPT)
    assert review.is_approvable


def test_resolving_a_flagged_item_as_accept_is_allowed():
    section, report = mixed()
    review = cr.build_coordinator_review(section, report)
    resolve_all(review)
    assert review.by_status(cr.FLAGGED) and review.is_approvable


def test_empty_review_is_not_approvable():
    assert not cr.CoordinatorReview(section={}).is_approvable


def test_resolve_rejects_unknown_resolution():
    item = approvable_review().review_items[0]
    with pytest.raises(ValueError):
        item.resolve("approved")


# ---------------------------------------------------------------------------
# decide
# ---------------------------------------------------------------------------

def test_decide_approved_raises_while_unresolved():
    review = approvable_review()
    with pytest.raises(ValueError, match="cannot approve"):
        review.decide("approved")
    assert review.decision is None


def test_decide_approved_raises_while_any_fix_needed():
    review = approvable_review()
    resolve_all(review)
    review.review_items[0].resolve(cr.FIX_NEEDED)
    with pytest.raises(ValueError, match="1 marked fix_needed"):
        review.decide("approved")
    assert review.decision is None


def test_decide_approved_succeeds_once_approvable():
    review = approvable_review()
    resolve_all(review)
    review.decide("approved")
    assert review.decision == cr.APPROVED


def test_decide_rejected_works_even_though_fix_needed_makes_it_unapprovable():
    review = approvable_review()
    resolve_all(review)
    review.review_items[0].resolve(cr.FIX_NEEDED)
    review.decide("rejected")
    assert review.decision == cr.REJECTED


def test_decide_rejects_unknown_decision_and_a_second_decision():
    review = approvable_review()
    with pytest.raises(ValueError, match="decision must be"):
        review.decide("maybe")
    review.decide("rejected")
    with pytest.raises(ValueError, match="already decided"):
        review.decide("rejected")
    assert review.decision == cr.REJECTED
