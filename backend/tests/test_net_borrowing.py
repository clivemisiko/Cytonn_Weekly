"""The net domestic borrowing log built from CBK's auction results (fixed_income/net_borrowing.py).

Public documents only.  The parser tests read the few result PDFs kept as fixtures; the
arithmetic is tested on a captured value file (every release from 1 July to 9 October 2026 as
the parsers read it); the whole set of result PDFs is read again only when it is present
under the sample folder (``cbk_results/``), and that test is skipped otherwise.

Golden figures, worked out from CBK's files on 2026-10-12: net borrowing of Kshs 507.484 bn
at the 28 September value date and 572.296 bn at 5 October with no switch counted; 594.112 bn
with the 26 August switch at CBK's printed 21,816.46 mn; 594.807 bn with the 22,510.90 mn the
fixed income team's log holds for it, which is the 594.8 the Q3'2026 review printed.
"""

import json
import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from cytonn_weekly import paths
from cytonn_weekly.checkers.digital_payments import MISSING, SOURCES_DISAGREE
from cytonn_weekly.common.checks import check_table_block
from cytonn_weekly.common.review import build_review, check_section, numbered, second_sources
from cytonn_weekly.fixed_income import cbk_auctions as cbk
from cytonn_weekly.fixed_income import net_borrowing as nb
from cytonn_weekly.fixed_income import weekly as fiw
from cytonn_weekly.weekly import analyst, inputs
from cytonn_weekly.weekly.week import Week
from tests import weekly_helpers as wh
from tests.test_weekly_fixed_income import BULLETIN, blocks, build, fetchers, figures, items

FX = wh.FIXTURES
CAPTURED = json.loads((FX / "cbk_net_borrowing_releases_fy2026-27_captured_2026-10-12.json").read_text(encoding="utf-8"))
RELEASES = CAPTURED["releases"]
FY = date(2026, 7, 1)
WEEK = wh.WEEK                      # ending 2 October 2026: its auctions settle 3 to 9 October
EARLIER = Week(date(2026, 9, 25))   # its auctions settle 26 September to 2 October
TARGET = 919.36
TBILL_LISTING = FX / "cbk_tbill_listing_2026-10-12_excerpt.html"
TBOND_LISTING = FX / "cbk_tbond_listing_2026-10-05_excerpt.html"
TBILLS = {"2026-09-28": "cbk_tbill_2026-09-28.pdf", "2026-10-05": "cbk_tbill_2026-10-05.pdf"}
TBONDS = {"2026-07-13": "cbk_tbond_2026-07-13.pdf", "2026-07-15": "cbk_tbond_2026-07-15_switch.pdf",
          "2026-07-27": "cbk_tbond_2026-07-27.pdf", "2026-08-17": "cbk_tbond_2026-08-17.pdf",
          "2026-08-26": "cbk_tbond_2026-08-26_switch.pdf", "2026-09-07": "cbk_tbond_2026-09-07.pdf",
          "2026-09-09": "cbk_tbond_2026-09-09_switch.pdf", "2026-09-21": "cbk_tbond_2026-09-21.pdf"}


def parsed(name, parse):
    return parse(*cbk._tables_and_text((FX / name).read_bytes()))


def cbk_get(url: str) -> bytes:
    """CBK as kept in the fixtures: the two listing excerpts and the result PDFs, by the value date in the file name."""
    if url == cbk.TBILL_LISTING:
        return TBILL_LISTING.read_bytes()
    if url == cbk.TBOND_LISTING:
        return TBOND_LISTING.read_bytes()
    when = cbk.link_value_date(url).isoformat()
    name = (TBILLS if "treasury_bill" in url else TBONDS).get(when)
    if name is None:
        raise FileNotFoundError(f"not captured: {url}")
    return (FX / name).read_bytes()


def captured_releases(start, end, folder):
    return {"start": start.isoformat(), "end": end.isoformat(), "warnings": [],
            "releases": [r for r in RELEASES if start.isoformat() <= r["value_date"] <= end.isoformat()]}


def log_at(week=WEEK, **kwargs):
    return nb.build_log(RELEASES, FY, week.value_date_window[1], **kwargs)


class Typed:
    """A typed amount, as weekly/analyst.py hands one to a builder."""

    def __init__(self, number):
        self.number, self.source, self.ref = number, "analyst input typed on the weekly form (switch of 2026-08-26)", "the form"


# ---------------------------------------------------------------------------
# 1. The parsers
# ---------------------------------------------------------------------------

