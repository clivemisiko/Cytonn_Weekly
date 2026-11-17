from datetime import date

from cytonn_weekly.common import sources as src
from cytonn_weekly.real_estate import snips
from tests import section_helpers as sh

FRIDAY = date(2026, 11, 13)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
OTHER = b"\x89PNG\r\n\x1a\n" + b"1" * 32


def confirmed(day, sector, data, tmp_path):
    e = snips.add(day, sector, f"{sector}.png", data, tmp_path / "snips")
    snips.reading(day, e["hash"], "Land prices rose 5%.", tmp_path / "snips")
    return snips.confirm(day, e["hash"], tmp_path / "snips", tmp_path / "src")


def problems(tmp_path, day=FRIDAY):
    return snips.problems(day, tmp_path / "snips", tmp_path / "src")


def test_an_uploaded_snip_that_is_not_confirmed_is_named_with_its_sector():
    snips.add(FRIDAY, "land", "land.png", PNG)
    [line] = snips.problems(FRIDAY)
    assert line.startswith("Land: ") and '"land.png"' in line and "not confirmed" in line and "does not use it" in line


def test_a_confirmed_snip_and_an_empty_week_are_no_problem(tmp_path):
    assert problems(tmp_path) == []
    confirmed(FRIDAY, "land", PNG, tmp_path)
    assert problems(tmp_path) == []


def test_a_snip_filed_under_a_nearby_other_friday_is_named_but_a_distant_one_is_not(tmp_path):
    snips.add(date(2026, 11, 6), "residential", "a.png", PNG, tmp_path / "snips")
    snips.add(date(2026, 10, 9), "land", "b.png", OTHER, tmp_path / "snips")   # five weeks earlier
    lines = [ln for ln in problems(tmp_path) if "filed under" in ln]
    assert len(lines) == 1 and "week ending 2026-11-06" in lines[0] and "Residential sector" in lines[0]
    assert "not this draft's week ending 2026-11-13" in lines[0] and "not used" in lines[0]


def test_a_confirmed_snip_whose_saved_source_is_gone_is_named(tmp_path):
    e = confirmed(FRIDAY, "land", PNG, tmp_path)
    assert problems(tmp_path) == []
    src.remove(e["source_id"], tmp_path / "src")
    [line] = problems(tmp_path)
    assert line.startswith("Land: ") and "no saved source filed under this sector" in line and "Confirm it again" in line


def test_a_draft_still_goes_ahead_and_says_what_it_did_not_read():
    snips.add(sh.TODAY, "land", "late.png", PNG)   # uploaded, never confirmed
    snips.add(date(2026, 9, 25), "hospitality", "wrong-week.png", OTHER)
    review = sh.real_estate_review()
    warnings = review.section["warnings"]
    assert any("late.png" in w and "not confirmed" in w for w in warnings)
    assert any("wrong-week.png" not in w and "week ending 2026-09-25" in w for w in warnings)
    assert review.section["pieces_found"] >= 1


def test_the_listing_carries_the_week_problems(tmp_path):
    from fastapi.testclient import TestClient

    from api.main import create_app

    client = TestClient(create_app(db_path=tmp_path / "a.db", sources_root=tmp_path / "inputs" / "sources", load_dotenv=False))
    snips.add(date(2026, 11, 6), "land", "a.png", PNG, tmp_path / "inputs" / "snips")
    body = client.get("/api/snips/2026-11-13").json()
    assert any("week ending 2026-11-06" in w for w in body["warnings"])
