"""The Word summary and its email are for the weekly report only: every other report type is refused, by name.

Before the guard, a Markets Review fell through to ``KeyError: 'items'`` (it has blocks, not the weekly's items
and outlook).  A weekly-shaped review stamped with another type is the harder case: its shape would have fit.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cytonn_weekly.digital_payments import delivery as dl
from cytonn_weekly.digital_payments import review_store as rs
from cytonn_weekly.digital_payments import summary as sm
from tests import periodic_helpers as ph
from tests.review_helpers import make_review

NON_WEEKLY = [("quarterly", "Q3'2026"), ("half_year", "H1'2026"), ("annual", "FY'2025"), ("companion", "Weekly #37.2026")]


def approve(review):
    for item in review.review_items:
        if item.status != "clean":
            item.resolve("accept", None)
    review.accept_all_clean()
    review.decide("approved")
    return review


def block_review(report_type, period):
    """The Q3 Markets Review's Digital Payments (block-shaped), approved, stamped with the report type."""
    review = ph.digital_payments_review()
    review.report_type, review.period = report_type, period
    return approve(review)


def weekly_shaped_review(report_type, period):
    """Weekly Digital Payments content (items, outlook) that WOULD render, stamped as another report type."""
    review = make_review()
    review.report_type, review.period = report_type, period
    return approve(review)


@pytest.fixture
def smtp(monkeypatch):
    cls = MagicMock(name="SMTP")
    monkeypatch.setattr(dl.smtplib, "SMTP", cls)
    monkeypatch.setenv("CYTONN_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("CYTONN_SMTP_USER", "tool@example.com")
    monkeypatch.setenv("CYTONN_SMTP_PASSWORD", "s3cret")
    monkeypatch.setenv("CYTONN_SUMMARY_RECIPIENTS", "edwin@example.com")
    return SimpleNamespace(cls=cls)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "reviews.db"


SHAPES = [pytest.param(block_review, id="block-shaped"), pytest.param(weekly_shaped_review, id="weekly-shaped")]


@pytest.mark.parametrize("report_type,period", NON_WEEKLY)
@pytest.mark.parametrize("build", SHAPES)
def test_write_summary_refuses_a_non_weekly_review(build, report_type, period, tmp_path):
    review = build(report_type, period)
    with pytest.raises(sm.SummaryNotAllowed, match=f"is a {report_type} review .*weekly report only"):
        sm.write_summary(review, tmp_path / "out.docx")
    assert not (tmp_path / "out.docx").exists()


@pytest.mark.parametrize("report_type,period", NON_WEEKLY)
@pytest.mark.parametrize("build", SHAPES)
def test_email_summary_refuses_a_non_weekly_review_and_never_touches_smtp(build, report_type, period, tmp_path, smtp):
    review = build(report_type, period)
    path = tmp_path / "out.docx"
    path.write_bytes(b"not a real docx")
    with pytest.raises(sm.SummaryNotAllowed, match=f"is a {report_type} review"):
        dl.email_summary(path, review, recipients=["edwin@example.com"])
    smtp.cls.assert_not_called()


@pytest.mark.parametrize("report_type,period", NON_WEEKLY)
@pytest.mark.parametrize("build", SHAPES)
def test_latest_functions_refuse_a_non_weekly_review_and_never_touch_smtp(build, report_type, period, db, tmp_path, smtp):
    rs.save_review(build(report_type, period), section="digital_payments", db_path=db)
    with pytest.raises(sm.SummaryNotAllowed, match=f"is a {report_type} review"):
        sm.write_latest_summary(tmp_path / "a.docx", report_type=report_type, db_path=db)
    with pytest.raises(sm.SummaryNotAllowed, match=f"is a {report_type} review"):
        dl.deliver_latest_summary(report_type=report_type, db_path=db, out_path=tmp_path / "b.docx")
    smtp.cls.assert_not_called()
    assert not list(tmp_path.glob("*.docx"))


@pytest.mark.parametrize("report_type,period", NON_WEEKLY)
def test_default_latest_calls_ignore_a_newer_non_weekly_review(report_type, period, db, tmp_path, smtp):
    """The defaults are unchanged: weekly only, so a newer non-weekly review is never even loaded."""
    rs.save_review(block_review(report_type, period), section="digital_payments", db_path=db)
    with pytest.raises(sm.SummaryNotAllowed, match="no saved review"):
        sm.write_latest_summary(tmp_path / "a.docx", db_path=db)
    with pytest.raises(sm.SummaryNotAllowed, match="no saved review"):
        dl.deliver_latest_summary(db_path=db, out_path=tmp_path / "b.docx")
    smtp.cls.assert_not_called()


def test_a_weekly_review_still_summarizes_and_sends(db, tmp_path, smtp):
    rs.save_review(approve(make_review()), section="digital_payments", db_path=db)
    assert sm.write_latest_summary(tmp_path / "a.docx", db_path=db).exists()
    dl.deliver_latest_summary(db_path=db, out_path=tmp_path / "b.docx")
    smtp.cls.assert_called_once()
