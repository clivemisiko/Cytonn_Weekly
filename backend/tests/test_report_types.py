"""Report types, period labels, and the section registry per type (report_types.py, report_sections.py)."""

from datetime import date

import pytest

from cytonn_weekly import report_sections as rs
from cytonn_weekly.periodic import (
    company_updates,
    companion,
    digital_payments,
    equities,
    executive_summary,
    fixed_income,
    global_markets,
    kenya_macro,
    real_estate,
    ssa,
)
from cytonn_weekly.periodic.common import PeriodContext
from cytonn_weekly.report_types import (
    PeriodError,
    normalize_period,
    period_window,
    prose_label,
    suggested_period,
    year_ago,
)

# ---------------------------------------------------------------------------
# Period labels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("report_type, typed, stored", [
    ("quarterly", "Q3'2026", "Q3'2026"),
    ("quarterly", "q3 2026", "Q3'2026"),
    ("quarterly", "Q1’2026", "Q1'2026"),       # the report's own curly apostrophe
    ("half_year", "H1 2026", "H1'2026"),
    ("annual", "2025", "FY'2025"),
    ("annual", "FY'2025", "FY'2025"),
    ("weekly", "#38.2026", "Weekly #38.2026"),
    ("weekly", "Weekly #8/2026", "Weekly #08.2026"),
    ("weekly", "", ""),                              # unlabelled, as every pre-report-type run
    ("companion", "weekly #37.2026", "Weekly #37.2026"),
])
def test_periods_are_stored_normalized(report_type, typed, stored):
    assert normalize_period(report_type, typed) == stored


@pytest.mark.parametrize("report_type, typed, says", [
    ("quarterly", "Q2'2026", "half-year"),   # Cytonn publishes Q2 as the H1 review
    ("quarterly", "Q4'2026", "annual"),      # and Q4 as the annual review
    ("half_year", "H2'2026", "annual"),
    ("quarterly", "", "needs a period"),
    ("annual", "", "needs a period"),
    ("companion", "", "needs a period"),
    ("weekly", "next week", "issue number"),
    ("weekly", "#60.2026", "issue number"),
    ("quarterly", "Q3", "not a quarter"),
    ("monthly", "x", "unknown report type"),
])
def test_periods_that_do_not_fit_are_refused_with_a_reason(report_type, typed, says):
    with pytest.raises(PeriodError, match=says):
        normalize_period(report_type, typed)


def test_period_windows_and_framing():
    assert period_window("quarterly", "Q3'2026") == (date(2026, 7, 1), date(2026, 9, 30))
    assert period_window("quarterly", "Q1'2026") == (date(2026, 1, 1), date(2026, 3, 31))
    assert period_window("half_year", "H1'2026") == (date(2026, 1, 1), date(2026, 6, 30))
    assert period_window("annual", "FY'2025") == (date(2025, 1, 1), date(2025, 12, 31))
    assert period_window("weekly", "Weekly #38.2026") is None
    assert year_ago("Q3'2026") == "Q3'2025" and year_ago("FY'2025") == "FY'2024"
    assert prose_label("Q3'2026") == "Q3’2026"


def test_suggested_period_is_the_one_just_ended():
    today = date(2026, 10, 5)  # the day after the Q3'2026 review went out
    assert [suggested_period(t, today) for t in ("weekly", "quarterly", "half_year", "annual", "companion")] == \
        ["", "Q3'2026", "H1'2026", "FY'2025", ""]
    assert suggested_period("quarterly", date(2026, 5, 1)) == "Q1'2026"
    assert suggested_period("quarterly", date(2026, 2, 1)) == "Q3'2025"
    assert suggested_period("half_year", date(2026, 3, 1)) == "H1'2025"


# ---------------------------------------------------------------------------
# Registry per type
# ---------------------------------------------------------------------------

MARKETS_REVIEW = ["executive_summary", "company_updates", "global_markets", "ssa", "kenya_macro", "fixed_income",
                  "equities", "real_estate"]


def test_each_type_has_its_own_section_list_in_report_order():
    assert [s.slug for s in rs.sections_for("weekly")] == ["fixed_income", "equities", "digital_payments",
                                                         "real_estate", "focus"]
    assert rs.sections_for("weekly") is rs.SECTIONS  # unchanged
    assert [s.slug for s in rs.sections_for("quarterly")] == MARKETS_REVIEW + ["digital_payments"]
    assert [s.slug for s in rs.sections_for("half_year")] == MARKETS_REVIEW + ["digital_payments"]
    # FY'2025 predates the Digital Payments section, which first ran in May 2026.
    assert [s.slug for s in rs.sections_for("annual")] == MARKETS_REVIEW
    assert rs.sections_for("companion") == ()  # a companion report lists its sections once a kind is chosen
    with pytest.raises(KeyError):
        rs.sections_for("monthly")


