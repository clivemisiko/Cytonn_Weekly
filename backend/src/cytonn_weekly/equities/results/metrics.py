from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Optional

from cytonn_weekly.common.computed import ANALYST, SOURCE, a_figure, an_input, pct_change, ratio_pct
from cytonn_weekly.common.formatting import NUMBER, PCT

from .statement import Statement

GOVT = ("govt_securities_dealing", "govt_securities_amortised", "govt_securities_fvoci")
# The lists that reproduce the team's yield, NIM and cost of funds for Equity, KCB and Co-op
# alike (46.2026). Without the two "other securities" lines Equity's yield is 12.3% against 10.5%.
EARNING_ASSETS = ("loans", *GOVT, "other_securities_amortised", "other_securities_fvoci",
                  "due_from_local_banks", "due_from_abroad_banks")
BEARING_LIABILITIES = ("customer_deposits", "borrowed_funds", "due_to_local_banks", "due_to_abroad_banks")
# Shareholders' funds without non-controlling interest, wherever the bank prints it.
SHAREHOLDERS_FUNDS = "shareholders_funds"


@dataclass(frozen=True)
class Settings:
    # Averaging dates, as months before the period end: (0, 12) is the period end and a year
    # earlier; (0, 3, 6, 9, 12) the five quarter-ends.
    average_months: tuple[int, ...] = (0, 12)
    # "ttm": year to date + last full year - the same year to date a year earlier (reproduces
    # the team's ROE, ROA, yield and NIM); "annualised": year to date x 12 / months.
    income_basis: str = "ttm"
    earning_assets: tuple[str, ...] = EARNING_ASSETS
    bearing_liabilities: tuple[str, ...] = BEARING_LIABILITIES


class Unavailable(Exception):
    pass


def month_end(p: date, months_back: int) -> date:
    y, m = divmod(p.year * 12 + p.month - 1 - months_back, 12)
    return date(y, m + 1, calendar.monthrange(y, m + 1)[1])


class _Calc:
    """Builds one figure's expression and records every statement line it reads."""

    def __init__(self, st: Statement, s: Settings, extra: dict[str, dict[date, Any]]):
        self.st, self.s, self.extra = st, s, extra
        self.e = st.group_entity
        if self.e is None:
            raise Unavailable(f"the {st.bank} statement has no single group or consolidated column")
        self.inputs: dict[str, dict[str, Any]] = {}

    def line(self, key: str, p: date) -> str:
        v = self.st.values.get(self.e, {}).get(key, {}).get(p)
        if v is None or v.value is None:
            where = "is not a column of this statement" if p not in self.st.periods else "is not printed"
            raise Unavailable(f"{key} at {p:%d %b %Y} {where} ({self.st.bank}, {self.e})")
        name = f"{key}@{p.isoformat()}"
        self.inputs[name] = an_input(v.value, SOURCE,
                                     f"{self.st.bank} results p.{v.page} '{v.label}' ({self.e}, {p:%d %b %Y})")
        return name

    def given(self, name: str, p: date) -> str:
        value = self.extra.get(name, {}).get(p)
        if value is None:
            raise Unavailable(f"{name} at {p:%d %b %Y} is not in the statement and was not supplied")
        key = f"{name}@{p.isoformat()}"
        self.inputs[key] = an_input(value, ANALYST, f"{name} supplied by the analyst ({p:%d %b %Y})")
        return key

    def total(self, terms: tuple[str, ...], p: date):
        parts: list = []
        for t in terms:
            if t == SHAREHOLDERS_FUNDS:
                nci = self.st.nci_in_equity(self.e)
                parts.append(self.total(("total_equity", "-minority_interest") if nci else ("total_equity",), p))
            elif t.startswith("-"):
                parts.append(["neg", self.line(t[1:], p)])
            else:
                parts.append(self.line(t, p))
        return parts[0] if len(parts) == 1 else ["sum", *parts]

    def avg(self, terms, p: date):
        return ["mean", *(self.total(terms, month_end(p, m)) for m in self.s.average_months)]

    def year(self, terms, p: date):
        """A full year's worth of income-statement lines, which the statement prints year to date."""
        if self.s.income_basis == "annualised":
            return ["mul", self.total(terms, p), ["div", 12, p.month]]
        if self.s.income_basis != "ttm":
            raise ValueError(f"unknown income basis {self.s.income_basis!r}")
        if p.month == 12:
            return self.total(terms, p)
        return ["sub", ["add", self.total(terms, p), self.total(terms, date(p.year - 1, 12, 31))],
                self.total(terms, month_end(p, 12))]


