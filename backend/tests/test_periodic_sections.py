"""The Markets Review sections: real sources parsed, real pipelines on fake edges (tests/periodic_helpers.py)."""

from datetime import date

import pytest

from api.serialize import is_dev_draft
from cytonn_weekly.common.review import SUPPLIED_TEXT
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.digital_payments.coordinator_review import APPROVED, CLEAN, FLAGGED, NOT_AUTO_VERIFIED
from cytonn_weekly.fixed_income import cbk_auctions
from cytonn_weekly.narrative import anthropic_provider
from cytonn_weekly.narrative.base import NarrativeBrief
from cytonn_weekly.periodic import executive_summary, fixed_income, kenya_macro
from cytonn_weekly.periodic.common import period_brief
from tests import periodic_helpers as ph
from tests import section_helpers as sh

# ---------------------------------------------------------------------------
# Fixed Income: CBK's results PDFs against the real Q3'2026 table
# ---------------------------------------------------------------------------


def q3_table():
    review = ph.fixed_income_review()
    block = next(b for b in review.section["blocks"] if b["id"] == "bond_issuances")
    return review, block, {r["key"]: r for r in block["rows"]}


def test_q3_bond_table_matches_the_issue_where_cbk_and_the_issue_agree():
    """Cytonn Q3' 2026 Markets Review, "Bond Issuances in Q3' 2026", rows as printed (where CBK agrees)."""
    _, block, rows = q3_table()
    assert block["title"] == "Bond Issuances in Q3’2026"
    assert [c["label"] for c in block["columns"]][:3] == ["Issue Date", "Bond Auctioned", "Effective Tenor to Maturity (Years)"]
    first = rows["2026-09-21 FXD1/2019/020"]
    assert [first[k] for k in ("issue_date", "years_to_maturity", "coupon_pct", "offered_kes_bn", "accepted_kes_bn",
                               "bids_kes_bn", "subscription_pct", "acceptance_pct")] == \
        ["21/09/2026", "12.6", "12.9%", "60.0", "33.5", "43.8", "135.7%", "76.4%"]
    second = rows["2026-09-21 FXD1/2026/030"]  # merged cells: the offer and subscription print once per auction
    assert (second["issue_date"], second["offered_kes_bn"], second["subscription_pct"], second["acceptance_pct"]) == \
        ("21/09/2026", "-", "-", "44.5%")
    ifb = rows["2026-08-17 IFB1/2019/016"]
    assert (ifb["coupon_pct"], ifb["accepted_kes_bn"], ifb["subscription_pct"], ifb["acceptance_pct"]) == \
        ("11.8%", "112.6", "306.9%", "67.8%")


def test_q3_totals_exclude_switches_and_reproduce_the_issue():
    """380.0 / 543.8 / 840.4 and the Average's 12.8%, 13.5%, 221.2%, 64.7% are the issue's own figures."""
    _, _, rows = q3_table()
    total, average = rows["Q3'2026 total"], rows["Q3'2026 average"]
    assert (total["offered_kes_bn"], total["accepted_kes_bn"], total["bids_kes_bn"]) == ("380.0", "543.8", "840.4")
    assert (average["coupon_pct"], average["avg_rate_pct"], average["subscription_pct"], average["acceptance_pct"]) == \
        ("12.8%", "13.5%", "221.2%", "64.7%")
    switches = [r for r in rows.values() if r["bond"].endswith("-Switch")]
    assert [r["bond"] for r in switches] == ["FXD4/2019/010-Switch", "FXD4/2019/010-Switch", "FXD1/2012/020-Switch"]


