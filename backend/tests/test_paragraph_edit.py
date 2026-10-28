from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.problems import PROBLEMS
from api.serialize import serialize_review
from cytonn_weekly.common.computed import carried_block
from cytonn_weekly.common.review import EDITED_PARAGRAPH_NOTE, build_review, check_section, supplied_block, unavailable_block
from cytonn_weekly.digital_payments import review_store as rs
from cytonn_weekly.fixed_income import weekly as fi_weekly
from cytonn_weekly.weekly import sentence_edit as se

NOW = datetime(2026, 10, 27, 8, 42, tzinfo=timezone.utc)
FROM = {"issue_id": 891, "url": "https://cytonnreport.com/x", "published": "2026-09-27"}
OLD = "Rates in the fixed income market have declined MTD. Inflation stood at 6.6%."
NEW = "Rates have eased this month, and inflation stood at 6.6% in September."
OUTLOOK_REF = "Rates and outlook (carried forward)"


def make(extra_blocks=()):
    blocks = [carried_block("outlook", "Rates and outlook", OLD, FROM),
              carried_block("pressure", "What pressures the shilling", "The shilling is expected to remain under pressure.", FROM),
              unavailable_block("later", "Something later", "No source yet.", "Supply one."), *extra_blocks]
    content = {"section": "focus", "title": "Focus of the Week", "blocks": blocks}
    return build_review(content, check_section(content))


def idx(review, ref):
    return next(n for n, i in enumerate(review.review_items) if i.ref == ref)


def edit(review, text=NEW, ref=OUTLOOK_REF):
    return se.apply_paragraph(review, idx(review, ref), text, now=NOW)


def carried(review, block_id="outlook"):
    return next(b for b in review.section["blocks"] if b["id"] == block_id)


# --- the typed text -------------------------------------------------------------------------------

def test_a_paragraph_may_be_longer_than_a_sentence_up_to_1200_characters():
    assert len(se.plain("x" * 1200, paragraph=True)) == 1200
    with pytest.raises(se.TextRefused, match="paragraph is 1201 characters; the limit is 1200"):
        se.plain("x" * 1201, paragraph=True)
    with pytest.raises(se.TextRefused, match="limit is 600"):
        se.plain("x" * 601)


def test_line_breaks_in_a_paragraph_become_spaces_and_markup_is_refused():
    assert se.plain("One line.\n\nAnother   line.", paragraph=True) == "One line. Another line."
    for bad in ["see [a](b)", "a <b>", "# heading", "- item", "1. item"]:
        with pytest.raises(se.TextRefused, match="the paragraph cannot start|plain text only"):
            se.plain(bad, paragraph=True)
    with pytest.raises(se.TextRefused, match="Type the new paragraph"):
        se.plain("  ", paragraph=True)


# --- editing --------------------------------------------------------------------------------------

def test_an_edited_paragraph_is_a_new_review_and_the_old_one_is_untouched():
    old = make()
    done = edit(old)
    assert done.action == "paragraph" and done.review is not old
    assert carried(done.review)["body_md"] == NEW
    assert carried(old)["body_md"] == OLD and "edits" not in carried(old)
    assert old.review_items[idx(old, OUTLOOK_REF)].status == "flagged"
    assert done.review.decision is None


def test_the_edited_item_is_not_auto_verified_with_the_plain_note_and_the_flag_is_gone():
    done = edit(make())
    item = done.review.review_items[idx(done.review, OUTLOOK_REF)]
    assert item.status == "not_auto_verified" and item.detail == EDITED_PARAGRAPH_NOTE
    assert EDITED_PARAGRAPH_NOTE == ("You wrote this paragraph, so the checker has no source for it. "
                                     "Read every figure in it against its source by hand.")
    assert item.context["text"] == NEW and item.context["was"] == OLD and item.context["edited_at"] == "2026-10-27T08:42:00+00:00"
    assert item.resolution is None
    other = done.review.review_items[idx(done.review, "What pressures the shilling (carried forward)")]
    assert other.status == "flagged"


def test_the_edited_paragraph_must_be_acknowledged_before_the_section_can_be_approved():
    done = edit(make())
    for item in done.review.review_items:
        if item.ref != OUTLOOK_REF:
            item.resolve("accept")
    assert not done.review.is_approvable
    done.review.review_items[idx(done.review, OUTLOOK_REF)].resolve("accept")
    assert done.review.is_approvable


def test_typed_figures_are_not_compared_with_anything():
    done = edit(make(), "Inflation stood at 99.9% and nobody checked it.")
    assert done.review.review_items[idx(done.review, OUTLOOK_REF)].status == "not_auto_verified"


def test_notes_and_accepts_on_other_items_carry_over_and_the_edited_one_starts_unresolved():
    old = make()
    for n, item in enumerate(old.review_items):
        item.resolve("accept", note=f"note {n}")
    done = edit(old)
    for item in done.review.review_items:
        if item.ref == OUTLOOK_REF:
            assert item.resolution is None and item.resolution_note is None
        else:
            assert item.resolution == "accept" and item.resolution_note.startswith("note ")
    assert done.changed_items == 1


def test_a_second_edit_keeps_the_first_original():
    first = edit(make())
    second = edit(first.review, "Rates eased again.")
    assert [e["was"] for e in carried(second.review)["edits"]] == [OLD, OLD]
    assert second.review.review_items[idx(second.review, OUTLOOK_REF)].context["was"] == OLD


