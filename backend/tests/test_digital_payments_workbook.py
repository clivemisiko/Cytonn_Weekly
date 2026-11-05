import io
import json
import re
import zipfile
from decimal import Decimal

import pytest
from openpyxl import Workbook as XlsxWorkbook

from cytonn_weekly.common.formatting import round_half_up
from cytonn_weekly.digital_payments import workbook as dpw
from cytonn_weekly.digital_payments.coordinator_review import ACCEPT, FIX_NEEDED, WORKBOOK_QUARTER
from cytonn_weekly.digital_payments.review_run import build_digital_payments_review, workbook_pe
from datetime import date

from cytonn_weekly.weekly import inputs
from cytonn_weekly.weekly.week import Week
from review_helpers import TODAY, FakeProvider, src_row
from weekly_helpers import FIXTURES, sample

# Same layout as the team's file, invented figures. Every company's quarterly earnings are its position (1..10) in
# every quarter and its FY'27 estimate is 10x that, at a price of 100 and 1bn shares, so by hand:
# TTM P/E = 100 / (4 x n) and forward P/E = 100 / (10 x n). Global Payments' quarters are negative.
NAMES = ["American Express", "Visa", "Mastercard", "Circle", "Block", "Paypal Holdings", "Global Payments Inc",
         "Coinbase Global", "Wise PLC", "JPMorgan Chase & Co."]
GPN, COINBASE = 6, 7   # indexes into NAMES
TTM_FORMULA = "=(E{r}/((Earnings!H{r}+Earnings!G{r}+Earnings!E{r}+Earnings!D{r})/'Stock Performance'!K{r}))/1000000000"


def _earn(i: int) -> float:
    return -(i + 1) if i == GPN else i + 1


def _build(swap: bool = False, cached: dict | None = None, rename: dict | None = None) -> bytes:
    """The workbook as bytes. ``swap`` puts Coinbase and Global Payments in opposite order on Earnings only,
    as the team's file had them. ``cached`` maps a Stock Performance cell to the value Excel last saved for it."""
    wb = XlsxWorkbook()
    stock, earn = wb.active, wb.create_sheet("Earnings")
    stock.title = "Stock Performance"
    stock.append(["Cytonn Report: Digital Payments"])
    stock.append(["Company", "Year Open 2026", "Price 30/09/2026", "Price 23/10/2026", "Price 30/10/2026", "w/w change", "m/m change",
                  "YTD change", "TTM P/E", "Forward P/E", "Outstanding shares Figures"])
    for i, name in enumerate(NAMES):
        r = i + 3
        stock.append([name, 50 + i, 90, 95, 100, None, None, None, TTM_FORMULA.format(r=r), f"=E{r}/Earnings!B{r + 14}", 1_000_000_000])
    stock.append(["Average", None, None, None, None, None, None, None, "=AVERAGE(I3,I4,I5,I7,I8,I9,I6)", "=AVERAGE(J3,J4,J5,J7,J8,J9,J6)"])
    earn.append(["EARNINGS"])
    earn.append(["Company ", "Q1'25", "Q2'25", "Q3'25", "Q4'25", "FY'25", "Q1'26", "Q2'26", "Q3'26", "Q4'26", "FY'26"])
    order = list(range(10))
    if swap:
        order[GPN], order[COINBASE] = order[COINBASE], order[GPN]
    for i in order:
        n = _earn(i)
        earn.append([NAMES[i], n, n, n, n, 4 * n, n, n])
    earn.append([])
    earn.append([])
    earn.append(["Average Analyst Consesus Estimates"])
    earn.append(["Company ", "Estimate FY'27"])
    for i in order:
        earn.append([NAMES[i], 10 * (i + 1)])
    for sheet, old, new in ((earn, k, v) for k, v in (rename or {}).items()):
        for row in sheet.iter_rows(min_col=1, max_col=1):
            if row[0].value == old:
                row[0].value = new
                break
    out = io.BytesIO()
    wb.save(out)
    return _with_cached(out.getvalue(), cached or {})


