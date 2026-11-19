import json

import pytest

from dataclasses import replace

from cytonn_weekly.review.blocks import CLAIM
from cytonn_weekly.review.model import FLAGGED, NOT_AUTO_VERIFIED
from cytonn_weekly.focus.review_run import (
    GUIDE_NOTE, MAX_SECTION_TITLE, build_focus_review, clean_sections, clean_topic, parse_outline, section_brief,
)
from cytonn_weekly.drafting.prompts import narrative_system
from cytonn_weekly.drafting.replies import piece_from_reply
from tests.section_helpers import TODAY, FakeNarrativeProvider, focus_review, previous_issue

TYPED = "Overview\nSection 3: Yields\nRecommendations and Conclusion"


def blocks(review, role=None):
    return [b for b in review.section["blocks"] if role is None or b.get("role") == role]


def said(item):
    return " ".join(f.message for f in item.detail)


def test_topic_is_required_and_bounded():
    assert clean_topic("  SSA   Eurobonds ") == "SSA Eurobonds"
    with pytest.raises(ValueError, match="needs a topic"):
        clean_topic("   ")
    with pytest.raises(ValueError, match="the limit is 500"):
        clean_topic("x" * 501)


def test_typed_titles_are_used_as_typed_numbered_in_code_and_prefix_stripped():
    review = focus_review(sections=TYPED)
    assert review.section["outline"] == {"titles": ["Overview", "Yields", "Recommendations and Conclusion"], "source": "typed"}
    assert [b["group_heading"] for b in blocks(review) if "group_heading" in b] == ["Section I: Overview", "Section II: Yields"]
    assert blocks(review, "contents")[0]["body_md"].split("\n\n")[-1] == "Section III: Recommendations and Conclusion"


def test_titles_beyond_the_limits_are_refused_with_a_sentence():
    with pytest.raises(ValueError, match="9 section titles; the limit is 8"):
        clean_sections("\n".join(f"T{i}" for i in range(9)))
    with pytest.raises(ValueError, match=f"section title 2 is 121 characters; the limit is {MAX_SECTION_TITLE}"):
        clean_sections("Fine\n" + "x" * 121)
    with pytest.raises(ValueError, match="section title 1 is empty"):
        clean_sections("Section 2:")
    assert clean_sections("\n\n  A  b \n") == ["A b"]


def test_blank_sections_propose_an_outline_with_overview_first_and_conclusion_last():
    provider = FakeNarrativeProvider()
    review = focus_review(provider)
    assert review.section["outline"]["source"] == "proposed"
    titles = review.section["outline"]["titles"]
    assert titles[0] == "Overview of the topic" and titles[-1] == "Recommendations and Conclusion"
    assert "propose the section titles" in provider.completions[0][0] and provider.completions[0][2] == 300


@pytest.mark.parametrize("reply", [
    "Here is a long sentence of prose that the model wrote instead of a list of titles, which should be refused outright.",
    "Overview\nOnly two\nRecommendations and Conclusion",
    "Market\nPerformance\nRisks\nRecommendations and Conclusion",
    "Overview\nPerformance\nRisks\nOutlook",
])
def test_an_outline_that_is_not_titles_is_refused_with_a_way_out(reply):
    provider = FakeNarrativeProvider()
    provider.replies["propose the section titles"] = reply
    with pytest.raises(ValueError, match="Type the section titles yourself"):
        focus_review(provider)
    assert provider.calls == []


def test_parse_outline_strips_bullets_and_numbering():
    assert parse_outline("1. **Overview**\n- Yields\n* Risks\n2) Section IV: Recommendations and Conclusion") == [
        "Overview", "Yields", "Risks", "Recommendations and Conclusion"]


def test_block_order_and_contents_list_every_title():
    review = focus_review(sections=TYPED)
    assert [b.get("role") for b in blocks(review)] == ["contents", "findings", "findings", "disclaimer"]
    assert blocks(review, "contents")[0]["body_md"].split("\n\n") == [
        "Section I: Overview", "Section II: Yields", "Section III: Recommendations and Conclusion"]


def test_each_section_is_findings_only_and_the_tool_writes_no_lead_or_conclusion():
    provider = FakeNarrativeProvider()
    review = focus_review(provider, sections=TYPED)
    assert provider.calls == ["focus_section_1", "focus_section_2"] and provider.completions == []
    assert review.section["model_calls"] == 2 and review.section["api_requests"] == 2
    assert review.section["pieces_expected"] == 2 and review.section["pieces_found"] == 2
    findings = blocks(review, "findings")
    assert all(b["body"] == "" and b["body_md"] == "" and b["links"] == [] and len(b["claims"]) == 2 for b in findings)
    assert not blocks(review, "lead") and not blocks(review, "conclusion")
    claims = [i for i in review.review_items if i.kind == CLAIM]
    assert len(claims) == 4 and all(i.status == NOT_AUTO_VERIFIED for i in claims)


def test_a_finding_whose_figure_is_not_in_its_quote_is_reported_but_never_flagged():
    review = focus_review(FakeNarrativeProvider(bad_figure=True), sections=TYPED)
    bad = [i for i in review.review_items if i.kind == CLAIM and "99.9" in i.ref]
    assert bad and all(i.status == NOT_AUTO_VERIFIED and isinstance(i.detail, str) and "99.9" in i.detail for i in bad)


def test_a_findings_focus_has_nothing_flagged_so_approving_needs_no_acknowledgement():
    review = focus_review(FakeNarrativeProvider(bad_figure=True, no_story={"focus_section_2"}), sections=TYPED,
                          previous=lambda _day: (_ for _ in ()).throw(OSError("site down")))   # a missing section and an unreadable disclaimer too
    assert review.flagged_count == 0 and review.is_approvable
    review.decide("approved")
    assert review.decision == "approved"


