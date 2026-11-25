import re

import pytest

from cytonn_weekly import report_sections
from cytonn_weekly.report_types import WEEKLY
from cytonn_weekly.weekly import analyst, inputs
from tests import section_helpers as sh
from tests import test_weekly_equities as eq_tests
from tests import test_weekly_fixed_income as fi_tests
from tests import weekly_helpers as wh
from tests.weekly_helpers import text_pdfs  # noqa: F401 - a fixture

WEEK = wh.WEEK
ITEMS = (*analyst.FIELD_LIST, *analyst.TABLE_LIST)
OPTIONAL_TODAY = {"cmmf_last_week", "liquidity_driver", "fiscal_year_start", "foreign_prior_year", "borrowing_log"}

# WeeklyInputs caches each input under one of these keys; every read of one goes through WeeklyInputs._once.
CACHE_KEY = {"eq": inputs.EQUITIES_WORKBOOK, "fi": inputs.FI_WORKBOOK, "dp": inputs.DP_WORKBOOK, "kcbw": inputs.KCB_WEEKLY,
             "kcbd": inputs.KCB_DAILY, "bulletin": inputs.CBK_BULLETIN, "curve": inputs.NSE_YIELD_CURVE}
# Equities opens the fixed income workbook only for a second reading of the exchange rates, CBK's own being the source, so the
# slot does not list Equities and week_status does not ask Equities for it.
SECOND_SOURCE = {"equities": {inputs.FI_WORKBOOK}}


def test_required_is_false_exactly_where_the_label_or_help_says_optional():
    said = {i.key for i in ITEMS if re.search("optional", f"{i.label} {i.help}", re.I)}
    assert {i.key for i in ITEMS if not i.required} == said == OPTIONAL_TODAY


def test_both_status_outputs_carry_the_new_facts(tmp_path):
    slots = inputs.status(WEEK, tmp_path)["slots"]
    assert {s["slug"]: s["sections"] for s in slots} == {
        "equities_workbook": ["equities"], "fi_workbook": ["fixed_income"], "kcb_daily": ["equities"],
        "cbk_bulletin": ["fixed_income", "equities"], "nse_yield_curve": ["fixed_income"], "dp_workbook": ["digital_payments"]}
    form = analyst.status(WEEK, tmp_path)["groups"]
    assert {i["key"] for g in form for i in g["items"] if not i["required"]} == OPTIONAL_TODAY


@pytest.fixture
def reads(monkeypatch):
    assert set(CACHE_KEY.values()) == set(inputs.BY_SLUG)   # a new slot must be added to the map above
    seen: set[str] = set()
    real = inputs.WeeklyInputs._once

    def once(self, key, load):
        if key in CACHE_KEY:
            seen.add(CACHE_KEY[key])
        return real(self, key, load)

    monkeypatch.setattr(inputs.WeeklyInputs, "_once", once)
    return seen


def listed(section):
    return {s.slug for s in inputs.SLOTS if section in s.sections} | SECOND_SOURCE.get(section, set())


def test_the_fixed_income_builder_reads_only_the_slots_listed_for_it(tmp_path, reads):
    inputs.store(WEEK, "cbk_bulletin", fi_tests.BULLETIN, "b.pdf", tmp_path)
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(), "FI.xlsx", tmp_path)
    fi_tests.build(tmp_path)
    assert {"fi_workbook", "cbk_bulletin"} <= reads <= listed("fixed_income")


def test_the_equities_builder_reads_only_the_slots_listed_for_it(tmp_path, text_pdfs, reads):
    inputs.store(WEEK, "equities_workbook", wh.equities_workbook_bytes(), "E.xlsx", tmp_path)
    inputs.store(WEEK, "kcb_weekly", wh.fake_pdf(wh.kcb_weekly_text()), "w.pdf", tmp_path)
    inputs.store(WEEK, "kcb_daily", wh.fake_pdf(wh.kcb_daily_text(WEEK.ending, turnover=500_000_000)), "f.pdf", tmp_path)
    inputs.store(WEEK, "cbk_bulletin", eq_tests.BULLETIN, "b.pdf", tmp_path)
    eq_tests.build(tmp_path)
    assert {"equities_workbook", "kcb_weekly", "kcb_daily", "cbk_bulletin"} <= reads <= listed("equities")


def test_the_digital_payments_draft_reads_only_its_workbook(tmp_path, reads, monkeypatch):
    monkeypatch.setattr("cytonn_weekly.digital_payments.review_run.build_digital_payments_review", lambda **kw: "built")
    ctx = report_sections.DraftContext(report_type=WEEKLY, period="Week ending 2026-10-02", week_ending=WEEK.ending, inputs_root=tmp_path)
    assert report_sections.spec_for(WEEKLY, "digital_payments").build(ctx) == "built"
    assert reads == listed("digital_payments") == {"dp_workbook"}


def test_the_real_estate_and_focus_drafts_read_no_weekly_input_at_all(reads):
    # Neither builder takes WeeklyInputs (Real Estate reads snips, Focus reads sources), so this only pins that they stay that way.
    sh.real_estate_review()
    sh.focus_review()
    assert reads == set() and not any({"real_estate", "focus"} & set(s.sections) for s in inputs.SLOTS)