def _with_cached(data: bytes, cached: dict) -> bytes:
    """openpyxl saves a formula with no value; put in the value Excel would have saved."""
    src, out = zipfile.ZipFile(io.BytesIO(data)), io.BytesIO()
    with zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            body = src.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                text = body.decode()
                for cell, value in cached.items():
                    text, n = re.subn(rf'(<c r="{cell}"[^>]*><f>[^<]*</f>)<v></v>', rf"\g<1><v>{value!r}</v>", text)
                    assert n == 1, cell
                body = text.encode()
            dst.writestr(item, body)
    return out.getvalue()


def _ttm(i):
    return Decimal(100) / (4 * Decimal(_earn(i)))


def _fwd(i):
    return Decimal(100) / (10 * Decimal(i + 1))


def _by_name_cached():
    """What Excel saves when the rows line up (the by-name figures), keyed by cell."""
    cells = {f"I{i + 3}": float(_ttm(i)) for i in range(10)} | {f"J{i + 3}": float(_fwd(i)) for i in range(10)}
    seven = [0, 1, 2, 3, 4, 5, GPN]
    cells["I13"] = float(sum(_ttm(i) for i in seven) / 7)
    cells["J13"] = float(sum(_fwd(i) for i in seven) / 7)
    return cells


def _read(data):
    return dpw.read_dp_workbook(dpw.open_dp_workbook(data))


def test_by_name_figures_are_the_hand_worked_ones():
    book = _read(_build(cached=_by_name_cached()))
    gpn = book.row("global payments")
    assert round_half_up(gpn.ttm_pe, 1) == Decimal("-3.6") and round_half_up(gpn.forward_pe, 1) == Decimal("1.4")
    assert round_half_up(book.row("visa").ttm_pe, 1) == Decimal("12.5") and book.row("visa").forward_pe == Decimal(5)
    assert book.price_date.isoformat() == "2026-10-30"
    assert book.warnings == [] and book.blank == []


def test_a_negative_pe_stays_in_the_average_and_only_the_seven_are_averaged():
    book = _read(_build(cached=_by_name_cached()))
    seven = [0, 1, 2, 3, 4, 5, GPN]
    assert book.average_ttm == sum(_ttm(i) for i in seven) / 7   # Global Payments' negative P/E is in
    assert round_half_up(book.average_ttm, 1) == Decimal("8.2")
    without_negative = sum(_ttm(i) for i in seven if i != GPN) / 6
    eight = sum(_ttm(i) for i in seven + [COINBASE]) / 8
    assert book.average_ttm not in (without_negative, eight) and round_half_up(without_negative, 1) == Decimal("10.2")
    assert book.average_forward == sum(_fwd(i) for i in seven) / 7


def test_rows_in_the_same_order_give_the_same_results_and_no_warning():
    assert _read(_build(cached=_by_name_cached())).warnings == []


def test_swapped_rows_give_the_same_figures_by_name_and_the_workbooks_own_cells_are_called_out():
    # what Excel saved: each of the two rows read the other's earnings
    cached = _by_name_cached() | {
        "I9": 100 / 32, "J9": 100 / 80,           # Global Payments read Coinbase's earnings (8 a quarter, estimate 80)
        "I10": 100 / -28, "J10": 100 / 70,        # Coinbase read Global Payments' (-7 a quarter, estimate 70)
    }
    cached["I13"] = float((sum(_ttm(i) for i in range(6)) + Decimal(100) / 32) / 7)
    cached["J13"] = float((sum(_fwd(i) for i in range(6)) + Decimal(100) / 80) / 7)
    book = _read(_build(swap=True, cached=cached))
    assert round_half_up(book.row("global payments").ttm_pe, 2) == round_half_up(_ttm(GPN), 2)
    assert round_half_up(book.row("coinbase global").ttm_pe, 2) == round_half_up(_ttm(COINBASE), 2)
    assert book.average_ttm == sum(_ttm(i) for i in [0, 1, 2, 3, 4, 5, GPN]) / 7
    text = "\n".join(book.warnings)
    assert "Global Payments Inc: the workbook's TTM P/E ('Stock Performance'!I9)" in text
    assert "Global Payments Inc: the workbook's forward P/E ('Stock Performance'!J9)" in text
    assert "Coinbase Global: the workbook's TTM P/E ('Stock Performance'!I10)" in text
    assert "so the workbook's P/E for Global Payments Inc uses another company's earnings" in text
    assert "Coinbase Global (row 9)" in text    # the row the Global Payments formula reads
    assert "Average: the workbook's TTM P/E average ('Stock Performance'!I13)" in text
    assert "The tool's figure is the one to use." in text
    assert not any(w.startswith(("American Express", "Visa", "Mastercard")) for w in book.warnings)


