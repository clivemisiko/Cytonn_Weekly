"""The approved weekly report as one Word file: only when every section is approved, in the real order.

The sections here are real reviews: Company Updates and Fixed Income from the weekly
builders (synthetic inputs, the public bulletin), the others from the section helpers.
The .docx is checked by opening it again with python-docx.
"""

import io
from datetime import date

import pytest
from docx import Document
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.digital_payments.delivery import DevModeDeliveryBlocked
from cytonn_weekly.equities import weekly as eq_weekly
from cytonn_weekly.fixed_income import weekly as fi_weekly
from cytonn_weekly.weekly import company_updates, export, inputs
from tests import section_helpers as sh
from tests import weekly_helpers as wh
from tests.review_helpers import LocalFakeProvider, make_review
from tests.test_weekly_equities import SYNTHETIC_BOXES
from tests.test_weekly_equities import fetchers as eq_fetchers
from tests.test_weekly_fixed_income import BULLETIN
from tests.test_weekly_fixed_income import fetchers as fi_fetchers
from tests.weekly_helpers import text_pdfs  # noqa: F401 - a fixture

WEEK = wh.WEEK
PERIOD = "Week ending 2026-10-02"
ORDER = ["Company Updates", "Fixed Income", "Equities", "Real Estate", "Digital Payments Weekly Highlights", "Focus of the Week"]


def _approve(review):
    for item in review.review_items:
        item.resolve("accept")
    review.decide("approved")
    return review


def _save(db, slug, review, approve=True):
    review.report_type, review.period = "weekly", PERIOD
    review.section.setdefault("section", slug)
    if approve:
        _approve(review)
    review_store.save_review(review, section=slug, db_path=db)
    return review


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """The two computed sections, built once: (fixed income, equities)."""
    from cytonn_weekly.weekly import kcb   # what the text_pdfs fixture patches, done here at module scope

    root = tmp_path_factory.mktemp("inputs")
    real_text = kcb.pdf_text
    kcb.pdf_text = lambda b: wh.text_of(b) if b"%%synthetic-text" in b else real_text(b)
    try:
        inputs.store(WEEK, "cbk_bulletin", BULLETIN, "bulletin.pdf", root)
        inputs.store(WEEK, "fi_workbook", wh.fi_workbook_bytes(), "FI.xlsx", root)
        inputs.store(WEEK, "equities_workbook", wh.equities_workbook_bytes(), "Equities.xlsx", root)
        inputs.store(WEEK, "kcb_weekly", wh.fake_pdf(wh.kcb_weekly_text()), "weekly.pdf", root)
        inputs.store(WEEK, "kcb_daily", wh.fake_pdf(wh.kcb_daily_text(WEEK.ending)), "fri.pdf", root)
        fi = fi_weekly.build_fixed_income_review(WEEK.ending, inputs=inputs.WeeklyInputs(WEEK, root), fetchers=fi_fetchers(),
                                                 draft=wh.no_draft)
        eq = eq_weekly.build_equities_weekly_review(WEEK.ending, inputs=inputs.WeeklyInputs(WEEK, root), draft=wh.no_draft,
                                                    today=date(2026, 10, 9), fetchers=eq_fetchers(SYNTHETIC_BOXES))
    finally:
        kcb.pdf_text = real_text
    return fi, eq


def _copy(review):
    """A fresh, undecided copy of a built review (each test saves and decides its own)."""
    import copy

    return copy.deepcopy(review)


@pytest.fixture
def week(tmp_path, built):
    """A database holding the week's six sections, every one approved."""
    db = tmp_path / "app.db"
    fi, eq = built
    _save(db, "company_updates", company_updates.build_company_updates_weekly_review("Investment Updates:\n\nRates held.", WEEK.ending))
    _save(db, "fixed_income", _copy(fi))
    _save(db, "equities", _copy(eq))
    _save(db, "real_estate", sh.real_estate_review())
    _save(db, "digital_payments", make_review())
    _save(db, "focus", sh.focus_review(topic="SSA Eurobonds"))
    return db


def _text(path_or_bytes):
    doc = Document(io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else str(path_or_bytes))
    return doc, [p.text for p in doc.paragraphs]


