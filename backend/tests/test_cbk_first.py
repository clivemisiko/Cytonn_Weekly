"""CBK first for the figures it publishes: the bulletin's Table 6 before KCB IB, a notice when another source is used,
and the shilling's source line naming the source its rates came from."""

from datetime import date
from types import SimpleNamespace

from cytonn_weekly.common.computed import ANALYST, SOURCE
from cytonn_weekly.equities import weekly as eqw
from cytonn_weekly.fixed_income import weekly as fiw
from cytonn_weekly.weekly import cbk_bulletin, cbk_rates, inputs
from cytonn_weekly.weekly.prose import fallback_notices, typed
from cytonn_weekly.weekly.week import Week

WEEK = Week(date(2026, 10, 2))
MON, TUE, WED, THU, FRI = WEEK.trading_days
LAST_FRI = WEEK.previous_friday
TABLE_6 = "CBK Weekly Bulletin, Table 6"
KCB = "KCB Investment Bank"


def bulletin(days, **values):
    """A bulletin whose Table 6 holds ``days``, each with the same figures."""
    out = cbk_bulletin.Bulletin(issue_date=WEEK.ending)
    out.market = [{"date": d, "nasi": 180.5, "nse_20": 3900.0, "nse_25": 6900.0, "equity_turnover_mn": 400.25, **values}
                  for d in days]
    return out


def kcb_report(day, turnover=500_000_000.0, nasi=200.0):
    return SimpleNamespace(report_date=day, previous_date=None, equities_turnover=turnover,
                           indicators={"nasi": {"current": nasi, "previous": None}})


def kcb_weekly(nasi=(202.0, 200.0)):
    return SimpleNamespace(report_date=WEEK.ending, previous_date=WEEK.previous_friday, equities_turnover=None,
                           indicators={"nasi": {"previous": nasi[0], "current": nasi[1]}})


def market(bulletin=None, weekly=None, daily=None, typed_indices=None, boxes=None):
    return eqw.Market(week=WEEK, inputs=SimpleNamespace(kcb_weekly=weekly, kcb_daily=daily or {}), bulletin=bulletin, rates={},
                      boxes=boxes or {}, year_open_day=None, afx=None, typed_indices=typed_indices)


def test_cbk_is_used_when_it_has_the_figure_and_no_notice_is_given():
    m = market(bulletin([LAST_FRI, MON, TUE, WED, THU]), weekly=kcb_weekly(), daily={MON: kcb_report(MON)})
    level = eqw._level(m, "nasi", "last_week")
    assert (level["value"], level["source"], level["origin"]) == (180.5, TABLE_6, SOURCE)   # not KCB's 202.0
    turnover = eqw._day_turnover(m, MON)
    assert (turnover["value"], turnover["source"]) == (400_250_000.0, TABLE_6)
    assert turnover["second"]["source"].startswith(f"{KCB} daily report")   # KCB stays as the second reading
    assert turnover["decimals"] == -4                                         # compared at the bulletin's precision, as before
    assert fallback_notices(m.fallbacks) == []


def test_the_friday_cbk_does_not_cover_comes_from_kcb_and_the_notice_names_it():
    m = market(bulletin([LAST_FRI, MON, TUE, WED, THU]), weekly=kcb_weekly(),
               daily={d: kcb_report(d) for d in WEEK.trading_days})
    sources = {d: eqw._day_turnover(m, d)["source"] for d in WEEK.trading_days}
    assert [sources[d] for d in (MON, TUE, WED, THU)] == [TABLE_6] * 4
    assert sources[FRI] == f"{KCB} daily report, 2026-10-02, trading stats"
    today = eqw._level(m, "nasi", "today")
    assert (today["value"], today["source"]) == (200.0, f"{KCB} weekly report, 2026-10-02")
    notices = {n["figure"]: n for n in fallback_notices(m.fallbacks)}
    assert notices["Equities turnover"]["text"] == (
        "Equities turnover for Friday 2 Oct came from the KCB Investment Bank daily report. CBK Table 6 does not cover that day.")
    assert notices["NASI close"]["text"] == (
        "NASI close for Friday 2 Oct came from the KCB Investment Bank weekly report. CBK Table 6 does not cover that day.")
    n = notices["NASI close"]
    assert (n["kind"], n["level"], n["source"], n["days"]) == ("source", "info", f"{KCB} weekly report", ["2026-10-02"])
    assert set(n) >= {"location", "reason", "issue_date", "sha256", "text"}   # the shape the review screen already reads
    assert (today["origin"], eqw._day_turnover(m, FRI)["origin"]) == (SOURCE, SOURCE)   # KCB is not marked as not verified