def test_a_company_missing_from_earnings_is_refused_by_name():
    with pytest.raises(dpw.DpWorkbookError, match="Earnings: Coinbase Global has no row under Earnings row 2"):
        _read(_build(rename={"Coinbase Global": "Coinbase"}))


def test_a_company_listed_twice_is_refused_by_name():
    with pytest.raises(dpw.DpWorkbookError, match="Earnings: Visa appears twice under Earnings row 2"):
        _read(_build(rename={"Wise PLC": "Visa"}))


def test_a_company_missing_from_the_estimates_is_refused_by_name():
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(_build()))
    book["Earnings"]["A20"] = "Circle Group Two"   # the estimates table's Circle row
    out = io.BytesIO()
    book.save(out)
    with pytest.raises(dpw.DpWorkbookError, match="Circle has no row under Earnings row 16"):
        _read(out.getvalue())


def test_a_workbook_without_the_sheets_is_refused():
    out = io.BytesIO()
    XlsxWorkbook().save(out)
    with pytest.raises(dpw.WorkbookError, match="has no sheet 'Stock Performance'"):
        dpw.open_dp_workbook(out.getvalue())


def test_the_average_needs_all_seven_companies():
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(_build()))
    book["Stock Performance"]["A6"] = "Circle Ltd Placeholder"
    book["Earnings"]["A6"] = "Circle Ltd Placeholder"
    book["Earnings"]["A20"] = "Circle Ltd Placeholder"
    out = io.BytesIO()
    book.save(out)
    with pytest.raises(dpw.DpWorkbookError, match="the Average covers .* circle has no row"):
        _read(out.getvalue())


# ---- the weekly inputs slot ------------------------------------------------------------------------------------------

def test_the_upload_slot_reads_the_date_and_hands_the_workbook_to_the_review(tmp_path):
    week = Week(date(2026, 10, 30))
    entry = inputs.store(week, "dp_workbook", _build(), "dp.xlsx", tmp_path)
    assert entry["read_date"] == "2026-10-30" and entry["matches"]
    assert dpw.read_dp_workbook(inputs.WeeklyInputs(week, tmp_path).dp_book).row("visa") is not None
    assert inputs.WeeklyInputs(Week(date(2026, 10, 23)), tmp_path).dp_book is None


def test_the_upload_slot_refuses_a_workbook_with_a_company_missing_naming_it(tmp_path):
    with pytest.raises(inputs.InputError, match="Coinbase Global has no row"):
        inputs.store(Week(date(2026, 10, 30)), "dp_workbook", _build(rename={"Coinbase Global": "Coinbase"}), "dp.xlsx", tmp_path)


# ---- Year Open against the first trading day's close in the stored Yahoo fixture -------------------------------------

def _fixture_rows():
    closes = json.loads((FIXTURES / "cytonn_dp_period_tables_2026-10-06.json").read_text(encoding="utf-8"))["closes"]
    names = {"AXP": "American Express", "V": "Visa", "MA": "Mastercard", "CRCL": "Circle Internet Group", "XYZ": "Block Inc.",
             "PYPL": "PayPal Holdings", "GPN": "Global Payments"}
    rows = []
    for ticker, name in names.items():
        first = min(closes[ticker])
        rows.append({"company": name, "ticker": ticker, "error": None, "ytd_open": closes[ticker][first], "ytd_open_date": first})
    return rows


