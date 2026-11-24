import pytest

from cytonn_weekly.real_estate import snips
from cytonn_weekly.real_estate.review_run import NO_SNIP, SECTOR_BRIEFS, UNBLOCK, build_real_estate_review
from cytonn_weekly.report_sections import BY_SLUG
from cytonn_weekly.review.blocks import UNAVAILABLE_PART
from cytonn_weekly.weekly import recheck
from tests import section_helpers as sh

NEW = [("mixed_use", "Mixed-use developments"), ("infrastructure", "Infrastructure")]
OLD = ("industry", "residential", "land", "hospitality")


def _review(sectors):
    sh.confirm_snips(sectors)
    provider = sh.FakeNarrativeProvider()
    review = build_real_estate_review(provider=provider, today=sh.TODAY, fetch_reits=lambda _today: sh.reits(),
                                      fetch_previous_issue=lambda _day: None)
    return review, provider


def _block(review, sid):
    return next(b for b in review.section["blocks"] if b["id"] == f"sector_{sid}")


def _item(review, label):
    return next(i for i in review.review_items if i.kind == UNAVAILABLE_PART and i.ref.startswith(label + " ("))


def test_the_new_sectors_follow_hospitality_and_come_before_reits():
    assert snips.SECTORS == (("industry", "Industry reports"), ("residential", "Residential sector"), ("land", "Land"),
                             ("hospitality", "Hospitality and Tourism"), *NEW)
    assert [b.id for b in SECTOR_BRIEFS] == [sid for sid, _ in snips.SECTORS]
    assert BY_SLUG["real_estate"].subsections[-3:] == ("Mixed-use developments", "Infrastructure", "REITs")


@pytest.mark.parametrize("sid,label", NEW)
def test_a_new_sector_is_in_the_snip_panel_and_takes_an_upload(sid, label, tmp_path):
    from fastapi.testclient import TestClient

    from api.main import create_app

    client = TestClient(create_app(db_path=tmp_path / "a.db", sources_root=tmp_path / "inputs" / "sources", load_dotenv=False))
    body = client.get("/api/snips/2026-11-13").json()
    assert {"id": sid, "label": label} in body["sectors"]
    assert snips.LIVE[sid] == snips.LABELS[sid] == label
    e = snips.add(sh.TODAY, sid, f"{sid}.png", b"\x89PNG\r\n\x1a\n" + sid.encode() * 8, tmp_path / "snips")
    assert e["sector"] == sid


@pytest.mark.parametrize("sid,label", NEW)
def test_a_snip_confirmed_for_a_new_sector_reaches_its_part_of_the_draft(sid, label):
    review, provider = _review((*OLD, sid))
    assert sid in provider.calls
    block = _block(review, sid)
    assert block["kind"] == "narrative" and block["sector"] == sid and block["headline"] == f"{label}: a development"


@pytest.mark.parametrize("sid,label", NEW)
def test_an_empty_new_sector_is_left_out_exactly_as_an_empty_land_is(sid, label):
    review, provider = _review(("industry",))
    land, new = _block(review, "land"), _block(review, sid)
    assert sid not in provider.calls
    assert (new["kind"], new["reason"], new["unblock"], new["title"]) == ("unavailable", NO_SNIP, UNBLOCK, label)
    assert {k: v for k, v in new.items() if k not in ("id", "title", "sector", "numeral")} == \
           {k: v for k, v in land.items() if k not in ("id", "title", "sector", "numeral")}
    assert _item(review, label).status == _item(review, "Land").status


@pytest.mark.parametrize("sid,label", NEW)
def test_fix_this_on_an_empty_new_sector_opens_its_snip_panel(sid, label):
    review, _ = _review(("industry",))
    item = _item(review, label)
    assert recheck.fix_inputs("real_estate", review.section, item) == [{"panel": recheck.SNIPS_PANEL, "key": sid}]
    assert recheck.SNIPS_PANEL == "snips"
