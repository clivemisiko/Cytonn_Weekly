from datetime import date
from pathlib import Path

import pytest

from cytonn_weekly.common.computed import a_figure, check_figure_record
from cytonn_weekly.equities.results.metrics import (
    BEARING_LIABILITIES, EARNING_ASSETS, GOVT, RATIOS, TABLES, Settings, _Calc, bank_results, core_eps,
    cross_bank_row, month_end,
)
from cytonn_weekly.equities.results.statement import Statement, Value, read_statement

S26, J26, M26, D25, S25 = date(2026, 9, 30), date(2026, 6, 30), date(2026, 3, 31), date(2025, 12, 31), date(2025, 9, 30)
SOURCES = Path(__file__).parent / "fixtures" / "sources"


# --- synthetic -------------------------------------------------------------------------------

def _st(lines: dict[str, dict[date, float]], periods=None) -> Statement:
    periods = periods or sorted({p for v in lines.values() for p in v}, reverse=True)
    values = {"GROUP": {k: {p: Value(v, 1, k, i) for p, v in by.items()} for i, (k, by) in enumerate(lines.items())}}
    return Statement("Test Bank", ["GROUP"], periods, values, [])


def _ratio(st, key, p, s=Settings()):
    c = _Calc(st, s, {})
    return a_figure(key, key, "pct", 1, c.inputs, RATIOS[key][1](c, p), in_text=False)["display"]


def test_half_up_at_a_x5_boundary():
    st = _st({"loans": {S26: 1235}, "customer_deposits": {S26: 10000}})
    assert _ratio(st, "ldr", S26) == "12.4%"   # 12.35, never half-to-even


@pytest.mark.parametrize("key,lines,expected", [
    ("govt_to_deposits", {"govt_securities_dealing": 1, "govt_securities_amortised": 2, "govt_securities_fvoci": 3,
                          "customer_deposits": 60}, "10.0%"),
    ("cost_of_risk", {"loan_loss_provision": 5, "total_operating_income": 40}, "12.5%"),
    ("nii_share", {"net_interest_income": 30, "total_operating_income": 40}, "75.0%"),
    ("nfi_share", {"total_non_interest_income": 10, "total_operating_income": 40}, "25.0%"),
    ("cost_to_income", {"total_opex": 22, "total_operating_income": 40}, "55.0%"),
    ("cost_to_income_ex_llp", {"total_opex": 22, "loan_loss_provision": 2, "total_operating_income": 40}, "50.0%"),
    ("cost_to_assets", {"total_opex": 22, "loan_loss_provision": 2, "total_assets": 400}, "5.0%"),
])
def test_point_in_time_expressions(key, lines, expected):
    assert _ratio(_st({k: {S26: v} for k, v in lines.items()}), key, S26) == expected


def _flat(keys, value):
    return {k: {S26: value, S25: value} for k in keys}


def test_averaged_expressions():
    # ttm income = 9M'26 + FY'25 - 9M'25 = 90 + 100 - 70 = 120
    income = lambda k: {k: {S26: 90, D25: 100, S25: 70}}
    st = _st({**_flat(EARNING_ASSETS, 100), **_flat(BEARING_LIABILITIES, 100), **_flat(("total_assets", "total_equity"), 1000),
              **income("total_interest_income"), **income("net_interest_income"), **income("total_interest_expense"),
              **income("pat")})
    n_ea, n_bl = len(EARNING_ASSETS), len(BEARING_LIABILITIES)
    assert _ratio(st, "yield", S26) == f"{120 / (100 * n_ea) * 100:.1f}%"
    assert _ratio(st, "nim", S26) == _ratio(st, "yield", S26)
    assert _ratio(st, "cost_of_funds", S26) == f"{120 / (100 * n_bl) * 100:.1f}%"
    assert _ratio(st, "roe", S26) == _ratio(st, "roa", S26) == "12.0%"
    assert _ratio(st, "spread", S26) == "(" + f"{120 / (100 * n_bl) * 100 - 120 / (100 * n_ea) * 100:.1f}".lstrip("-") + "%)"


@pytest.mark.parametrize("p,expected", [(date(2026, 3, 31), "12.0%"), (date(2026, 6, 30), "6.0%"),
                                        (S26, "4.0%"), (date(2026, 12, 31), "3.0%")])
def test_annualising_q1_h1_q3_fy(p, expected):
    st = _st({"pat": {p: 30}, "total_assets": {p: 1000, month_end(p, 12): 1000}})
    assert _ratio(st, "roa", p, Settings(income_basis="annualised")) == expected