def test_a_carried_paragraph_edit_keeps_the_stored_summary_whole():
    bidding = supplied_block("bidding_range", "T-Bonds: recommended bidding range", "We recommend bidding 13.5% to 13.9%.")
    blocks = [bidding, carried_block("outlook", "Rates and outlook", OLD, FROM)]
    content = {"section": "fixed_income", "title": "Fixed Income", "blocks": blocks,
               "summary": fi_weekly.compose_summary(blocks)}
    old = build_review(content, check_section(content))
    done = edit(old)
    assert carried(done.review)["body_md"] == NEW
    assert done.review.section["summary"] == old.section["summary"] == "We recommend bidding 13.5% to 13.9%."


def test_the_same_paragraph_is_refused():
    with pytest.raises(se.TextRefused, match="same as before"):
        edit(make(), "Rates in the fixed income market  have declined MTD. Inflation stood at 6.6%.")


# --- refusals -------------------------------------------------------------------------------------

def test_an_item_that_is_not_a_carried_paragraph_is_refused():
    old = make()
    with pytest.raises(se.NotPossible, match="carried-forward paragraph"):
        se.apply_paragraph(old, idx(old, "Something later (not available yet)"), NEW)
    with pytest.raises(se.NotPossible):
        se.apply_paragraph(old, 99, NEW)
    assert not se.can_edit_paragraph(old, 2) and se.can_edit_paragraph(old, 0)


def test_a_piece_carried_from_another_sections_approved_review_is_refused():
    old = make()
    carried(old)["source_run_id"] = 5
    with pytest.raises(se.NotPossible, match="another section's approved review"):
        edit(old)
    assert not se.can_edit_paragraph(old, idx(old, OUTLOOK_REF))


def test_a_block_that_cannot_be_found_by_its_title_changes_nothing():
    old = make()
    carried(old)["title"] = "Renamed since"
    with pytest.raises(se.NotFound, match="exactly once"):
        edit(old)
    twin = make([carried_block("again", "Rates and outlook", "Same title.", FROM)])
    with pytest.raises(se.NotFound, match="exactly once"):
        edit(twin)
    assert carried(twin)["body_md"] == OLD


# --- the route ------------------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    return tmp_path / "app.db"


@pytest.fixture
def client(db):
    return TestClient(create_app(db_path=db, load_dotenv=False))


def saved(db, review=None):
    review = review or make()
    return rs.save_review(review, section="focus", db_path=db), review


def post(client, run_id, index, **body):
    return client.post(f"/api/reviews/{run_id}/items/{index}/sentence", json={"action": "paragraph", **body})


def test_the_serialized_review_offers_the_edit_on_carried_items_only(db):
    run_id, review = saved(db)
    shown = serialize_review(review)["review_items"]
    assert [i["edit_paragraph"] for i in shown] == [True, True, False]
    assert not any(i["edit_sentence"] for i in shown)


def test_the_route_saves_a_new_undecided_version_and_shows_the_edit_on_the_block(client, db):
    run_id, review = saved(db)
    r = post(client, run_id, idx(review, OUTLOOK_REF), text=NEW)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["review"]["run_id"] != run_id and out["review"]["decision"] is None
    assert out["result"] == {"action": "paragraph", "changed_items": 1, "earlier_run_id": run_id, "was_approved": False}
    block = out["review"]["section"]["blocks"][0]
    assert block["body_md"] == NEW and block["edits"][0]["was"] == OLD
    item = out["review"]["review_items"][0]
    assert item["status"] == "not_auto_verified" and item["edit_paragraph"] is True
    assert "Rates in the fixed income" in rs.load_review(run_id, db_path=db).section["blocks"][0]["body_md"]


def test_an_approved_section_stays_approved_and_the_new_version_needs_approving_again(client, db):
    review = make()
    for item in review.review_items:
        item.resolve("accept")
    review.decide("approved")
    run_id, _ = saved(db, review)
    r = post(client, run_id, idx(review, OUTLOOK_REF), text=NEW)
    assert r.status_code == 200, r.text
    assert r.json()["result"]["was_approved"] is True and r.json()["review"]["decision"] is None
    assert rs.load_review(run_id, db_path=db).decision == "approved"


def expect(r, status, code, detail_has):
    assert r.status_code == status, r.text
    body = r.json()
    headline, target = PROBLEMS[code]
    assert body["problems"] == [{"code": code, "headline": headline, "target": target}] and detail_has in body["detail"]


def test_the_route_refuses_in_plain_words_and_changes_nothing(client, db):
    run_id, review = saved(db)
    i = idx(review, OUTLOOK_REF)
    expect(post(client, run_id, i, text="see [a](b)"), 422, "edit_text_refused", "plain text only")
    expect(post(client, run_id, i, text="x" * 1201), 422, "edit_text_refused", "the limit is 1200")
    expect(post(client, run_id, idx(review, "Something later (not available yet)"), text=NEW), 409,
           "edit_paragraph_not_possible", "carried-forward paragraph")
    expect(post(client, run_id, 99, text=NEW), 409, "edit_paragraph_not_possible", "carried-forward paragraph")
    assert rs.load_latest_review(section="focus", db_path=db).run_id == run_id


def test_a_block_the_route_cannot_find_says_so_and_saves_nothing(client, db):
    review = make()
    carried(review)["title"] = "Renamed since"
    run_id, _ = saved(db, review)
    expect(post(client, run_id, 0, text=NEW), 409, "edit_paragraph_not_possible", "exactly once")
    assert rs.load_latest_review(section="focus", db_path=db).run_id == run_id
