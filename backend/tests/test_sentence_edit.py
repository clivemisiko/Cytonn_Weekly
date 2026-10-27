import copy
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.problems import PROBLEMS
from api.serialize import is_dev_draft, serialize_review
from cytonn_weekly.digital_payments import review_store as rs
from cytonn_weekly.weekly import sentence_edit as se
from tests import section_helpers as sh

NOW = datetime(2026, 10, 27, 8, 42, tzinfo=timezone.utc)
GOOD = "Lending rose to Sh30.1 billion over the quarter."
BAD = "Lending rose to Sh88.8 billion over the quarter."


def drafted(provider=None):
    """A Focus review whose second claim ("Lending rose to Sh99.9 billion.") quotes a figure its cited text lacks."""
    return sh.focus_review(provider=provider or sh.FakeNarrativeProvider(bad_figure=True))


def flagged_index(review):
    return next(n for n, i in enumerate(review.review_items) if i.status == "flagged")


def block_of(review):
    return next(b for b in review.section["blocks"] if b["kind"] == "narrative")


def apply(review, action, text=None, index=None):
    return se.apply(review, flagged_index(review) if index is None else index, action, text, now=NOW)


# --- the typed text -------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["", "   ", None])
def test_an_empty_sentence_is_refused(text):
    with pytest.raises(se.TextRefused, match="Remove this sentence"):
        se.plain(text)


def test_a_sentence_over_the_limit_is_refused_with_its_length():
    with pytest.raises(se.TextRefused, match="601 characters; the limit is 600"):
        se.plain("x" * 601)
    assert len(se.plain("x" * 600)) == 600


@pytest.mark.parametrize("text", ["see [this](https://x.example)", "a <b>bold</b> word", "a *star*", "a `tick`", "a\\b",
                                  "# heading", "- item", "+ item", "1. item", "2) item", "a\x07b"])
def test_text_that_is_not_plain_is_refused(text):
    with pytest.raises(se.TextRefused, match="plain text only"):
        se.plain(text)


def test_plain_text_is_kept_on_one_line_with_single_spaces():
    assert se.plain("  Lending  rose\n to 8.75% (a quote: \"x\") in Q3'2026.  ") == "Lending rose to 8.75% (a quote: \"x\") in Q3'2026."


# --- editing --------------------------------------------------------------------------------------

def test_editing_in_a_figure_the_source_has_clears_the_flag():
    old = drafted()
    assert old.review_items[flagged_index(old)].status == "flagged"
    done = apply(old, "edit", GOOD)
    block = block_of(done.review)
    assert GOOD in block["body_md"] and "Sh99.9" not in block["body_md"] and GOOD in block["body"]
    edited = next(i for i in done.review.review_items if i.context.get("edited_at"))
    assert edited.status == "not_auto_verified" and edited.context["text"] == GOOD
    assert edited.context["edited_at"] == "2026-10-27T08:42:00+00:00"
    assert edited.context["was"] == "Lending rose to Sh99.9 billion."
    assert not any(i.status == "flagged" for i in done.review.review_items)


def test_editing_in_a_figure_no_source_has_keeps_the_flag_and_says_so():
    done = apply(drafted(), "edit", BAD)
    edited = next(i for i in done.review.review_items if i.context.get("edited_at"))
    assert edited.status == "flagged"
    assert "88.8 do not appear in the text the search tool cited" in edited.detail[0].message


def test_the_earlier_review_is_never_touched():
    old = drafted()
    old.review_items[0].resolve("accept", "read it")
    before = (copy.deepcopy(old.section), [i.to_dict() for i in old.review_items], old.decision)
    done = apply(old, "edit", GOOD)
    assert done.review is not old and done.review.run_id is None and done.review.decision is None
    assert (old.section, [i.to_dict() for i in old.review_items], old.decision) == before


def test_the_new_version_keeps_the_report_type_and_period():
    old = drafted()
    old.report_type, old.period = "weekly", "Week ending 2026-10-02"
    done = apply(old, "edit", GOOD)
    assert (done.review.report_type, done.review.period) == ("weekly", "Week ending 2026-10-02")


def test_notes_and_accepts_on_the_other_items_carry_over_and_the_changed_item_starts_undecided():
    old = drafted()
    other = next(n for n, i in enumerate(old.review_items) if i.status != "flagged")
    old.review_items[other].resolve("accept", "checked against the source")
    old.review_items[flagged_index(old)].resolve("fix_needed", "figure is wrong")
    done = apply(old, "edit", GOOD)
    kept = next(i for i in done.review.review_items if i.context.get("text") == old.review_items[other].context["text"])
    assert (kept.resolution, kept.resolution_note) == ("accept", "checked against the source")
    edited = next(i for i in done.review.review_items if i.context.get("edited_at"))
    assert (edited.resolution, edited.resolution_note) == (None, None)
    assert done.changed_items == 1