def test_a_finding_can_be_removed_but_not_edited():
    from api.serialize import serialize_review

    shown = serialize_review(focus_review(FakeNarrativeProvider(bad_figure=True), sections=TYPED))["review_items"]
    claims = [i for i in shown if i["kind"] == "claim"]
    assert claims and not any(i["edit_sentence"] for i in claims) and all(i["remove_finding"] for i in claims)


def test_the_outline_is_still_one_model_call_and_counts_in_the_calls():
    provider = FakeNarrativeProvider()
    review = focus_review(provider)
    assert [c[2] for c in provider.completions] == [300] and review.section["model_calls"] == 4


def test_section_briefs_ask_for_findings_with_the_caps_and_the_title_list():
    provider = FakeNarrativeProvider()
    seen = []
    draft = provider.draft_piece
    provider.draft_piece = lambda brief, **kw: (seen.append(brief), draft(brief, **kw))[1]
    focus_review(provider, sections=TYPED)
    assert all(b.max_searches == 5 and b.max_tokens == 3000 and b.findings and not b.headed for b in seen)
    assert "Section III: Recommendations and Conclusion" in seen[0].context
    system = narrative_system(seen[0])
    assert "write no prose" in system and "words" not in system


def test_titles_with_no_closing_part_are_all_drafted_with_a_search():
    provider = FakeNarrativeProvider()
    review = focus_review(provider, sections="Overview\nYields")
    assert provider.calls == ["focus_section_1", "focus_section_2"]
    assert [b.get("role") for b in blocks(review)] == ["contents", "findings", "findings", "disclaimer"]


def test_a_findings_reply_keeps_the_claims_and_drops_any_paragraph():
    brief = section_brief("T", ["A", "B"], 0)
    url = "https://example.org/a"
    reply = json.dumps({"is_genuine_announcement": True, "headline": "ignored", "paragraph": "Prose the model wrote anyway.",
                        "claims": [{"claim": "Yields rose 1.2%.", "url": url}, {"claim": "unseen", "url": "https://x.org/z"}]})
    warnings = []
    piece = piece_from_reply(reply, brief, "web", [{"url": url, "title": "A"}], warnings, who="model", label="L", drafted_by="test")
    assert piece.paragraph == "" and piece.paragraph_md == "" and piece.headline == "A" and piece.links == []
    assert [c["text"] for c in piece.claims] == ["Yields rose 1.2%."]
    none = json.dumps({"is_genuine_announcement": True, "paragraph": "Only prose.", "claims": []})
    assert piece_from_reply(none, brief, "web", [], warnings, who="model", label="L", drafted_by="test") is None
    assert any("returned no findings" in w for w in warnings)


def test_a_heading_the_model_adds_to_a_prose_section_is_dropped_with_a_warning_and_never_cuts_the_piece():
    brief = replace(section_brief("T", ["A", "B"], 0), findings=False, words=(1, 100))
    reply = json.dumps({"is_genuine_announcement": True, "headline": "ignored", "claims": [],
                        "paragraph": "### x\nFirst paragraph here.\n\n# y\nSecond paragraph here."})
    warnings = []
    piece = piece_from_reply(reply, brief, "web", [], warnings, who="model", label="L", drafted_by="test")
    assert piece.paragraph.count("paragraph") == 2 and "x" not in piece.paragraph.split()
    assert piece.headline == "A" and any("removed heading line(s)" in w for w in warnings)


def test_nothing_found_raises_instead_of_saving_an_empty_review():
    with pytest.raises(LookupError, match=r"^No section produced a sourced draft, so nothing was saved\. 2 of 2 sections: "):
        build_focus_review("Obscure", provider=FakeNarrativeProvider(no_story={"focus_section_1", "focus_section_2"}),
                           today=TODAY, sections=TYPED, previous_issue=previous_issue())


def test_a_section_with_nothing_found_is_an_unavailable_part_the_rest_still_drafts():
    review = focus_review(FakeNarrativeProvider(no_story={"focus_section_2"}), sections=TYPED)
    section = blocks(review)[2]
    assert section["kind"] == "unavailable" and section["group_heading"] == "Section II: Yields"
    assert review.section["pieces_found"] == 1 and review.section["shortfall"] == 1


def test_disclaimer_is_carried_verbatim_and_shown_but_needs_no_acknowledgement():
    review = focus_review(sections=TYPED)
    block = blocks(review, "disclaimer")[0]
    assert block["kind"] == "carried" and block["body_md"] == "Disclaimer: Past performance is not a guide."
    assert not any("carried" in i.ref for i in review.review_items) and review.flagged_count == 0


def test_disclaimer_unavailable_when_the_previous_issue_cannot_be_read_or_has_none():
    def down(_day):
        raise OSError("site down")

    block = blocks(focus_review(sections=TYPED, previous=down), "disclaimer")[0]
    assert block["kind"] == "unavailable" and "Paste the disclaimer in by hand" in block["unblock"] and "site down" in block["reason"]
    none = focus_review(sections=TYPED, previous=previous_issue({"x": {"name": "X", "body": "<p>Nothing.</p>"}}))
    assert "no paragraph starting" in blocks(none, "disclaimer")[0]["reason"]


def test_every_findings_section_says_it_is_research_notes_not_report_text():
    notes = [b["analyst_note"] for b in blocks(focus_review(sections=TYPED)) if b.get("analyst_note")]
    assert notes == [GUIDE_NOTE] * 2 and "not report text" in GUIDE_NOTE and "not exported" in GUIDE_NOTE