def test_tbill_results_give_redemptions_per_tenor_and_next_weeks():
    out = parsed("cbk_tbill_2026-09-28.pdf", cbk.parse_tbill_results)
    assert out["redemptions_kes_m"] == {"91-day": 14471.40, "182-day": 2731.85, "364-day": 12347.70, "total": 29550.95}
    assert out["accepted_kes_m"] == {"91-day": 16546.14, "182-day": 10260.23, "364-day": 6543.85, "total": 33350.22}
    assert out["next_week_redemptions_kes_m"] == 33890.45 and out["next_value_date"] == "2026-10-05"
    # what the parser returned before is unchanged
    assert out["auction_date"] == "2026-09-28" and [r["tenor"] for r in out["rows"]] == list(cbk.TENORS)
    assert [(r["accepted_kes_bn"], r["avg_rate_pct"], r["prior_avg_rate_pct"]) for r in out["rows"]] == [
        (16.54614, 8.7781, 8.7837), (10.26023, 8.8949, 8.9099), (6.54385, 9.0431, 9.0566)]


def test_section_c_is_next_weeks_section_a():
    this, following = parsed("cbk_tbill_2026-09-28.pdf", cbk.parse_tbill_results), parsed("cbk_tbill_2026-10-05.pdf", cbk.parse_tbill_results)
    assert this["next_week_redemptions_kes_m"] == following["redemptions_kes_m"]["total"] == 33890.45
    assert following["accepted_kes_m"]["total"] == 41196.84 and following["next_value_date"] == "2026-10-12"


def test_tbond_results_give_redemptions_and_the_sum_of_the_issues():
    out = parsed("cbk_tbond_2026-08-17.pdf", cbk.parse_tbond_results)
    # CBK prints "1 18,137" (kerned) and a total accepted rounded to 312,027; the issues add to 312,027.34
    assert out["redemptions_kes_m"] == 118137.0 and out["accepted_kes_m"] == 312027.34
    assert [r["issue"] for r in out["rows"]] == ["IFB1/2019/016", "IFB1/2021/018", "IFB1/2021/021"]   # as before
    assert [r["accepted_kes_bn"] for r in out["rows"]] == [112.63678, 105.53734, 93.85322]
    dash = parsed("cbk_tbond_2026-07-13.pdf", cbk.parse_tbond_results)
    assert dash["redemptions_kes_m"] == 0.0 and dash["accepted_kes_m"] == 70599.25       # a printed "-" is zero


def test_a_switch_and_a_tap_sale_state_no_redemptions():
    switch = parsed("cbk_tbond_2026-08-26_switch.pdf", cbk.parse_tbond_results)
    assert switch["redemptions_kes_m"] is None and switch["accepted_kes_m"] == 21816.46
    assert parsed("cbk_tbond_2025-08-25_tap.pdf", cbk.parse_tbond_results)["redemptions_kes_m"] is None
    assert cbk.parse_tbond_results([[["Nothing", "here"]]])["accepted_kes_m"] is None
    empty = cbk.parse_tbill_results([[["Something else", "1", "2", "3"]]])
    assert empty["redemptions_kes_m"]["total"] is None and empty["next_week_redemptions_kes_m"] is None


# ---------------------------------------------------------------------------
# 2. The fetch and the kept files
# ---------------------------------------------------------------------------

def test_tbills_are_taken_by_the_value_date_in_the_file_name():
    out = cbk.fetch_period_tbills(date(2026, 9, 22), date(2026, 10, 9), get=cbk_get)
    assert [a["value_date"] for a in out["auctions"]] == ["2026-10-05", "2026-09-28"] and out["listing_url"] == cbk.TBILL_LISTING
    assert all(a["error"] is None and a["kind"] == "tbill" for a in out["auctions"])
    assert out["auctions"][0]["redemptions_kes_m"]["total"] == 33890.45
    unread = cbk.fetch_period_tbills(date(2026, 9, 15), date(2026, 9, 27), get=cbk_get)["auctions"]   # 21-09 is listed, not captured
    assert [a["value_date"] for a in unread] == ["2026-09-21"] and unread[0]["error"].startswith("FileNotFoundError")


class Site:
    """A stand-in for centralbank.go.ke that counts what it is asked."""

    def __init__(self):
        self.files = {"https://cbk/uploads/a DATED 05-10-2026.pdf": b"%PDF first"}
        self.headers = {"content-length": "10", "last-modified": "Mon, 05 Oct 2026 15:34:55 GMT"}
        self.gets, self.heads, self.sleeps = [], [], []

    def get(self, url):
        self.gets.append(url)
        return self.files[url]

    def head(self, url):
        self.heads.append(url)
        return dict(self.headers, server="x")

    def cache(self, folder, probe=True):
        return nb.ResultsCache(folder, self.get, self.head if probe else None, self.sleeps.append)