def test_only_the_one_sentence_changes_in_its_block():
    old = drafted()
    done = apply(old, "edit", GOOD)
    a, b = block_of(old), block_of(done.review)
    assert b["body_md"] == a["body_md"].replace("Lending rose to Sh99.9 billion.", GOOD)
    assert {k: v for k, v in b.items() if k not in ("body_md", "body", "claims", "edits")} == \
           {k: v for k, v in a.items() if k not in ("body_md", "body", "claims", "edits")}
    assert b["claims"][0] == a["claims"][0] and b["claims"][1]["url"] == a["claims"][1]["url"]
    assert b["claims"][1]["cited_text"] == a["claims"][1]["cited_text"]
    assert b["edits"] == [{"kind": "edited", "at": "2026-10-27T08:42:00+00:00", "was": "Lending rose to Sh99.9 billion.", "now": GOOD}]


def test_editing_the_same_sentence_again_keeps_the_first_wording_as_the_original():
    bad = apply(drafted(), "edit", BAD).review
    again = se.apply(bad, flagged_index(bad), "edit", GOOD, now=NOW).review
    block = block_of(again)
    assert block["edits"] == [{"kind": "edited", "at": "2026-10-27T08:42:00+00:00", "was": "Lending rose to Sh99.9 billion.", "now": GOOD}]
    assert block["claims"][1]["was"] == "Lending rose to Sh99.9 billion."


def test_the_same_text_is_not_saved_again():
    old = drafted()
    with pytest.raises(se.TextRefused, match="same as before"):
        apply(old, "edit", "Lending rose to Sh99.9 billion.")


# --- removing -------------------------------------------------------------------------------------

def test_removing_takes_the_sentence_out_of_the_text_and_shows_removed_by_you_in_the_item_list():
    old = drafted()
    done = apply(old, "remove")
    block = block_of(done.review)
    assert "Sh99.9" not in block["body_md"] and "Sh99.9" not in block["body"]
    assert "  " not in block["body_md"] and not block["body_md"].endswith(" ")
    assert len(block["claims"]) == 1
    assert block["edits"] == [{"kind": "removed", "at": "2026-10-27T08:42:00+00:00", "was": "Lending rose to Sh99.9 billion."}]
    removed = next(i for i in done.review.review_items if "removed_at" in i.context)
    assert removed.ref.endswith("(removed by you)") and removed.status == "not_auto_verified"
    assert removed.detail.startswith("Removed by you.") and removed.resolution is None
    assert "removed by you" not in block["body_md"].lower()


def test_a_removed_sentence_item_has_no_edit_actions_and_a_later_change_keeps_the_removal():
    done = apply(drafted(), "remove").review
    removed_at = next(n for n, i in enumerate(done.review_items) if "removed_at" in i.context)
    assert not se.can_edit(done, removed_at)
    bad = apply(drafted(), "edit", BAD).review
    block_of(bad)["edits"].append(block_of(done)["edits"][0])   # a review that holds both
    again = se.apply(bad, flagged_index(bad), "edit", GOOD, now=NOW).review
    assert [e["kind"] for e in block_of(again)["edits"]] == ["removed", "edited"]
    assert sum("removed_at" in i.context for i in again.review_items) == 1


def test_removing_an_edited_sentence_drops_its_edited_mark():
    bad = apply(drafted(), "edit", BAD).review
    gone = se.apply(bad, flagged_index(bad), "remove", None, now=NOW).review
    assert [e["kind"] for e in block_of(gone)["edits"]] == ["removed"]


def test_removing_the_only_text_is_refused():
    old = drafted()
    block = block_of(old)
    block["body_md"] = block["body"] = "Lending rose to Sh99.9 billion."
    with pytest.raises(se.NotPossible, match="no text"):
        apply(old, "remove")


# --- when the sentence cannot be found, or the item is not one -----------------------------------

def test_a_sentence_that_appears_twice_is_not_changed():
    old = drafted()
    block = block_of(old)
    block["body_md"] += " Lending rose to Sh99.9 billion."
    before = copy.deepcopy(old.section)
    with pytest.raises(se.NotFound, match="exactly once"):
        apply(old, "edit", GOOD)
    assert old.section == before


def test_a_sentence_that_runs_across_a_link_is_not_changed():
    old = drafted()
    block = block_of(old)
    block["body_md"] = block["body_md"].replace("rose to", "[rose](https://example.org/x) to")
    with pytest.raises(se.NotFound):
        apply(old, "remove")


def test_an_item_that_is_not_a_flagged_sentence_is_refused():
    old = drafted()
    clean = next(n for n, i in enumerate(old.review_items) if i.status != "flagged")
    for index in (clean, -1, 999):
        with pytest.raises(se.NotPossible, match="flagged sentence of a drafted piece"):
            apply(old, "edit", GOOD, index=index)
        assert not se.can_edit(old, index)


def test_a_piece_carried_from_another_sections_review_is_refused():
    old = drafted()
    block_of(old)["source_run_id"] = 7
    with pytest.raises(se.NotPossible, match="another section's approved review"):
        apply(old, "edit", GOOD)


def test_a_table_section_item_is_not_a_sentence():
    review = sh.equities_review(provider=sh.FakeNarrativeProvider(bad_figure=True))
    tables = [n for n, i in enumerate(review.review_items) if i.kind != "claim"]
    assert tables and not any(se.can_edit(review, n) for n in tables)