def test_ttm_of_a_full_year_is_the_year_itself():
    p = date(2026, 12, 31)
    st = _st({"pat": {p: 30}, "total_assets": {p: 1000, month_end(p, 12): 1000}})
    assert _ratio(st, "roa", p) == "3.0%"


def test_two_and_five_point_averages():
    assets = {S26: 1000, J26: 900, M26: 800, D25: 700, S25: 600}
    st = _st({"pat": {S26: 80, D25: 60, S25: 40}, "total_assets": assets})
    assert _ratio(st, "roa", S26) == "12.5%"                                     # 100 / 800
    assert _ratio(st, "roa", S26, Settings(average_months=(0, 3, 6, 9, 12))) == "12.5%"  # 100 / 800 again
    st.values["GROUP"]["total_assets"][M26].value = 300
    assert _ratio(st, "roa", S26) == "12.5%"
    assert _ratio(st, "roa", S26, Settings(average_months=(0, 3, 6, 9, 12))) == "14.3%"  # 100 / 700


def test_points_change_from_unrounded_ratios():
    # 23.14% -> 20.26% prints 23.1 and 20.3; the change is (2.9%) from the unrounded
    # -2.88, not the (2.8%) the rounded figures would give.
    st = _st({"govt_securities_dealing": {S26: 2026, S25: 2314}, "govt_securities_amortised": {S26: 0, S25: 0},
              "govt_securities_fvoci": {S26: 0, S25: 0}, "customer_deposits": {S26: 10000, S25: 10000}})
    TABLES["test"] = {"balance_sheet": [], "income_statement": [], "balance_ratios": ["govt_to_deposits"],
                      "income_ratios": []}
    try:
        row = bank_results(st, S26, "test")["balance_ratios"][0]
    finally:
        del TABLES["test"]
    assert (row["previous"]["display"], row["current"]["display"], row["change"]["display"]) == ("23.1%", "20.3%", "(2.9%)")


def test_missing_line_is_a_named_unavailable():
    fig = cross_bank_row(_st({"loans": {S26: 1, S25: 1}}), S26)["Loan to Deposit Ratio"]
    assert fig["unavailable"] == "customer_deposits at 30 Sep 2026 is not printed (Test Bank, GROUP)"
    fig = cross_bank_row(_st({"loans": {S26: 1}, "customer_deposits": {S26: 1}}), S26)["Loan growth"]
    assert "loans at 30 Sep 2025 is not a column of this statement" in fig["unavailable"]


def test_bank_without_a_row_set_is_unavailable():
    out = bank_results(_st({"loans": {S26: 1}}), S26, "coop")
    assert out["unavailable"] == "no table row set for 'coop': its published tables have not been mapped"
    assert "balance_sheet" not in out


def test_no_group_column_is_unavailable():
    st = _st({"loans": {S26: 1}})
    st.entities = ["BANK", "COMPANY"]
    assert "no single group" in cross_bank_row(st, S26)["Loan growth"]["unavailable"]


def test_core_eps_needs_the_share_count():
    st = _st({"pat": {S26: 9000}})
    assert "shares at 30 Sep 2026 is not in the statement" in core_eps(st, S26)["unavailable"]
    fig = core_eps(st, S26, {S26: 1000000})
    assert fig["display"] == "9.0" and fig["inputs"]["shares@2026-09-30"]["origin"] == "analyst_input"


# --- acceptance: the team's published 46.2026 tables, group column, Q3'2025 then Q3'2026 ------------

@pytest.fixture(scope="module")
def banks():
    return {b: read_statement(SOURCES / f"results_{b}_2026-09-30.pdf", b) for b in ("equity", "kcb", "coop")}


@pytest.fixture(scope="module")
def results(banks):
    return {b: bank_results(st, S26, b, extra={"branches": {}}) for b, st in banks.items()}


# The figures a single Q3'2026 statement cannot give: each needs the 30 Sep 2024 balance sheet or
# the FY'2024 and 9M'2024 income, which only last year's statement prints.
NEEDS_LAST_YEAR = "a column of this statement"

