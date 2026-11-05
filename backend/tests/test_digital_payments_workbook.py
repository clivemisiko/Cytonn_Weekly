import io
import json
import re
import zipfile
from decimal import Decimal

import pytest
from openpyxl import Workbook as XlsxWorkbook

from cytonn_weekly.common.formatting import round_half_up
from cytonn_weekly.digital_payments import workbook as dpw
from cytonn_weekly.digital_payments.review_run import build_digital_payments_review
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
    assert book.warnings == [] and book.blank_quarters == []


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


def test_a_blank_quarter_counts_as_zero_as_in_excel_and_is_listed():
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(_build()))
    book["Earnings"]["H4"] = None   # Visa's Q2'26
    out = io.BytesIO()
    book.save(out)
    read = _read(out.getvalue())
    assert read.blank_quarters == ["Earnings!H4"]
    assert read.row("visa").ttm_pe == Decimal(100) / 6   # three quarters of 2


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

def _review(workbook):
    rows = [src_row("V", "Visa"), src_row("GPN", "Global Payments")]
    rows[1]["ytd_open"] = 75.529999
    return build_digital_payments_review(provider=FakeProvider(), today=TODAY, fetch_table=lambda today: rows, workbook=workbook)


def test_review_shows_the_workbook_warnings_and_without_a_workbook_has_none_of_them():
    plain = _review(None).section["warnings"]
    assert not any("workbook" in w for w in plain)
    swapped = _by_name_cached() | {"I9": 100 / 32}
    warned = _review(dpw.open_dp_workbook(_build(swap=True, cached=swapped))).section["warnings"]
    assert any("Global Payments Inc: the workbook's TTM P/E" in w for w in warned)


def test_review_flags_a_year_open_that_is_not_the_fetched_close():
    warned = _review(dpw.open_dp_workbook(_build(cached=_by_name_cached()))).section["warnings"]
    assert any(w.startswith("Global Payments Inc: Year Open is 56.00 in the workbook") and "is 75.53" in w for w in warned)


# ---- the team's real 30 October file, read only; skipped when it is not there ------------------------------------------

def test_real_file_by_name():
    data = sample("Digital_Payments_workbook_30-10-2026_v4.xlsx")
    book = _read(data)
    gpn, coin = book.row("global payments"), book.row("coinbase global")
    assert (round_half_up(gpn.ttm_pe, 1), round_half_up(gpn.forward_pe, 1)) == (Decimal("-26.9"), Decimal("6.0"))
    assert (round_half_up(coin.ttm_pe, 1), round_half_up(coin.forward_pe, 1)) == (Decimal("-38.4"), Decimal("47.5"))
    assert (round_half_up(book.average_ttm, 1), round_half_up(book.average_forward, 1)) == (Decimal("22.8"), Decimal("21.3"))
    assert gpn.year_open == Decimal("75.53")
    assert dpw.year_open_warnings(book, _fixture_rows()) == []
    # the rows of this file line up on both sheets (the swap has been fixed at the source), so the saved cells agree
    assert book.warnings == [] and book.blank_quarters == ["Earnings!G11", "Earnings!I11", "Earnings!I8"]
