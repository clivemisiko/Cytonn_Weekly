import copy
from decimal import Decimal
from datetime import date
from pathlib import Path

import pytest

from cytonn_weekly.common.formatting import round_half_up
from cytonn_weekly.equities.results.statement import (
    SOURCE_DISAGREES, StatementRefused, check, read_statement,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sources" / "results_coop_2026-09-30.pdf"
S26, J26, M26, D25, S25 = date(2026, 9, 30), date(2026, 6, 30), date(2026, 3, 31), date(2025, 12, 31), date(2025, 9, 30)
G, K, C = "GROUP", "KINGDOM BANK", "CO-OP BANK"

# The page rounds every line to thousands on its own, so some printed totals are 1 to 3
# away from the sum of their printed lines. Each was added up by hand from the page.
KNOWN_ROUNDING = {
    (G, S26, "total_interest_expense", 21649698, 21649699),
    (G, D25, "total_opex", 51989766, 51989767),
    (G, D25, "pat", 29754529, 29754528),
    (K, M26, "total_assets", 53066111, 53066113),
    (K, S25, "total_assets", 48684162, 48684163),
    (C, S26, "total_equity", 161420271, 161420270),
    (C, S26, "total_interest_expense", 19360190, 19360191),
    (C, S26, "total_non_interest_income", 20408212, 20408213),
    (C, S26, "total_opex", 35222084, 35222083),
    (C, S26, "pat", 23827262, 23827261),
    (C, J26, "total_assets", 796475610, 796475611),
    (C, J26, "total_liabilities", 642259694, 642259695),
    (C, J26, "total_non_interest_income", 13523776, 13523777),
    (C, J26, "total_opex", 23321884, 23321885),
    (C, M26, "total_equity", 157956858, 157956857),
    (C, M26, "total_non_interest_income", 6736668, 6736669),
    (C, M26, "total_opex", 11369152, 11369151),
    (C, M26, "pat", 7192578, 7192579),
    (C, D25, "total_assets", 759406531, 759406533),
    (C, D25, "total_liabilities", 608693379, 608693378),
    (C, D25, "total_equity", 150713152, 150713151),
    (C, D25, "total_interest_expense", 27672408, 27672407),
    (C, D25, "total_non_interest_income", 23786437, 23786436),
    (C, D25, "total_opex", 46591667, 46591666),
    (C, S25, "total_assets", 746887139, 746887142),  # assets lines
    (C, S25, "total_liabilities", 596358615, 596358616),
    (C, S25, "total_assets", 746887139, 746887138),  # balance
    (C, S25, "total_liabilities_and_equity", 746887139, 746887138),
}


@pytest.fixture(scope="module")
def st():
    return read_statement(FIXTURE, "Co-operative Bank")


def _flags(statement):
    return {(f["entity"], f["period"], f["line"], f["printed"], f["computed"]) for f in statement.flags}


def test_layout(st):
    assert st.entities == [G, K, C]
    assert st.periods == [S26, J26, M26, D25, S25]
    assert st.group_entity == G
    # Lines other banks print and this one does not.
    assert st.missing == ["investment_securities", "amortised_cost_securities", "fvoci_securities",
                          "exceptional_items", "pat_nci", "pat_owners", "oci_remeasurement"]
    assert st.unmatched == [] and st.problems == []


def test_every_total_checks_except_the_pages_own_rounding(st):
    assert _flags(st) == KNOWN_ROUNDING
    assert all(f["kind"] == SOURCE_DISAGREES for f in st.flags)
    # The balance check fails by 1 or 2 thousand, so both bank columns are unavailable.
    assert set(st.unavailable) == {K, C}


@pytest.mark.parametrize("entity,key,period,printed", [
    (G, "total_assets", S26, 907443128),
    (G, "tax_recoverable", J26, 4521),          # plain text drops this row's blanks
    (K, "tax_recoverable", S26, 462158),
    (C, "tax_recoverable", S26, 0),
    (G, "tax_payable", J26, None),              # blank cell on the page
    (G, "fvtpl", M26, 645005),
    (K, "retained_earnings", D25, -71198),
    (G, "minority_interest", S26, -12954),
    (C, "customer_deposits", S25, 511418761),
    (G, "share_of_associates", S25, 358961),
    (K, "deferred_tax", D25, 69430),
    (C, "pat", M26, 7192578),
    (C, "npl_gross", J26, 66065929),
    (C, "liquidity_ratio", S26, 51.5),
    (G, "eps_basic", S26, 4.68),
])
def test_spot_values(st, entity, key, period, printed):
    assert st.get(entity, key, period) == printed


def test_value_keeps_page_and_label(st):
    v = st.values[C]["pat"][M26]
    assert (v.page, v.label) == (2, "Profit/(loss) after tax and exceptional items")
    v = st.values[G]["govt_securities_fvoci"][S26]
    assert (v.page, v.label) == (1, "Investment Securities: Fair Value through other "
                                    "comprehensive income (-FVOCI) Kenya Government Securities")


SOURCES = FIXTURE.parent
BANKS = {  # fixture, the page's own rounding differences
    "coop": (FIXTURE, KNOWN_ROUNDING),
    "equity": (SOURCES / "results_equity_2026-09-30.pdf", set()),
    "kcb": (SOURCES / "results_kcb_2026-09-30.pdf", set()),
}


@pytest.fixture(scope="module")
def statements():
    return {b: read_statement(path, b) for b, (path, _) in BANKS.items()}


@pytest.fixture(params=list(BANKS))
def bank(request, statements):
    st = statements[request.param]
    return st, st.group_entity, BANKS[request.param][1]


def test_planted_changed_total(bank):
    st, grp, known = bank
    planted = copy.deepcopy(st)
    planted.values[grp]["total_liabilities"][S26].value += 1000
    check(planted)
    new = {(f[2]) for f in _flags(planted) - known}
    assert new == {"total_liabilities", "total_assets", "total_liabilities_and_equity"}
    assert grp in planted.unavailable


def test_planted_swapped_columns(bank):
    st, grp, known = bank
    planted = copy.deepcopy(st)
    row = planted.values[grp]["customer_deposits"]
    row[S26], row[J26] = row[J26], row[S26]
    check(planted)
    new = {(f[1], f[2]) for f in _flags(planted) - known}
    assert {(S26, "total_liabilities"), (J26, "total_liabilities")} <= new
    assert grp not in planted.unavailable  # the printed totals still balance


def test_planted_removed_line(bank):
    st, grp, known = bank
    planted = copy.deepcopy(st)
    del planted.values[grp]["borrowed_funds"]
    check(planted)
    new = {(f[1], f[2]) for f in _flags(planted) - known}
    assert {(p, "total_liabilities") for p in st.periods} <= new


def test_planted_missing_date_column(bank):
    st, grp, _ = bank
    planted = copy.deepcopy(st)
    for line in planted.values[grp].values():
        line.pop(S25)
    check(planted)
    gone = [f for f in planted.flags if f["entity"] == grp and f["period"] == S25]
    assert gone and all(f["kind"] == "cannot check" for f in gone)
    assert grp in planted.unavailable


def _pdf(path, content: bytes):
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(out)
    return path


def test_refuses_no_text_layer(tmp_path):
    with pytest.raises(StatementRefused, match="no text layer"):
        read_statement(_pdf(tmp_path / "scan.pdf", b"0 0 m 100 100 l S"), "Any Bank")


def test_refuses_other_layout(tmp_path):
    pdf = _pdf(tmp_path / "other.pdf", b"BT /F1 12 Tf 72 720 Td (Annual report 2026) Tj ET")
    with pytest.raises(StatementRefused, match="STATEMENT OF FINANCIAL POSITION.*OTHER DISCLOSURES"):
        read_statement(pdf, "Any Bank")


# Acceptance: the Co-operative Bank row of the team's published cross-bank table, from
# the GROUP column. Growth is 30-Sep-26 over 30-Sep-25.
PUBLISHED = {
    "Core EPS growth": "27.2%", "Interest Income growth": "7.0%", "Interest Expense growth": "(4.4%)",
    "Net Interest Income growth": "12.7%", "Net Interest Margin": "8.9%", "Non-Funded Income growth": "9.2%",
    "NFI to Total Operating Income": "32.1%", "Fees and Commissions growth": "11.8%", "Deposit growth": "15.4%",
    "Government Securities growth": "6.1%", "Loan to Deposit Ratio": "78.5%", "Loan growth": "22.2%",
    "Return on Average Equity": "20.7%", "Cost of Funds": "4.4%", "Yield on interest-earning assets": "12.8%",
}


def _pct(x):
    r = round_half_up(x * 100, 1)
    return f"({-r}%)" if r < 0 else f"{r}%"


def _row(st):
    def g(key, p=S26):
        return st.get(G, key, p) or 0

    def growth(f):
        return f(S26) / f(S25) - 1

    def line(key):
        return lambda p: g(key, p)

    def avg(f):
        return (f(S26) + f(S25)) / 2

    def ttm(key):  # 9M'26 + FY'25 - 9M'25
        return g(key) + g(key, D25) - g(key, S25)

    govt = lambda p: _govt(st, G, p)
    earning = lambda p: g("loans", p) + govt(p) + g("due_from_local_banks", p) + g("due_from_abroad_banks", p)
    bearing = lambda p: g("customer_deposits", p) + g("borrowed_funds", p)
    annual = 12 / 9
    return {
        # Core EPS growth = PAT growth: paid-up capital is 5,867,180 at both dates, so
        # the share count is assumed unchanged.
        "Core EPS growth": growth(line("pat")),
        "Interest Income growth": growth(line("total_interest_income")),
        "Interest Expense growth": growth(line("total_interest_expense")),
        "Net Interest Income growth": growth(line("net_interest_income")),
        "Net Interest Margin": g("net_interest_income") * annual / avg(earning),
        "Non-Funded Income growth": growth(line("total_non_interest_income")),
        "NFI to Total Operating Income": g("total_non_interest_income") / g("total_operating_income"),
        "Fees and Commissions growth": growth(lambda p: g("fees_on_loans", p) + g("other_fees", p)),
        "Deposit growth": growth(line("customer_deposits")),
        "Government Securities growth": growth(govt),
        "Loan to Deposit Ratio": g("loans") / g("customer_deposits"),
        "Loan growth": growth(line("loans")),
        # ROE and yield reproduce only on trailing twelve months; see the test below.
        "Return on Average Equity": ttm("pat") / avg(line("total_equity")),
        "Cost of Funds": g("total_interest_expense") * annual / avg(bearing),
        "Yield on interest-earning assets": ttm("total_interest_income") / avg(earning),
    }, (g, avg, earning, bearing, annual, ttm)


def test_acceptance_cross_bank_row(st):
    row, _ = _row(st)
    assert {k: _pct(v) for k, v in row.items()} == PUBLISHED


def test_acceptance_alternatives_that_do_not_reproduce(st):
    # Known difference, not a tolerance: the team's NIM and cost of funds are 9M annualised
    # by 12/9, but its ROE and yield are trailing twelve months. On 9M annualised they give:
    _, (g, avg, earning, bearing, annual, ttm) = _row(st)
    assert _pct(g("pat") * annual / avg(lambda p: g("total_equity", p))) == "21.3%"
    assert _pct(g("total_interest_income") * annual / avg(earning)) == "12.7%"
    # and on trailing twelve months NIM and cost of funds would not match:
    assert _pct(ttm("net_interest_income") / avg(earning)) == "9.0%"
    assert _pct(ttm("total_interest_expense") / avg(bearing)) == "4.5%"
    # Adding the two due-to-banks lines to interest-bearing liabilities leaves 4.4%.
    with_banks = lambda p: bearing(p) + g("due_to_local_banks", p) + g("due_to_abroad_banks", p)
    assert _pct(g("total_interest_expense") * annual / avg(with_banks)) == "4.4%"
    # ROE with non-controlling interest in equity is also 20.7%.
    assert _pct(ttm("pat") / avg(lambda p: g("total_equity", p) + g("minority_interest", p))) == "20.7%"


def _govt(st, entity, p):
    # Kenya Government securities wherever the balance sheet holds them: for dealing,
    # at amortised cost and at FVOCI. KCB's 46.2026 figures need the dealing line;
    # Equity and Co-op print a dash there.
    return sum(st.get(entity, k, p) or 0 for k in
               ("govt_securities_dealing", "govt_securities_amortised", "govt_securities_fvoci"))


EB, EC, EG = "BANK", "COMPANY", "GROUP"
KB, KC, KG = "KCB BANK KENYA", "KCB GROUP PLC COMPANY", "KCB GROUP PLC CONSOLIDATED"


def test_layout_equity_and_kcb(statements):
    eq, kcb = statements["equity"], statements["kcb"]
    assert eq.entities == [EB, EC, EG] and kcb.entities == [KB, KC, KG]
    assert eq.periods == kcb.periods == [S26, J26, M26, D25, S25]  # Equity's two-line headers too
    # The group column is the one whose name ends GROUP or CONSOLIDATED; KCB's company
    # column also contains "GROUP" but ends COMPANY.
    assert (eq.group_entity, kcb.group_entity) == (EG, KG)
    assert eq.missing == ["capital_grants", "exceptional_early_retirement", "share_of_associates",
                          "oci_revaluation", "eps_diluted"]
    assert kcb.missing == ["amortised_cost_securities", "fvoci_securities", "exceptional_early_retirement",
                           "share_of_associates", "oci_revaluation", "eps_diluted"]
    for st in (eq, kcb):
        assert st.unmatched == [] and st.problems == []
    # KCB's section III has two entities, Equity's three (dashes under COMPANY).
    for block in ("other:npl", "other:insider", "other:off_balance", "other:capital", "other:liquidity"):
        assert kcb.block_entities[block] == [KB, KG]
        assert eq.block_entities[block] == [EB, EC, EG]
    assert kcb.block_entities["sfp"] == [KB, KC, KG]
    # Equity counts non-controlling interest inside total shareholders' funds.
    assert eq.nci_in_equity(EG) and not kcb.nci_in_equity(KG)


@pytest.mark.parametrize("name", ["equity", "kcb"])
def test_every_total_checks(statements, name):
    st = statements[name]
    assert st.flags == [] and st.unavailable == {}


@pytest.mark.parametrize("name,entity,key,period,printed", [
    ("equity", EG, "total_assets", M26, 2036547132),     # three totals glued into one word
    ("equity", EG, "total_assets", D25, 1970992243),
    ("equity", EG, "total_assets", S25, 1817015883),
    ("equity", EB, "tax_recoverable", M26, 0),
    ("equity", EC, "tax_recoverable", S26, 392301),
    ("equity", EG, "current_tax", S26, -18578427),       # tax printed as a signed amount
    ("equity", EG, "minority_interest", S26, 19199276),
    ("equity", EC, "net_interest_income", D25, -26662),
    ("equity", EG, "govt_securities_amortised", S25, 35039113),
    ("equity", EG, "govt_securities_fvoci", S26, 279726673),
    ("equity", EC, "dividends_payable", J26, 12196875),
    ("equity", EG, "npl_gross", S25, 129172731),
    ("equity", EB, "eps_basic", S26, 1356.06),
    ("equity", EG, "core_to_rwa", S26, 18.2),
    ("kcb", KB, "cash", S26, 9462174),                   # under the kerned "3 0-Sep-26"
    ("kcb", KC, "cash", S25, 0),
    ("kcb", KG, "due_from_local_banks", S25, 853024),
    ("kcb", KG, "govt_securities_dealing", S26, 33582692),
    ("kcb", KC, "dividend_income", S26, 28350008),
    ("kcb", KG, "pat_nci", S26, 1435354),
    ("kcb", KB, "pat_nci", S26, None),                   # printed for the group only
    ("kcb", KC, "current_tax", S26, 451692),
    ("kcb", KG, "current_tax", S25, -19351121),
    ("kcb", KB, "npl_gross", S26, 161999946),
    ("kcb", KC, "npl_gross", S26, None),                 # section III has no company column
    ("kcb", KG, "npl_gross", S25, 222068738),
    ("kcb", KG, "rwa", S26, 1853022895),
    ("kcb", KG, "total_to_rwa", S25, 19.6),
    ("kcb", KG, "minority_interest", S26, 4062219),
])
def test_spot_values_equity_and_kcb(statements, name, entity, key, period, printed):
    assert statements[name].get(entity, key, period) == printed


# Acceptance: the team's published 46.2026 per-bank tables, group column, KSh bn to 1 dp,
# Q3'2025 then Q3'2026. The two banks' tables have different rows: Equity prints
# Non-Interest Income and Deposits per branch, KCB prints Net non-Interest Income, Staff
# Costs and Other Operating expenses. Deposits per branch (Equity 3.4, 3.9) needs branch
# counts, which the statement does not hold, so it is left out.
def _bn(thousands):
    r = round_half_up(Decimal(thousands) / 1000000, 1)
    return f"({-r:,})" if r < 0 else f"{r:,}"


def _line(key, sign=1):
    return lambda st, e, p: sign * (st.get(e, key, p) or 0)


def _equity_less_nci(st, e, p):  # shareholders' funds without non-controlling interest
    nci = (st.get(e, "minority_interest", p) or 0) if st.nci_in_equity(e) else 0
    return (st.get(e, "total_equity", p) or 0) - nci


def _kcb_other_opex(st, e, p):  # the team's Other Operating expenses: the rest of the total
    return (st.get(e, "total_opex", p) or 0) - sum(st.get(e, k, p) or 0 for k in ("loan_loss_provision", "staff_costs"))


COMMON = {
    "Government Securities": _govt,
    "Net Loans and Advances": _line("loans"),
    "Total Assets": _line("total_assets"),
    "Customer Deposits": _line("customer_deposits"),
    "Total Liabilities": _line("total_liabilities"),
    "Shareholders' Funds": _equity_less_nci,
    "Net Interest Income": _line("net_interest_income"),
    "Total Operating income": _line("total_operating_income"),
    "Profit before tax": _line("pbt"),
    "Profit after tax": _line("pat"),  # before non-controlling interest
}
TABLES = {
    "equity": ({**COMMON,
                "Non-Interest Income": _line("total_non_interest_income"),
                # Equity's table prints the costs as negatives; the statement prints them positive.
                "Loan Loss provision": _line("loan_loss_provision", -1),
                "Total Operating expenses": _line("total_opex", -1)}, {
        "Government Securities": ("310.4", "320.3"), "Net Loans and Advances": ("859.8", "1,007.7"),
        "Total Assets": ("1,817.0", "2,149.0"), "Customer Deposits": ("1,345.5", "1,583.9"),
        "Total Liabilities": ("1,513.8", "1,779.3"), "Shareholders' Funds": ("288.4", "350.5"),
        "Net Interest Income": ("93.6", "107.7"), "Non-Interest Income": ("62.7", "84.4"),
        "Total Operating income": ("156.3", "192.0"), "Loan Loss provision": ("(11.6)", "(10.2)"),
        "Total Operating expenses": ("(90.7)", "(102.2)"), "Profit before tax": ("65.6", "89.8"),
        "Profit after tax": ("54.1", "71.5")}),
    "kcb": ({**COMMON,
             # the file's 4.6 "Total other operating income", nothing netted off
             "Net non-Interest Income": _line("total_non_interest_income"),
             "Loan Loss provision": _line("loan_loss_provision"),
             "Staff Costs": _line("staff_costs"),
             "Other Operating expenses": _kcb_other_opex,
             "Total Operating expenses": _line("total_opex")}, {
        "Government Securities": ("333.8", "410.3"), "Net Loans and Advances": ("1,139.9", "1,286.8"),
        "Total Assets": ("2,044.5", "2,359.0"), "Customer Deposits": ("1,525.8", "1,755.2"),
        "Total Liabilities": ("1,727.1", "1,992.9"), "Shareholders' Funds": ("308.5", "362.0"),
        "Net Interest Income": ("104.3", "112.9"), "Net non-Interest Income": ("45.1", "54.9"),
        "Total Operating income": ("149.4", "167.8"), "Loan Loss provision": ("18.3", "16.6"),
        "Staff Costs": ("30.9", "32.9"), "Other Operating expenses": ("38.2", "40.4"),
        "Total Operating expenses": ("87.4", "89.9"), "Profit before tax": ("62.1", "77.9"),
        "Profit after tax": ("47.3", "58.6")}),
}
# Known difference, not a tolerance: KCB's Q3'2025 operating expenses total 87,349,295
# thousand, 87.3 bn; the table's 87.4 is the sum of its own rounded rows 18.3 + 30.9 + 38.2.
PINNED = {("kcb", "Total Operating expenses", 0): "87.3"}


@pytest.mark.parametrize("name", list(TABLES))
def test_acceptance_per_bank_table(statements, name):
    st = statements[name]
    rows, published = TABLES[name]
    assert rows.keys() == published.keys()
    for row, f in rows.items():
        for i, p in enumerate((S25, S26)):
            expected = PINNED.get((name, row, i), published[row][i])
            assert _bn(f(st, st.group_entity, p)) == expected, (name, row, p)


def test_acceptance_tables_have_different_rows():
    assert set(TABLES["equity"][1]) ^ set(TABLES["kcb"][1]) == {
        "Non-Interest Income", "Net non-Interest Income", "Staff Costs", "Other Operating expenses"}


def test_kcb_pinned_total_is_the_sum_of_rounded_rows(statements):
    rows = TABLES["kcb"][0]
    parts = ("Loan Loss provision", "Staff Costs", "Other Operating expenses")
    assert sum(Decimal(_bn(rows[r](statements["kcb"], KG, S25))) for r in parts) == Decimal("87.4")
