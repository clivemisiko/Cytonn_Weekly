"""Optional chart images: the store, its routes, the inputs summary and the Word export (temp folders, invented images)."""

import struct
import zlib
from datetime import date, timedelta

import pytest
from docx.shared import Emu, Pt
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.equities import weekly as equities
from cytonn_weekly.fixed_income import weekly as fixed_income
from cytonn_weekly.charts import store as chart_store
from cytonn_weekly.common.review import build_review, check_section
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.weekly import chart_uploads, export, inputs
from cytonn_weekly.weekly.week import Week
from cytonn_weekly.report_sections import BY_SLUG
from tests.test_weekly_export_charts import CAPTIONS, PERIOD, approved, placeholders
from tests.weekly_helpers import WEEK

JPEG = b"\xff\xd8\xff\xe0" + b"invented jpeg body"
URL = f"/api/inputs/weekly/{WEEK.ending.isoformat()}/charts"


def png(width: int = 2, height: int = 1) -> bytes:
    """A real, tiny PNG (no dpi chunk, so python-docx reads it at 72 dpi)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (chart_uploads.MAGIC["png"] + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=tmp_path / "weekly"))


def folder(tmp_path):
    return inputs.week_dir(WEEK, tmp_path / "weekly") / "charts"


def exported(review, charts, tmp_path):
    return export.build_weekly_document([(BY_SLUG["equities"], review)], PERIOD, charts_root=charts,
                                        inputs_root=tmp_path / "weekly")


def by_key(body):
    return {c["key"]: c for c in body["charts"]}


def revised(review, tmp_path, charts=None, *, approve=True):
    """The review saved again with its chart slots read from the stored uploads (as the upload route does), approved."""
    new = chart_uploads.refresh(review, tmp_path / "weekly", charts, "invented reason")
    if approve:
        for item in new.review_items:
            if item.resolution is None:
                item.resolve("accept")
        new.decide("approved")
    review_store.save_review(new, section=new.section["section"], db_path=tmp_path / "app.db")
    chart_store.persist(new, charts)
    return new


def slot_item(review, ref):
    [item] = [i for i in review.review_items if i.ref == ref]
    return item


# ---------------------------------------------------------------------------
# Accepted and refused
# ---------------------------------------------------------------------------

def test_a_png_and_a_jpeg_are_accepted_and_the_summary_says_so(client):
    data = png()
    r = client.put(f"{URL}/tbill_yields", content=data)
    assert r.status_code == 200
    assert (by_key(r.json())["tbill_yields"]["type"], by_key(r.json())["tbill_yields"]["size"]) == ("png", len(data))
    r = client.put(f"{URL}/nasi_pe", content=JPEG)
    assert r.status_code == 200 and by_key(r.json())["nasi_pe"]["type"] == "jpeg"
    image = client.get(f"{URL}/nasi_pe/image")
    assert image.status_code == 200 and image.content == JPEG and image.headers["content-type"] == "image/jpeg"


def test_wrong_magic_bytes_under_a_png_name_are_refused(client, tmp_path):
    r = client.put(f"{URL}/tbill_yields?filename=chart.png", content=b"%PDF-1.7 not an image",
                   headers={"Content-Type": "image/png"})
    assert r.status_code == 422 and r.json()["problems"][0]["code"] == "upload_refused"
    assert r.json()["detail"] == "This is not a PNG or JPEG image. Save the chart as a PNG or JPEG and upload that."
    assert not (folder(tmp_path) / "tbill_yields.png").exists()


def test_an_empty_file_is_refused(client):
    r = client.put(f"{URL}/tbill_yields", content=b"")
    assert r.status_code == 422 and r.json()["detail"] == "The file is empty. Choose the chart's image file again."


def test_a_file_over_5_mb_is_refused(client):
    r = client.put(f"{URL}/tbill_yields", content=chart_uploads.MAGIC["png"] + b"\x00" * chart_uploads.MAX_BYTES)
    assert r.status_code == 413 and r.json()["problems"][0]["code"] == "upload_too_big"
    assert r.json()["detail"] == "The image is over the 5 MB limit. Save a smaller copy and upload that."


def test_an_unknown_slot_and_an_invalid_week_are_refused(client):
    assert client.put(f"{URL}/real_estate_chart", content=png()).status_code == 404
    assert client.get(f"{URL}/real_estate_chart/image").status_code == 404
    thursday = client.put("/api/inputs/weekly/2026-10-01/charts/tbill_yields", content=png())
    assert thursday.status_code == 422 and thursday.json()["problems"][0]["code"] == "week_not_valid"
    assert client.put("/api/inputs/weekly/not-a-date/charts/tbill_yields", content=png()).status_code == 422


# ---------------------------------------------------------------------------
# Replace, delete, the name on disk, the lead-in
# ---------------------------------------------------------------------------

def test_a_new_upload_replaces_the_old_one(client, tmp_path):
    client.put(f"{URL}/nasi_pe", content=png())
    r = client.put(f"{URL}/nasi_pe", content=JPEG)
    assert by_key(r.json())["nasi_pe"]["type"] == "jpeg"
    assert sorted(p.name for p in folder(tmp_path).iterdir()) == ["charts.json", "nasi_pe.jpg"]
    assert client.get(f"{URL}/nasi_pe/image").content == JPEG


def test_delete_removes_the_image_and_keeps_the_lead_in(client, tmp_path):
    client.put(f"{URL}/interbank", content=png())
    client.put(f"{URL}/interbank/lead-in", json={"lead_in": "Invented lead-in."})
    r = client.delete(f"{URL}/interbank")
    assert r.status_code == 200
    assert (by_key(r.json())["interbank"]["has_image"], by_key(r.json())["interbank"]["lead_in"]) == (False, "Invented lead-in.")
    assert not (folder(tmp_path) / "interbank.png").exists()
    assert client.get(f"{URL}/interbank/image").status_code == 404
    assert client.delete(f"{URL}/interbank").status_code == 404


def test_the_file_on_disk_is_named_by_the_server_not_the_client(client, tmp_path):
    client.put(f"{URL}/money_market?filename=..%2F..%2Fevil%20name.png", content=png())
    assert sorted(p.name for p in folder(tmp_path).iterdir()) == ["charts.json", "money_market.png"]
    assert not any("evil" in p.name for p in (tmp_path / "weekly").rglob("*"))


def test_the_lead_in_is_saved_cleared_and_limited(client):
    r = client.put(f"{URL}/import_cover/lead-in", json={"lead_in": "  The chart below shows   import cover. "})
    assert by_key(r.json())["import_cover"]["lead_in"] == "The chart below shows import cover."
    assert by_key(client.put(f"{URL}/import_cover/lead-in", json={"lead_in": ""}).json())["import_cover"]["lead_in"] == ""
    long = client.put(f"{URL}/import_cover/lead-in", json={"lead_in": "x" * (chart_uploads.MAX_LEAD_IN + 1)})
    assert long.status_code == 422 and long.json()["problems"][0]["code"] == "note_refused"


def test_the_source_line_is_stored_returned_trimmed_and_kept_as_typed(client):
    r = client.put(f"{URL}/import_cover/source", json={"source": "  <b>Invented</b>  Bureau  "})
    assert r.status_code == 200
    assert by_key(r.json())["import_cover"]["source"] == "<b>Invented</b>  Bureau"
    assert by_key(client.get(f"/api/inputs/weekly/{WEEK.ending.isoformat()}").json())["import_cover"]["source"] == "<b>Invented</b>  Bureau"
    exact = "x" * chart_uploads.MAX_SOURCE
    assert by_key(client.put(f"{URL}/import_cover/source", json={"source": exact}).json())["import_cover"]["source"] == exact


def test_the_source_line_and_the_lead_in_do_not_touch_each_other(client):
    client.put(f"{URL}/import_cover/lead-in", json={"lead_in": "Invented lead-in."})
    both = by_key(client.put(f"{URL}/import_cover/source", json={"source": "Invented Bureau"}).json())["import_cover"]
    assert (both["lead_in"], both["source"]) == ("Invented lead-in.", "Invented Bureau")
    client.put(f"{URL}/import_cover/lead-in", json={"lead_in": ""})
    assert by_key(client.get(f"/api/inputs/weekly/{WEEK.ending.isoformat()}").json())["import_cover"]["source"] == "Invented Bureau"


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_an_empty_source_line_clears_it(client, empty):
    client.put(f"{URL}/import_cover/source", json={"source": "Invented Bureau"})
    r = client.put(f"{URL}/import_cover/source", json={"source": empty})
    assert by_key(r.json())["import_cover"]["source"] == ""


@pytest.mark.parametrize("value, message", [
    ("x" * (chart_uploads.MAX_SOURCE + 1), "Shorten it by 1."),
    ("Invented\nBureau", "one line"), ("Invented\r\nBureau", "one line"), ("Invented Bureau\n", "one line"),
    ("Invented\u2028Bureau", "one line"),
])
def test_a_source_line_too_long_or_on_two_lines_is_refused_and_nothing_is_stored(client, tmp_path, value, message):
    client.put(f"{URL}/import_cover/source", json={"source": "Invented Bureau"})
    r = client.put(f"{URL}/import_cover/source", json={"source": value})
    assert r.status_code == 422 and message in str(r.json())
    assert chart_uploads.source(WEEK, "import_cover", tmp_path / "weekly") == "Invented Bureau"


def test_the_source_line_refuses_an_unknown_slot(client):
    assert client.put(f"{URL}/not_a_slot/source", json={"source": "Invented Bureau"}).status_code == 404


def test_an_older_charts_json_without_the_source_still_loads(tmp_path):
    root = tmp_path / "weekly"
    folder = inputs.week_dir(WEEK, root) / "charts"
    folder.mkdir(parents=True)
    (folder / "charts.json").write_text('{"interbank": {"lead_in": "Invented lead-in."}}', encoding="utf-8")
    slot = {c["key"]: c for c in chart_uploads.status(WEEK, root)}["interbank"]
    assert (slot["lead_in"], slot["source"]) == ("Invented lead-in.", "")
    assert chart_uploads.source(WEEK, "interbank", root) == ""


def test_deleting_the_image_removes_the_source_and_replacing_it_keeps_the_source(client):
    assert client.put(f"{URL}/interbank", content=png()).status_code == 200
    client.put(f"{URL}/interbank/source", json={"source": "Invented Bureau"})
    r = client.put(f"{URL}/interbank", content=png(3, 1))
    assert by_key(r.json())["interbank"]["source"] == "Invented Bureau"
    assert by_key(client.delete(f"{URL}/interbank").json())["interbank"]["source"] == ""


def test_the_summary_lists_every_slot_with_its_state(client):
    client.put(f"{URL}/nasi_yield", content=png())
    charts = client.get(f"/api/inputs/weekly/{WEEK.ending.isoformat()}").json()["charts"]
    assert [c["key"] for c in charts] == list(chart_uploads.KEYS)
    assert [c["section"] for c in charts].count("fixed_income") == 6 and [c["section"] for c in charts].count("equities") == 2
    assert [c["template_lead_in"] for c in charts] == [chart_uploads.template(k, WEEK) for k in chart_uploads.KEYS]
    assert by_key({"charts": charts})["nasi_yield"]["file_name"] == "nasi_yield.png"   # uploaded with no name given
    assert [c["key"] for c in charts if c["has_image"]] == ["nasi_yield"]
    empty = by_key({"charts": charts})["tbill_91_growth"]
    assert (empty["type"], empty["size"], empty["lead_in"]) == (None, None, "")


def test_every_slot_has_a_template_sentence_dated_from_the_week():
    t = {k: chart_uploads.template(k, WEEK) for k in chart_uploads.KEYS}   # the week ending Friday 2 October 2026
    assert t["tbill_91_growth"] == ("The chart below shows the yield growth rate for the 91-day paper over the last year, "
                                    "from October 2025 to October 2026:")
    assert t["tbill_yields"].endswith("over the last two years, from October 2024 to October 2026:")
    assert t["tbill_subscription"].endswith("obtained in 2023, 2024, 2025 and 2026 Year-to-date (YTD):")
    assert t["money_market"] == "The chart below shows the money market yields as at 2nd October 2026:"
    assert t["interbank"].endswith("up to October 2026:")
    assert t["import_cover"].endswith("from October 2024 to October 2026:")
    assert t["nasi_pe"] == t["nasi_yield"] == "The charts below indicate the historical P/E and dividend yields of the market"
    later = chart_uploads.template("money_market", Week(WEEK.ending + timedelta(days=7)))
    assert later == "The chart below shows the money market yields as at 9th October 2026:"   # dates follow the week
    assert not any("uncaptioned" in x or chr(0x2014) in x for x in t.values())
    assert not hasattr(chart_uploads, "DEFAULT_LEAD_INS")


def test_the_window_month_is_the_month_of_the_sunday_after_the_report_friday():
    month = lambda friday: f"{chart_uploads.window_month(Week(friday)):%B %Y}"
    assert month(date(2026, 10, 30)) == "November 2026"     # Sunday 1 November
    assert month(date(2026, 10, 23)) == "October 2026"      # Sunday 25 October
    assert month(date(2027, 12, 31)) == "January 2028"      # Sunday 2 January: the window crosses the year
    t = {k: chart_uploads.template(k, Week(date(2026, 10, 30))) for k in chart_uploads.KEYS}
    assert t["tbill_91_growth"].endswith("from November 2025 to November 2026:")
    assert t["tbill_yields"].endswith("from November 2024 to November 2026:")
    assert t["import_cover"].endswith("from November 2024 to November 2026:")
    assert t["interbank"].endswith("up to November 2026:")
    assert t["money_market"].endswith("as at 30th October 2026:")                 # a day, not a window
    assert t["tbill_subscription"].endswith("2023, 2024, 2025 and 2026 Year-to-date (YTD):")


def test_the_export_status_counts_the_charts_with_no_image(client, tmp_path):
    assert client.get("/api/export/weekly", params={"period": PERIOD}).json()["charts_missing"] == 8
    client.put(f"{URL}/nasi_pe", content=png())
    assert client.get("/api/export/weekly", params={"period": PERIOD}).json()["charts_missing"] == 7
    # No week named and no reviews: the latest Friday's uploads count, so 8 only while that Friday's folder is empty.
    root = tmp_path / "weekly"
    assert export.export_status(tmp_path / "app.db", "", today=WEEK.ending + timedelta(days=8), inputs_root=root)["charts_missing"] == 8
    assert export.export_status(tmp_path / "app.db", "", today=WEEK.ending + timedelta(days=1), inputs_root=root)["charts_missing"] == 7


def test_the_export_status_does_not_count_the_charts_the_tool_drew(tmp_path):
    approved(tmp_path)   # an Equities review with both NASI charts drawn, saved for the week
    root = tmp_path / "weekly"
    assert export.export_status(tmp_path / "app.db", PERIOD, inputs_root=root)["charts_missing"] == 6
    approved(tmp_path / "team", team=("nasi_pe",))   # set aside for the team's own chart: a placeholder again
    assert export.export_status(tmp_path / "team" / "app.db", PERIOD, inputs_root=root)["charts_missing"] == 7


# ---------------------------------------------------------------------------
# The Word export
# ---------------------------------------------------------------------------

def test_a_filled_slot_prints_its_lead_in_and_image_and_an_empty_one_keeps_the_placeholder(tmp_path):
    review, charts = approved(tmp_path, workbook=False)
    chart_uploads.store(WEEK, "nasi_pe", png(), tmp_path / "weekly")
    chart_uploads.set_lead_in(WEEK, "nasi_pe", "Invented lead-in for the P/E chart.", tmp_path / "weekly")
    doc = exported(revised(review, tmp_path, charts), charts, tmp_path)
    texts = [p.text for p in doc.paragraphs]
    assert len(doc.inline_shapes) == 1
    assert doc.inline_shapes[0]._inline.docPr.get("descr") == "Invented lead-in for the P/E chart."
    at = next(i for i, p in enumerate(doc.paragraphs) if p._p.xpath(".//w:drawing"))
    assert texts[at - 1] == "Invented lead-in for the P/E chart."
    assert texts[at + 1] == "Uploaded by analyst, not verified."
    assert placeholders(doc) == [f"[Chart to add: {CAPTIONS[1]}]"]


def test_a_source_line_prints_under_the_uploaded_image_in_the_source_style(tmp_path):
    review, charts = approved(tmp_path, workbook=False)
    chart_uploads.store(WEEK, "nasi_pe", png(), tmp_path / "weekly")
    chart_uploads.set_source(WEEK, "nasi_pe", "<i>Invented Bureau</i>", tmp_path / "weekly")
    doc = exported(revised(review, tmp_path, charts), charts, tmp_path)
    at = next(i for i, p in enumerate(doc.paragraphs) if p._p.xpath(".//w:drawing"))
    line = doc.paragraphs[at + 1]
    assert line.text == "Source: <i>Invented Bureau</i>"
    assert (line.runs[0].font.size, line.runs[0].italic) == (Pt(9), False)
    assert doc.paragraphs[at].paragraph_format.keep_with_next is True
    # Then the line saying it is not verified, in the style of the drawn chart's "From the analyst workbook, not verified."
    marked = doc.paragraphs[at + 2]
    assert marked.text == export.UPLOAD_NOT_VERIFIED == "Uploaded by analyst, not verified."
    drawn, folder = approved(tmp_path / "drawn")
    from tests.test_weekly_export_charts import document
    drawn_doc = document(drawn, folder)
    [ref] = [p for p in drawn_doc.paragraphs if p.text == export.CHART_NOT_VERIFIED][:1]
    look = lambda para: (para.runs[0].font.size, para.runs[0].italic, para.runs[0].font.color.rgb, para.style.name)
    assert look(marked) == look(ref)


def test_an_empty_source_line_prints_nothing_under_the_uploaded_image(tmp_path):
    review, charts = approved(tmp_path, workbook=False)
    chart_uploads.store(WEEK, "nasi_pe", png(), tmp_path / "weekly")
    doc = exported(revised(review, tmp_path, charts), charts, tmp_path)
    at = next(i for i, p in enumerate(doc.paragraphs) if p._p.xpath(".//w:drawing"))
    assert doc.paragraphs[at + 1].text == export.UPLOAD_NOT_VERIFIED


def test_a_source_line_with_no_image_prints_nothing(tmp_path):
    review, charts = approved(tmp_path, workbook=False)
    chart_uploads.set_source(WEEK, "nasi_pe", "Invented Bureau", tmp_path / "weekly")
    doc = exported(review, charts, tmp_path)
    assert not [p.text for p in doc.paragraphs if "Invented Bureau" in p.text]
    assert placeholders(doc)[0] == f"[Chart to add: {CAPTIONS[0]}]"


def test_an_upload_wins_over_a_drawn_chart_and_a_blank_lead_in_prints_the_template_once(tmp_path):
    review, charts = approved(tmp_path)
    data = png(3, 1)
    chart_uploads.store(WEEK, "nasi_yield", data, tmp_path / "weekly", "yield.png")
    new = revised(review, tmp_path, charts)
    doc = exported(new, charts, tmp_path)
    texts = [p.text for p in doc.paragraphs]
    shapes = list(doc.inline_shapes)
    assert len(shapes) == 2                       # the drawn P/E chart and the uploaded dividend yield image
    uploaded = shapes[1]
    assert doc.part.related_parts[uploaded._inline.graphic.graphicData.pic.blipFill.blip.embed].blob == data
    at = [i for i, p in enumerate(doc.paragraphs) if p._p.xpath(".//w:drawing")]
    # The pair shares the published sentence: printed above the drawn P/E chart, not again above the upload.
    assert texts[at[0] - 1] == chart_uploads.NASI_PAIR and texts.count(chart_uploads.NASI_PAIR) == 1
    assert texts[at[1] - 1] == "From the analyst workbook, not verified."
    assert texts[at[1] + 1] == "Uploaded by analyst, not verified."
    assert CAPTIONS[1] not in texts and uploaded._inline.docPr.get("descr") == chart_uploads.NASI_PAIR
    item = slot_item(new, "NASI dividend yield chart: uploaded image")
    assert "It replaces the chart the tool drew from the equities workbook." in item.detail[0].message


def test_a_wide_image_is_scaled_to_the_text_width_keeping_its_proportions(tmp_path):
    review, charts = approved(tmp_path, workbook=False)
    chart_uploads.store(WEEK, "nasi_pe", png(2000, 500), tmp_path / "weekly")   # 27.8 in wide at 72 dpi
    doc = exported(revised(review, tmp_path, charts), charts, tmp_path)
    page = doc.sections[-1]
    text_width = page.page_width - page.left_margin - page.right_margin
    [shape] = doc.inline_shapes
    assert shape.width == text_width and abs(shape.height - Emu(text_width // 4)) <= 1


def test_a_corrupt_stored_image_falls_back_to_the_placeholder_and_a_warning_line(tmp_path):
    review, charts = approved(tmp_path, workbook=False)
    chart_uploads.store(WEEK, "nasi_pe", chart_uploads.MAGIC["png"] + b"not a picture", tmp_path / "weekly")
    doc = exported(revised(review, tmp_path, charts), charts, tmp_path)
    assert len(doc.inline_shapes) == 0
    assert placeholders(doc) == [f"[Chart to add: {c}]" for c in CAPTIONS]
    [line] = [p for p in doc.paragraphs if p.text == export.UPLOAD_UNREADABLE]
    assert line.runs[0].italic and line.runs[0].font.color.rgb == export._RED


# ---------------------------------------------------------------------------
# The week the export reads uploads for
# ---------------------------------------------------------------------------

OTHER = Week(WEEK.ending - timedelta(days=7))
FI_SLOTS = [s["key"] for s in chart_uploads.slots() if s["section"] == "fixed_income"]


def fixed_income_review(week_ending: str, period: str = "", root=None):
    """An approved Fixed Income-like review: a tbills block, the section's own chart placement and, with ``root``, its chart
    slots read from the uploads stored there, as the builder stores them."""
    blocks = [{"kind": "supplied", "id": "tbills", "title": "T-Bills", "body_md": "Invented T-bill text.",
               "supplied_by": "coordinator"}]
    if root is not None:
        blocks += chart_uploads.slot_blocks("fixed_income", Week(date.fromisoformat(week_ending)), root, blocks)
    content = {"section": "fixed_income", "title": "Fixed Income", "week_ending": week_ending, "blocks": blocks,
               "chart_after": fixed_income.CHART_AFTER, "chart_notes": list(fixed_income.CHARTS)}
    review = build_review(content, check_section(content))
    for item in review.review_items:
        if item.resolution is None:
            item.resolve("accept")
    review.decide("approved")
    review.report_type, review.period = "weekly", period
    return review


def upload_fixed_income(week, root, keys=None):
    for key in keys or [k for k in FI_SLOTS if k != "interbank"]:
        chart_uploads.store(week, key, png(), root)


def test_an_unlabelled_period_exports_the_uploads_of_the_reviews_week(tmp_path):
    root = tmp_path / "weekly"
    upload_fixed_income(WEEK, root)
    doc = export.build_weekly_document([(BY_SLUG["fixed_income"], fixed_income_review(WEEK.ending.isoformat(), root=root))],
                                       "", inputs_root=root)
    texts = [p.text for p in doc.paragraphs]
    assert len(doc.inline_shapes) == 5
    uploaded = [c for k, c in zip(chart_uploads.KEYS, fixed_income.CHARTS) if k != "interbank"]
    assert not any(t == f"[Chart to add: {c}]" for t in texts for c in uploaded)
    # The three T-bill charts follow the tbills block, each under its template sentence and over the "not verified" line.
    at = texts.index("Invented T-bill text.")
    assert texts[at + 1:at + 10:3] == [chart_uploads.template(k, WEEK) for k in FI_SLOTS[:3]]
    assert all(doc.paragraphs[at + i]._p.xpath(".//w:drawing") for i in (2, 5, 8))
    assert texts[at + 3:at + 10:3] == ["Uploaded by analyst, not verified."] * 3


def test_a_fixed_income_slot_with_no_image_keeps_its_placeholder(tmp_path):
    root = tmp_path / "weekly"
    upload_fixed_income(WEEK, root)
    review = fixed_income_review(WEEK.ending.isoformat(), root=root)
    doc = export.build_weekly_document([(BY_SLUG["fixed_income"], review)], "", inputs_root=root)
    assert placeholders(doc) == [f"[Chart to add: {fixed_income.CHARTS[4]}]"]   # the interbank slot
    [run] = [p for p in doc.paragraphs if p.text.startswith("[Chart to add: ")][0].runs
    assert run.italic and run.font.color.rgb == export._RED      # red, like "[Chart not drawn: ...]"
    # The review asked about it: one "no chart" item, resolved by accepting it.
    item = slot_item(review, "Interbank rates chart: no chart")
    assert item.resolution == "accept" and item.detail[0].message.startswith("No chart: the Word file will show a placeholder.")


def test_the_export_status_counts_uploads_for_an_unlabelled_period(tmp_path):
    root = tmp_path / "weekly"
    chart_uploads.store(WEEK, "tbill_yields", png(), root)
    status = export.export_status(tmp_path / "app.db", "", today=WEEK.ending, inputs_root=root)
    assert status["charts_missing"] == 7


def test_the_export_prints_the_uploads_the_review_recorded_whatever_the_period_names(tmp_path):
    root = tmp_path / "weekly"
    upload_fixed_income(OTHER, root)
    review = fixed_income_review(WEEK.ending.isoformat(), PERIOD, root=root)   # recorded for WEEK, which has no uploads
    named = f"Week ending {OTHER.ending.isoformat()}"
    assert len(export.build_weekly_document([(BY_SLUG["fixed_income"], review)], named, inputs_root=root).inline_shapes) == 0


def test_an_equities_only_export_with_an_unlabelled_period_uses_the_equities_reviews_week(tmp_path):
    review, charts = approved(tmp_path, workbook=False)   # its section week_ending is WEEK
    review.period = ""
    root = tmp_path / "weekly"
    chart_uploads.store(WEEK, "nasi_pe", png(), root)
    review = revised(review, tmp_path, charts)
    review.period = ""
    reviews = [(BY_SLUG["equities"], review)]
    assert export.export_week("", reviews, today=OTHER.ending) == WEEK
    doc = export.build_weekly_document(reviews, "", charts_root=charts, inputs_root=root)
    assert len(doc.inline_shapes) == 1
    assert placeholders(doc) == [f"[Chart to add: {CAPTIONS[1]}]"]


def test_fixed_incomes_week_wins_and_a_bad_stored_week_is_skipped(tmp_path):
    review, _ = approved(tmp_path, workbook=False)   # Equities, week_ending WEEK
    fi = fixed_income_review(OTHER.ending.isoformat())
    assert export.export_week("", [(BY_SLUG["fixed_income"], fi), (BY_SLUG["equities"], review)]) == OTHER
    broken = fixed_income_review("not a date")
    assert export.export_week("", [(BY_SLUG["fixed_income"], broken), (BY_SLUG["equities"], review)]) == WEEK
    assert export.export_week("", [(BY_SLUG["fixed_income"], broken)], today=WEEK.ending + timedelta(days=3)) == WEEK


# ---------------------------------------------------------------------------
# The charts in the review: an upload or a missing chart is an item to resolve, and a change after approval sends the
# section back for approval
# ---------------------------------------------------------------------------

def test_an_upload_is_a_flagged_item_naming_the_file_and_the_template_sentence(tmp_path):
    review, charts = approved(tmp_path, workbook=False)
    chart_uploads.store(WEEK, "nasi_pe", png(), tmp_path / "weekly", "C:\\fakepath\\nasi pe chart.png")
    new = revised(review, tmp_path, charts, approve=False)
    item = slot_item(new, "NASI P/E chart: uploaded image")
    message = item.detail[0].message
    assert item.status == "flagged" and item.kind == "chart" and item.detail[0].kind == "uploaded_chart"
    assert message.startswith("NASI P/E: chart image uploaded by the analyst (nasi pe chart.png, SHA-256 ")
    assert "not verified by the tool" in message and "replaces" not in message
    assert message.endswith(f'Sentence printed above it (template sentence used): "{chart_uploads.NASI_PAIR}"')
    assert item.context["text"] == chart_uploads.NASI_PAIR
    assert item.context["chart_upload"] == {"key": "nasi_pe", "week_ending": WEEK.ending.isoformat(),
                                            "file_name": "nasi pe chart.png"}
    assert not new.is_approvable
    for i in new.review_items:
        i.resolve("accept")
    assert new.is_approvable


def test_a_typed_lead_in_replaces_the_template_and_the_item_says_so(tmp_path):
    review, charts = approved(tmp_path, workbook=False)
    root = tmp_path / "weekly"
    chart_uploads.store(WEEK, "nasi_pe", png(), root)
    chart_uploads.set_lead_in(WEEK, "nasi_pe", "Invented typed sentence:", root)
    chart_uploads.set_source(WEEK, "nasi_pe", "Invented Bureau", root)
    message = slot_item(revised(review, tmp_path, charts, approve=False), "NASI P/E chart: uploaded image").detail[0].message
    assert 'Sentence printed above it (the sentence the analyst typed): "Invented typed sentence:"' in message
    assert message.endswith('Source line under it: "Invented Bureau".')


def test_a_slot_with_no_chart_is_an_item_accepted_to_export_a_red_placeholder(tmp_path):
    review, charts = approved(tmp_path, workbook=False)   # no workbook, so no drawn NASI chart
    new = revised(review, tmp_path, charts, approve=False)
    items = [i for i in new.review_items if i.ref.endswith("chart: no chart")]
    assert [i.ref for i in items] == ["NASI P/E chart: no chart", "NASI dividend yield chart: no chart"]
    assert items[0].status == "flagged" and items[0].detail[0].kind == "no_chart"
    assert items[0].detail[0].message == ("No chart: the Word file will show a placeholder. NASI P/E: no image was uploaded "
                                          "and the tool drew none. Accept to export the section without it.")
    for i in new.review_items:
        if i not in items:
            i.resolve("accept")
    assert not new.is_approvable                          # held up only until the "no chart" items are resolved
    for i in items:
        i.resolve("accept")
    assert new.is_approvable
    new.decide("approved")
    doc = exported(new, charts, tmp_path)
    marks = [p for p in doc.paragraphs if p.text.startswith("[Chart to add: ")]
    assert [p.text for p in marks] == [f"[Chart to add: {c}]" for c in CAPTIONS]
    assert all(p.runs[0].font.color.rgb == export._RED for p in marks)


def test_a_drawn_chart_has_no_slot_item(tmp_path):
    review, charts = approved(tmp_path)
    new = revised(review, tmp_path, charts, approve=False)
    assert not [i for i in new.review_items if i.ref.endswith(("chart: uploaded image", "chart: no chart"))]
    assert {b["state"] for b in new.section["blocks"] if b["kind"] == "chart_slot"} == {"drawn"}


def test_an_upload_after_approval_sends_the_section_back_for_approval_and_records_why(tmp_path):
    review, _ = approved(tmp_path, workbook=False)   # saved for "Week ending 2026-10-02", approved
    client = TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=tmp_path / "weekly",
                                   charts_root=tmp_path / "charts"))
    r = client.put(f"{URL}/nasi_pe?filename=pe.png", content=png())
    assert r.status_code == 200
    [revision] = r.json()["reviews_revised"]
    assert revision["section"] == "equities" and revision["earlier_run_id"] == review.run_id and revision["was_approved"]
    assert revision["reason"] == "chart image uploaded for NASI P/E (pe.png)"
    latest = review_store.load_latest_review("equities", report_type="weekly", period=PERIOD, db_path=tmp_path / "app.db")
    assert latest.run_id == revision["run_id"] and latest.decision is None
    assert latest.section["revisions"][-1]["reason"] == revision["reason"]
    assert latest.section["revisions"][-1]["from_run_id"] == review.run_id
    earlier = review_store.load_review(review.run_id, db_path=tmp_path / "app.db")
    assert earlier.decision == "approved"                     # the approved run is never touched
    # The review predates chart slots, so both slot items are new and wait for the reviewer.
    assert slot_item(latest, "NASI P/E chart: uploaded image").resolution is None
    assert slot_item(latest, "NASI dividend yield chart: no chart").resolution is None
    # Approve it, then replace the image: back to needing approval again.
    for i in latest.review_items:
        if i.resolution is None:
            i.resolve("accept")
    latest.decide("approved")
    review_store.save_review(latest, section="equities", db_path=tmp_path / "app.db")
    again = client.put(f"{URL}/nasi_pe?filename=pe2.png", content=png(3, 1)).json()["reviews_revised"]
    assert [(x["earlier_run_id"], x["was_approved"]) for x in again] == [(latest.run_id, True)]
    newest = review_store.load_latest_review("equities", report_type="weekly", period=PERIOD, db_path=tmp_path / "app.db")
    assert newest.decision is None and len(newest.section["revisions"]) == 2
    # The replaced image is a new item to resolve; the slot that did not change keeps its mark.
    assert slot_item(newest, "NASI P/E chart: uploaded image").resolution is None
    assert slot_item(newest, "NASI dividend yield chart: no chart").resolution == "accept"
    # A lead-in edit and a deletion are changes too; a lead-in edit on an empty slot changes nothing printed.
    reason = client.put(f"{URL}/nasi_pe/lead-in", json={"lead_in": "Invented sentence:"}).json()["reviews_revised"][0]["reason"]
    assert reason == "sentence above the NASI P/E chart changed"
    assert client.delete(f"{URL}/nasi_pe").json()["reviews_revised"][0]["reason"] == "chart image removed for NASI P/E"
    assert client.put(f"{URL}/tbill_yields/lead-in", json={"lead_in": "Invented:"}).json()["reviews_revised"] == []


def test_the_export_refuses_when_the_charts_differ_from_what_the_review_recorded(tmp_path):
    review, charts = approved(tmp_path, workbook=False)
    root = tmp_path / "weekly"
    reviews = [(BY_SLUG["equities"], review)]
    export.require_charts_unchanged(reviews, root)                  # nothing uploaded: nothing to refuse
    chart_uploads.store(WEEK, "nasi_pe", png(), root)                 # an image the review never saw
    with pytest.raises(export.ExportNotAllowed) as refused:
        export.require_charts_unchanged(reviews, root)
    assert str(refused.value) == ("The weekly report cannot be exported yet, because chart images or the sentences above them "
                                  "changed after these sections were reviewed: Equities (NASI P/E). Open each section, "
                                  "review its chart items and approve it again.")
    new = revised(review, tmp_path, charts)
    export.require_charts_unchanged([(BY_SLUG["equities"], new)], root)
    chart_uploads.set_lead_in(WEEK, "nasi_pe", "Invented sentence changed behind the review's back:", root)
    with pytest.raises(export.ExportNotAllowed):
        export.require_charts_unchanged([(BY_SLUG["equities"], new)], root)
