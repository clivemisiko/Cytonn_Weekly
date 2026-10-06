"""Tests for cytonn_weekly.digital_payments.summary (the Edwin/Liz Word-doc summary).

Reviews are real CoordinatorReviews built by the real pipeline code on fake edges
(review_helpers), saved to and reloaded from a real temp SQLite file, as the real
flow does.  The output is checked by re-opening the saved .docx with python-docx
and reading its paragraphs and tables in document order.
"""

import pytest
from docx import Document
from docx.table import Table
from review_helpers import LocalFakeProvider, make_review

from cytonn_weekly.digital_payments import coordinator_review as cr
from cytonn_weekly.digital_payments import review_store as rs
from cytonn_weekly.digital_payments import summary as sm
from cytonn_weekly.digital_payments.providers.base import LINK_RE

VISA_LINKED = (
    "During the week, Visa [announced a thing](https://investor.visa.com/a) and "
    "[expanded it](https://investor.visa.com/b), as [announced](https://investor.visa.com/a) earlier."
)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "reviews.db"


def approve(review):
    review.accept_all_clean()
    for i in review.review_items:
        if i.resolution is None:
            i.resolve(cr.ACCEPT)
    review.decide("approved")
    return review


def approved_review(db, **kwargs):
    """An approved review saved to ``db``, with a linked highlight and price dates added to the section."""
    review = make_review(**kwargs)
    review.section["items"][0]["body_md"] = VISA_LINKED
    for it in review.section["items"]:
        for row in it.get("rows", []):
            row["current_price_date"] = "2026-09-30"
    approve(review)
    rs.save_review(review, db_path=db)
    return review


def read_docx(path):
    """(lines, tables): every paragraph's text in order, and each table as a list of row-lists."""
    doc = Document(str(path))
    lines, tables = [], []
    for block in doc.iter_inner_content():
        if isinstance(block, Table):
            tables.append([[c.text for c in row.cells] for row in block.rows])
        else:
            lines.append(block.text)
    return lines, tables


def full_text(path):
    lines, tables = read_docx(path)
    return "\n".join(lines + [c for t in tables for row in t for c in row])


def latest_summary(db, tmp_path, name="out.docx"):
    return sm.write_latest_summary(tmp_path / name, db_path=db)


# ---------------------------------------------------------------------------
# Only approved reviews produce a document
# ---------------------------------------------------------------------------

def test_missing_review_raises_and_writes_nothing(db, tmp_path):
    with pytest.raises(sm.SummaryNotAllowed, match="no saved review"):
        sm.write_latest_summary(tmp_path / "out.docx", db_path=db)  # empty database
    with pytest.raises(sm.SummaryNotAllowed):
        sm.write_summary(None, tmp_path / "out.docx")
    assert not (tmp_path / "out.docx").exists()


def test_in_progress_review_raises(db, tmp_path):
    review = make_review()
    review.review_items[0].resolve(cr.ACCEPT)
    rs.save_review(review, db_path=db)
    with pytest.raises(sm.SummaryNotAllowed, match="still in progress"):
        sm.write_latest_summary(tmp_path / "out.docx", db_path=db)
    assert not (tmp_path / "out.docx").exists()


def test_rejected_review_raises(db, tmp_path):
    review = make_review()
    review.decide("rejected")
    rs.save_review(review, db_path=db)
    with pytest.raises(sm.SummaryNotAllowed, match="rejected, not approved"):
        sm.write_latest_summary(tmp_path / "out.docx", db_path=db)
    assert not (tmp_path / "out.docx").exists()


def test_a_decision_field_alone_is_not_enough(tmp_path):
    review = make_review()
    review.decision, review.decided_at = cr.APPROVED, "2026-10-01T09:00:00+00:00"  # bypassing decide()
    with pytest.raises(sm.SummaryNotAllowed, match="not every item is resolved"):
        sm.write_summary(review, tmp_path / "out.docx")
    review.review_items[0].resolve(cr.FIX_NEEDED)
    with pytest.raises(sm.SummaryNotAllowed):
        sm.write_summary(review, tmp_path / "out.docx")
    assert not (tmp_path / "out.docx").exists()