PUBLISHED_RATIOS = {
    "equity": {
        "Loan to Deposit Ratio": ("63.9%", "63.6%"), "Government Securities to Deposits": ("23.1%", "20.2%"),
        "Return on Average Equity": ("24.5%", "29.1%"), "Return on Average Assets": ("3.5%", "4.7%"),
        "Yield on Interest Earning Assets": ("11.3%", "10.5%"), "Cost of Funding": ("3.7%", "2.8%"),
        "Cost of Risk": ("7.4%", "5.3%"), "Net Interest Margin": ("7.9%", "8.0%"),
        "Net Interest Income as % of operating income": ("59.9%", "56.1%"),
        "Non-Funded Income as a % of operating income": ("40.1%", "43.9%"),
        "Cost to Income": ("58.0%", "53.2%"), "Cost to Income Without LLP": ("50.6%", "47.9%"),
        "Cost to Assets": ("4.4%", "4.3%"),
    },
    "kcb": {
        "Loan to Deposit Ratio": ("74.7%", "73.3%"), "Government Securities to Deposits": ("21.9%", "23.4%"),
        "Return on Average Equity": ("22.7%", "23.8%"), "Return on Average Assets": ("3.1%", "3.6%"),
        "Yield on Interest Earning Assets": ("12.2%", "11.3%"), "Cost of Funding": ("4.0%", "3.5%"),
        "Net Interest Spread": ("8.1%", "7.8%"), "Net Interest Margin": ("8.4%", "8.1%"),
        "Cost of Risk": ("12.2%", "9.9%"), "Net Interest Income as % of operating income": ("69.8%", "67.3%"),
        "Non-Funded Income as a % of operating income": ("30.2%", "32.7%"),
        "Cost to Income": ("58.5%", "53.6%"), "Cost to Income Without LLP": ("46.2%", "43.7%"),
    },
}
AVERAGED = {"Return on Average Equity", "Return on Average Assets", "Yield on Interest Earning Assets",
            "Cost of Funding", "Net Interest Margin", "Net Interest Spread"}


@pytest.mark.parametrize("bank", ["equity", "kcb"])
def test_acceptance_ratios(results, bank):
    rows = {r["label"]: r for r in results[bank]["balance_ratios"] + results[bank]["income_ratios"]}
    assert rows.keys() == PUBLISHED_RATIOS[bank].keys()
    for label, (prev, cur) in PUBLISHED_RATIOS[bank].items():
        assert rows[label]["current"]["display"] == cur, (bank, label)
        if label in AVERAGED:
            assert NEEDS_LAST_YEAR in rows[label]["previous"]["unavailable"], (bank, label)
            assert "unavailable" in rows[label]["change"]
        else:
            assert rows[label]["previous"]["display"] == prev, (bank, label)


def test_acceptance_points_change_equity_govt_to_deposits(results):
    row = next(r for r in results["equity"]["balance_ratios"] if r["label"] == "Government Securities to Deposits")
    assert row["change"]["display"] == "(2.8%)"   # 23.1 -> 20.2 printed, from the unrounded ratios


PUBLISHED_AMOUNTS = {
    "equity": {
        "Government Securities": ("310.4", "320.3"), "Net Loans and Advances": ("859.8", "1,007.7"),
        "Total Assets": ("1,817.0", "2,149.0"), "Customer Deposits": ("1,345.5", "1,583.9"),
        "Total Liabilities": ("1,513.8", "1,779.3"), "Shareholders' Funds": ("288.4", "350.5"),
        "Net Interest Income": ("93.6", "107.7"), "Non-Interest Income": ("62.7", "84.4"),
        "Total Operating income": ("156.3", "192.0"), "Loan Loss provision": ("(11.6)", "(10.2)"),
        "Total Operating expenses": ("(90.7)", "(102.2)"), "Profit before tax": ("65.6", "89.8"),
        "Profit after tax": ("54.1", "71.5")},
    "kcb": {
        "Government Securities": ("333.8", "410.3"), "Net Loans and Advances": ("1,139.9", "1,286.8"),
        "Total Assets": ("2,044.5", "2,359.0"), "Customer Deposits": ("1,525.8", "1,755.2"),
        "Total Liabilities": ("1,727.1", "1,992.9"), "Shareholders' Funds": ("308.5", "362.0"),
        "Net Interest Income": ("104.3", "112.9"), "Net non-Interest Income": ("45.1", "54.9"),
        "Total Operating income": ("149.4", "167.8"), "Loan Loss provision": ("18.3", "16.6"),
        "Staff Costs": ("30.9", "32.9"), "Other Operating expenses": ("38.2", "40.4"),
        "Total Operating expenses": ("87.4", "89.9"), "Profit before tax": ("62.1", "77.9"),
        "Profit after tax": ("47.3", "58.6")},
}
# Known difference: KCB's Q3'2025 operating expenses are 87,349,295 thousand, 87.3 bn; the team's
# 87.4 is the sum of its own rounded rows 18.3 + 30.9 + 38.2.
PINNED_AMOUNTS = {("kcb", "Total Operating expenses", 0): "87.3"}