URL = "https://cbk/uploads/a DATED 05-10-2026.pdf"


def test_a_result_file_is_downloaded_once_kept_with_its_hash_and_rechecked(tmp_path):
    site = Site()
    first = site.cache(tmp_path)
    assert first.get(URL) == b"%PDF first" and first.downloaded == ["a DATED 05-10-2026.pdf"]
    kept = json.loads((tmp_path / "index.json").read_text())[URL]
    assert kept["sha256"] == nb.sha256(b"%PDF first") and kept["bytes"] == 10 and (tmp_path / kept["file"]).read_bytes() == b"%PDF first"
    again = site.cache(tmp_path)
    assert again.get(URL) == b"%PDF first" and again.downloaded == [] and again.changes == []
    assert site.gets == [URL] and site.heads == [URL]              # the second run asked only for the file's size and date
    third = site.cache(tmp_path)
    assert third.get(URL) == b"%PDF first" and third.changes == [] and site.gets == [URL]   # unchanged at CBK: not downloaded
    assert third.get("https://cbk/listing/") if site.files.setdefault("https://cbk/listing/", b"<html>") else True
    assert site.gets == [URL, "https://cbk/listing/"]             # a listing page is always fetched
    assert site.sleeps == [nb.GET_DELAY]                           # a pause before every request after the run's first


def test_a_file_cbk_replaced_is_downloaded_again_and_the_change_is_reported(tmp_path):
    site = Site()
    site.cache(tmp_path).get(URL)
    site.cache(tmp_path).get(URL)                                  # remembers CBK's size and date for the kept copy
    site.files[URL] = b"%PDF revised!"
    site.headers = {"content-length": "13", "last-modified": "Wed, 16 Sep 2026 07:49:38 GMT"}
    run = site.cache(tmp_path)
    assert run.get(URL) == b"%PDF revised!" and run.downloaded == ["a DATED 05-10-2026.pdf"]
    assert len(run.changes) == 1 and "CBK's file changed after it was downloaded" in run.changes[0]
    old, new = nb.sha256(b"%PDF first"), nb.sha256(b"%PDF revised!")
    assert f"sha256 {old[:12]} then, {new[:12]} now" in run.changes[0]
    assert (tmp_path / f"a DATED 05-10-2026.replaced-{old[:8]}.pdf").read_bytes() == b"%PDF first"    # the earlier copy is kept
    assert json.loads((tmp_path / "index.json").read_text())[URL]["sha256"] == new
    quiet = site.cache(tmp_path)
    assert quiet.get(URL) == b"%PDF revised!" and quiet.changes == []
    # a new date on the same content is not a change
    site.headers = {"content-length": "13", "last-modified": "Thu, 17 Sep 2026 07:00:00 GMT"}
    same = site.cache(tmp_path)
    assert same.get(URL) == b"%PDF revised!" and same.changes == [] and same.downloaded == ["a DATED 05-10-2026.pdf"]


def test_a_kept_file_that_no_longer_matches_its_hash_is_not_trusted(tmp_path):
    site = Site()
    site.cache(tmp_path).get(URL)
    (tmp_path / "a DATED 05-10-2026.pdf").write_bytes(b"%PDF edited on disk")
    run = site.cache(tmp_path)
    assert run.get(URL) == b"%PDF first"
    assert run.changes == ["a DATED 05-10-2026.pdf: the kept copy no longer matched the hash recorded when it was downloaded; "
                           "it was downloaded again and is unchanged at CBK."]


def test_a_file_that_cannot_be_rechecked_is_used_and_said_so(tmp_path):
    site = Site()
    site.cache(tmp_path).get(URL)

    def down(url):
        raise ConnectionError("no route")

    run = nb.ResultsCache(tmp_path, site.get, down, site.sleeps.append)
    assert run.get(URL) == b"%PDF first" and run.unchecked == ["a DATED 05-10-2026.pdf (ConnectionError)"] and run.changes == []
    assert site.cache(tmp_path, probe=False).get(URL) == b"%PDF first" and site.heads == []   # no probe: the hash check alone