def test_year_open_that_differs_from_the_first_trading_days_close_is_flagged():
    gpn = next(r for r in _fixture_rows() if r["ticker"] == "GPN")
    assert round_half_up(gpn["ytd_open"], 2) == Decimal("75.53") and gpn["ytd_open_date"] == "2026-01-02"
    rows = [dpw.DpRow(n, dpw.company_key(n), Decimal(str(y)), f"Stock Performance!B{i}", Decimal(1), Decimal(1))
            for i, (n, y) in enumerate([("Global Payments Inc", "77.02"), ("Visa", "346.48")])]
    book = dpw.DpBook(rows, Decimal(0), Decimal(0))
    warnings = dpw.year_open_warnings(book, _fixture_rows())
    assert warnings == ["Global Payments Inc: Year Open is 77.02 in the workbook (Stock Performance!B0) but the close of the first "
                        "trading day (2026-01-02) is 75.53. The table prints 75.53."]


def test_year_open_that_could_not_be_fetched_is_said_not_skipped():
    row = dpw.DpRow("Visa", "visa", Decimal("346.48"), "Stock Performance!B4", Decimal(1), Decimal(1))
    out = dpw.year_open_warnings(dpw.DpBook([row], Decimal(0), Decimal(0)), [{"company": "Visa", "error": "boom"}])
    assert out and "could not be compared" in out[0]


# ---- the review ------------------------------------------------------------------------------------------------------

def _review(workbook, search=None):
    rows = [src_row("V", "Visa"), src_row("GPN", "Global Payments")]
    rows[1]["ytd_open"] = 75.529999
    return build_digital_payments_review(provider=FakeProvider(), today=TODAY, fetch_table=lambda today: rows, workbook=workbook,
                                         search=search or (lambda quarter, domains: []))


def test_review_shows_the_workbook_warnings_and_without_a_workbook_has_none_of_them():
    plain = _review(None).section["warnings"]
    assert not any("workbook" in w for w in plain)
    swapped = _by_name_cached() | {"I9": 100 / 32}
    warned = _review(dpw.open_dp_workbook(_build(swap=True, cached=swapped))).section["warnings"]
    assert any("Global Payments Inc: the workbook's TTM P/E" in w for w in warned)


def test_review_flags_a_year_open_that_is_not_the_fetched_close():
    warned = _review(dpw.open_dp_workbook(_build(cached=_by_name_cached()))).section["warnings"]
    assert any(w.startswith("Global Payments Inc: Year Open is 56.00 in the workbook") and "is 75.53" in w for w in warned)


# ---- the team's two real 30 October files, read only; each test names its file and skips when it is absent -----------

V3 = "Digital_Payments_workbook_30-10-2026_v3.xlsx"   # the original: Coinbase and Global Payments swapped, Year Open 77.02
V4 = "Digital_Payments_workbook_30-10-2026_v4.xlsx"   # the corrected file


def _real(name):
    return _read(sample(name))


def _same_by_name_results(book):
    gpn, coin = book.row("global payments"), book.row("coinbase global")
    assert (round_half_up(gpn.ttm_pe, 1), round_half_up(gpn.forward_pe, 1)) == (Decimal("-26.9"), Decimal("6.0"))
    assert (round_half_up(coin.ttm_pe, 1), round_half_up(coin.forward_pe, 1)) == (Decimal("-38.4"), Decimal("47.5"))
    # PayPal's TTM P/E waits on its blank Q3'26, so the TTM Average covers the other six; the forward Average still has all seven
    assert (round_half_up(book.average_ttm, 1), round_half_up(book.average_forward, 1)) == (Decimal("24.3"), Decimal("21.3"))
    assert sorted(q.ref for q in book.blank) == ["Earnings!G11", "Earnings!I11", "Earnings!I8"]


def test_real_v3_swapped_file_gives_the_swap_warning_and_the_year_open_warning():
    book = _real(V3)
    _same_by_name_results(book)
    text = " ".join(book.warnings)
    assert "Global Payments Inc: the workbook's TTM P/E ('Stock Performance'!I9)" in text
    assert "so the workbook's P/E for Global Payments Inc uses another company's earnings" in text
    assert "Coinbase Global: the workbook's forward P/E ('Stock Performance'!J10)" in text
    assert "Average: the workbook's TTM P/E average" in text
    assert "left out, because their TTM P/E is unavailable: Paypal Holdings" in text
    assert book.row("global payments").year_open == Decimal("77.02")
    year = dpw.year_open_warnings(book, _fixture_rows())
    assert len(year) == 1 and year[0].startswith("Global Payments Inc: Year Open is 77.02") and "is 75.53" in year[0]


