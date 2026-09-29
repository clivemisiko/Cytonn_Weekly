"""Unit tests for cytonn_weekly.checkers.digital_payments (task 6a).

Pure exact-match logic on mocked figures; no network, no LLM.
"""

from decimal import Decimal

import pytest

from cytonn_weekly.checkers import digital_payments as ck
from cytonn_weekly.checkers.digital_payments import (
    MISMATCH, MISSING, NOT_IMPLEMENTED, SOURCES_DISAGREE, UNSOURCED, SourceValue,
)


def src(ticker, price=100.0, prior=90.0, ytd_open=80.0, wow=11.11, ytd=25.0, pe=24.99, error=None):
    if error:
        return {"ticker": ticker, "error": error, "current_price": None, "prior_close": None,
                "ytd_open": None, "wow_pct": None, "ytd_pct": None, "forward_pe": None}
    return {"ticker": ticker, "error": None, "current_price": price, "prior_close": prior,
            "ytd_open": ytd_open, "wow_pct": wow, "ytd_pct": ytd, "forward_pe": pe}


def drafted(ticker, price=100.0, prior=90.0, ytd_open=80.0, wow=11.11, ytd=25.0, pe=25.0):
    return {"ticker": ticker, "current_price": price, "prior_close": prior,
            "ytd_open": ytd_open, "wow_pct": wow, "ytd_pct": ytd, "forward_pe": pe}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (24.99, "25.0"), (24.94, "24.9"), (24.95, "25.0"), (24.05, "24.1"),  # half up
    (2.675, "2.7"), (-1.25, "-1.3"), ("24.99", "25.0"),
])
def test_normalize_one_decimal_rounds_half_up(raw, expected):
    assert str(ck.normalize(raw, 1)) == expected


@pytest.mark.parametrize("raw,val", [
    ("$1,234.50", "1234.50"), ("+1.22%", "1.22"), ("-3.4%", "-3.4"), ("24.5x", "24.5"),
    ("−3.4", "-3.4"), ("£870.40", "870.40"), (5, "5"), (Decimal("2.5"), "2.5"),
])
def test_parse_number_strips_display_formatting(raw, val):
    assert ck.parse_number(raw) == Decimal(val)


@pytest.mark.parametrize("bad", ["abc", "", True, None, float("nan"), float("inf"), [1]])
def test_parse_number_rejects_non_numbers(bad):
    with pytest.raises(ValueError):
        ck.parse_number(bad)


# ---------------------------------------------------------------------------
# check_figure: pass / normalized pass / mismatch
# ---------------------------------------------------------------------------

def test_exact_match_passes():
    assert ck.check_figure("table", "V", "current_price", 367.79, 367.79, 2) is None


def test_normalized_equal_passes_25_0_vs_24_99_at_one_decimal():
    assert ck.check_figure("table", "V", "forward_pe", 25.0, 24.99, 1) is None


def test_formatted_drafted_string_passes_when_equal():
    assert ck.check_figure("table", "V", "wow_pct", "+1.22%", 1.2199, 2) is None
    assert ck.check_figure("table", "V", "forward_pe", "25.0x", 24.99, 1) is None


def test_no_tolerance_band_off_by_one_display_unit_is_a_mismatch():
    f = ck.check_figure("table", "V", "forward_pe", 25.1, 24.99, 1)
    assert f.kind == MISMATCH and f.expected == "25.0" and f.drafted == 25.1
    assert f.source_value == 24.99 and f.decimals == 1


def test_tiny_difference_is_still_a_mismatch_at_display_precision():
    f = ck.check_figure("table", "V", "current_price", 367.80, 367.79, 2)
    assert f.kind == MISMATCH  # 0.003% apart, still an error


def test_drafted_with_extra_precision_is_flagged_with_note():
    f = ck.check_figure("table", "V", "forward_pe", 24.99, 24.99, 1)
    assert f.kind == MISMATCH and "more than the 1 display decimals" in f.message


def test_unparseable_drafted_value_is_a_mismatch_flag():
    f = ck.check_figure("table", "V", "forward_pe", "twenty", 24.99, 1)
    assert f.kind == MISMATCH and "unreadable" in f.message


def test_absent_drafted_figure_with_source_is_missing():
    f = ck.check_figure("table", "V", "forward_pe", None, 24.99, 1)
    assert f.kind == MISSING and f.expected == "25.0"


def test_drafted_figure_with_no_source_is_unsourced():
    f = ck.check_figure("table", "CRCL", "forward_pe", 56.3, None, 1)
    assert f.kind == UNSOURCED


@pytest.mark.parametrize("blank", [None, "", "-", "n/a", "n/m", "—"])
def test_both_blank_passes(blank):
    assert ck.check_figure("table", "CRCL", "forward_pe", blank, None, 1) is None


def test_zero_is_a_real_value_not_blank():
    assert ck.check_figure("table", "V", "wow_pct", 0.0, 0.0, 2) is None
    assert ck.check_figure("table", "V", "wow_pct", None, 0.0, 2).kind == MISSING