def test_releases_are_fetched_kept_and_carry_their_hash(tmp_path):
    out = nb.fetch_releases(date(2026, 8, 11), date(2026, 10, 2), tmp_path, get=cbk_get, probe=None, sleep=lambda s: None)
    got = [(r["value_date"], r["kind"], r["accepted_kes_m"], r["redemptions_kes_m"]) for r in out["releases"]]
    assert got == [("2026-08-17", "primary", 312027.34, 118137.0), ("2026-08-26", "switch", 21816.46, None),
                   ("2026-09-07", "primary", 47748.5, 0.0), ("2026-09-09", "switch", 11020.44, None),
                   ("2026-09-21", "tbill", None, None), ("2026-09-21", "primary", 50175.06, 0.0),
                   ("2026-09-28", "tbill", 33350.22, 29550.95)]
    assert out["releases"][4]["error"].startswith("FileNotFoundError")       # listed by CBK, not among the fixtures
    assert out["warnings"] == [] and len(out["downloaded"]) == 6
    switch = out["releases"][1]
    assert switch["sha256"] == nb.sha256((FX / "cbk_tbond_2026-08-26_switch.pdf").read_bytes()) and switch["file"].endswith("Final.pdf")
    assert (tmp_path / switch["file"]).is_file()
    # what the captured value file holds for the same releases is what the parsers read today
    held = {(r["value_date"], r["kind"]): r for r in RELEASES}
    for r in out["releases"]:
        if r["error"] is None:
            assert {k: v for k, v in held[(r["value_date"], r["kind"])].items()} == r
    again = nb.fetch_releases(date(2026, 8, 11), date(2026, 10, 2), tmp_path, get=cbk_get, probe=None, sleep=lambda s: None)
    assert again["downloaded"] == [] and again["releases"] == out["releases"]


def test_a_changed_file_reaches_the_warnings(tmp_path):
    nb.fetch_releases(date(2026, 8, 20), date(2026, 8, 31), tmp_path, get=cbk_get, probe=None, sleep=lambda s: None)
    index = json.loads((tmp_path / "index.json").read_text())
    (url, entry), = index.items()
    (tmp_path / entry["file"]).write_bytes(b"%PDF an earlier version of the switch results")
    entry["sha256"] = nb.sha256(b"%PDF an earlier version of the switch results")
    entry["headers"] = {"content-length": "1", "last-modified": "Thu, 27 Aug 2026 09:00:00 GMT"}
    (tmp_path / "index.json").write_text(json.dumps(index))
    head = {"content-length": "123902", "last-modified": "Wed, 16 Sep 2026 07:49:38 GMT"}
    out = nb.fetch_releases(date(2026, 8, 20), date(2026, 8, 31), tmp_path, get=cbk_get, probe=lambda u: head, sleep=lambda s: None)
    assert len(out["warnings"]) == 1 and out["warnings"][0].startswith("CBK auction results: 1872718579_SWITCH RESULTS")
    assert "CBK's file changed after it was downloaded" in out["warnings"][0] and "check the figures it changes" in out["warnings"][0]
    assert out["releases"][0]["accepted_kes_m"] == 21816.46


def test_the_whole_set_of_result_files_reads_as_the_captured_values(tmp_path):
    folder = Path(os.environ.get(wh.SAMPLE_DIR_ENV_VAR) or paths.REPO_ROOT / "sample data") / "cbk_results"
    files = {}
    for f in list(folder.glob("*.pdf")) + list(FX.glob("cbk_tbill_2026-*.pdf")) + list(FX.glob("cbk_tbond_2026-*.pdf")):
        kind = "tbill" if "tbill" in f.name else "switch" if "switch" in f.name else "primary"
        files[(kind, re.search(r"\d{4}-\d{2}-\d{2}", f.name).group(0))] = f
    if len(files) < len(RELEASES) or not (folder / "tbill_listing.html").is_file():
        pytest.skip("real sample not present: cbk_results (CBK's result PDFs since 1 July 2026)")

    def get(url):
        if url in (cbk.TBILL_LISTING, cbk.TBOND_LISTING):
            return (folder / ("tbill_listing.html" if url == cbk.TBILL_LISTING else "tbond_listing.html")).read_bytes()
        return files[("tbill" if "treasury_bill" in url else cbk.link_kind(url), cbk.link_value_date(url).isoformat())].read_bytes()

    out = nb.fetch_releases(FY, date(2026, 10, 9), tmp_path, get=get, probe=None, sleep=lambda s: None)
    assert out["releases"] == RELEASES and len(out["releases"]) == 24 and out["warnings"] == []


# ---------------------------------------------------------------------------
# 3. The log
# ---------------------------------------------------------------------------