def test_real_v4_corrected_file_gives_neither_warning():
    book = _real(V4)
    _same_by_name_results(book)
    assert book.row("global payments").year_open == Decimal("75.53")
    assert not any("another company's earnings" in w or "TTM P/E ('Stock" in w and "worked out" in w for w in book.warnings)
    assert dpw.year_open_warnings(book, _fixture_rows()) == []


# ---- a blank quarter is never zero --------------------------------------------------------------------------------------

def _blank(data, *cells):
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(data))
    for cell in cells:
        book["Earnings"][cell] = None
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _with_results(data, rows):
    """Add a Financial Results sheet laid out like the team's: (title, prior-year net income, current net income) per company."""
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(data))
    sheet = book.create_sheet("Financial Results")
    sheet.append(["Cytonn Report: Digital Payments Financial Results"])
    sheet.append(["Company", "Metric", "Prior Year (2025)", "Current (2026)", "y/y Change"])
    for title, prior, current in rows:
        sheet.append([title, "Net revenue (USD bn)", 9, 10, 0.1])
        sheet.append([None, "Net income (USD bn)", prior, current, None])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


VISA_H4 = "Earnings!H4"   # Visa's Q2'26, which its TTM P/E reads
PAGE = ("Visa Inc. Announces Fiscal Second Quarter 2026 Results. GAAP net income in the quarter was $2.5 billion, up 3% "
        "from a year ago. Net revenue was $9.1 billion.")
URL = "https://investor.visa.com/news/q2-2026"
ORDINALS = ("first", "second", "third", "fourth")


def _search(pages, seen=None):
    def search(quarter, domains):
        if seen is not None:
            seen.append((quarter.ref, domains))
        return pages
    return search


def _fills(data, search=None):
    book = dpw.open_dp_workbook(data)
    fills, reasons = dpw.fill_blanks(book, TODAY, search)
    return dpw.read_dp_workbook(book, fills, reasons), fills


def _visa_pe(table):
    return next(r for r in table["rows"] if r["key"] == "visa")["ttm_pe"]


def test_a_blank_quarter_is_never_zero_and_is_listed_with_company_label_and_cell():
    read = _read(_blank(_build(), "H4"))
    assert [(q.company, q.label, q.ref) for q in read.blank] == [("Visa", "Q2'26", VISA_H4)]
    visa = read.row("visa")
    assert visa.ttm_pe is None and visa.filled_ttm is None   # not 100/6, the sum of three quarters of 2
    assert "Q2'26 (Earnings!H4) is blank" in visa.reason
    assert any(w.startswith("Visa: TTM P/E unavailable") and "never counted as zero" in w for w in read.warnings)


def test_a_blank_quarter_is_filled_from_the_financial_results_sheet_and_waits_for_acceptance():
    data = _with_results(_blank(_build(), "H4"), [("Visa (Q2)", 2, 2.5), ("Mastercard (Q2)", 3, 3.5)])
    read, fills = _fills(data)
    (fill,) = fills
    assert (fill.value, fill.source, fill.fetched) == (Decimal("2.5"), "'Financial Results'!D4", TODAY.isoformat())
    assert "Visa (Q2): Net income (USD bn) 2.5" in fill.quoted
    visa = read.row("visa")
    assert visa.ttm_pe is None and visa.filled_ttm == Decimal(100) / Decimal("8.5") and visa.needs == (VISA_H4,)
    assert "USD 2.5 bn was found in 'Financial Results'!D4" in visa.reason
    rows = [r.as_dict() for r in read.rows]
    assert _visa_pe(dpw.pe_table(rows)) is None
    accepted = dpw.pe_table(rows, {VISA_H4})
    assert _visa_pe(accepted) == Decimal(100) / Decimal("8.5") and accepted["left_out"] == []