def test_q3_bond_table_checks_clean_and_says_what_cbk_did_not_print():
    review, _, _ = q3_table()
    table_items = {i.ref: i for i in review.review_items if i.kind == "table_row"}
    ago = [r for r in table_items if "Q3'2025" in r]
    avg = next(r for r in table_items if r.endswith("Q3'2026 Average"))
    assert len(table_items) == 19 and all(i.status == CLEAN for r, i in table_items.items() if r not in ago + [avg])
    # The Average tenor matches the tool's own mean of 9 bonds, so only the incompleteness flag keeps it from reading clean.
    assert table_items[avg].status == FLAGGED
    assert [(f.field, f.message) for f in table_items[avg].detail] == [(
        "years_to_maturity",
        "incomplete: average of 9 of 12 bonds: no years_to_maturity for FXD1/2022/010, FXD1/2021/020, FXD1/2026/030")]
    warnings = " ".join(review.section["warnings"])
    # The 13-07-2026 results print no remaining life, so the average is over the bonds that have one.
    assert "over 9 of 12 bonds" in warnings and "FXD1/2022/010" in warnings
    # Last year's PDFs are not captured here: its Total and Average are flagged, never summed from what was read.
    assert len(ago) == 2 and all(table_items[r].status == FLAGGED for r in ago)
    assert "Q3'2025 Total and Average rows are flagged" in warnings


def test_the_three_cbk_layouts_parse():
    tables, text = cbk_auctions._tables_and_text((ph.SOURCES / "cbk_tbond_2026-07-13.pdf").read_bytes())
    issues_in_tenor_row = cbk_auctions.parse_tbond_results(tables, text)
    assert [r["issue"] for r in issues_in_tenor_row["rows"]] == ["FXD1/2022/010", "FXD1/2021/020", "FXD1/2026/030"]
    assert all(r["years_to_maturity"] is None for r in issues_in_tenor_row["rows"])
    tables, text = cbk_auctions._tables_and_text((ph.SOURCES / "cbk_tbond_2025-08-25_tap.pdf").read_bytes())
    tap = cbk_auctions.parse_tbond_results(tables, text)
    assert tap["total_offered_kes_bn"] == 50.0  # "Total Advertised Amount"
    assert [(r["issue"], r["accepted_kes_bn"], r["avg_rate_pct"]) for r in tap["rows"]] == [
        ("IFB1/2018/015", 127.98299, 12.9934), ("IFB1/2022/019", 51.79191, 13.9991)]


def test_period_fetch_reads_the_listing_by_value_date_and_kind():
    out = cbk_auctions.fetch_period_tbonds(date(2026, 7, 1), date(2026, 9, 30), get=ph.cbk_get)
    assert [a["value_date"] for a in out["auctions"]] == sorted(ph.TBOND_PDFS, reverse=True)
    assert {a["kind"] for a in out["auctions"]} == {"primary", "switch"}
    assert cbk_auctions.link_kind("x/TAPSALE RESULTS FOR IFB1 DATED 25-08-2025.pdf") == "tap"
    year_ago = cbk_auctions.fetch_period_tbonds(date(2025, 7, 1), date(2025, 9, 30), get=ph.cbk_get)
    assert [a["kind"] for a in year_ago["auctions"]].count("tap") == 1
    assert all(a["error"] for a in year_ago["auctions"])  # not captured: each keeps its place with the error


def test_tap_sales_count_in_the_summary_and_switches_do_not():
    """Q3'2026's "Q3'2025 Total" counts the 25-08-2025 tap: 200.0 offered by the four primaries, plus its 50.0."""
    tap = {"kind": "tap", "total_offered_kes_bn": 50.0, "rows": [
        {"issue": "IFB1/2018/015", "accepted_kes_bn": 10.0, "bids_kes_bn": 20.0, "coupon_pct": 12.5, "avg_rate_pct": 13.0,
         "years_to_maturity": 7.0}]}
    switch = {"kind": "switch", "total_offered_kes_bn": 15.0, "rows": [
        {"issue": "FXD4/2019/010", "accepted_kes_bn": 21.8, "bids_kes_bn": 21.9, "coupon_pct": 12.3, "avg_rate_pct": 11.2,
         "years_to_maturity": 3.2}]}
    primary = {"kind": "primary", "total_offered_kes_bn": 40.0, "rows": [
        {"issue": "FXD1/2019/020", "accepted_kes_bn": 30.0, "bids_kes_bn": 60.0, "coupon_pct": 12.9, "avg_rate_pct": 13.9,
         "years_to_maturity": 12.8}]}
    (total, average), _ = fixed_income.summary_rows("Q3'2025", [tap, switch, primary])
    assert (total["offered_kes_bn"], total["accepted_kes_bn"], total["bids_kes_bn"]) == (90.0, 40.0, 80.0)
    assert average["subscription_pct"] == pytest.approx(80 / 90 * 100)
    assert average["years_to_maturity"] == pytest.approx(9.9)

