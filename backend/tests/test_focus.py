"""Focus of the Week: the coordinator's topic, one long-form cited piece, checked like any claim."""

import pytest

from cytonn_weekly.common.review import CLAIM
from cytonn_weekly.digital_payments.coordinator_review import FLAGGED, NOT_AUTO_VERIFIED
from cytonn_weekly.focus.review_run import SECTION, WORDS, brief_for, build_focus_review, clean_topic
from tests.section_helpers import TODAY, FakeNarrativeProvider, focus_review


def test_topic_is_required_and_bounded():
    assert clean_topic("  SSA   Eurobonds ") == "SSA Eurobonds"
    with pytest.raises(ValueError, match="needs a topic"):
        clean_topic("   ")
    with pytest.raises(ValueError, match="the limit is 500"):
        clean_topic("x" * 501)


def test_brief_is_long_form_and_free_of_the_highlight_opener():
    b = brief_for("SSA Eurobonds")
    assert b.words == WORDS and b.opener is None and b.label == "SSA Eurobonds"


def test_review_carries_the_topic_and_every_claim():
    provider = FakeNarrativeProvider()
    review = focus_review(provider)
    assert provider.calls == ["focus"]
    assert review.section["section"] == SECTION and review.section["topic"] == "SSA Eurobonds performance"
    assert [b["kind"] for b in review.section["blocks"]] == ["narrative"]
    assert [(i.kind, i.status) for i in review.review_items] == [(CLAIM, NOT_AUTO_VERIFIED)] * 2


def test_unsupported_figure_is_flagged():
    review = focus_review(FakeNarrativeProvider(bad_figure=True))
    assert [i.status for i in review.review_items] == [NOT_AUTO_VERIFIED, FLAGGED]


def test_local_provider_claims_are_unchecked_not_passed():
    review = focus_review(FakeNarrativeProvider(cited=False))
    assert all("could not be checked" in i.detail for i in review.review_items)


def test_nothing_found_raises_instead_of_saving_an_empty_review():
    with pytest.raises(LookupError, match="no sourced material"):
        build_focus_review("Obscure", provider=FakeNarrativeProvider(no_story={"focus"}), today=TODAY)