def test_a_blank_quarter_found_by_search_is_a_review_item_with_its_citation_until_accepted():
    seen = []
    review = _review(dpw.open_dp_workbook(_blank(_build(), "H4")), search=_search([{"url": URL, "text": PAGE}], seen))
    assert seen == [(VISA_H4, ["investor.visa.com", "sec.gov"])]
    (item,) = [i for i in review.review_items if i.kind == WORKBOOK_QUARTER]
    assert item.context == {"company": "Visa", "cell": VISA_H4, "quarter": "Q2'26", "value": "2.5", "source": URL,
                            "fetched": TODAY.isoformat(),
                            "quoted": "GAAP net income in the quarter was $2.5 billion, up 3% from a year ago."}
    assert URL in item.detail and "$2.5 billion" in item.detail and "stays unavailable until you accept" in item.detail
    assert any(URL in w and "accept it in the review" in w for w in review.section["warnings"])
    assert item.resolution is None and not review.is_approvable
    assert _visa_pe(workbook_pe(review)) is None   # before acceptance
    item.resolve(FIX_NEEDED)
    assert _visa_pe(workbook_pe(review)) is None
    item.resolve(ACCEPT)
    assert _visa_pe(workbook_pe(review)) == Decimal(100) / Decimal("8.5")


@pytest.mark.parametrize("page, why", [
    ({"url": URL, "text": PAGE, "figure": "$2.9 billion"}, "is not in the page text"),   # the backend's number is not on the page
    ({"url": URL, "text": PAGE + " Net income was $2.7 billion on an adjusted basis."}, "more than one net income figure"),
    ({"url": URL, "text": "Visa announces a new partnership. Net income was $2.5 billion."}, "does not say it covers Q2'26"),
    ({"url": "https://example.com/visa", "text": PAGE}, "is not an investor relations or SEC page"),
])
def test_a_figure_that_is_not_verbatim_in_an_ir_or_sec_page_is_rejected(page, why):
    read, fills = _fills(_blank(_build(), "H4"), _search([page]))
    assert fills == [] and read.row("visa").ttm_pe is None and read.row("visa").filled_ttm is None
    assert why in read.row("visa").reason


def test_a_figure_the_backend_claims_is_accepted_only_when_it_is_in_the_page_text():
    read, fills = _fills(_blank(_build(), "H4"), _search([{"url": URL, "text": PAGE, "figure": "$2.5 billion"}]))
    assert [f.value for f in fills] == [Decimal("2.5")] and read.row("visa").filled_ttm is not None


def test_a_figure_in_millions_is_converted():
    page = "Visa reports second quarter 2026 results. Net income was $2,512 million for the quarter."
    _, fills = _fills(_blank(_build(), "H4"), _search([{"url": URL, "text": page}]))
    assert [f.value for f in fills] == [Decimal("2.512")]


@pytest.mark.parametrize("search", [None, _search([]), lambda q, d: 1 / 0])
def test_with_no_source_anywhere_the_pe_is_unavailable_with_a_reason_and_never_computed(search):
    read, fills = _fills(_blank(_build(), "H4"), search)
    visa = read.row("visa")
    assert fills == [] and visa.ttm_pe is None and visa.filled_ttm is None and visa.needs == ()
    assert "Q2'26 (Earnings!H4) is blank and Financial Results has no Q2'26 net income for it and " in visa.reason
    # accepting a cell that was never filled changes nothing
    assert _visa_pe(dpw.pe_table([r.as_dict() for r in read.rows], {VISA_H4})) is None


def test_the_average_leaves_out_a_company_without_a_pe_and_names_it():
    read, _ = _fills(_blank(_build(cached=_by_name_cached()), "H4"))
    others = [0, 2, 3, 4, 5, GPN]
    assert read.average_ttm == sum(_ttm(i) for i in others) / 6 and [x["company"] for x in read.left_out] == ["Visa"]
    text = [w for w in read.warnings if w.startswith("Average: the workbook's TTM P/E average")]
    assert text and "left out, because their TTM P/E is unavailable: Visa" in text[0] and "6 companies" in text[0]


def test_the_average_says_what_was_left_out_even_when_the_workbooks_own_average_agrees():
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(_blank(_build(), "H4")))
    book["Stock Performance"]["I13"] = float(sum(_ttm(i) for i in [0, 2, 3, 4, 5, GPN]) / 6)
    out = io.BytesIO()
    book.save(out)
    read, _ = _fills(out.getvalue())
    assert [w for w in read.warnings if w.startswith("Average: the TTM P/E average covers 6 of the seven companies")]