# ---------------------------------------------------------------------------
# Sources-disagree: its own flag type
# ---------------------------------------------------------------------------

def test_sources_disagree_is_a_distinct_flag_with_all_sources_listed():
    f = ck.check_figure(
        "table", "V", "forward_pe", 25.0, 24.99, 1,
        extra_sources=[SourceValue("other-vendor", 27.4)], primary_source="yahoo",
    )
    assert f.kind == SOURCES_DISAGREE and f.kind != MISMATCH
    assert f.sources == [
        {"source": "yahoo", "value": 24.99, "normalized": "25.0"},
        {"source": "other-vendor", "value": 27.4, "normalized": "27.4"},
    ]
    assert "does not imply the draft is wrong" in f.message


def test_sources_disagree_is_raised_even_when_the_draft_matches_one_source():
    f = ck.check_figure("table", "V", "forward_pe", 27.4, 24.99, 1,
                        extra_sources=[SourceValue("other", 27.4)])
    assert f.kind == SOURCES_DISAGREE


def test_agreeing_sources_after_normalization_are_not_a_disagreement():
    # 24.99 and 25.04 both normalize to 25.0 at one decimal.
    assert ck.check_figure("table", "V", "forward_pe", 25.0, 24.99, 1,
                           extra_sources=[SourceValue("other", 25.04)]) is None


def test_agreeing_sources_but_wrong_draft_is_an_ordinary_mismatch():
    f = ck.check_figure("table", "V", "forward_pe", 30.0, 24.99, 1,
                        extra_sources=[SourceValue("other", 25.04)])
    assert f.kind == MISMATCH


def test_blank_extra_source_is_ignored():
    assert ck.check_figure("table", "V", "forward_pe", 25.0, 24.99, 1,
                           extra_sources=[SourceValue("other", None)]) is None


def test_table_check_accepts_extra_sources_keyed_by_ticker_and_field():
    r = ck.check_table([src("V")], [drafted("V")],
                       extra_sources={("V", "forward_pe"): [SourceValue("alt", 40.0)]})
    assert [f.kind for f in r.flags] == [SOURCES_DISAGREE]
    assert (r.flags[0].subject, r.flags[0].field) == ("V", "forward_pe")


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

def test_table_all_match_including_normalized_pe_is_clean():
    rows = [src("V"), src("MA", price=567.65)]
    d = [drafted("V"), drafted("MA", price=567.65)]
    r = ck.check_table(rows, d)
    assert r.clean and r.flags == []
    assert r.checked == 2 * len(ck.TABLE_DECIMALS)


def test_table_mismatch_names_the_ticker_and_field():
    r = ck.check_table([src("V"), src("MA")], [drafted("V"), drafted("MA", wow=11.12)])
    assert [(f.kind, f.subject, f.field) for f in r.flags] == [(MISMATCH, "MA", "wow_pct")]
    assert not r.clean


def test_table_covers_all_six_figures():
    d = drafted("V", price=101, prior=91, ytd_open=81, wow=12, ytd=26, pe=26)
    r = ck.check_table([src("V")], [d])
    assert {f.field for f in r.flags} == set(ck.TABLE_DECIMALS)


def test_table_accepts_formatted_display_strings():
    d = {"ticker": "V", "current_price": "$100.00", "prior_close": "$90.00", "ytd_open": "$80.00",
         "wow_pct": "+11.11%", "ytd_pct": "+25.00%", "forward_pe": "25.0x"}
    assert ck.check_table([src("V")], [d]).clean


def test_table_missing_drafted_row_and_unsourced_extra_row():
    r = ck.check_table([src("V"), src("MA")], [drafted("V"), drafted("ZZZ")])
    kinds = {(f.kind, f.subject) for f in r.flags}
    assert kinds == {(MISSING, "MA"), (UNSOURCED, "ZZZ")}


def test_table_failed_source_row_is_flagged_not_compared():
    r = ck.check_table([src("V", error="down")], [drafted("V")])
    assert len(r.flags) == 1 and r.flags[0].kind == MISSING and "down" in r.flags[0].message
    assert r.checked == 0


def test_table_source_without_pe_and_draft_without_pe_passes():
    s = src("CRCL")
    s["forward_pe"] = None
    d = drafted("CRCL", pe=None)
    assert ck.check_table([s], [d]).clean


def test_table_custom_decimals_override():
    r = ck.check_table([src("V", pe=24.99)], [drafted("V", pe=24.99)], decimals={"forward_pe": 2})
    assert r.clean and r.checked == 1


# ---------------------------------------------------------------------------
# Outlook stats
# ---------------------------------------------------------------------------

ROWS = [src("V", wow=1.0, ytd=10.0, pe=20.0), src("MA", wow=-3.0, ytd=2.0, pe=30.0),
        src("AXP", wow=5.0, ytd=-4.0, pe=10.0), src("GPN", error="x")]