Build = Callable[[_Calc, date], Any]


def _share(num, den) -> Build:
    return lambda c, p: ratio_pct(c.total(num, p), c.total(den, p))


def _on_average(num, den: Callable[[Settings], tuple]) -> Build:
    return lambda c, p: ratio_pct(c.year(num, p), c.avg(den(c.s), p))


# key: (label, build). Percentages; ratios of year-to-date lines need no annualising.
RATIOS: dict[str, tuple[str, Build]] = {
    "ldr": ("Loan to Deposit Ratio", _share(("loans",), ("customer_deposits",))),
    "govt_to_deposits": ("Government Securities to Deposits", _share(GOVT, ("customer_deposits",))),
    "roe": ("Return on Average Equity", _on_average(("pat",), lambda s: (SHAREHOLDERS_FUNDS,))),
    "roa": ("Return on Average Assets", _on_average(("pat",), lambda s: ("total_assets",))),
    "yield": ("Yield on Interest Earning Assets", _on_average(("total_interest_income",), lambda s: s.earning_assets)),
    "cost_of_funds": ("Cost of Funding", _on_average(("total_interest_expense",), lambda s: s.bearing_liabilities)),
    "nim": ("Net Interest Margin", _on_average(("net_interest_income",), lambda s: s.earning_assets)),
    "cost_of_risk": ("Cost of Risk", _share(("loan_loss_provision",), ("total_operating_income",))),
    "nii_share": ("Net Interest Income as % of operating income",
                  _share(("net_interest_income",), ("total_operating_income",))),
    "nfi_share": ("Non-Funded Income as a % of operating income",
                  _share(("total_non_interest_income",), ("total_operating_income",))),
    "cost_to_income": ("Cost to Income", _share(("total_opex",), ("total_operating_income",))),
    "cost_to_income_ex_llp": ("Cost to Income Without LLP",
                              _share(("total_opex", "-loan_loss_provision"), ("total_operating_income",))),
    # year to date over the period-end assets, not annualised: what reproduces Equity's 4.4, 4.3
    "cost_to_assets": ("Cost to Assets", _share(("total_opex", "-loan_loss_provision"), ("total_assets",))),
}
RATIOS["spread"] = ("Net Interest Spread",
                    lambda c, p: ["sub", RATIOS["yield"][1](c, p), RATIOS["cost_of_funds"][1](c, p)])

# (label, ratio line, its minimum statutory ratio line), read from Section III.
CAPITAL = (
    ("Core Capital/Total Liabilities", "core_to_deposits", "core_to_deposits_min"),
    ("Core Capital/Total Risk Weighted Assets", "core_to_rwa", "core_to_rwa_min"),
    ("Total Capital/Total Risk Weighted Assets", "total_to_rwa", "total_to_rwa_min"),
    ("Liquidity Ratio", "liquidity_ratio", "liquidity_min"),
)


def _growth(terms) -> Build:
    return lambda c, p: pct_change(c.total(terms, p), c.total(terms, month_end(p, 12)))


