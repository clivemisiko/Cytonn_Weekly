import io
from datetime import date

from docx import Document

from cytonn_weekly.review.blocks import CARRIED_TEXT, COMPUTED_FIGURE
from cytonn_weekly.review import store as review_store
from cytonn_weekly.review.model import CLEAN, FLAGGED
from cytonn_weekly.real_estate import review_run
from cytonn_weekly.real_estate.review_run import build_real_estate_review, industry_briefs, standing_text
from cytonn_weekly.report_sections import BY_SLUG
from cytonn_weekly.weekly import export, sentence_edit
from cytonn_weekly.weekly.previous_issue import Issue
from tests import section_helpers as sh

PERIOD = "Week ending 2026-09-25"
BENEFITS = "REITs offer various benefits to investors, including liquidity and diversification."
ISSUE = Issue(issue_id=899, published=date(2026, 11, 15), sections={"real-estate": {"name": "Real Estate", "body": (
    "<p>Hospitality news.</p><p>" + BENEFITS + "</p><p>Additional general challenges include:</p><p>High entry costs</p>"
    "<p>Low liquidity</p><p>Together, these challenges continue to limit the performance of Kenyan REITs.</p>"
    "<p>We expect the performance of the sector to remain resilient.</p>")}})


def _build(**kw):
    sh.confirm_snips()
    return build_real_estate_review(provider=sh.FakeNarrativeProvider(no_story={"hospitality"}), today=sh.TODAY,
                                    fetch_reits=lambda _today: sh.reits(), **kw)


def _block(review, block_id):
    return next(b for b in review.section["blocks"] if b["id"] == block_id)


def test_the_reit_prices_are_a_computed_paragraph_whose_figures_check_clean():
    review = _build(fetch_previous_issue=lambda _day: None)
    block = _block(review, "reits_prices")
    assert block["kind"] == "computed" and block["sector"] == "reits"
    assert block["body_md"] == (
        "Acorn D-REIT closed at Kshs 29.7 per unit, representing a 48.3% gain from the Kshs 20.0 inception price. "
        "Acorn I-REIT closed at Kshs 24.4 per unit, representing a 22.2% gain from the Kshs 20.0 inception price. "
        "ILAM Fahari I-REIT closed at Kshs 13.8 per unit, representing a 31.0% loss from the Kshs 20.0 inception price.")
    figures = [i for i in review.review_items if i.kind == COMPUTED_FIGURE and "REIT" in i.ref]
    assert len(figures) == 6 and all(i.status == CLEAN for i in figures)


def test_the_parts_only_the_analyst_can_write_are_flagged_and_printed_as_red_lines():
    review = _build(fetch_previous_issue=lambda _day: None)
    mine = [b for b in review.section["blocks"] if b.get("role") == "analyst"]
    assert [b["id"] for b in mine] == ["industry_closing", "outlook_reits"]   # no hospitality piece (no story), so no "going forward"
    flagged = {i.ref for i in review.review_items if i.kind == CARRIED_TEXT and i.status == FLAGGED}
    assert {f"{b['title']} (analyst to write)" for b in mine} <= flagged
    assert any(r.endswith("(carried forward)") for r in flagged)   # the standing text is real carried text and keeps its label
    review.report_type, review.period = "weekly", PERIOD
    buf = io.BytesIO()
    export.build_weekly_document([(BY_SLUG["real_estate"], review)], PERIOD).save(buf)
    text = [p.text for p in Document(io.BytesIO(buf.getvalue())).paragraphs]
    assert f"[Analyst to write: {review_run.INDUSTRY_CLOSING}]" in text and f"[Analyst to write: {review_run.REITS_OUTLOOK}]" in text
    assert f"Analyst to write: {review_run.REITS_OUTLOOK}" not in text   # only the bracketed line, never the placeholder body


def test_an_analyst_to_write_part_can_be_written_by_editing_it():
    review = _build(fetch_previous_issue=lambda _day: None)
    review.report_type, review.period = "weekly", PERIOD
    title = f"{review_run.REITS_OUTLOOK} (analyst to write)"
    index = next(n for n, i in enumerate(review.review_items) if i.ref == title)
    edited = sentence_edit.apply_paragraph(review, index, "We expect REIT performance to remain muted.")
    assert _block(edited.review, "outlook_reits")["body_md"] == "We expect REIT performance to remain muted."


def test_industry_reports_are_one_piece_each():
    sh.confirm_snips(("residential",))
    for n in range(2):
        label = review_run.snips.LABELS["industry"]
        review_run.source_store.from_snip(f"image-{n}".encode(), ".png", f"Report {n} figures.", label, sh.TODAY, sh.TODAY.isoformat(), f"r{n}.png")
    briefs = industry_briefs(sh.TODAY)
    assert [b.id for b in briefs] == ["industry", "industry_2"] and all(len(b.source_ids) == 1 and b.takeouts for b in briefs)
    assert briefs[0].source_ids != briefs[1].source_ids


def test_the_standing_text_is_read_from_the_previous_issue_when_no_review_is_approved():
    block = _block(_build(fetch_previous_issue=lambda _day: ISSUE), "standing")
    assert not block.get("placeholder") and block["carried_from"]["issue_id"] == 899
    assert block["body_md"].splitlines() == [
        BENEFITS, "Additional general challenges include:", "i. High entry costs", "ii. Low liquidity",
        "Together, these challenges continue to limit the performance of Kenyan REITs."]


def test_the_standing_text_is_a_placeholder_when_nothing_holds_it():
    block = _block(_build(fetch_previous_issue=lambda _day: None), "standing")
    assert block["placeholder"] and block["body_md"] == review_run.PLACEHOLDER
    assert standing_text(["Nothing here."]) is None


def test_an_approved_review_comes_before_the_previous_issue_and_an_unapproved_one_is_ignored(tmp_path):
    db = tmp_path / "app.db"
    first = _build(fetch_previous_issue=lambda _day: ISSUE, db_path=db)
    first.report_type, first.period = "weekly", PERIOD
    review_store.save_review(first, section="real_estate", db_path=db)   # saved, not approved: it must not be used
    other = Issue(issue_id=900, published=date(2026, 11, 16), sections={"real-estate": {"name": "Real Estate", "body": (
        "<p>REITs offer various benefits, from the newer issue.</p>")}})
    block = _block(_build(fetch_previous_issue=lambda _day: other, db_path=db), "standing")
    assert block["carried_from"]["issue_id"] == 900   # the issue, because the saved review is undecided
    for i in first.review_items:
        i.resolve("accept")
    first.decide("approved", first.flagged_count)
    review_store.save_review(first, section="real_estate", db_path=db)
    block = _block(_build(fetch_previous_issue=lambda _day: other, db_path=db), "standing")
    assert "approved Real Estate review" in block["carried_from"]["note"] and block["body_md"].startswith(BENEFITS)