GOOD_STATS = {"companies_included": 3, "companies_failed": 1, "avg_wow_pct": 1.0,
              "avg_ytd_pct": 2.67, "advancers": 2, "decliners": 1, "avg_forward_pe": 20.0}


def test_expected_outlook_stats_recomputed_from_source_rows():
    e = ck.expected_outlook_stats(ROWS)
    assert e["companies_included"] == 3 and e["companies_failed"] == 1
    assert e["advancers"] == 2 and e["decliners"] == 1
    assert float(e["avg_wow_pct"]) == 1.0 and float(e["avg_forward_pe"]) == 20.0
    assert str(ck.normalize(e["avg_ytd_pct"], 2)) == "2.67"


def test_outlook_stats_matching_the_table_are_clean():
    r = ck.check_outlook_stats(GOOD_STATS, ROWS)
    assert r.clean and r.checked == len(ck.OUTLOOK_DECIMALS)


def test_outlook_stat_mismatch_is_flagged_per_stat():
    bad = dict(GOOD_STATS, avg_forward_pe=21.0, advancers=3)
    r = ck.check_outlook_stats(bad, ROWS)
    assert {(f.kind, f.field) for f in r.flags} == {(MISMATCH, "avg_forward_pe"), (MISMATCH, "advancers")}
    assert all(f.scope == "outlook" for f in r.flags)


def test_outlook_stat_normalization_applies_to_averages():
    # true avg ytd = 2.6666...; drafted 2.67 passes, 2.66 does not.
    assert ck.check_outlook_stats(dict(GOOD_STATS, avg_ytd_pct=2.66), ROWS).flags[0].field == "avg_ytd_pct"


def test_outlook_missing_and_unknown_stats():
    stats = {k: v for k, v in GOOD_STATS.items() if k != "avg_forward_pe"}
    stats["mystery"] = 1
    r = ck.check_outlook_stats(stats, ROWS)
    assert {(f.kind, f.field) for f in r.flags} == {(MISSING, "avg_forward_pe"), (UNSOURCED, "mystery")}


def test_outlook_without_any_pe_source_passes_when_draft_omits_it():
    rows = [dict(r, forward_pe=None) for r in ROWS]
    stats = {k: v for k, v in GOOD_STATS.items() if k != "avg_forward_pe"}
    assert ck.check_outlook_stats(stats, rows).clean


def test_outlook_stats_agree_with_the_drafters_own_table_stats():
    from cytonn_weekly.drafters.digital_payments_highlights import table_stats

    assert ck.check_outlook_stats(table_stats(ROWS), ROWS).clean


def test_outlook_sources_disagree_extension_point():
    r = ck.check_outlook_stats(GOOD_STATS, ROWS,
                               extra_sources={("outlook", "avg_forward_pe"): [SourceValue("alt", 22.0)]})
    assert [f.kind for f in r.flags] == [SOURCES_DISAGREE]


# ---------------------------------------------------------------------------
# Highlight stub + entrypoint
# ---------------------------------------------------------------------------

def test_verify_highlight_claim_is_an_explicit_stub():
    flags = ck.verify_highlight_claim({"headline": "Visa thing", "claims": []})
    assert [f.kind for f in flags] == [NOT_IMPLEMENTED]
    assert flags[0].scope == "highlight" and flags[0].subject == "Visa thing"


def test_entrypoint_runs_all_parts_and_routes_highlights_to_the_stub():
    report = ck.check_digital_payments(
        ROWS[:3],
        drafted_rows=[drafted("V", pe=25.0) | {"forward_pe": 20.0}, drafted("MA", wow=-3.0, ytd=2.0, pe=30.0),
                      drafted("AXP", wow=5.0, ytd=-4.0, pe=10.0)],
        drafted_outlook_stats=dict(GOOD_STATS, companies_failed=0, avg_forward_pe=20.0),
        highlights=[{"headline": "A"}, {"headline": "B"}],
    )
    kinds = [f.kind for f in report.flags]
    assert kinds.count(NOT_IMPLEMENTED) == 2
    assert {f.scope for f in report.flags if f.kind != NOT_IMPLEMENTED} <= {"table"}
    assert report.checked == 3 * len(ck.TABLE_DECIMALS) + len(ck.OUTLOOK_DECIMALS)
    assert not report.clean  # unchecked highlights keep the report from being clean


def test_entrypoint_checks_only_the_parts_given():
    r = ck.check_digital_payments([src("V")], drafted_rows=[drafted("V")])
    assert r.clean and r.checked == len(ck.TABLE_DECIMALS)
    assert ck.check_digital_payments([src("V")]).checked == 0


def test_entrypoint_collects_mismatch_and_disagreement_separately():
    r = ck.check_digital_payments(
        [src("V")], drafted_rows=[drafted("V", price=101.0)],
        extra_sources={("V", "forward_pe"): [SourceValue("alt", 40.0)]},
    )
    assert len(r.by_kind(MISMATCH)) == 1 and len(r.by_kind(SOURCES_DISAGREE)) == 1