def test_a_dev_mode_draft_stays_a_dev_draft():
    old = drafted(sh.LocalFakeNarrativeProvider(bad_figure=True))
    assert is_dev_draft(old)
    assert is_dev_draft(apply(old, "edit", GOOD).review)


def test_the_screen_is_told_which_items_can_be_edited_and_what_was_edited():
    old = drafted()
    shown = serialize_review(old)["review_items"]
    assert [i["edit_sentence"] for i in shown] == [i.status == "flagged" for i in old.review_items]
    done = apply(old, "edit", GOOD).review
    out = serialize_review(done)
    assert next(b for b in out["section"]["blocks"] if b["kind"] == "narrative")["edits"][0]["kind"] == "edited"
    assert not any(i["edit_sentence"] for i in out["review_items"])


# --- the route ------------------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    return tmp_path / "app.db"


@pytest.fixture
def client(db):
    return TestClient(create_app(db_path=db, load_dotenv=False))


def saved(db, review=None):
    review = review or drafted()
    return rs.save_review(review, section="focus", db_path=db), review


def post(client, run_id, index, **body):
    return client.post(f"/api/reviews/{run_id}/items/{index}/sentence", json=body)


def expect(r, status, code, detail_has):
    assert r.status_code == status, r.text
    body = r.json()
    assert set(body) == {"detail", "problems"} and detail_has in body["detail"]
    headline, target = PROBLEMS[code]
    assert body["problems"] == [{"code": code, "headline": headline, "target": target}]


def test_the_route_saves_a_new_undecided_version_and_leaves_the_old_one(client, db):
    run_id, review = saved(db)
    r = post(client, run_id, flagged_index(review), action="edit", text=GOOD)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["review"]["run_id"] != run_id and out["review"]["decision"] is None
    assert out["result"] == {"action": "edit", "changed_items": 1, "earlier_run_id": run_id, "was_approved": False}
    assert GOOD in out["review"]["section"]["blocks"][0]["body_md"]
    old = rs.load_review(run_id, db_path=db)
    assert "Sh99.9" in block_of(old)["body_md"] and old.decision is None
    assert rs.load_latest_review(section="focus", db_path=db).run_id == out["review"]["run_id"]


def test_an_approved_section_is_not_changed_and_the_new_version_needs_approving_again(client, db):
    review = drafted()
    for item in review.review_items:
        item.resolve("accept")
    review.decide("approved")
    run_id, _ = saved(db, review)
    r = post(client, run_id, flagged_index(review), action="remove")
    assert r.status_code == 200, r.text
    assert r.json()["result"]["was_approved"] is True and r.json()["review"]["decision"] is None
    assert rs.load_review(run_id, db_path=db).decision == "approved"


def test_the_route_refuses_in_plain_words_and_changes_nothing(client, db):
    run_id, review = saved(db)
    flagged = flagged_index(review)
    clean = next(n for n, i in enumerate(review.review_items) if i.status != "flagged")
    expect(post(client, run_id, flagged, action="edit", text="see [a](b)"), 422, "edit_text_refused", "plain text only")
    expect(post(client, run_id, flagged, action="edit", text=""), 422, "edit_text_refused", "Type the new sentence")
    expect(post(client, run_id, flagged, action="edit", text="x" * 601), 422, "edit_text_refused", "the limit is 600")
    expect(post(client, run_id, clean, action="edit", text=GOOD), 409, "edit_not_possible", "flagged sentence")
    expect(post(client, 99999, 0, action="remove"), 404, "review_not_found", "no saved review")
    assert client.post(f"/api/reviews/{run_id}/items/{flagged}/sentence", json={"action": "delete"}).status_code == 422
    assert rs.load_latest_review(section="focus", db_path=db).run_id == run_id


def test_the_route_names_a_sentence_it_cannot_find(client, db):
    review = drafted()
    block_of(review)["body_md"] += " Lending rose to Sh99.9 billion."
    run_id, _ = saved(db, review)
    expect(post(client, run_id, flagged_index(review), action="edit", text=GOOD), 409, "edit_sentence_not_found", "exactly once")


def boom(*args, **kwargs):
    raise RuntimeError("secret library detail")


def test_a_failed_check_shows_a_fixed_sentence_not_the_library_text(client, db, monkeypatch):
    run_id, review = saved(db)
    monkeypatch.setattr(se, "check_section", boom)
    r = post(client, run_id, flagged_index(review), action="edit", text=GOOD)
    expect(r, 500, "edit_save_failed", "could not be checked")
    assert "secret library detail" not in r.text


def test_a_failed_save_shows_a_fixed_sentence_not_the_library_text(client, db, monkeypatch):
    run_id, review = saved(db)
    monkeypatch.setattr(rs, "save_review", boom)
    r = post(client, run_id, flagged_index(review), action="edit", text=GOOD)
    expect(r, 500, "edit_save_failed", "could not be saved")
    assert "secret library detail" not in r.text