def test_the_same_slug_is_a_different_spec_per_type():
    weekly, quarterly = rs.spec_for("weekly", "fixed_income"), rs.spec_for("quarterly", "fixed_income")
    assert weekly.available is False and "KCB" in weekly.reason       # the weekly section is still blocked
    assert quarterly.available is True and quarterly.build is not None  # the quarter's bond table is CBK's
    assert rs.spec_for("annual", "digital_payments") is None
    assert rs.spec_for("quarterly", "focus") is None                    # Markets Reviews have no Focus of the Week
    assert rs.spec_for("annual", "ssa").title == "Sub-Saharan Africa Regional Review"   # FY'2025's own heading
    assert rs.spec_for("quarterly", "ssa").title == "Sub-Saharan Africa Region Review"   # Q3'2026's


@pytest.mark.parametrize("report_type", ["quarterly", "half_year", "annual"])
def test_markets_review_specs_carry_the_real_issue(report_type):
    for spec in rs.sections_for(report_type):
        assert spec.available and spec.build is not None, spec.slug
        assert spec.subsections, spec.slug
        assert spec.steps[-1][0] == "Your review", spec.slug
    by = {s.slug: s for s in rs.sections_for(report_type)}
    assert by["company_updates"].needs_text and by["company_updates"].subsections == ("Investment Updates:", "Hospitality Updates:")
    assert by["executive_summary"].requires_approved
    assert by["fixed_income"].charts and by["kenya_macro"].charts  # chart titles recorded, not drawn


def test_q3_chart_checklist_matches_the_issue():
    """Q3'2026 has 23 chart images (cytonnreport.com, read 2026-10-05); every one is listed for the coordinator."""
    total = sum(len(s.charts) for s in rs.sections_for("quarterly"))
    assert total == 23
    assert "Bond Issuances" not in " ".join(rs.spec_for("quarterly", "fixed_income").charts)  # tables are not charts
    assert rs.spec_for("quarterly", "kenya_macro").charts[0] == "Kenya's Purchasing Manager's Index for the Last 24 Months"


def test_companion_kinds_are_registered_and_every_section_is_a_stub():
    kinds = {k["slug"]: k for k in rs.companion_kinds()}
    assert set(kinds) == {"ssa_eurobonds", "listed_banks", "reits", "nma_residential"}
    assert kinds["listed_banks"]["issue"] == "Weekly #37.2026" and kinds["reits"]["issue"] == "Weekly #33.2026"
    for kind in kinds:
        specs = rs.sections_for("companion", kind)
        assert len(specs) == 4 and all(s.slug.startswith(f"{kind}.") for s in specs)
        assert all(not s.available and s.reason == companion.BLOCKED_REASON and s.unblock == companion.UNBLOCK
                   for s in specs)
        assert specs[0].title.startswith("Section I:")
        with pytest.raises(NotImplementedError, match="Cytonn's own analysis"):
            companion.build_companion_report(kind)
    assert rs.spec_for("companion", "reits.section_3").title.startswith("Section III: Summary Performance of the REITs")


# ---------------------------------------------------------------------------
# Stubs: NotImplementedError with a named reason and what unblocks it
# ---------------------------------------------------------------------------

MODULES = [global_markets, ssa, kenya_macro, fixed_income, equities, real_estate, digital_payments, company_updates,
           executive_summary]


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_every_stub_fails_loudly_with_its_reason(module):
    ctx = PeriodContext.of("quarterly", "Q3'2026", today=date(2026, 10, 4))
    for stub in module.STUBS:
        assert stub.blocked_reason and stub.unblock, stub.id
        with pytest.raises(NotImplementedError) as exc:
            stub.fetch(ctx)
        assert str(exc.value) == stub.blocked_reason
        block = stub.block()
        assert (block["kind"], block["reason"], block["unblock"]) == ("unavailable", stub.blocked_reason, stub.unblock)


def test_stub_reasons_are_the_module_constants():
    """The kcb_email.py pattern: each stub's reason and unblock are named module constants."""
    assert fixed_income.STUBS[0].blocked_reason is fixed_income.TBILLS_BLOCKED_REASON
    assert {s.id: s.blocked_reason for s in ssa.STUBS}["currency_performance"] is ssa.CURRENCY_BLOCKED_REASON
    assert {s.id: s.unblock for s in kenya_macro.STUBS}["pmi"] is kenya_macro.PMI_UNBLOCK
    assert "Yahoo" in ssa.CURRENCY_BLOCKED_REASON and "129.2" in ssa.CURRENCY_BLOCKED_REASON  # the evidence, not a guess