def test_net_borrowing_with_no_switch_counted():
    earlier, later = log_at(EARLIER), log_at(WEEK)
    assert (earlier.as_at, earlier.days, round(earlier.net_bn, 3)) == (date(2026, 9, 28), 89, Decimal("507.484"))
    assert (later.as_at, later.days, round(later.net_bn, 3)) == (date(2026, 10, 5), 96, Decimal("572.296"))
    assert (round(earlier.prorated_bn(TARGET), 3), round(later.prorated_bn(TARGET), 3)) == (Decimal("224.789"), Decimal("242.469"))
    assert (round(earlier.share_pct(TARGET), 1), round(later.share_pct(TARGET), 1)) == (Decimal("225.8"), Decimal("236.0"))
    assert earlier.usable and later.usable and earlier.flags == later.flags == []
    assert (earlier.counted, later.counted) == (18, 20) and len(later.rows) == 24
    assert [s["value_date"] for s in later.uncounted_switches] == ["2026-07-15", "2026-08-26", "2026-09-09", "2026-10-07"]
    assert [s["value_date"] for s in earlier.uncounted_switches] == ["2026-07-15", "2026-08-26", "2026-09-09"]
    assert nb.switches_listed(earlier.uncounted_switches) == ("15-07-2026 (Kshs 7,954.71 mn), 26-08-2026 (Kshs 21,816.46 mn), "
                                                              "09-09-2026 (Kshs 11,020.44 mn)")


def test_a_switch_counts_only_when_chosen_at_cbks_amount_or_the_analysts():
    chosen = log_at(switches={"2026-08-26": {"count": True}})
    assert round(chosen.net_bn, 3) == Decimal("594.112") and [s["value_date"] for s in chosen.counted_switches] == ["2026-08-26"]
    assert round(log_at(EARLIER, switches={"2026-08-26": {"count": True}}).net_bn, 3) == Decimal("529.301")
    assert round(log_at(switches={"2026-08-26": {"count": False, "override": Typed(22510.90)}}).net_bn, 3) == Decimal("572.296")
    typed = log_at(switches={"2026-08-26": {"count": True, "override": Typed(22510.90)}})
    earlier = log_at(EARLIER, switches={"2026-08-26": {"count": True, "override": Typed(22510.90)}})
    assert round(typed.net_bn, 3) == Decimal("594.807") and round(earlier.net_bn, 3) == Decimal("529.995")
    assert (round(earlier.share_pct(TARGET), 1), round(typed.share_pct(TARGET), 1)) == (Decimal("235.8"), Decimal("245.3"))
    # the typed amount is an analyst input with CBK's printed amount as its second reading; no redemptions are subtracted
    amount = typed.inputs["accepted 2026-08-26 switch (typed)"]
    assert (amount["value"], amount["origin"], amount["second"]["value"]) == (22510.90, "analyst_input", 21816.46)
    assert "redemptions 2026-08-26 T-bond switch" not in typed.inputs
    row = next(r for r in typed.rows if r["key"] == "2026-08-26 T-bond switch")
    assert (row["accepted_kes_m"], row["redemptions_kes_m"], row["net_kes_m"], row["counted"], row["_origin"]) == (
        22510.90, None, 22510.90, "Yes", "analyst_input")
    assert {"row": row["key"], "column": "accepted_kes_m", "value": 21816.46,
            "source": "CBK Treasury bond switch auction results, value date 2026-08-26"} in typed.second_sources
    not_counted = next(r for r in log_at().rows if r["key"] == "2026-08-26 T-bond switch")
    assert (not_counted["accepted_kes_m"], not_counted["net_kes_m"], not_counted["counted"]) == (21816.46, None, "No")


def test_the_net_is_accepted_less_redemptions_release_by_release():
    log = log_at()
    rows = {r["key"]: r for r in log.rows}
    bond = rows["2026-08-17 T-bonds"]
    assert (bond["accepted_kes_m"], bond["redemptions_kes_m"], bond["net_kes_m"]) == (312027.34, 118137.0, 193890.34)
    assert rows["2026-09-07 T-bills"]["net_kes_m"] == -6505.12        # a week that redeemed more than it raised
    assert rows["2026-10-05 T-bonds"]["running_bn"] == 572.29569 and rows["2026-10-07 T-bond switch"]["running_bn"] == 572.29569
    assert sum(Decimal(repr(r["net_kes_m"])) for r in log.rows if r["net_kes_m"] is not None) == log.net_kes_m
    # every figure in the sentence is worked out again from these inputs: each tenor's and each issue's accepted amount
    assert len(log.accepted) == 14 * 3 + 14 and len(log.redeemed) == 20 and set(log.inputs) == set(log.accepted) | set(log.redeemed)
    assert {i["origin"] for i in log.inputs.values()} == {"source"}
    assert log.inputs["accepted 2026-08-17 IFB1/2021/021"] == {
        "value": 93853.22, "origin": "source", "source": "CBK Treasury bond auction results, value date 2026-08-17, IFB1/2021/021"}
    assert any("not CBK's printed total for 06-07-2026 (24,730.57 against 24,730.58)" in w for w in log.warnings)


