"""check_table_block's optional second sources (common/checks.py).

``extra_sources`` is forwarded to the Digital Payments checker's ``check_figure``, figure
by figure, so a table cell with a second source is judged by the same code as a weekly
Digital Payments figure.  No production caller passes it: no second source exists yet.

Left out, the check must be what it was before the argument existed.  That is pinned by
``fixtures/check_table_block_before.json``, captured from the code before the change
(2026-10-06): every table of the helpers' reviews, and one small table with each kind of
flag planted in it.
"""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from cytonn_weekly.checkers import digital_payments as ck
from cytonn_weekly.checkers.digital_payments import MISMATCH, SOURCES_DISAGREE, SourceValue
from cytonn_weekly.common import formatting as fm
from cytonn_weekly.common.checks import check_table_block, row_subject
from tests import periodic_helpers as ph
from tests import section_helpers as sh

BEFORE = Path(__file__).parent / "fixtures" / "check_table_block_before.json"

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


def planted_table():
    """One table holding a mismatch, an absent row, a failed source row, an incomplete figure and an unsourced row."""
    src = [SRC[0], SRC[1],
           {"k": "C", "name": "Gamma", "price": 5.0, "wow_pct": 1.0, "error": None},
           {"k": "D", "name": "Delta", "price": None, "wow_pct": None, "error": "page did not load"},
           {"k": "E", "name": "Total", "price": 35.655, "wow_pct": 0.0, "error": None,
            "incomplete": {"price": "sum of 2 of 3 rows"}}]
    rows = fm.format_rows(src, COLS)
    for d, s in zip(rows, src):
        d["k"] = s["k"]
    rows[0]["price"] = "29.60"                       # a mismatch
    rows = [r for r in rows if r["k"] != "C"]        # a row absent from the draft
    rows.append({"k": "Z", "name": "Zeta", "price": "1.00", "wow_pct": "1.0%"})   # a row with no source
    return dict(table(), rows=rows, source_rows=src)


def tables():
    """Every table block the helpers' reviews hold, by name, plus the planted one."""
    reviews = {"weekly_equities": sh.equities_review(), "weekly_real_estate": sh.real_estate_review()}
    reviews.update({f"q3_{slug}": build() for slug, build in ph.BUILDERS.items()})
    found = {f"{name}/{b['id']}": b for name, review in reviews.items()
             for b in review.section["blocks"] if b["kind"] == "table"}
    found["planted"] = planted_table()
    found["fixture_clean"] = table()
    return found


def results(**kwargs):
    out = {}
    for name, block in tables().items():
        report = check_table_block(block, **kwargs)
        out[name] = {"checked": report.checked, "flags": [asdict(f) for f in report.flags]}
    return json.loads(json.dumps(out, default=str, sort_keys=True))


# --- left out: unchanged ---------------------------------------------------------

def test_without_extra_sources_every_table_checks_as_it_did_before_the_argument_existed():
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    assert len(before) >= 9 and before["planted"]["flags"]     # the baseline is not an empty one
    assert results() == before


@pytest.mark.parametrize("empty", [None, {}])
def test_none_and_an_empty_mapping_are_the_same_as_leaving_it_out(empty):
    assert results(extra_sources=empty) == json.loads(BEFORE.read_text(encoding="utf-8"))


def test_a_second_source_for_another_table_or_figure_changes_nothing():
    extra = {("other/A", "price"): [SourceValue("alt", 99.0)], (row_subject("t", "A"), "name"): [SourceValue("alt", 99.0)]}
    assert check_table_block(table(), extra_sources=extra).clean


# --- given: exactly check_figure's handling ----------------------------------------

def cell(drafted_price, extra_value):
    """The flags for row A's price, drafted as given, with one second source; and check_figure's own answer."""
    rows = fm.format_rows(SRC, COLS)
    rows[0]["price"] = drafted_price
    extra = [SourceValue("alt", extra_value)]
    subject = row_subject("t", "A")
    report = check_table_block(table(rows), extra_sources={(subject, "price"): extra})
    direct = ck.check_figure("table", subject, "price", drafted_price, 29.65, 2, extra_sources=extra, primary_source="test")
    return report, direct


def test_a_figure_matching_only_the_second_source_is_a_sources_disagree_flag_as_for_a_weekly_figure():
    # check_figure never passes a figure on its second source: two sources that normalize
    # differently are a human call, whichever one the draft equals (test_digital_payments_checks.py,
    # test_sources_disagree_is_raised_even_when_the_draft_matches_one_source).
    report, direct = cell("31.20", 31.2)
    assert direct.kind == SOURCES_DISAGREE
    assert report.flags == [direct] and report.checked == 4
    assert report.flags[0].sources == [{"source": "test", "value": 29.65, "normalized": "29.65"},
                                       {"source": "alt", "value": 31.2, "normalized": "31.20"}]
    # the weekly table's own check, on the same figures, gives the same kind of flag
    weekly = ck.check_table([{"ticker": "V", "company": "Visa", "error": None, "forward_pe": 29.65}],
                            [{"ticker": "V", "forward_pe": "31.2"}], {"forward_pe": 2},
                            extra_sources={("V", "forward_pe"): [SourceValue("alt", 31.2)]})
    assert [f.kind for f in weekly.flags if f.field == "forward_pe"] == [SOURCES_DISAGREE]


def test_a_figure_matching_neither_source_is_still_flagged():
    report, direct = cell("30.00", 31.2)                      # the sources differ: a human call
    assert report.flags == [direct] and direct.kind == SOURCES_DISAGREE
    report, direct = cell("30.00", 29.654)                    # the sources agree at 2 dp: the draft is wrong
    assert report.flags == [direct] and direct.kind == MISMATCH


def test_an_agreeing_second_source_leaves_a_matching_figure_clean():
    report, direct = cell("29.65", 29.654)
    assert direct is None and report.clean and report.checked == 4


def test_only_the_named_figure_gets_the_second_source():
    extra = {(row_subject("t", "A"), "price"): [SourceValue("alt", 31.2)]}
    report = check_table_block(table(), extra_sources=extra)
    assert [(f.subject, f.field, f.kind) for f in report.flags] == [("t/A", "price", SOURCES_DISAGREE)]
