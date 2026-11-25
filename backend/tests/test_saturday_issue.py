import io
import json
from datetime import date

import pytest
from openpyxl import load_workbook

from cytonn_weekly.weekly import analyst, fi_workbook, inputs
from cytonn_weekly.weekly.inputs import InputError
from cytonn_weekly.weekly.week import saturday_issue, saturday_note
from tests import weekly_helpers as wh
from tests.test_weekly_analyst import item, save, stores
from tests.weekly_helpers import text_pdfs  # noqa: F401 - a fixture

WEEK = wh.WEEK                       # the week ending Friday 2 Oct 2026
SATURDAY, SUNDAY = "2026-10-03", "2026-10-04"
NOTE = "Saturday 3 Oct 2026 is entered as Friday 2 Oct 2026: the Saturday issue prints Friday's rates."
SNIP_ROWS = [{"rank": str(n), "fund": f, "rate": r} for n, (f, r) in enumerate(
    [("Cytonn Money Market Fund", "11.00"), ("Alpha Money Market Fund", "10.85"), ("Beta Money Market Fund", "10.70"),
     ("Gamma Money Market Fund", "10.60"), ("Delta Money Market Fund", "10.50"), ("Epsilon Money Market Fund", "9.00")], 1)]


def stored(root):
    return json.loads((root / WEEK.ending.isoformat() / "analyst.json").read_text(encoding="utf-8"))


def test_only_a_saturday_is_moved_to_the_friday_before():
    assert saturday_issue(date(2026, 10, 3)) == date(2026, 10, 2)
    assert saturday_issue(date(2026, 10, 4)) is None and saturday_issue(date(2026, 10, 2)) is None
    assert saturday_note(date(2026, 10, 3)) == NOTE


def test_a_saturday_typed_on_the_form_is_stored_as_its_friday_and_the_form_says_so(tmp_path):
    save(tmp_path, {"mmf_published": SATURDAY})
    assert stored(tmp_path)["fields"]["mmf_published"] == "2026-10-02"
    assert item("mmf_published", tmp_path)["value"] == "2026-10-02" and item("mmf_published", tmp_path)["notice"] == NOTE
    save(tmp_path, {"mmf_published": "2026-10-02"})          # the Friday typed itself: no note
    assert item("mmf_published", tmp_path)["notice"] is None


def test_the_saturday_rule_also_reads_a_day_first_date(tmp_path):
    save(tmp_path, {"mmf_published": "3 October 2026"})
    assert stored(tmp_path)["fields"]["mmf_published"] == "2026-10-02" and item("mmf_published", tmp_path)["notice"] == NOTE


@pytest.mark.parametrize("day", [SUNDAY, "2026-09-26", "2026-10-09"])   # a Sunday, another week's Saturday, another week's Friday
def test_a_sunday_or_a_day_of_another_week_is_still_refused_on_the_form(tmp_path, day):
    with pytest.raises(InputError, match="outside this week"):
        save(tmp_path, {"mmf_published": day})


def test_a_saturday_on_a_confirmed_snip_is_stored_as_its_friday(tmp_path):
    analyst.fund_snip(WEEK, SNIP_ROWS, SATURDAY, "sha256 of an invented image", [], tmp_path)
    assert stored(tmp_path)["fields"]["mmf_published"] == "2026-10-02"
    assert item("mmf_published", tmp_path)["notice"] == NOTE


@pytest.mark.parametrize("day", [SUNDAY, "2026-09-26", "2026-10-09"])
def test_a_sunday_or_another_week_on_a_snip_is_still_refused(tmp_path, day):
    with pytest.raises(InputError, match="outside this week"):
        analyst.fund_snip(WEEK, SNIP_ROWS, day, "sha256 of an invented image", [], tmp_path)


def workbook_titled(title_day: str) -> bytes:
    book = load_workbook(io.BytesIO(wh.fi_workbook_bytes()))
    book["Money Market Performance"]["S10"] = f"Money Market Fund Yield for Fund Managers as published on {title_day}"
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_a_workbook_fund_table_titled_saturday_reads_for_its_friday(tmp_path, text_pdfs):  # noqa: F811
    data = workbook_titled("3rd October 2026")
    table = fi_workbook.read_mmf_table(fi_workbook.open_fi_workbook(data, "FI"), WEEK)
    assert table["published"] == date(2026, 10, 2) and table["saturday"] == date(2026, 10, 3)
    assert inputs.identify(inputs.BY_SLUG["fi_workbook"], data, WEEK)["matches"] is True
    stores(tmp_path)
    inputs.store(WEEK, "fi_workbook", data, "FI.xlsx", tmp_path)
    got = item("mmf_published", tmp_path)
    assert got["workbook"]["value"] == "2026-10-02" and got["notice"] == NOTE and got["workbook_stale"] is None


@pytest.mark.parametrize("title_day", ["4th October 2026", "26th September 2026"])
def test_a_workbook_fund_table_titled_sunday_or_another_week_is_still_refused(title_day):
    book = fi_workbook.open_fi_workbook(workbook_titled(title_day), "FI")
    with pytest.raises(fi_workbook.WorkbookWeekError):
        fi_workbook.read_mmf_table(book, WEEK)