def test_the_log_table_checks_clean_but_for_the_week_section_c_was_revised():
    block = nb.log_block(log_at())
    assert block["export"] is False and block["id"] == "borrowing_log" and len(block["rows"]) == 24
    assert block["rows"][-2] == {"key": "2026-10-05 T-bonds", "value_date": "2026-10-05", "kind": "T-bonds",
                                 "accepted_kes_m": "57,505.01", "redemptions_kes_m": "0.00", "net_kes_m": "57,505.01",
                                 "counted": "Yes", "running_bn": "572.3"}
    assert block["rows"][-1]["redemptions_kes_m"] == "-" and block["rows"][-1]["net_kes_m"] == "-"     # a switch: not stated
    seconds = {s["row"]: s for s in block["second_sources"]}
    assert len(seconds) == 13 and seconds["2026-10-05 T-bills"]["value"] == 33890.45        # each week against the week before
    assert seconds["2026-10-05 T-bills"]["source"] == ("CBK Treasury bill auction results, value date 2026-09-28, section C "
                                                       "(the next auction's redemptions)")
    flags = check_table_block(block, second_sources(block)).flags
    # 17 August's results announced redemptions of 31,874.00 for 24 August; that week's own results print 31,874.15
    assert [(f.kind, f.subject, f.field) for f in flags] == [(SOURCES_DISAGREE, "borrowing_log/2026-08-24 T-bills", "redemptions_kes_m")]
    assert [s["value"] for s in flags[0].sources] == [31874.15, 31874.0]
    tampered = nb.log_block(log_at())
    tampered["source_rows"][4]["net_kes_m"] = 11517.56
    assert any("worked out from its inputs" in f.message for f in check_table_block(tampered).flags)


def test_a_missing_week_an_unread_file_and_unstated_redemptions_are_never_passed_over():
    without = [r for r in RELEASES if not (r["kind"] == "tbill" and r["value_date"] == "2026-08-10")]
    gap = nb.build_log(without, FY, WEEK.value_date_window[1])
    assert gap.flags == ["no Treasury bill results were found with a value date between 2026-08-03 and 2026-08-17; a week may "
                         "be missing from the log"]
    unread = [dict(r, error="ValueError: the columns do not line up", accepted_kes_m=None) if r["value_date"] == "2026-09-21"
              and r["kind"] == "primary" else r for r in RELEASES]
    broken = nb.build_log(unread, FY, WEEK.value_date_window[1])
    assert not broken.usable and broken.problems == ["CBK's t-bonds results with value date 2026-09-21 could not be read "
                                                     "(ValueError: the columns do not line up)"]
    assert any(f.kind == MISSING for f in check_table_block(nb.log_block(broken)).flags)
    tap = RELEASES + [{"value_date": "2026-10-06", "kind": "tap", "url": "u", "error": None, "accepted_kes_m": 1000.0,
                       "accepted_parts": [{"label": "FXD1/2018/025", "kes_m": 1000.0}], "redemptions_kes_m": None}]
    tapped = nb.build_log(tap, FY, WEEK.value_date_window[1])
    assert tapped.usable and tapped.as_at == date(2026, 10, 6) and tapped.days == 97
    assert tapped.flags == ["CBK's t-bond tap sale results of 06-10-2026 state no redemptions; none is subtracted for it"]
    assert round(tapped.net_bn, 3) == Decimal("573.296")
    assert nb.build_log([], FY, WEEK.value_date_window[1]).usable is False


# ---------------------------------------------------------------------------
# 4. The section: complete from CBK alone, with the typed target
# ---------------------------------------------------------------------------

def with_target(root, week=WEEK, target="919.36"):
    analyst.save_form(week, {"fields": {"borrowing_target": target}}, root)
    return root


def cbk_build(root, week=WEEK, **over):
    return fiw.build_fixed_income_review(week.ending, inputs=inputs.WeeklyInputs(week, root),
                                         fetchers=fetchers(releases=captured_releases, **over), draft=wh.no_draft)


