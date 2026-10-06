"""The shared checking layer and generic review builder (common/checks.py, common/review.py)."""

from decimal import Decimal

import pytest

from cytonn_weekly.checkers.digital_payments import MISMATCH, MISSING, UNSOURCED, CheckReport
from cytonn_weekly.common import formatting as fm
from cytonn_weekly.common.checks import check_claim, check_table_block, figures_in
from cytonn_weekly.common.review import (
    CLAIM,
    UNAVAILABLE_PART,
    build_review,
    check_section,
    numbered,
    unavailable_block,
)
from cytonn_weekly.digital_payments.coordinator_review import (
    CLEAN, FLAGGED, NOT_AUTO_VERIFIED, TABLE_ROW, ReviewItem,
)

COLS = [
    {"key": "name", "label": "Name", "fmt": fm.TEXT},
    {"key": "price", "label": "Price", "fmt": fm.PRICE, "decimals": 2},
    {"key": "wow_pct", "label": "w/w %", "fmt": fm.PCT, "decimals": 1},
]
SRC = [{"k": "A", "name": "Alpha", "price": 29.65, "wow_pct": -4.04, "error": None},
       {"k": "B", "name": "Beta", "price": 1.005, "wow_pct": 2.25, "error": None}]


def table(rows=None, src=SRC):
    display = fm.format_rows(src, COLS) if rows is None else rows
    for d, s in zip(display, src):
        d.setdefault("k", s["k"])
    return {"kind": "table", "id": "t", "title": "Table", "columns": COLS, "key_field": "k", "label_field": "name",
            "rows": display, "source_rows": src, "source": {"name": "test"}}


# --- formatting ------------------------------------------------------------------

@pytest.mark.parametrize("value,fmt,dec,expected", [
    (-4.04, fm.PCT, 1, "(4.0%)"), (6.25, fm.PCT, 1, "6.3%"), (2.25, fm.PCT, 1, "2.3%"),  # half-up, not banker's
    (1.005, fm.PRICE, 2, "1.01"), (1234.5, fm.NUMBER, 2, "1,234.50"), (15.46, fm.MULTIPLE, 1, "15.5x"),
    (-0.04, fm.PCT, 1, "0.0%"), (None, fm.PCT, 1, "-"), ("x", fm.TEXT, 0, "x"), ("", fm.TEXT, 0, "-"),
])
def test_fmt_value_follows_the_report_conventions(value, fmt, dec, expected):
    assert fm.fmt_value(value, fmt, dec) == expected


@pytest.mark.parametrize("text,expected", [
    ("2 9.65", 29.65), ("8 ,674,903,573", 8674903573.0), ("1 12.28", 112.28), ("8.7781%", 8.7781),
    ("-", None), ("", None), (None, None),
])
def test_clean_pdf_number_repairs_kerned_digits(text, expected):
    assert fm.clean_pdf_number(text) == expected


def test_clean_pdf_number_refuses_to_guess():
    with pytest.raises(ArithmeticError):
        fm.clean_pdf_number("n.a.")


# --- tables ------------------------------------------------------------------------

def test_formatted_table_checks_clean():
    rep = check_table_block(table())
    assert rep.flags == [] and rep.checked == 4  # 2 rows x 2 numeric columns


def test_tampered_figure_is_a_mismatch_with_no_tolerance():
    rows = fm.format_rows(SRC, COLS)
    rows[0]["price"] = "29.66"
    rep = check_table_block(table(rows))
    assert [(f.kind, f.subject, f.field) for f in rep.flags] == [(MISMATCH, "t/A", "price")]


def test_missing_failed_and_unsourced_rows():
    src = SRC + [{"k": "C", "name": "Gamma", "price": None, "wow_pct": None, "error": "timeout"}]
    rows = [r for r in fm.format_rows(SRC, COLS)]
    rows[1] = {**rows[1], "k": "Z"}
    rep = check_table_block(table(rows, src))
    kinds = sorted((f.kind, f.subject) for f in rep.flags)
    assert kinds == [(MISSING, "t/B"), (MISSING, "t/C"), (UNSOURCED, "t/Z")]


# --- claims -----------------------------------------------------------------------

def test_row_marked_incomplete_is_flagged_even_though_every_figure_matches_its_source():
    """An average over some of its inputs equals its own derivation exactly; the source row's ``incomplete`` flags it."""
    src = [dict(SRC[0], incomplete={"price": "average of 9 of 12 bonds: no price for X"}), dict(SRC[1])]
    block = table(src=src)
    assert check_table_block(dict(block, source_rows=[SRC[0], SRC[1]])).clean  # the same rows without the mark are clean
    report = check_table_block(block)
    assert [(f.kind, f.subject, f.field, f.message) for f in report.flags] == [
        (MISSING, "t/A", "price", "incomplete: average of 9 of 12 bonds: no price for X")]
    review = build_review({"section": "x", "blocks": [block]}, report)
    rows = [i for i in review.review_items if i.kind == TABLE_ROW]
    assert [i.status for i in rows] == [FLAGGED, CLEAN]


