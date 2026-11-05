from types import SimpleNamespace as NS

import pytest

from cytonn_weekly.common.review import CLAIM, PIECE_CHECK
from cytonn_weekly.digital_payments.coordinator_review import FLAGGED, NOT_AUTO_VERIFIED
from cytonn_weekly.focus.review_run import (
    JUDGEMENT, MAX_SECTION_TITLE, build_focus_review, clean_sections, clean_topic, parse_outline, section_brief,
)
from cytonn_weekly.narrative.anthropic_provider import parse_piece
from tests.section_helpers import TODAY, FakeNarrativeProvider, focus_review, previous_issue

TYPED = "Overview\nSection 3: Yields\nRecommendations and Conclusion"


def blocks(review, role=None):
    return [b for b in review.section["blocks"] if role is None or b.get("role") == role]


def said(item):
    return " ".join(f.message for f in item.detail)


def piece_item(review, word):
    return next(i for i in review.review_items if i.kind == PIECE_CHECK and word in i.ref)


def test_topic_is_required_and_bounded():
    assert clean_topic("  SSA   Eurobonds ") == "SSA Eurobonds"
    with pytest.raises(ValueError, match="needs a topic"):
        clean_topic("   ")
    with pytest.raises(ValueError, match="the limit is 500"):
        clean_topic("x" * 501)


def test_typed_titles_are_used_as_typed_numbered_in_code_and_prefix_stripped():
    review = focus_review(sections=TYPED)
    assert review.section["outline"] == {"titles": ["Overview", "Yields", "Recommendations and Conclusion"], "source": "typed"}
    assert [b["group_heading"] for b in blocks(review) if "group_heading" in b] == [
        "Section I: Overview", "Section II: Yields", "Section III: Recommendations and Conclusion"]


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


def test_block_order_and_contents_equal_the_headings():
    review = focus_review(sections=TYPED)
    assert [b.get("role") for b in blocks(review)] == ["lead", "contents", "section", "section", "conclusion", "disclaimer"]
    contents = blocks(review, "contents")[0]["body_md"].split("\n\n")
    assert contents == [b["group_heading"] for b in blocks(review) if "group_heading" in b]


def test_each_section_is_its_own_cited_piece_and_the_conclusion_is_written_without_a_search():
    provider = FakeNarrativeProvider()
    review = focus_review(provider, sections=TYPED)
    assert provider.calls == ["focus_section_1", "focus_section_2"]
    assert [c[2] for c in provider.completions] == [2000, 600]
    assert "Section I: Overview" in provider.completions[0][1] and "grew" in provider.completions[0][1]
    assert review.section["model_calls"] == 4 and review.section["api_requests"] == 4
    assert review.section["pieces_expected"] == 4 and review.section["pieces_found"] == 4
    claims = [i for i in review.review_items if i.kind == CLAIM]
    assert len(claims) == 4 and all(i.status == NOT_AUTO_VERIFIED for i in claims)


def test_section_briefs_carry_the_caps_and_the_title_list():
    provider = FakeNarrativeProvider()
    seen = []
    draft = provider.draft_piece
    provider.draft_piece = lambda brief, **kw: (seen.append(brief), draft(brief, **kw))[1]
    focus_review(provider, sections=TYPED)
    assert all(b.max_searches == 5 and b.max_tokens == 2000 and b.words == (350, 650) and not b.headed for b in seen)
    assert "Section III: Recommendations and Conclusion" in seen[0].context


def test_titles_with_no_closing_part_are_all_drafted_with_a_search():
    provider = FakeNarrativeProvider()
    review = focus_review(provider, sections="Overview\nYields")
    assert provider.calls == ["focus_section_1", "focus_section_2"]
    assert [b.get("role") for b in blocks(review)] == ["lead", "contents", "section", "section", "disclaimer"]


def test_the_conclusion_is_always_flagged_for_the_analyst():
    item = piece_item(focus_review(sections=TYPED), "Conclusion")
    assert item.status == FLAGGED and JUDGEMENT in said(item)


def test_a_capitalised_rating_is_flagged_and_a_lowercase_word_is_not():
    provider = FakeNarrativeProvider()
    provider.replies["closing part"] = "We rate the outlook NEUTRAL for the next quarter."
    review = focus_review(provider, sections=TYPED)
    assert "NEUTRAL" in said(piece_item(review, "Conclusion"))
    provider.replies["closing part"] = "The outlook is neutral for the next quarter."
    assert "NEUTRAL" not in said(piece_item(focus_review(provider, sections=TYPED), "Conclusion"))


def test_a_lead_figure_that_no_section_holds_is_flagged_and_a_known_one_is_not():
    provider = FakeNarrativeProvider()
    provider.replies["opening paragraph"] = "The report covers yields of 8.75% and a surprise 42.5% rise."
    lead = piece_item(focus_review(provider, sections=TYPED), "Lead")
    assert lead.status == FLAGGED and "42.5" in said(lead) and "8.75" not in said(lead)
    provider.replies["opening paragraph"] = "The report covers yields of 8.75%."
    assert piece_item(focus_review(provider, sections=TYPED), "Lead").status == NOT_AUTO_VERIFIED


def test_a_heading_the_model_adds_is_dropped_with_a_warning_and_never_cuts_the_piece():
    brief = section_brief("T", ["A", "B"], 0)
    content = [NS(type="text", text="### x\nFirst paragraph here.\n\n# y\nSecond paragraph here.", citations=None)]
    piece = parse_piece(content, brief)
    assert piece["body"].count("paragraph") == 2 and "x" not in piece["body"].split()
    assert piece["headline"] == "A" and any("removed 2 heading line(s)" in w for w in piece["warnings"])


def test_nothing_found_raises_instead_of_saving_an_empty_review():
    with pytest.raises(LookupError, match="no sourced material"):
        build_focus_review("Obscure", provider=FakeNarrativeProvider(no_story={"focus_section_1", "focus_section_2"}),
                           today=TODAY, sections=TYPED, previous_issue=previous_issue())


def test_a_section_with_nothing_found_is_an_unavailable_part_the_rest_still_drafts():
    review = focus_review(FakeNarrativeProvider(no_story={"focus_section_2"}), sections=TYPED)
    section = blocks(review)[3]
    assert section["kind"] == "unavailable" and section["group_heading"] == "Section II: Yields"
    assert review.section["pieces_found"] == 3 and review.section["shortfall"] == 1


def test_disclaimer_is_carried_verbatim_and_flagged():
    review = focus_review(sections=TYPED)
    block = blocks(review, "disclaimer")[0]
    assert block["kind"] == "carried" and block["body_md"] == "Disclaimer: Past performance is not a guide."
    assert any(i.status == FLAGGED and "carried forward" in said(i) for i in review.review_items)


def test_disclaimer_unavailable_when_the_previous_issue_cannot_be_read_or_has_none():
    def down(_day):
        raise OSError("site down")

    block = blocks(focus_review(sections=TYPED, previous=down), "disclaimer")[0]
    assert block["kind"] == "unavailable" and "Paste the disclaimer in by hand" in block["unblock"] and "site down" in block["reason"]
    none = focus_review(sections=TYPED, previous=previous_issue({"x": {"name": "X", "body": "<p>Nothing.</p>"}}))
    assert "no paragraph starting" in blocks(none, "disclaimer")[0]["reason"]


def test_every_section_carries_the_analyst_note():
    notes = [b["analyst_note"] for b in blocks(focus_review(sections=TYPED)) if b.get("analyst_note")]
    assert notes == ["Analyst to add: Cytonn's own tables and charts for this section"] * 3
