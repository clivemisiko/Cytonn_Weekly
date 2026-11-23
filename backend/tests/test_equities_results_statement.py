import copy
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
    assert st.missing == [] and st.unmatched == [] and st.problems == []


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


def test_planted_changed_total(st):
    planted = copy.deepcopy(st)
    planted.values[G]["total_liabilities"][S26].value += 1000
    check(planted)
    new = {(f[2]) for f in _flags(planted) - KNOWN_ROUNDING}
    assert new == {"total_liabilities", "total_assets", "total_liabilities_and_equity"}
    assert G in planted.unavailable


def test_planted_swapped_columns(st):
    planted = copy.deepcopy(st)
    row = planted.values[G]["customer_deposits"]
    row[S26], row[J26] = row[J26], row[S26]
    check(planted)
    new = {(f[1], f[2]) for f in _flags(planted) - KNOWN_ROUNDING}
    assert {(S26, "total_liabilities"), (J26, "total_liabilities")} <= new
    assert G not in planted.unavailable  # the printed totals still balance


def test_planted_removed_line(st):
    planted = copy.deepcopy(st)
    del planted.values[G]["borrowed_funds"]
    check(planted)
    new = {(f[1], f[2]) for f in _flags(planted) - KNOWN_ROUNDING}
    assert {(p, "total_liabilities") for p in st.periods} <= new


def test_planted_missing_date_column(st):
    planted = copy.deepcopy(st)
    for line in planted.values[G].values():
        line.pop(S25)
    check(planted)
    gone = [f for f in planted.flags if f["entity"] == G and f["period"] == S25]
    assert gone and all(f["kind"] == "cannot check" for f in gone)
    assert G in planted.unavailable


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

    govt = lambda p: g("govt_securities_amortised", p) + g("govt_securities_fvoci", p)
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