# ---------------------------------------------------------------------------
# Kenya Macro: KNBS's CPI release against the real Q3'2026 table
# ---------------------------------------------------------------------------


def test_major_inflation_changes_match_knbs_and_the_issue():
    """"Major Inflation Changes - September 2026" in Q3'2026 is exactly KNBS's Table 1 for the divisions it names."""
    review = ph.kenya_macro_review()
    block = next(b for b in review.section["blocks"] if b["id"] == "major_inflation_changes")
    assert block["title"] == "Major Inflation Changes – September 2026"
    assert [c["label"] for c in block["columns"]] == [
        "Broad Commodity Group", "Price change m/m (September-2026/August-2026)",
        "Price change y/y (September-2026/September-2025)"]
    assert [(r["group"], r["mm_pct"], r["yy_pct"]) for r in block["rows"]] == [
        ("Food and Non-Alcoholic Beverages", "0.9%", "9.5%"),
        ("Transport", "(0.4%)", "15.6%"),
        ("Housing, Water, Electricity, Gas and Other Fuels", "0.1%", "3.2%"),
        ("Overall Inflation", "0.4%", "6.8%"),
    ]
    assert block["source"]["url"].endswith("Kenya-Consumer-Price-Indices-and-Inflation-Rates-September-2026.pdf")
    rows = [i for i in review.review_items if i.kind == "table_row"]
    assert len(rows) == 4 and all(i.status == CLEAN for i in rows)


def test_cpi_release_is_looked_for_in_its_month_then_the_next():
    urls = kenya_macro.cpi_urls(date(2026, 12, 1))
    assert urls[0].startswith("https://www.knbs.or.ke/wp-content/uploads/2026/12/") and "/2027/01/" in urls[1]
    assert urls[0].endswith("Inflation-Rates-December-2026.pdf")


def test_a_missing_cpi_release_is_a_flagged_row_not_a_missing_table():
    def gone(month):
        raise LookupError("KNBS CPI release for September 2026 not found")
    from cytonn_weekly.periodic.kenya_macro import inflation_table
    block, _ = inflation_table(ph.ctx(), gone)
    assert block["source_rows"][0]["error"].startswith("LookupError")


def test_annual_macro_has_its_extra_parts_and_no_budget_table():
    ids = [b["id"] for b in ph.kenya_macro_review(ph.ctx("annual", "FY'2025")).section["blocks"]]
    assert {"credit_ratings", "asset_class_returns", "macro_outlook"} <= set(ids) and "budget_comparison" not in ids
    assert "budget_comparison" in [b["id"] for b in ph.kenya_macro_review().section["blocks"]]

# ---------------------------------------------------------------------------
# Every section, every type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("report_type, period", [("quarterly", "Q3'2026"), ("half_year", "H1'2026"), ("annual", "FY'2025")])
@pytest.mark.parametrize("slug", list(ph.BUILDERS))
def test_each_section_builds_with_its_period_and_charts(report_type, period, slug):
    if report_type == "annual" and slug == "digital_payments":
        with pytest.raises(ValueError, match="no Digital Payments"):
            ph.BUILDERS[slug](ph.ctx(report_type, period))
        return
    review = ph.BUILDERS[slug](ph.ctx(report_type, period))
    sec = review.section
    assert (sec["section"], sec["report_type"], sec["period"]) == (slug, report_type, period)
    assert sec["period_start"] < sec["period_end"]
    # Every missing part is a flagged item the coordinator must acknowledge; nothing is silently left out.
    unavailable = [b for b in sec["blocks"] if b["kind"] == "unavailable"]
    assert len([i for i in review.review_items if i.kind == "unavailable_part"]) == len(unavailable)
    assert all(i.status == FLAGGED for i in review.review_items if i.kind == "unavailable_part")
    if sec["chart_notes"]:
        assert sec["chart_reference"]