def test_the_window_warning_fires_when_financial_results_is_a_quarter_ahead_and_not_otherwise():
    ahead = _fills(_with_results(_build(), [("Visa (Q3)", 2, 3)]))[0]   # Earnings stops at Q2'26
    assert ("Visa: the TTM window may be one quarter behind: its latest quarter on Earnings is Q2'26 "
            "but Financial Results has Q3'26.") in ahead.warnings
    assert not any("window" in w for w in _fills(_with_results(_build(), [("Visa (Q2)", 2, 3)]))[0].warnings)
    assert not any("window" in w for w in _fills(_build())[0].warnings)   # no Financial Results sheet at all


def test_a_filled_quarter_counts_as_the_latest_for_the_window_warning():
    data = _with_results(_blank(_build(), "H4"), [("Visa (Q2)", 2, 2.5)])
    assert not any("window" in w for w in _fills(data)[0].warnings)


def test_the_real_v4_blank_quarter_is_filled_from_financial_results_and_waits_for_acceptance():
    read, fills = _fills(sample(V4), _search([]))
    (fill,) = fills
    assert (fill.quarter.company, fill.quarter.ref, fill.value, fill.source) == (
        "Paypal Holdings", "Earnings!I8", Decimal("1.073"), "'Financial Results'!D11")
    assert read.row("paypal").ttm_pe is None and round_half_up(read.row("paypal").filled_ttm, 1) == Decimal("10.6")
    assert "Wise PLC: TTM P/E unavailable" in " ".join(read.warnings)
    assert [x["company"] for x in read.left_out] == ["Paypal Holdings"] and round_half_up(read.average_ttm, 1) == Decimal("24.3")
    text = " ".join(read.warnings)
    assert "American Express: the TTM window may be one quarter behind: its latest quarter on Earnings is Q2'26 but Financial Results has Q3'26." in text
    assert "Visa: the TTM window may be one quarter behind: its latest quarter on Earnings is Q3'26 but Financial Results has Q4'26." in text


def _blank_in_xml(raw, ref):
    """The workbook with one Earnings cell emptied in the XML, so every other cell keeps the value Excel saved
    (an openpyxl round trip would drop the saved value of every formula cell)."""
    src, out = zipfile.ZipFile(io.BytesIO(raw)), io.BytesIO()
    with zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            body = src.read(item.filename)
            if item.filename == "xl/worksheets/sheet2.xml":
                text, n = re.subn(rf'<c r="{ref}"( s="\d+")?><v>[^<]*</v></c>', r'<c r="%s"\1/>' % ref, body.decode())
                assert n == 1
                body = text.encode()
            dst.writestr(item, body)
    return out.getvalue()


def test_a_real_v4_copy_with_one_more_quarter_blanked_is_found_by_search_or_left_unavailable():
    raw = sample(V4)
    book = dpw.open_dp_workbook(raw)
    stock = book.sheet("Stock Performance")
    row = next(r for r in range(1, stock.max_row + 1) if stock.value(r, 1) == "Mastercard")
    ref = re.search(r"Earnings!\$?([A-Z]+\d+)", book.formula(stock.cell(row, 9))).group(1)
    blanked = _blank_in_xml(raw, ref)
    none_found, fills = _fills(blanked, _search([]))
    assert [f.quarter.company for f in fills] == ["Paypal Holdings"]
    assert none_found.row("mastercard").ttm_pe is None and none_found.row("mastercard").filled_ttm is None
    assert sorted(x["company"] for x in none_found.left_out) == ["Mastercard", "Paypal Holdings"]
    q = next(q for q in none_found.blank if q.company == "Mastercard")
    page = (f"Mastercard Incorporated reports {ORDINALS[int(q.label[1]) - 1]} quarter {2000 + int(q.label[-2:])} results. "
            "Net income was $3.9 billion for the quarter.")
    found, fills = _fills(blanked, _search([{"url": "https://investor.mastercard.com/news/x", "text": page}]))
    assert [(f.quarter.company, f.value) for f in fills if f.quarter.company == "Mastercard"] == [("Mastercard", Decimal("3.9"))]
    assert found.row("mastercard").ttm_pe is None and found.row("mastercard").filled_ttm is not None