def test_without_a_workbook_or_a_typed_log_the_sentence_is_worked_out_from_cbk(tmp_path):
    review = cbk_build(with_target(tmp_path))
    by = blocks(review)
    assert list(by)[-2:] == ["borrowing", "borrowing_log"]
    b = by["borrowing"]
    assert b["body_md"] == ("The government is at 236.0% of its pro-rated net domestic borrowing target of Kshs 242.5 bn, with a "
                            "net borrowing position of Kshs 572.3 bn (inclusive of T-bills).")
    f = figures(b)
    assert (f["net_borrowing"], f["prorated_target"], f["ratio"]) == ("572.3", "242.5", "236.0%")
    assert [s["name"] for s in b["sources"]] == ["CBK Treasury bill and bond auction results", "Weekly analyst inputs"]
    by_ref = {i.ref: i for i in review.review_items}
    net = by_ref["Net domestic borrowing against the pro-rated target: Net domestic borrowing (Kshs bn) (572.3)"]
    assert net.status == "clean"                       # every input is a figure CBK printed, worked out again by the checker
    assert net.context["note"] == ("20 CBK results from 2026-07-01 to 2026-10-05 (14 Treasury bill auctions, 6 Treasury bond "
                                   "auctions): accepted amounts less redemptions.")
    target = by_ref["Net domestic borrowing against the pro-rated target: Pro-rated net domestic borrowing target (Kshs bn) (242.5)"]
    assert target.status == "flagged" and target.context["note"] == (
        "96 days from 2026-07-01 to the latest auction's value date, 2026-10-05, over a 364-day year.")
    switches = next(i for ref, i in by_ref.items() if "Switch auctions found, not counted" in ref)
    assert switches.ref == ("Net domestic borrowing against the pro-rated target: Switch auctions found, not counted: "
                            "15-07-2026 (Kshs 7,954.71 mn), 26-08-2026 (Kshs 21,816.46 mn), 09-09-2026 (Kshs 11,020.44 mn), "
                            "07-10-2026 (Kshs 8,963.83 mn); in all, Kshs bn (49.8)")
    assert switches.status == "flagged" and "none of these switch auctions is counted" in switches.detail[0].message
    rows = items(review, "Net domestic borrowing log:")
    assert len(rows) == 24 and [i.ref for i in rows if i.status == "flagged"] == ["Net domestic borrowing log: 2026-08-24 T-bills"]
    assert {i.status for i in rows} == {"clean", "flagged"}
    assert any("not CBK's printed total for 06-07-2026" in w for w in review.section["warnings"])
    assert "ahead" not in b["body_md"]


def test_the_week_before_is_worked_out_to_its_own_latest_value_date(tmp_path):
    b = blocks(cbk_build(with_target(tmp_path, EARLIER), EARLIER, tbonds=lambda start, end: {"auctions": []}))["borrowing"]
    assert b["body_md"] == ("The government is at 225.8% of its pro-rated net domestic borrowing target of Kshs 224.8 bn, with a "
                            "net borrowing position of Kshs 507.5 bn (inclusive of T-bills).")
    assert "89 days from 2026-07-01 to the latest auction's value date, 2026-09-28" in b["figures"][1]["note"]


def test_an_uploaded_workbooks_log_is_the_second_reading_row_by_row(tmp_path):
    inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(), "FI.xlsx", tmp_path)   # a synthetic log: 30,000 less 20,000 a week
    review = cbk_build(tmp_path)
    by = blocks(review)
    assert figures(by["borrowing"])["net_borrowing"] == "572.3"          # CBK's figures are what is printed
    row = next(i for i in items(review, "Net domestic borrowing log: 2026-10-05 T-bills"))
    assert row.status == "flagged" and {f.kind for f in row.detail} == {SOURCES_DISAGREE}
    sources = {s["source"]: s["value"] for f in row.detail if f.field == "accepted_kes_m" for s in f.sources}
    assert sources["CBK Treasury bill and bond auction results"] == 41196.84
    assert 30000.0 in sources.values() and any(k.startswith("analyst input from Fixed income workbook 'Government Borrowing'!")
                                               for k in sources)
    assert any("has no row for 2026-07-13 T-bonds" in w for w in review.section["warnings"])


def test_the_real_workbooks_log_differs_from_cbk_only_on_the_switch(tmp_path):
    inputs.store(WEEK, "fi_workbook", wh.sample("FI_MASTERSHEET_05.10.2026.v1.xlsx"), "FI.xlsx", tmp_path)
    inputs.store(WEEK, "cbk_bulletin", BULLETIN, "b.pdf", tmp_path)
    review = cbk_build(tmp_path)
    assert blocks(review)["borrowing"]["body_md"].startswith("The government is at 236.0% of its pro-rated")
    flagged = {i.ref.split(": ", 1)[1]: i for i in items(review, "Net domestic borrowing log:") if i.status == "flagged"}
    assert sorted(flagged) == ["2026-07-06 T-bills", "2026-08-24 T-bills", "2026-08-26 T-bond switch"]
    switch = flagged["2026-08-26 T-bond switch"].detail[0]
    assert switch.kind == SOURCES_DISAGREE and [s["value"] for s in switch.sources] == [21816.46, 22510.9]