def test_period_briefs_name_the_report_and_its_period_not_the_week():
    ctx = ph.ctx()
    brief = period_brief(ctx, "growth", "Global Markets Review", "Growth", "global growth", ("worldbank.org",))
    system = anthropic_provider.system_prompt(brief)
    prompt = anthropic_provider._prompt(brief, False, ctx.start, ctx.end, ctx.today)
    assert "quarterly markets review" in system and "report period" in system and "that week" not in system
    assert "The report period is 2026-07-01 to 2026-09-30" in prompt
    assert "Q3’2026" in brief.focus and brief.opener is None


def test_weekly_prompts_are_unchanged():
    brief = NarrativeBrief(id="x", section="Real Estate", label="Land", focus="land prices")
    system = anthropic_provider.system_prompt(brief)
    assert "section of a weekly investment research report" in system
    assert "published during the report week given in the user" in system and "If nothing published that week" in system
    prompt = anthropic_provider._prompt(brief, False, date(2026, 9, 26), date(2026, 10, 2), date(2026, 10, 2))
    assert "The report week is 2026-09-26 to 2026-10-02" in prompt


def test_period_drafts_search_the_whole_period():
    seen = []

    class Recording(sh.FakeNarrativeProvider):
        def draft_piece(self, brief, *, start, end, today):
            seen.append((start, end))
            return super().draft_piece(brief, start=start, end=end, today=today)

    ph.global_markets_review(provider=Recording())
    assert set(seen) == {(date(2026, 7, 1), date(2026, 9, 30))}

# ---------------------------------------------------------------------------
# Digital Payments, Company Updates, Executive Summary
# ---------------------------------------------------------------------------


def test_quarterly_digital_payments_table_has_the_period_columns():
    review = ph.digital_payments_review()
    table = next(b for b in review.section["blocks"] if b["kind"] == "table")
    assert [c["label"] for c in table["columns"]] == [
        "Company", "Year Open 2026", "Price 6/30/2026", "Price 9/25/2026", "Price 9/30/2026", "Price 10/02/2026",
        "w/w change", "Q/Q change", "YTD change", "Forward P/E"]
    visa = next(r for r in table["rows"] if r["ticker"] == "V")
    assert (visa["period_start_close"], visa["period_end_close"], visa["period_pct"]) == ("80.0", "96.0", "20.0%")
    assert "month_change" in [b["id"] for b in review.section["blocks"]]   # m/m: its base date is unverified
    assert all(i.status == CLEAN for i in review.review_items if i.kind == "table_row")


def test_half_year_digital_payments_follows_h1s_columns():
    review = ph.digital_payments_review(ph.ctx("half_year", "H1'2026", today=date(2026, 7, 5)))
    table = next(b for b in review.section["blocks"] if b["kind"] == "table")
    labels = [c["label"] for c in table["columns"]]
    assert "Q/Q change" not in labels and labels[-1] == "P/E" and "Price 6/30/2026" not in labels[2:3]
    assert "half_change" in [b["id"] for b in review.section["blocks"]]


def test_company_updates_is_carried_verbatim_and_never_verified():
    review = ph.company_updates_review(text="Investment Updates: CMMF closed at 11.0% p.a.")
    (block,) = review.section["blocks"]
    assert (block["kind"], block["body_md"]) == ("supplied", "Investment Updates: CMMF closed at 11.0% p.a.")
    (item,) = review.review_items
    assert (item.kind, item.status) == (SUPPLIED_TEXT, NOT_AUTO_VERIFIED)
    with pytest.raises(ValueError, match="paste"):
        ph.company_updates_review(text="   ")


def save_approved(review, db, report_type="quarterly", period="Q3'2026"):
    review.report_type, review.period = report_type, period
    for item in review.review_items:
        item.resolve("accept")
    review.decide(APPROVED)
    review_store.save_review(review, section=review.section["section"], db_path=db)
    return review


def test_executive_summary_waits_for_every_section_and_names_them(tmp_path):
    db = tmp_path / "app.db"
    save_approved(ph.global_markets_review(), db)
    with pytest.raises(executive_summary.SectionsNotApproved) as exc:
        executive_summary.build_executive_summary_review(ph.ctx(db_path=db))
    assert "Global Markets Review" not in str(exc.value)
    assert "Fixed Income (not drafted)" in str(exc.value) and "Company Updates" not in str(exc.value)


