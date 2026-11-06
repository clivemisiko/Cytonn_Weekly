import inspect
from datetime import date

import pytest

from cytonn_weekly import source_pieces
from cytonn_weekly.digital_payments import review_run as dp_run
from cytonn_weekly.digital_payments.highlights import HIGHLIGHT_COMPANIES
from cytonn_weekly.equities import weekly as equities_weekly
from cytonn_weekly.equities.review_run import BRIEFS as EQUITIES_BRIEFS
from cytonn_weekly.fixed_income import weekly as fi_weekly
from cytonn_weekly.fixed_income.weekly import BRIEFS as FI_BRIEFS
from cytonn_weekly.real_estate.review_run import BRIEFS as RE_BRIEFS
from cytonn_weekly.source_pieces import Piece, pieces_for
from tests import periodic_helpers as ph
from tests import section_helpers as sh
from tests.review_helpers import ROWS, FakeProvider

FRIDAY = date(2026, 10, 2)
PERIOD = "Week ending 2026-10-02"
TITLES = ["Overview of the topic", "Market performance", "Risks", "Recommendations and Conclusion"]


class Recording(sh.FakeNarrativeProvider):
    """The fake narrative provider that remembers what each piece was asked about and as of which day."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.asked = []

    def draft_piece(self, brief, *, start, end, today):
        self.asked.append(Piece(brief.label, end))
        return super().draft_piece(brief, start=start, end=end, today=today)


class RecordingHighlights(FakeProvider):
    def __init__(self):
        self.asked = []

    def find_highlight(self, company, ir_domain, *, start, end, today, aliases=None, style_examples=""):
        self.asked.append(Piece(company, end))
        return super().find_highlight(company, ir_domain, start=start, end=end, today=today, aliases=aliases,
                                      style_examples=style_examples)


# --- what is enumerated ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("slug,briefs", [("fixed_income", FI_BRIEFS), ("equities", EQUITIES_BRIEFS), ("real_estate", RE_BRIEFS)])
def test_a_weekly_section_has_one_piece_per_brief_on_the_weeks_friday(slug, briefs):
    assert pieces_for("weekly", PERIOD, slug) == [Piece(b.label, FRIDAY) for b in briefs]


def test_weekly_digital_payments_has_its_five_companies():
    assert pieces_for("weekly", PERIOD, "digital_payments") == [Piece(c["name"], FRIDAY) for c in HIGHLIGHT_COMPANIES]
    assert [p.subject for p in pieces_for("weekly", PERIOD, "digital_payments")] == [
        "Visa", "Mastercard", "American Express", "PayPal", "Circle"]


def test_a_focus_has_a_piece_per_typed_title_and_none_for_the_closing_part():
    assert [p.subject for p in pieces_for("weekly", PERIOD, "focus", sections=TITLES)] == TITLES[:3]
    assert [p.subject for p in pieces_for("weekly", PERIOD, "focus", sections=TITLES[:3])] == TITLES[:3]
    assert pieces_for("weekly", PERIOD, "focus", sections=[]) == []        # none can be named until titles are typed
    spaced = pieces_for("weekly", PERIOD, "focus", sections=["  Market   performance "])
    assert [p.subject for p in spaced] == ["Market performance"]


def test_a_weekly_with_no_period_uses_the_latest_friday_and_a_named_week_uses_its_own():
    assert {p.end for p in pieces_for("weekly", "", "equities", today=date(2026, 11, 10))} == {date(2026, 11, 6)}
    assert {p.end for p in pieces_for("weekly", "", "equities", today=date(2026, 11, 6))} == {date(2026, 11, 6)}
    assert {p.end for p in pieces_for("weekly", PERIOD, "equities", today=date(2026, 11, 10))} == {FRIDAY}


@pytest.mark.parametrize("report_type,period,slug", [
    ("weekly", PERIOD, "company_updates"), ("weekly", PERIOD, "executive_summary"), ("weekly", PERIOD, "nope"),
    ("quarterly", "Q3'2026", "company_updates"), ("quarterly", "Q3'2026", "executive_summary"),
    ("monthly", "Oct'2026", "fixed_income"), ("companion", "", "fixed_income"),
])
def test_a_section_that_calls_no_provider_or_is_not_drafted_has_no_pieces(report_type, period, slug):
    assert pieces_for(report_type, period, slug) is None


@pytest.mark.parametrize("report_type,period", [("quarterly", "Q3'2026"), ("half_year", "H1'2026"), ("annual", "FY'2025")])
def test_a_markets_review_section_has_its_briefs_ending_on_the_period_end(report_type, period):
    ctx = ph.ctx(report_type, period)
    for slug in ("global_markets", "ssa", "kenya_macro", "fixed_income", "equities", "real_estate"):
        found = pieces_for(report_type, period, slug, today=ph.TODAY)
        assert found and {p.end for p in found} == {ctx.end}, slug
        assert len({p.subject for p in found}) == len(found), slug      # no two pieces share a name


def test_markets_review_digital_payments_has_its_companies_as_of_the_draft_day_and_the_months_other_highlights():
    found = pieces_for("quarterly", "Q3'2026", "digital_payments", today=ph.TODAY)
    assert [p.subject for p in found[:5]] == [c["name"] for c in HIGHLIGHT_COMPANIES]
    assert {p.end for p in found[:5]} == {ph.TODAY}
    assert found[5].subject.startswith("Other notable digital payments sector highlights") and len(found) == 6
    assert found[5].end == ph.ctx().window[1]


def test_a_piece_is_filed_under_the_friday_on_or_before_its_end():
    from cytonn_weekly.common import sources

    folder = lambda p: sources._folder(p.end, None).name  # noqa: E731
    assert {folder(p) for p in pieces_for("weekly", PERIOD, "real_estate")} == {"2026-10-02"}
    assert {folder(p) for p in pieces_for("quarterly", "Q3'2026", "kenya_macro", today=ph.TODAY)} == {"2026-09-25"}


# --- what the builders really ask --------------------------------------------------------------------------------------------

def test_the_weekly_real_estate_builder_asks_about_pieces_that_are_enumerated():
    provider = Recording()
    sh.real_estate_review(provider)
    expected = pieces_for("weekly", PERIOD, "real_estate")
    assert provider.asked and all(p in expected for p in provider.asked)


def test_the_weekly_digital_payments_builder_asks_about_pieces_that_are_enumerated():
    provider = RecordingHighlights()
    dp_run.build_digital_payments_review(provider=provider, today=FRIDAY, fetch_table=lambda today: ROWS)
    expected = pieces_for("weekly", PERIOD, "digital_payments")
    assert len(provider.asked) == 4 and all(p in expected for p in provider.asked)


def test_the_weekly_focus_builder_asks_about_exactly_the_enumerated_pieces():
    provider = Recording()
    sh.focus_review(provider=provider, sections=TITLES)
    assert provider.asked == pieces_for("weekly", PERIOD, "focus", sections=TITLES)


@pytest.mark.parametrize("module,name", [(fi_weekly, "fixed income"), (equities_weekly, "equities")])
def test_the_weekly_fixed_income_and_equities_builders_draft_over_the_week_ending_the_friday(module, name):
    # They need a week's inputs to run, so the dates they pass are pinned by reading the call: the window ends on the
    # week's Friday, which is what pieces_for files their sources under.
    source = inspect.getsource(module)
    assert "window=(week.ending - timedelta(days=6), week.ending)" in source, name
    assert "(draft or draft_pieces)(BRIEFS, N_HIGHLIGHTS" in source, name


@pytest.mark.parametrize("report_type,period", [("quarterly", "Q3'2026"), ("half_year", "H1'2026")])
@pytest.mark.parametrize("slug", ["global_markets", "ssa", "kenya_macro", "fixed_income", "equities", "real_estate"])
def test_a_markets_review_builder_asks_about_pieces_that_are_enumerated(report_type, period, slug):
    provider = Recording()
    c = ph.ctx(report_type, period)
    ph.BUILDERS[slug](c, provider=provider)
    expected = pieces_for(report_type, period, slug, today=ph.TODAY)
    assert provider.asked and all(p in expected for p in provider.asked), slug


@pytest.mark.parametrize("report_type,period", [("quarterly", "Q3'2026"), ("half_year", "H1'2026")])
def test_the_markets_review_digital_payments_builder_asks_about_pieces_that_are_enumerated(report_type, period):
    narrative, highlights = Recording(), RecordingHighlights()
    ph.digital_payments_review(ph.ctx(report_type, period), provider=highlights, narrative_provider=narrative)
    expected = pieces_for(report_type, period, "digital_payments", today=ph.TODAY)
    asked = highlights.asked + narrative.asked
    assert len(narrative.asked) == 1 and len(highlights.asked) == 4
    assert all(p in expected for p in asked)


def test_the_module_reads_the_briefs_and_companies_the_builders_use_rather_than_holding_its_own_lists():
    text = inspect.getsource(source_pieces)
    for label in ("Mortgage lending", "Visa", "Mastercard"):
        assert label not in text