def test_figures_in_reads_units_and_separators():
    assert figures_in("Sh30.1bn rose 8.75% to 1,234.5 in 2026 (4.0%)") == [
        Decimal("30.1"), Decimal("8.75"), Decimal("1234.5"), Decimal("2026"), Decimal("4.0")]


def test_claim_whose_figures_appear_in_the_cited_text_is_not_marked_verified():
    res = check_claim("b", 0, {"text": "Loans grew 10% to Sh307.2 billion.", "url": "https://x",
                               "cited_text": "home loans rose 10 percent to Sh307.2 billion"})
    assert res.flags == [] and "appear exactly" in res.note and "not automatically checked" in res.note


def test_claim_figure_absent_from_cited_text_is_flagged():
    res = check_claim("b", 1, {"text": "Loans grew 11%.", "url": "https://x", "cited_text": "loans grew 10 percent"})
    assert [(f.kind, f.subject) for f in res.flags] == [(UNSOURCED, "b#1")] and "11" in res.flags[0].message


def test_claim_without_url_is_unsourced_and_without_cited_text_is_unchecked():
    assert check_claim("b", 0, {"text": "x 5%", "url": ""}).flags[0].kind == UNSOURCED
    res = check_claim("b", 0, {"text": "x 5%", "url": "https://x", "cited_text": ""})
    assert res.flags == [] and "could not be checked" in res.note
    assert "No figures" in check_claim("b", 0, {"text": "a view", "url": "https://x", "cited_text": "y"}).note


# --- review builder -----------------------------------------------------------------

def content(blocks):
    return {"section": "test", "title": "Test", "week_start": "2026-09-26", "week_end": "2026-10-02",
            "blocks": numbered(blocks), "warnings": []}


def narrative(claims):
    return {"kind": "narrative", "id": "n", "headline": "Head", "body_md": "b", "claims": claims, "drafted_by": "fake"}


def test_review_covers_every_row_claim_and_missing_part():
    rows = fm.format_rows(SRC, COLS)
    rows[1]["wow_pct"] = "2.2%"
    c = content([
        table(rows),
        narrative([{"text": "rose 5%", "url": "https://x", "cited_text": "rose 5 percent"},
                   {"text": "rose 6%", "url": "https://x", "cited_text": "rose 5 percent"}]),
        unavailable_block("u", "Universe", "proprietary", "a sheet"),
    ])
    review = build_review(c, check_section(c))
    got = [(i.kind, i.status) for i in review.review_items]
    assert got == [(TABLE_ROW, CLEAN), (TABLE_ROW, FLAGGED), (CLAIM, NOT_AUTO_VERIFIED), (CLAIM, FLAGGED),
                   (UNAVAILABLE_PART, FLAGGED)]
    assert review.review_items[0].ref == "Table: Alpha"
    assert "Universe is not drafted" in review.review_items[4].detail[0].message and "proprietary" in review.review_items[4].context["text"]
    assert review.review_items[2].context["url"] == "https://x"


def test_unavailable_part_must_be_resolved_before_approval():
    c = content([table(), unavailable_block("u", "Universe", "proprietary", "a sheet")])
    review = build_review(c, check_section(c))
    review.accept_all_clean()
    assert not review.is_approvable
    review.review_items[-1].resolve("accept", "acknowledged: published without it")
    assert review.is_approvable


def test_items_round_trip_through_their_dict_form():
    c = content([table(), narrative([{"text": "rose 6%", "url": "https://x", "cited_text": "5"}])])
    for item in build_review(c, check_section(c)).review_items:
        assert ReviewItem.from_dict(item.to_dict()) == item


def test_a_piece_with_no_claims_is_flagged_not_skipped():
    c = content([narrative([])])
    review = build_review(c, check_section(c))
    assert [(i.kind, i.status) for i in review.review_items] == [(CLAIM, FLAGGED)]


def test_refuses_a_report_that_checked_nothing():
    with pytest.raises(ValueError, match="compared no table figures"):
        build_review(content([table()]), CheckReport())


def test_numbered_gives_report_numerals_in_order():
    assert [b["numeral"] for b in numbered([{"kind": "x"}] * 4)] == ["I", "II", "III", "IV"]