def test_the_export_is_refused_until_every_section_is_approved(tmp_path, built):
    db = tmp_path / "app.db"
    status = export.export_status(db, PERIOD)
    assert status["ready"] is False and [s["state"] for s in status["sections"]] == ["not_drafted"] * 6
    assert [s["title"] for s in status["sections"]] == ORDER and status["file_name"] == "Cytonn-Weekly-2026-10-02.docx"
    fi, _ = built
    _save(db, "fixed_income", _copy(fi), approve=False)
    _save(db, "company_updates", company_updates.build_company_updates_weekly_review("Text.", WEEK.ending))
    rejected = sh.real_estate_review()
    rejected.report_type, rejected.period = "weekly", PERIOD
    rejected.decide("rejected")
    review_store.save_review(rejected, section="real_estate", db_path=db)
    with pytest.raises(export.ExportNotAllowed) as refused:
        export.write_weekly_report(db, PERIOD, tmp_path / "out")
    assert str(refused.value) == (
        "The weekly report can be exported only when every section is approved. Not yet: Fixed Income (still in review); "
        "Equities (not drafted); Real Estate (rejected); Digital Payments Weekly Highlights (not drafted); Focus of the Week "
        "(not drafted).")
    assert not (tmp_path / "out").exists()   # nothing is written


def test_the_report_has_the_real_order_and_headings_with_a_summary_per_section(week, tmp_path):
    assert export.export_status(week, PERIOD)["ready"] is True
    path = export.write_weekly_report(week, PERIOD, tmp_path / "out")
    assert path.name == "Cytonn-Weekly-2026-10-02.docx"
    doc, text = _text(path)
    headings = [p.text for p in doc.paragraphs if p.style.name == "Heading 1"]
    assert headings == ORDER + ["Section summaries for the CMS"]
    assert text[0] == "Cytonn Weekly: week ending 2nd October 2026" and doc.core_properties.title == text[0]
    # the last part: one summary per section, in the same order; Company Updates has none, as published
    tail = text[text.index("Section summaries for the CMS"):]
    assert [t for t in tail if t in ORDER] == ORDER
    assert "No summary: the published issue's section has none." in tail
    assert any(t.startswith("This week, T-bills were oversubscribed, with the overall subscription rate coming in at 170.4%") for t in tail)


def test_computed_paragraphs_tables_charts_and_marked_text_are_all_in_the_file(week, tmp_path):
    doc, text = _text(export.write_weekly_report(week, PERIOD, tmp_path / "out"))
    body = "\n".join(text)
    # the golden figures of the published week, from the public bulletin and CBK
    assert "overall subscription rate coming in at 170.4%, higher than the subscription rate of 149.0%" in body
    assert "The average interbank volumes traded decreased by 34.4% to Kshs 9.5 bn from Kshs 14.5 bn" in body
    assert "increasing the most by 75.6 bps to 7.6% from 6.9% recorded the previous week" in body
    assert "the Kenya Shilling depreciated against the US Dollar by 10.8 bps, to close the week at Kshs 129.8" in body
    assert "is at 58.3% of its pro-rated net domestic borrowing target" in body and "ahead of its" not in body
    # charts are placeholders, where the issue puts them
    tbills = text.index("Money Markets, T-Bills Primary Auction")
    charts = [t for t in text if t.startswith("[Chart to add: ")]
    assert len(charts) == 6 + 2 and text[tbills + 3].startswith("[Chart to add: The chart below shows the yield growth rate")
    assert sum(t == "[Carried forward from the previous issue: edit before publishing]" for t in text) == 3
    assert any(t.startswith("[Not included: T-Bonds: recommended bidding range") for t in text)
    assert "Source: Business Daily" in text and "Source: Central Bank of Kenya (CBK) Weekly Highlights" in text
    assert "*Target Price as per Cytonn Analyst estimates" in text
    # tables are Word tables
    tables = {t.rows[0].cells[0].text + "|" + t.rows[0].cells[1].text: t for t in doc.tables}
    funds = tables["Rank|Fund Manager"]
    assert len(funds.rows) == 1 + len(wh.FUNDS) and funds.rows[1].cells[2].text == "11.0%"
    universe = tables["Company|Price as at 25/09/2026"]
    assert [c.text for c in universe.rows[1].cells][:4] == ["Alpha Bank", "40.0", "42.0", "5.0%"]
    # the Eurobond table as the issue prints it: issues across, the fixed rows on top
    euro = next(t for t in doc.tables if t.rows[1].cells[0].text == "Tenor")
    assert [c.text for c in euro.rows[0].cells] == ["", "2018", "2018", "2019", "2021", "2024"]
    assert [r.cells[0].text for r in euro.rows][2:6] == ["Amount Issued (USD)", "Years to Maturity", "Yields at Issue", "02-Jan-26"]
    assert [c.text for c in euro.rows[2].cells][1:] == ["1.0 bn", "1.0 bn", "1.2 bn", "1.0 bn", "1.5 bn"]
    assert not any(t.rows[0].cells[0].text == "Issue" for t in doc.tables)   # the review-only table is not repeated
    # Digital Payments keeps its own shape: the stock table with its Average row
    stocks = next(t for t in doc.tables if t.rows[0].cells[0].text == "Company" and t.rows[0].cells[1].text == "Ticker")
    assert stocks.rows[-1].cells[0].text == "Average"
    assert not doc.sections[0].header.paragraphs[0].text   # no dev mark on a normal report