def test_with_no_bulletin_the_current_source_is_used_and_the_notice_says_why():
    m = market(None, daily={d: kcb_report(d) for d in WEEK.trading_days})
    assert {eqw._day_turnover(m, d)["source"].split(",")[0] for d in WEEK.trading_days} == {f"{KCB} daily report"}
    [notice] = fallback_notices(m.fallbacks)
    assert notice["days"] == [d.isoformat() for d in WEEK.trading_days]
    assert notice["text"] == ("Equities turnover for Monday 28 Sep, Tuesday 29 Sep, Wednesday 30 Sep, Thursday 1 Oct and "
                              "Friday 2 Oct came from the KCB Investment Bank daily report. The CBK Weekly Bulletin for this "
                              "week was not available.")


def test_a_day_table_6_lists_without_the_figure_says_so():
    m = market(bulletin([MON], equity_turnover_mn=None), daily={MON: kcb_report(MON)})
    assert eqw._day_turnover(m, MON)["source"].startswith(f"{KCB} daily report")
    assert fallback_notices(m.fallbacks)[0]["reason"].endswith("CBK Table 6 has no figure for that day.")


def test_a_typed_value_still_stands_where_nothing_is_published_and_gives_no_cbk_notice():
    cell = SimpleNamespace(number=199.0, value=199.0, ref="'NSE Indices'!B5")
    m = market(None, typed_indices={"nasi": {"today": cell}})
    level = eqw._level(m, "nasi", "today")
    assert (level["value"], level["origin"]) == (199.0, ANALYST)   # analyst input: not auto-verified, as before
    assert fallback_notices(m.fallbacks) == []


def test_an_index_cbk_does_not_publish_gives_no_notice():
    m = market(bulletin([LAST_FRI]), boxes={FRI: SimpleNamespace(values={"nse_10": 2500.0})})
    assert eqw._level(m, "nse_10", "today")["source"] == "NSE daily price list of 2026-10-02"
    assert fallback_notices(m.fallbacks) == []


# ---------------------------------------------------------------------------
# The shilling's source line
# ---------------------------------------------------------------------------

CBK_RATES = cbk_rates.SOURCE_NAME


def _figure(*sources):
    return {"inputs": {f"i{n}": {"source": s} for n, s in enumerate(sources)}}


def test_the_shilling_source_line_names_only_the_sources_used():
    cbk = {"name": CBK_RATES, "url": cbk_rates.PAGE}
    assert fiw._rate_sources([_figure(CBK_RATES, CBK_RATES)], CBK_RATES) == [cbk]
    assert fiw._rate_sources([_figure("CBK Weekly Bulletin, Table 1")], CBK_RATES) == [
        {"name": "CBK Weekly Bulletin, Table 1", "url": cbk_bulletin.LISTING}]
    cell = SimpleNamespace(number=129.5, value=129.5, ref="'KES'!B9")
    from_book = typed(cell, fiw.WB)["source"]
    assert fiw._rate_sources([_figure(CBK_RATES, from_book)], CBK_RATES) == [cbk, {"name": fiw.WB}]


def test_the_shilling_paragraph_from_cbks_rates_does_not_name_the_workbook(tmp_path):
    rates = {date(2026, 1, 2): 129.2, LAST_FRI: 129.6, WEEK.ending: 129.7}
    blocks = fiw.shilling_blocks(inputs.WeeklyInputs(WEEK, tmp_path), None, rates, WEEK, None, [])
    shilling = next(b for b in blocks if b["id"] == "shilling")
    assert shilling["kind"] == "computed"
    assert shilling["sources"] == [{"name": CBK_RATES, "url": cbk_rates.PAGE}]
    assert all(i["source"] == CBK_RATES for f in shilling["figures"] for i in f["inputs"].values())