def test_a_typed_log_overrides_cbk_as_analyst_input_with_cbks_net_as_its_second_reading(tmp_path):
    with_target(tmp_path)
    analyst.save_form(WEEK, {"tables": {"borrowing_log": {"text": "2026-09-28 500000 (100000)\n2026-10-05 41196.84 (33890.45)"}}}, tmp_path)
    review = cbk_build(tmp_path)
    by = blocks(review)
    assert figures(by["borrowing"])["net_borrowing"] == "407.3" and "borrowing_log" in by
    net = next(i for i in review.review_items if i.ref.startswith("Net domestic borrowing against the pro-rated target: Net domestic"))
    assert net.status == "flagged" and net.detail[0].kind == SOURCES_DISAGREE
    assert "CBK Treasury bill and bond auction results (20 results to 2026-10-05) gives 572.296" in net.detail[0].message
    assert any("is used instead of CBK's auction results" in w for w in review.section["warnings"])


def test_when_cbk_cannot_be_fetched_the_workbook_or_the_typed_log_is_the_fallback(tmp_path):
    def down(start, end, folder):
        raise ConnectionError("no route to host")

    with_target(tmp_path)
    by = blocks(build(tmp_path, fetchers=fetchers(releases=down)))
    assert by["borrowing"]["kind"] == "unavailable" and "borrowing_log" not in by
    assert by["borrowing"]["reason"] == ("The fiscal year's auction log has not been typed under \"Weekly analyst inputs\", and the "
                                         "fixed income workbook for this week is not among this week's inputs. CBK's auction "
                                         "results could not be fetched from centralbank.go.ke.")
    analyst.save_form(WEEK, {"tables": {"borrowing_log": {"text": "2026-10-05 300000 (100000)"}}}, tmp_path)
    review = build(tmp_path, fetchers=fetchers(releases=down))
    assert figures(blocks(review)["borrowing"])["net_borrowing"] == "200.0"
    net = next(i for i in review.review_items if "Net domestic borrowing (Kshs bn)" in i.ref)
    assert net.status == "not_auto_verified" and "analyst input typed on the weekly form" in net.detail
    assert any("CBK Treasury bill and bond auction results: ConnectionError: no route to host" in w for w in review.section["warnings"])


def test_results_that_stop_before_this_week_or_cannot_be_read_do_not_make_a_figure(tmp_path):
    with_target(tmp_path)
    stale = lambda start, end, folder: {"releases": [r for r in RELEASES if r["value_date"] <= "2026-09-28"], "warnings": []}  # noqa: E731
    by = blocks(build(tmp_path, fetchers=fetchers(releases=stale)))
    assert by["borrowing"]["kind"] == "unavailable" and by["borrowing"]["reason"].endswith(
        "CBK's results list no auction settling in the week after 2026-10-02 (latest value date: 2026-09-28).")
    unread = lambda start, end, folder: {"warnings": [], "releases": [  # noqa: E731
        dict(r, error="FileNotFoundError: gone", accepted_kes_m=None) if r["value_date"] == "2026-08-17" and r["kind"] == "primary"
        else r for r in RELEASES]}
    by = blocks(build(tmp_path, fetchers=fetchers(releases=unread)))
    assert by["borrowing"]["kind"] == "unavailable" and by["borrowing"]["reason"].endswith(
        "CBK's t-bonds results with value date 2026-08-17 could not be read (FileNotFoundError: gone).")


def test_a_changed_cbk_file_is_reported_in_the_sections_warnings(tmp_path):
    changed = lambda start, end, folder: {**captured_releases(start, end, folder), "warnings": [  # noqa: E731
        "CBK auction results: x Final.pdf: CBK's file changed after it was downloaded on 2026-10-05 (sha256 aaa then, bbb now)."]}
    review = build(with_target(tmp_path), fetchers=fetchers(releases=changed))
    assert any(w.startswith("CBK auction results: x Final.pdf: CBK's file changed") for w in review.section["warnings"])


def test_the_fetch_is_handed_the_fiscal_year_and_a_folder_under_the_inputs(tmp_path):
    seen = {}

    def record(start, end, folder):
        seen.update(start=start, end=end, folder=folder)
        return captured_releases(start, end, folder)

    review = build(with_target(tmp_path), fetchers=fetchers(releases=record))
    assert (seen["start"], seen["end"]) == (date(2026, 7, 1), date(2026, 10, 9))
    assert seen["folder"] == tmp_path.parent / "cbk_results"
    counted = build_review(review.section, check_section({"blocks": numbered(review.section["blocks"])}))
    assert len(counted.review_items) == len(review.review_items)