def test_executive_summary_carries_each_approved_lead_piece_verbatim(tmp_path):
    db = tmp_path / "app.db"
    leads = {}
    for slug, build in ph.BUILDERS.items():
        provider = sh.LocalFakeNarrativeProvider() if slug == "equities" else None
        review = save_approved(build(provider=provider) if provider else build(), db)
        leads[slug] = next(b for b in review.section["blocks"] if b["kind"] == "narrative")
    # A newer, undecided draft of the same section blocks the summary again.
    other_period = ph.global_markets_review(ph.ctx(period="Q1'2026"))
    save_approved(other_period, db, period="Q1'2026")
    summary = executive_summary.build_executive_summary_review(ph.ctx(db_path=db))
    blocks = summary.section["blocks"]
    assert [b["source_section"] for b in blocks] == list(ph.BUILDERS)
    gm = blocks[0]
    assert (gm["headline"], gm["body_md"], gm["claims"]) == \
        ("Global Markets Review", leads["global_markets"]["body_md"], leads["global_markets"]["claims"])
    assert gm["source_headline"] == leads["global_markets"]["headline"]
    assert is_dev_draft(summary)  # the local-model Equities piece keeps its mark
    assert {i.status for i in summary.review_items} == {NOT_AUTO_VERIFIED}


def test_an_unreadable_auction_flags_the_totals_instead_of_summing_the_rest():
    ok = {"kind": "primary", "total_offered_kes_bn": 40.0, "url": "u1", "rows": [
        {"issue": "FXD1/2019/020", "accepted_kes_bn": 30.0, "bids_kes_bn": 60.0, "coupon_pct": 12.9, "avg_rate_pct": 13.9,
         "years_to_maturity": 12.8}]}
    broken = {"kind": "primary", "url": "u2", "value_date": "2026-09-07", "rows": [], "error": "HTTPError: 404"}
    rows, _ = fixed_income.summary_rows("Q3'2026", [ok, broken])
    assert [r["label"] for r in rows] == ["Q3'2026 Total", "Q3'2026 Average"]
    assert all("1 of 2" in r["error"] and "07/09/2026" in r["error"] and "offered_kes_bn" not in r for r in rows)


def test_period_tables_share_the_weekly_year_open_base(monkeypatch):
    """Q3 and H1 tables take Year Open and YTD from the weekly fetcher: the first trading day's close."""
    from cytonn_weekly.digital_payments import fetcher as dp_fetcher
    from cytonn_weekly.periodic import digital_payments as periodic_dp
    from tests.test_digital_payments import FakeTicker, _captured_history

    monkeypatch.setattr(dp_fetcher.yf, "Ticker",
                        lambda symbol: FakeTicker(symbol, {t: _captured_history(t) for _, t in dp_fetcher.COMPANIES}, {}))
    for report_type, period, today in (("quarterly", "Q3'2026", date(2026, 9, 25)), ("half_year", "H1'2026", date(2026, 9, 25))):
        c = ph.ctx(report_type, period, today=today)
        review = periodic_dp.build_digital_payments_review(
            c, provider=ph.FakeProvider(), narrative_provider=ph.narrative(),
            fetch_table=lambda d: dp_fetcher.fetch_digital_payments(today=d), history=ph.dp_history)
        table = next(b for b in review.section["blocks"] if b["kind"] == "table")
        rows = {r["ticker"]: r for r in table["rows"]}
        assert [(rows[t]["ytd_open"], rows[t]["ytd_pct"]) for t in ("AXP", "V", "MA", "CRCL", "XYZ", "PYPL")] == [
            ("372.7", "(17.1%)"), ("346.5", "6.0%"), ("563.1", "0.8%"), ("83.5", "6.6%"), ("65.2", "17.3%"), ("58.1", "(5.3%)")]
        assert (rows["GPN"]["ytd_open"], rows["GPN"]["ytd_pct"]) == ("75.5", "14.5%")  # known difference from the printed 77.0
        if report_type == "quarterly":  # (the shared fake history has no December close for H1's period start)
            assert all(i.status == CLEAN for i in review.review_items if i.kind == "table_row")  # the checker follows the base