def test_a_dev_mode_week_is_watermarked_and_never_sendable(week, tmp_path):
    dev = make_review(provider=LocalFakeProvider())
    _save(week, "digital_payments", dev)
    status = export.export_status(week, PERIOD)
    assert status["ready"] and status["is_dev_draft"] and status["can_send"] is False
    assert status["dev_sections"] == ["Digital Payments Weekly Highlights"] and status["dev_mode_label"] == export.DEV_LABEL
    doc, text = _text(export.write_weekly_report(week, PERIOD, tmp_path / "out"))
    assert text[0] == export.DEV_LABEL
    header = doc.sections[0].header
    assert header.paragraphs[0].text == export.DEV_LABEL
    assert 'string="DEV MODE DRAFT"' in header._element.xml and "rotation:315" in header._element.xml   # the watermark
    reviews = export.require_all_approved(export.weekly_reviews(week, PERIOD))
    with pytest.raises(DevModeDeliveryBlocked, match="Digital Payments Weekly Highlights hold pieces drafted by the local model"):
        export.refuse_to_send(reviews)


def test_a_normal_week_may_be_sent(week):
    export.refuse_to_send(export.require_all_approved(export.weekly_reviews(week, PERIOD)))   # does not raise


def test_each_week_exports_only_its_own_sections(week, tmp_path):
    other = "Week ending 2026-09-25"
    assert [s["state"] for s in export.export_status(week, other)["sections"]] == ["not_drafted"] * 6
    with pytest.raises(export.ExportNotAllowed):
        export.write_weekly_report(week, other, tmp_path / "out")
    assert export.file_name("") == "Cytonn-Weekly-unlabelled.docx" and export.file_name("Weekly #38.2026") == "Cytonn-Weekly-Weekly-38-2026.docx"
    assert export.report_title("Weekly #38.2026") == "Cytonn Weekly: Weekly #38.2026"


def test_the_api_reports_readiness_and_returns_the_file(week, tmp_path):
    client = TestClient(create_app(db_path=week, load_dotenv=False, export_root=tmp_path / "exports"))
    status = client.get("/api/export/weekly", params={"period": "2026-10-02"}).json()
    assert status["ready"] is True and status["period"] == PERIOD and len(status["sections"]) == 6
    r = client.post("/api/export/weekly", params={"period": "2026-10-02"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert 'filename="Cytonn-Weekly-2026-10-02.docx"' in r.headers["content-disposition"]
    _, text = _text(r.content)
    assert text[0] == "Cytonn Weekly: week ending 2nd October 2026"
    assert (tmp_path / "exports" / "Cytonn-Weekly-2026-10-02.docx").is_file()
    refused = client.post("/api/export/weekly", params={"period": "2026-09-25"})
    assert refused.status_code == 409 and refused.json()["detail"].startswith("The weekly report can be exported only when every section is approved.")
    assert client.get("/api/export/weekly", params={"period": "2026-10-03"}).status_code == 422


def test_nothing_in_the_app_sends_or_publishes_the_export():
    """The export hands a file to the coordinator; the CMS publish step is still the untouched stub."""
    import inspect

    from api import cms_publish

    source = inspect.getsource(export)
    assert "smtplib" not in source and "cms_publish" not in source and "publish_report" not in source
    with pytest.raises(cms_publish.PublishNotAllowed):
        cms_publish.publish_report("weekly", PERIOD, [])