CROSS_BANK: tuple[tuple[str, Build], ...] = (
    # Core EPS growth is PAT growth (before non-controlling interest): it reproduces all three
    # banks; the printed basic EPS gives Equity 31.9% against 32.0%.
    ("Core EPS growth", _growth(("pat",))),
    ("Interest Income growth", _growth(("total_interest_income",))),
    ("Interest Expense growth", _growth(("total_interest_expense",))),
    ("Net Interest Income growth", _growth(("net_interest_income",))),
    ("Net Interest Margin", RATIOS["nim"][1]),
    ("Non-Funded Income growth", _growth(("total_non_interest_income",))),
    ("NFI to Total Operating Income", RATIOS["nfi_share"][1]),
    ("Fees and Commissions growth", _growth(("fees_on_loans", "other_fees"))),
    ("Deposit growth", _growth(("customer_deposits",))),
    ("Government Securities growth", _growth(GOVT)),
    ("Loan to Deposit Ratio", RATIOS["ldr"][1]),
    ("Loan growth", _growth(("loans",))),
    ("Return on Average Equity", RATIOS["roe"][1]),
    ("Cost of Funds", RATIOS["cost_of_funds"][1]),
    ("Yield on interest-earning assets", RATIOS["yield"][1]),
)

# The per-bank tables as the team prints them (46.2026). Amount rows: (label, signed statement
# lines summed, optional supplied divisor); "-key" subtracts a line. Ratio rows: RATIOS keys.
_COMMON_SFP = [
    ("Government Securities", GOVT, None),
    ("Net Loans and Advances", ("loans",), None),
    ("Total Assets", ("total_assets",), None),
    ("Customer Deposits", ("customer_deposits",), None),
    ("Total Liabilities", ("total_liabilities",), None),
    ("Shareholders' Funds", (SHAREHOLDERS_FUNDS,), None),
]
TABLES: dict[str, dict[str, list]] = {
    "equity": {
        "balance_sheet": _COMMON_SFP + [("Deposits per Branch", ("customer_deposits",), "branches")],
        "balance_ratios": ["ldr", "govt_to_deposits", "roe", "roa"],
        "income_statement": [
            ("Net Interest Income", ("net_interest_income",), None),
            ("Non-Interest Income", ("total_non_interest_income",), None),
            ("Total Operating income", ("total_operating_income",), None),
            # Equity prints costs as negatives; the statement prints them positive.
            ("Loan Loss provision", ("-loan_loss_provision",), None),
            ("Total Operating expenses", ("-total_opex",), None),
            ("Profit before tax", ("pbt",), None),
            ("Profit after tax", ("pat",), None),
        ],
        "income_ratios": ["yield", "cost_of_funds", "cost_of_risk", "nim", "nii_share", "nfi_share",
                          "cost_to_income", "cost_to_income_ex_llp", "cost_to_assets"],
    },
    "kcb": {
        "balance_sheet": list(_COMMON_SFP),
        "balance_ratios": ["ldr", "govt_to_deposits", "roe", "roa"],
        "income_statement": [
            ("Net Interest Income", ("net_interest_income",), None),
            ("Net non-Interest Income", ("total_non_interest_income",), None),
            ("Total Operating income", ("total_operating_income",), None),
            ("Loan Loss provision", ("loan_loss_provision",), None),
            ("Staff Costs", ("staff_costs",), None),
            ("Other Operating expenses", ("total_opex", "-loan_loss_provision", "-staff_costs"), None),
            ("Total Operating expenses", ("total_opex",), None),
            ("Profit before tax", ("pbt",), None),
            ("Profit after tax", ("pat",), None),
        ],
        "income_ratios": ["yield", "cost_of_funds", "spread", "nim", "cost_of_risk", "nii_share", "nfi_share",
                          "cost_to_income", "cost_to_income_ex_llp"],
    },
}


def _figure(st, s, extra, key, label, fmt, build: Build, p: date, second: Optional[dict] = None) -> dict:
    try:
        c = _Calc(st, s, extra)
        expr = build(c, p)
    except Unavailable as exc:
        return {"key": key, "label": label, "unavailable": str(exc)}
    fig = a_figure(key, label, fmt, 1, c.inputs, expr, in_text=False)
    if second is not None:
        fig["second"] = second
    return fig