def test_13_july_remaining_lives_are_not_computed_from_due_dates():
    """CBK's printed remaining lives are not reproducible from the due dates (checked 2026-10-05).

    Of the nine Q3 bonds that print both, no day count and reference date reproduces more than 3 at 1 dp (the
    implied reference dates run from April to August), so the three 13 July bonds stay without a tenor and the
    Average says so.  The issue prints 5.8, 15.2 and 29.2 for them; 29.2 is not even their due date's remaining life.
    """
    _, _, rows = q3_table()
    assert [rows[k]["years_to_maturity"] for k in ("2026-07-13 FXD1/2022/010", "2026-07-13 FXD1/2021/020",
                                                   "2026-07-13 FXD1/2026/030")] == ["-", "-", "-"]
    assert rows["Q3'2026 average"]["years_to_maturity"] == "15.2"  # the issue prints 15.6 (all twelve bonds)


def test_totals_and_averages_flag_every_missing_component():
    """A Total or Average with an input left out matches its own derivation, so the flag must come from the inputs."""
    def auction(day, kind="primary", **row):
        base = {"issue": "FXD1/2020/010", "years_to_maturity": 5.0, "coupon_pct": 12.0, "accepted_kes_bn": 10.0,
                "bids_kes_bn": 20.0, "avg_rate_pct": 13.0, "subscription_pct": 200.0, "acceptance_pct": 50.0}
        return {"value_date": day, "kind": kind, "error": None, "url": "u", "total_offered_kes_bn": 10.0,
                "total_subscription_pct": 200.0, "rows": [{**base, **row}]}

    whole = fixed_income.summary_rows("Q3'2026", [auction("2026-07-13"), auction("2026-08-17", issue="X")])[0]
    assert whole[0]["incomplete"] == {} and whole[1]["incomplete"] == {}
    partial = fixed_income.summary_rows("Q3'2026", [auction("2026-07-13", years_to_maturity=None, coupon_pct=None,
                                                             accepted_kes_bn=None),
                                                    auction("2026-08-17", issue="X")])[0]
    total, average = partial
    assert average["incomplete"]["years_to_maturity"].startswith("average of 1 of 2 bonds")
    assert average["incomplete"]["coupon_pct"].startswith("average of 1 of 2 bonds")
    assert average["incomplete"]["acceptance_pct"].startswith("average of 1 of 2 bonds")  # a ratio of totals is as incomplete
    assert "avg_rate_pct" not in average["incomplete"] and "subscription_pct" not in average["incomplete"]
    assert total["incomplete"]["accepted_kes_bn"].startswith("total of 1 of 2 bonds")


def approved_report(db, **providers):
    """Every summarised Q3 section drafted on fakes and approved; ``providers`` swaps one section's provider."""
    for slug, build in ph.BUILDERS.items():
        save_approved(build(provider=providers[slug]) if slug in providers else build(), db)


def test_executive_summary_says_how_it_is_composed_and_what_each_section_leaves_out(tmp_path):
    db = tmp_path / "app.db"
    approved_report(db)
    summary = executive_summary.build_executive_summary_review(ph.ctx(db_path=db))
    sec = summary.section
    assert sec["summary_note"] == ("Composed from the lead piece of each section. It does not summarize tables, parts not "
                                   "yet drafted, or Cytonn's own outlook.")
    left = {c["section"]: c for c in sec["not_covered"]}
    assert list(left) == list(ph.BUILDERS)                     # every included section, in report order
    fi = left["fixed_income"]
    assert fi["tables"] == ["Bond Issuances in Q3’2026"]
    assert fi["unavailable"] == ["T-Bills primary auctions over the period",
                                 "Secondary Bond Market Activity: Bond Turnover and Yield Curve",
                                 "Money Market Performance: Money Market Fund Yields table",
                                 "Liquidity, and the week's T-bill and money market paragraphs",
                                 "Kenya Eurobonds Performance"]
    assert fi["further_pieces"] == ["Government borrowing and public debt: a development"]  # the lead is the MPC piece
    assert [t.startswith("Major Inflation Changes") for t in left["kenya_macro"]["tables"]] == [True]  # named by its own title
    assert all(c["run_id"] for c in left.values())
    # the same lists reach the screen
    from api.serialize import serialize_review

    served = serialize_review(summary)["section"]
    assert served["summary_note"] == sec["summary_note"] and served["not_covered"] == sec["not_covered"]
    assert serialize_review(ph.global_markets_review())["section"]["not_covered"] == []  # other sections carry no such note