@pytest.mark.parametrize("bank", ["equity", "kcb"])
def test_acceptance_amount_tables(results, bank):
    rows = {r["label"]: r for r in results[bank]["balance_sheet"] + results[bank]["income_statement"]}
    published = PUBLISHED_AMOUNTS[bank]
    assert rows.keys() - {"Deposits per Branch"} == published.keys()
    for label, pair in published.items():
        for i, col in enumerate(("previous", "current")):
            assert rows[label][col]["display"] == PINNED_AMOUNTS.get((bank, label, i), pair[i]), (bank, label, col)


def test_deposits_per_branch_needs_branch_counts(banks, results):
    row = next(r for r in results["equity"]["balance_sheet"] if r["label"] == "Deposits per Branch")
    assert "branches at 30 Sep 2026 is not in the statement and was not supplied" in row["current"]["unavailable"]
    assert "Deposits per Branch" not in [r[0] for r in TABLES["kcb"]["balance_sheet"]]
    # supplied, it is worked out (the count here is illustrative, not Equity's)
    out = bank_results(banks["equity"], S26, "equity", extra={"branches": {S26: 400, S25: 400}})
    row = next(r for r in out["balance_sheet"] if r["label"] == "Deposits per Branch")
    assert row["current"]["display"] == "4.0"


PUBLISHED_CAPITAL = {  # (Q3'25, Q3'26, minimum, excess Q3'25, excess Q3'26)
    "equity": {"Core Capital/Total Liabilities": ("19.1%", "19.8%", "8.0%", "11.1%", "11.8%"),
               "Core Capital/Total Risk Weighted Assets": ("16.6%", "18.2%", "10.5%", "6.1%", "7.7%"),
               "Total Capital/Total Risk Weighted Assets": ("18.3%", "19.5%", "14.5%", "3.8%", "5.0%"),
               "Liquidity Ratio": ("58.5%", "60.1%", "20.0%", "38.5%", "40.1%")},
    "kcb": {"Core Capital/Total Liabilities": ("18.5%", "19.0%", "8.0%", "10.5%", "11.0%"),
            "Core Capital/Total Risk Weighted Assets": ("17.0%", "18.0%", "10.5%", "6.5%", "7.5%"),
            "Total Capital/Total Risk Weighted Assets": ("19.6%", "21.1%", "14.5%", "5.1%", "6.6%"),
            "Liquidity Ratio": ("46.7%", "49.7%", "20.0%", "26.7%", "29.7%")},
}
# Known difference: the team prints Equity's Q3'2025 liquidity ratio as 58.5% (excess 38.5%), but the
# Q3'2026 release's comparative column reads 61.0% (excess 41.0%). Likely last year's published figure,
# with the comparative restated in this year's release. The tool prints the statement it was given.
PINNED_CAPITAL = {("equity", "Liquidity Ratio", 0): "61.0%", ("equity", "Liquidity Ratio", 3): "41.0%"}


@pytest.mark.parametrize("bank", ["equity", "kcb"])
def test_acceptance_capital(results, bank):
    rows = {r["label"]: r for r in results[bank]["capital"]}
    for label, published in PUBLISHED_CAPITAL[bank].items():
        got = tuple(rows[label][c]["display"] for c in ("previous", "current", "minimum", "excess_previous", "excess_current"))
        assert got == tuple(PINNED_CAPITAL.get((bank, label, i), v) for i, v in enumerate(published)), (bank, label)


COLUMNS = ["Core EPS growth", "Interest Income growth", "Interest Expense growth", "Net Interest Income growth",
           "Net Interest Margin", "Non-Funded Income growth", "NFI to Total Operating Income",
           "Fees and Commissions growth", "Deposit growth", "Government Securities growth", "Loan to Deposit Ratio",
           "Loan growth", "Return on Average Equity", "Cost of Funds", "Yield on interest-earning assets"]
PUBLISHED_ROW = {
    "equity": "32.0 8.4 (9.0) 15.1 8.0 34.6 43.9 24.3 17.7 3.2 63.6 17.2 29.1 2.8 10.5",
    "kcb": "23.9 6.2 1.7 8.2 8.1 21.8 32.7 17.4 15.0 22.9 73.3 12.9 23.8 3.5 11.3",
    "coop": "27.2 7.0 (4.4) 12.7 8.9 9.2 32.1 11.8 15.4 6.1 78.5 22.2 20.7 4.4 12.8",
}


@pytest.mark.parametrize("bank", list(PUBLISHED_ROW))
def test_acceptance_cross_bank_row(results, bank):
    row = results[bank]["cross_bank"]
    assert list(row) == COLUMNS
    assert " ".join(row[c]["display"].replace("%", "") for c in COLUMNS) == PUBLISHED_ROW[bank]


