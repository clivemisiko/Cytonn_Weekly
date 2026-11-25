import json

from cytonn_weekly.agent import readiness
from cytonn_weekly.equities import weekly as eqw
from cytonn_weekly.weekly import analyst, inputs
from tests import test_weekly_equities as eq_tests
from tests import weekly_helpers as wh
from tests.weekly_helpers import text_pdfs  # noqa: F401 - a fixture

WEEK = wh.WEEK


def slugs(root):
    return [s["slug"] for s in inputs.status(WEEK, root)["slots"]]


def ready_keys(root):
    got = readiness.classify("equities", inputs.status(WEEK, root), None)
    return {e["key"] for g in got["groups"].values() for e in g}


def test_off_by_default_the_slot_is_in_no_list(tmp_path):
    assert inputs.SHOW_KCB_WEEKLY is False
    assert "kcb_weekly" not in slugs(tmp_path) and "kcb_weekly" not in ready_keys(tmp_path)
    assert [s for s in slugs(tmp_path) if s in ("equities_workbook", "kcb_daily", "cbk_bulletin")] == \
        ["equities_workbook", "kcb_daily", "cbk_bulletin"]   # the Equities card's three
    from cytonn_weekly.agent import read_tools
    assert "kcb_weekly" not in read_tools.SLOT_SLUGS
    assert "kcb_weekly" in inputs.BY_SLUG   # the route and the readers still know it


def test_on_the_slot_is_listed_and_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(inputs, "SHOW_KCB_WEEKLY", True)
    assert "kcb_weekly" in slugs(tmp_path) and "kcb_weekly" in ready_keys(tmp_path)


def test_a_stored_weekly_report_is_still_read_while_hidden(tmp_path, text_pdfs):
    inputs.store(WEEK, "equities_workbook", wh.equities_workbook_bytes(), "Equities.xlsx", tmp_path)
    inputs.store(WEEK, "kcb_weekly", wh.fake_pdf(wh.kcb_weekly_text()), "weekly.pdf", tmp_path)
    assert "kcb_weekly" not in slugs(tmp_path)
    review = eq_tests.build(tmp_path)
    caps = eq_tests.blocks(review)["large_caps"]
    assert any("second" in f for f in caps["figures"])   # KCB IB's change is each mover's second reading
    assert any("weekly report" in s["name"] for s in caps["sources"])


def test_the_messages_follow_the_switch(monkeypatch):
    why, fix = eqw.need_movers_source()
    assert "equities workbook" in why and "Gainers & Losers" in fix and "weekly report" not in why + fix
    why, fix = eqw.foreign_missing("Monday 28 Sep 2026")
    assert "daily report" in why and "weekly report" not in why + fix
    assert "Gainers & Losers" in analyst.LARGE_CAPS_HELP and "week-on-week" not in analyst.LARGE_CAPS_HELP
    monkeypatch.setattr(inputs, "SHOW_KCB_WEEKLY", True)
    assert eqw.need_movers_source() == eqw.NEED_KCB_WEEKLY
    why, fix = eqw.foreign_missing("Monday 28 Sep 2026")
    assert "KCB IB's weekly report (which lists each weekday)" in why and fix.startswith("KCB IB's weekly report, or")


def test_with_no_workbook_and_no_weekly_report_the_movers_ask_for_the_workbook(tmp_path, text_pdfs):
    review = eq_tests.build(tmp_path)
    text = json.dumps(eq_tests.blocks(review)["large_caps"])
    assert "Gainers & Losers" in text and "KCB IB's weekly report for the Friday" not in text