class MixedProvider(sh.FakeNarrativeProvider):
    """A section whose lead piece is a normal draft and whose SECOND piece was drafted by the local model."""

    def draft_piece(self, brief, *, start, end, today):
        piece = super().draft_piece(brief, start=start, end=end, today=today)
        if brief.id == "public_debt":
            piece.drafted_by = "local:phi4-mini"
        return piece


def load_send_script():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("send_weekly_summary", Path(__file__).parents[1] / "scripts" / "send_weekly_summary.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


def every_dev_reader_sees(summary):
    """Each place that reads the dev flag, as booleans: API serializer, ribbon and alert label, delivery, send script scan."""
    from api.serialize import serialize_review
    from cytonn_weekly.digital_payments import delivery

    served = serialize_review(summary)
    scan = [d for d in load_send_script().drafted_by_values(summary.section) if d.startswith("local:")]
    return {"is_dev_draft": served["is_dev_draft"], "ribbon_label": bool(served["dev_mode_label"]),
            "delivery": delivery.is_dev_mode_review(summary), "script_scan": bool(scan)}


def test_mixed_section_marks_the_summary_as_dev_everywhere_while_the_carried_text_is_untouched(tmp_path):
    """Normal lead piece, local-model second piece: the approved section is a dev draft, so the summary is too."""
    db = tmp_path / "app.db"
    approved_report(db, fixed_income=MixedProvider())
    fi = review_store.load_latest_review("fixed_income", report_type="quarterly", period="Q3'2026", db_path=db)
    assert is_dev_draft(fi)
    summary = executive_summary.build_executive_summary_review(ph.ctx(db_path=db))
    assert is_dev_draft(summary)
    assert every_dev_reader_sees(summary) == {"is_dev_draft": True, "ribbon_label": True, "delivery": True, "script_scan": True}
    # The carried text and its drafted_by values stay as they were: every carried piece is a normal draft.
    assert {b["drafted_by"] for b in summary.section["blocks"]} == {"fake:test"}
    # The coverage list names which section and which piece caused the mark.
    caused = {c["section"]: c["dev_pieces"] for c in summary.section["not_covered"] if c["dev_pieces"]}
    assert caused == {"fixed_income": [{"piece": "Government borrowing and public debt: a development",
                                        "drafted_by": "local:phi4-mini"}]}
    fi_left = next(c for c in summary.section["not_covered"] if c["section"] == "fixed_income")
    assert fi_left["further_pieces"] == ["Government borrowing and public debt: a development"]
    assert {"section": "fixed_income", "run_id": fi.run_id} in summary.section["composed_from"]


def test_all_normal_sections_do_not_mark_the_summary_as_dev(tmp_path):
    db = tmp_path / "app.db"
    approved_report(db)
    summary = executive_summary.build_executive_summary_review(ph.ctx(db_path=db))
    assert every_dev_reader_sees(summary) == {"is_dev_draft": False, "ribbon_label": False, "delivery": False, "script_scan": False}
    assert all(c["dev_pieces"] == [] for c in summary.section["not_covered"])


def test_a_local_lead_piece_still_marks_the_summary_as_before(tmp_path):
    db = tmp_path / "app.db"
    approved_report(db, fixed_income=sh.LocalFakeNarrativeProvider())
    summary = executive_summary.build_executive_summary_review(ph.ctx(db_path=db))
    assert every_dev_reader_sees(summary) == {"is_dev_draft": True, "ribbon_label": True, "delivery": True, "script_scan": True}
    fi_block = next(b for b in summary.section["blocks"] if b["source_section"] == "fixed_income")
    assert fi_block["drafted_by"] == "local:phi4-mini"          # carried, with its own mark, as before
    left = next(c for c in summary.section["not_covered"] if c["section"] == "fixed_income")
    assert [d["piece"] for d in left["dev_pieces"]] == ["Monetary Policy Committee: a development",
                                                        "Government borrowing and public debt: a development"]