def _amount(terms, per) -> Build:
    def build(c, p):
        bn = ["div", c.total(terms, p), 1000000]
        return ["div", bn, c.given(per, p)] if per else bn
    return build


def _row(st, s, extra, table, label, build: Build, change: Callable[[Build], Build], fmt, p) -> dict:
    prev = month_end(p, 12)
    key = f"{table}/{label}"
    return {"label": label,
            "previous": _figure(st, s, extra, f"{key}/previous", label, fmt, build, prev),
            "current": _figure(st, s, extra, f"{key}/current", label, fmt, build, p),
            "change": _figure(st, s, extra, f"{key}/change", f"{label}, change", PCT, change(build), p)}


def _pct_change_of(build: Build) -> Build:
    return lambda c, p: pct_change(build(c, p), build(c, month_end(p, 12)))


def _points_of(build: Build) -> Build:
    # the difference of the unrounded ratios, rounded once
    return lambda c, p: ["sub", build(c, p), build(c, month_end(p, 12))]


def capital_table(st: Statement, p: date, s: Settings = Settings()) -> list[dict]:
    rows = []
    for label, ratio, minimum in CAPITAL:
        line = lambda k: (lambda c, q: c.line(k, q))
        row = {"label": label,
               "minimum": _figure(st, s, {}, f"capital/{label}/minimum", f"{label}, minimum", PCT, line(minimum), p)}
        for col, q in (("previous", month_end(p, 12)), ("current", p)):
            row[col] = _figure(st, s, {}, f"capital/{label}/{col}", label, PCT, line(ratio), q)
            printed = st.get(st.group_entity, ratio.replace("_ratio", "") + "_excess", q) if st.group_entity else None
            row[f"excess_{col}"] = _figure(
                st, s, {}, f"capital/{label}/excess_{col}", f"{label}, excess", PCT,
                lambda c, q: ["sub", c.line(ratio, q), c.line(minimum, q)], q,
                second=None if printed is None else {"source": f"{st.bank} results, printed excess", "value": printed})
        rows.append(row)
    return rows


def cross_bank_row(st: Statement, p: date, s: Settings = Settings()) -> dict[str, dict]:
    return {label: _figure(st, s, {}, f"cross_bank/{label}", label, PCT, build, p) for label, build in CROSS_BANK}


def core_eps(st: Statement, p: date, shares: Optional[dict[date, Any]] = None, s: Settings = Settings()) -> dict:
    """PAT over the share count, which the statement does not print: unavailable unless supplied."""
    return _figure(st, s, {"shares": shares or {}}, "core_eps", "Core EPS", NUMBER,
                   lambda c, q: ["div", c.line("pat", q), ["div", c.given("shares", q), 1000]], p)


def bank_results(st: Statement, p: date, bank: str, s: Settings = Settings(),
                 extra: Optional[dict[str, dict[date, Any]]] = None) -> dict[str, Any]:
    """Every table for one bank at period end p, with the previous year's column. ``bank`` names
    its row set in TABLES; ``extra`` holds supplied inputs the statement lacks ({"branches": {date: n}})."""
    extra = extra or {}
    out: dict[str, Any] = {"capital": capital_table(st, p, s), "cross_bank": cross_bank_row(st, p, s)}
    rows = TABLES.get(bank)
    if rows is None:
        out["unavailable"] = f"no table row set for {bank!r}: its published tables have not been mapped"
        return out
    for table in ("balance_sheet", "income_statement"):
        out[table] = [_row(st, s, extra, table, label, _amount(terms, per), _pct_change_of, NUMBER, p)
                      for label, terms, per in rows[table]]
    for table in ("balance_ratios", "income_ratios"):
        out[table] = [_row(st, s, extra, table, RATIOS[k][0], RATIOS[k][1], _points_of, PCT, p) for k in rows[table]]
    return out