def test_a_newer_unapproved_draft_blocks_summarizing_an_older_approved_one(db, tmp_path):
    approved_review(db)
    rs.save_review(make_review(), db_path=db)  # a newer draft, still in progress
    with pytest.raises(sm.SummaryNotAllowed, match="still in progress"):
        sm.write_latest_summary(tmp_path / "out.docx", db_path=db)


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

def test_header_names_the_week_and_the_approval_date(db, tmp_path):
    review = approved_review(db)
    lines, _ = read_docx(latest_summary(db, tmp_path))
    assert lines[0] == "Digital Payments: weekly insight summary"
    assert "Report week 24 Sep 2026 to 30 Sep 2026" in lines
    approved_on = sm._fmt_date(review.decided_at)
    assert any(f"approved by the coordinator on {approved_on}" in ln for ln in lines)


def test_four_highlights_in_order_with_numerals_headlines_and_paragraphs(db, tmp_path):
    approved_review(db)
    lines, _ = read_docx(latest_summary(db, tmp_path))
    heads = [ln for ln in lines if ln[:3] in ("I. ", "II.", "III", "IV.")]
    assert heads == [
        "I. Visa announces a thing", "II. Mastercard announces a thing",
        "III. American Express announces a thing", "IV. PayPal announces a thing",
    ]
    assert "During the week, Mastercard paid $5 million for a thing." in lines  # $ survives untouched
    order = [lines.index(h) for h in heads] + [lines.index("V. Digital Payments NYSE and LSE Stock Performance"),
                                              lines.index("Outlook")]
    assert order == sorted(order)


def test_citation_links_become_footnote_markers_with_a_sources_list(db, tmp_path):
    approved_review(db)
    text = full_text(latest_summary(db, tmp_path))
    assert "During the week, Visa announced a thing [1] and expanded it [2], as announced [1] earlier." in text
    assert "[1] announced a thing: https://investor.visa.com/a" in text
    assert "[2] expanded it: https://investor.visa.com/b" in text
    assert "](http" not in text and not LINK_RE.search(text)  # no raw markdown left


def test_footnote_links_unit():
    assert sm.footnote_links("plain text, no links") == ("plain text, no links", [])
    text, src = sm.footnote_links("A [x](https://a.example/1), B [y](https://b.example/2).")
    assert text == "A x [1], B y [2]." and src == [(1, "x", "https://a.example/1"), (2, "y", "https://b.example/2")]


def test_table_is_display_formatted_and_has_an_average_row(db, tmp_path):
    approved_review(db)
    _, tables = read_docx(latest_summary(db, tmp_path))
    (table,) = tables
    assert table[0] == ["Company", "Ticker", "Price", "Price 7 days ago", "Year Open", "w/w %", "YTD %", "Forward P/E"]
    by_name = {row[0]: row for row in table[1:]}
    assert by_name["Mastercard"] == ["Mastercard", "MA", "100.0", "98.0", "90.0", "(1.5%)", "10.0%", "20.0x"]
    assert by_name["Visa"][5] == "2.0%"  # positive: no plus sign
    assert by_name["Average"] == ["Average", "", "", "", "", "0.8%", "10.0%", "19.3x"]
    assert table[-1][0] == "Average" and len(table) == 5
    assert "-1.5" not in full_text(latest_summary(db, tmp_path, "again.docx"))  # raw float never shown


def test_table_notes_advancers_decliners_and_source(db, tmp_path):
    approved_review(db)
    lines, _ = read_docx(latest_summary(db, tmp_path))
    assert "Week over week: 2 advancers, 1 decliners." in lines
    assert any(ln.startswith("Source: Yahoo Finance, prices as of 30 Sep 2026.") for ln in lines)


