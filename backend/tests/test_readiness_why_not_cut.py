import pytest

from cytonn_weekly.agent import readiness
from cytonn_weekly.agent.read_tools import READ_TOOLS
from cytonn_weekly.agent.tools import trim

BY_NAME = {t.name: t for t in READ_TOOLS}

STALE = ("uploaded, but it is for another week: the week ending 13 Nov 2026, and this report is for the week ending 27 Nov 2026. "
         "The draft ignores it. Upload this week's workbook.")
LATER = ("uploaded, but it is for another week: the week ending 4 Dec 2026, and this report is for the week ending 27 Nov 2026. "
         "The draft still reads it, so check every value taken from it. Upload this week's workbook.")


@pytest.mark.parametrize(("found", "expected"), [("2026-11-13", STALE), ("2026-12-04", LATER)])
@pytest.mark.parametrize("section", ["fixed_income", "equities", "real_estate", "digital_payments", "focus"])
def test_the_other_week_sentence_reaches_the_page_whole(section, found, expected):
    why = readiness._other_week(found, "2026-11-27")
    assert why == expected
    # the readiness routes pass week_status through trim(); its shape is the same for every section
    entry = {"kind": "upload", "key": f"{section}_workbook", "label": "Workbook", "why": why, "other_week": True, "files": []}
    got = trim({"groups": {"needs_analyst": [entry]}}, BY_NAME["week_status"].shape)
    assert got["groups"]["needs_analyst"][0]["why"] == expected