def test_alternatives_that_do_not_reproduce(banks):
    # Each tried against the published row; the default reproduces all three banks.
    ann = Settings(income_basis="annualised")
    five = Settings(average_months=(0, 3, 6, 9, 12))
    narrow_assets = Settings(earning_assets=("loans", *GOVT, "due_from_local_banks", "due_from_abroad_banks"))
    narrow_liabs = Settings(bearing_liabilities=("customer_deposits", "borrowed_funds"))
    cases = {"roe ann": ("Return on Average Equity", ann), "yield ann": ("Yield on interest-earning assets", ann),
             "nim ann": ("Net Interest Margin", ann), "cof ann": ("Cost of Funds", ann),
             "roe five": ("Return on Average Equity", five), "yield five": ("Yield on interest-earning assets", five),
             "nim five": ("Net Interest Margin", five), "cof five": ("Cost of Funds", five),
             "yield narrow": ("Yield on interest-earning assets", narrow_assets),
             "nim narrow": ("Net Interest Margin", narrow_assets), "cof narrow": ("Cost of Funds", narrow_liabs)}
    got = {b: {n: cross_bank_row(st, S26, s)[c].get("display") for n, (c, s) in cases.items()} for b, st in banks.items()}
    # published: Equity ROE 29.1 yield 10.5 NIM 8.0 CoF 2.8; KCB 23.8 11.3 8.1 3.5; Co-op 20.7 12.8 8.9 4.4
    assert got == {
        "equity": {"roe ann": "29.8%", "yield ann": "10.7%", "nim ann": "8.2%", "cof ann": "2.8%",
                   "roe five": "28.9%", "yield five": "10.3%", "nim five": "7.9%", "cof five": "2.8%",
                   "yield narrow": "12.3%", "nim narrow": "9.4%", "cof narrow": "2.8%"},
        "kcb": {"roe ann": "23.3%", "yield ann": "11.0%", "nim ann": "7.8%", "cof ann": "3.5%",
                "roe five": "23.3%", "yield five": "11.4%", "nim five": "8.1%", "cof five": "3.5%",
                "yield narrow": "12.1%", "nim narrow": "8.6%", "cof narrow": "3.6%"},
        # Co-op leaves its held-for-dealing cell blank at 31 Dec 2025, so five points are unavailable there
        "coop": {"roe ann": "21.3%", "yield ann": "12.6%", "nim ann": "8.9%", "cof ann": "4.4%",
                 "roe five": "20.9%", "yield five": None, "nim five": None, "cof five": "4.4%",
                 "yield narrow": "12.8%", "nim narrow": "9.0%", "cof narrow": "4.5%"},
    }
    assert cross_bank_row(banks["coop"], S26, five)["Net Interest Margin"]["unavailable"] == (
        "govt_securities_dealing at 31 Dec 2025 is not printed (coop, GROUP)")


def test_core_eps_from_the_printed_basic_eps(banks):
    # The printed basic EPS (owners' share) reproduces Equity's Core EPS, 13.8 then 18.2, but
    # not KCB's 14.7 then 18.3, and its growth gives Equity 31.9% against the published 32.0%.
    eps = {b: [banks[b].get(banks[b].group_entity, "eps_basic", p) for p in (S25, S26)] for b in banks}
    assert eps == {"equity": [13.81, 18.22], "kcb": [14.32, 17.8], "coop": [3.68, 4.68]}
    # KCB's PAT over its paid-up capital at an assumed KSh 1 par gives 14.7 then 18.2: the
    # first matches, the second is 18.2 against 18.3, so KCB's Core EPS levels are not reproduced.
    kcb = banks["kcb"]
    shares = {p: kcb.get(kcb.group_entity, "paid_up_capital", p) * 1000 for p in (S25, S26)}
    assert [core_eps(kcb, p, shares)["display"] for p in (S25, S26)] == ["14.7", "18.2"]


def test_every_figure_checks(results):
    def figures(node):
        if isinstance(node, dict):
            if "expr" in node:
                yield node
            else:
                for v in node.values():
                    yield from figures(v)
        elif isinstance(node, list):
            for v in node:
                yield from figures(v)
    n = 0
    for bank, out in results.items():
        for fig in figures(out):
            flags, note = check_figure_record({"id": bank, "body_md": ""}, fig)
            assert flags == [] and note == "", (bank, fig["key"], flags)
            assert all(i["origin"] == "source" and "p." in i["source"] for i in fig["inputs"].values())
            n += 1
    assert n > 150