def test_failed_price_row_shows_dashes_and_is_called_out(db, tmp_path):
    review = make_review()
    row = next(r for it in review.section["items"] if it["kind"] == "stock_table" for r in it["rows"] if r["ticker"] == "AXP")
    row.update(error="no data", current_price=None, prior_close=None, ytd_open=None,
               wow_pct=None, ytd_pct=None, forward_pe=None)
    approve(review)
    rs.save_review(review, db_path=db)
    lines, tables = read_docx(latest_summary(db, tmp_path))
    axp = next(r for r in tables[0] if r[0] == "American Express")
    assert axp[2:] == ["-"] * 6
    assert "Price data could not be retrieved for: American Express (AXP)." in lines


def test_outlook_is_plain_text_without_markdown_markers(db, tmp_path):
    approved_review(db)
    lines, _ = read_docx(latest_summary(db, tmp_path))
    assert lines[lines.index("Outlook") + 1] == "Outlook: the sector gained $2 billion."
    assert "***" not in "\n".join(lines)


def test_shortfall_is_stated_when_fewer_than_four_highlights(db, tmp_path):
    review = make_review()
    review.section["items"].pop(3)  # drop highlight IV, as a week with only three stories would
    review.section["shortfall"] = 1
    approve(review)
    rs.save_review(review, db_path=db)
    lines, _ = read_docx(latest_summary(db, tmp_path))
    assert "Only 3 of 4 highlights were found this week." in lines


def test_none_of_the_review_mechanics_leak_into_the_document(db, tmp_path):
    review = make_review(tamper=True)  # flagged items exist, and the coordinator accepted them
    review.review_items[0].resolve(cr.ACCEPT, "SECRET-NOTE")
    approve(review)
    rs.save_review(review, db_path=db)
    text = full_text(latest_summary(db, tmp_path)).lower()
    for word in ("flag", "mismatch", "resolution", "fix needed", "fix_needed", "unresolved",
                 "not_auto_verified", "not automatically", "secret-note", "drafted by", "fake:test",
                 "cited_text", "sources_disagree", "unsourced"):
        assert word not in text, word


def test_dev_mode_draft_is_stamped_not_for_circulation(db, tmp_path):
    local = approve(make_review(provider=LocalFakeProvider()))
    rs.save_review(local, db_path=db)
    lines, _ = read_docx(latest_summary(db, tmp_path))
    assert lines[0] == "DEV MODE DRAFT (local model): NOT FOR CIRCULATION"

    other = tmp_path / "other.db"
    approved_review(other)
    lines, _ = read_docx(sm.write_latest_summary(tmp_path / "prod.docx", db_path=other))
    assert not any("DEV MODE" in ln for ln in lines)


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------

def test_summary_from_the_saved_review_matches_one_from_the_in_memory_review(db, tmp_path):
    review = approved_review(db)
    a = sm.write_summary(review, tmp_path / "memory.docx")
    b = latest_summary(db, tmp_path, "from_db.docx")
    assert read_docx(a) == read_docx(b)


def test_default_path_and_overwrite(db, tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "SUMMARY_DIR", tmp_path / "nested" / "summaries")
    review = approved_review(db)
    path = sm.write_latest_summary(db_path=db)
    assert path == tmp_path / "nested" / "summaries" / f"digital_payments_summary_2026-09-30_run{review.run_id}.docx"
    assert path.is_file()
    assert sm.write_latest_summary(db_path=db) == path  # replaced in place, no error


def test_document_properties_and_review_untouched(db, tmp_path):
    review = approved_review(db)
    before = rs.load_review(review.run_id, db_path=db)
    path = latest_summary(db, tmp_path)
    assert Document(str(path)).core_properties.title == "Digital Payments: weekly insight summary"
    assert rs.load_review(review.run_id, db_path=db) == before  # generating a summary changes nothing
