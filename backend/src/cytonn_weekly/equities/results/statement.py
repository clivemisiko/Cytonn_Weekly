from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Union

import pdfplumber

from cytonn_weekly.common.formatting import clean_pdf_number

SOURCE_DISAGREES = "source disagrees with itself"

SECTIONS = {
    "sfp": "statement of financial position",
    "income": "statement of comprehensive income",
    "other": "other disclosures",
}

# key: (section, part, accepted spellings). A part names the total a line adds into.
# Spellings are compared after normalise(); a key listed more than once in a block is
# consumed in print order (the capital ratios repeat "minimum statutory ratio").
LINES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    # I. Statement of financial position: assets
    "cash": ("sfp", "assets", ("cash local and foreign", "cash")),
    "cbk_balances": ("sfp", "assets", ("balances due from central bank of kenya",)),
    "govt_securities_dealing": ("sfp", "assets", (
        "kenya government and other securities held for dealing purposes",)),
    "fvtpl": ("sfp", "assets", ("financial assets at fair value through profit and loss fvtpl",
                                "financial assets at fair value through profit and loss")),
    "govt_securities_amortised": ("sfp", "assets", (
        "investment securities held at amortised cost kenya government securities",)),
    "other_securities_amortised": ("sfp", "assets", (
        "investment securities held at amortised cost other securities",)),
    "govt_securities_fvoci": ("sfp", "assets", (
        "investment securities fair value through other comprehensive income fvoci kenya government securities",)),
    "other_securities_fvoci": ("sfp", "assets", (
        "investment securities fair value through other comprehensive income fvoci other securities",)),
    "due_from_local_banks": ("sfp", "assets", (
        "deposits and balances due from local banking institutions",)),
    "due_from_abroad_banks": ("sfp", "assets", (
        "deposits and balances due from banking institutions abroad",)),
    "tax_recoverable": ("sfp", "assets", ("tax recoverable",)),
    "loans": ("sfp", "assets", ("loans and advances to customers net",)),
    "due_from_group_banks": ("sfp", "assets", ("balances due from banking institutions in the group",)),
    "associates": ("sfp", "assets", ("investments in associates",)),
    "subsidiaries": ("sfp", "assets", ("investments in subsidiary companies",)),
    "joint_ventures": ("sfp", "assets", ("investment in joint ventures", "investments in joint ventures")),
    "investment_properties": ("sfp", "assets", ("investment in properties", "investment properties")),
    "ppe": ("sfp", "assets", ("property plant and equipment",)),
    "prepaid_leases": ("sfp", "assets", ("prepaid lease rentals",)),
    "intangibles": ("sfp", "assets", ("intangible assets",)),
    "deferred_tax_asset": ("sfp", "assets", ("deferred tax asset",)),
    "retirement_benefit_asset": ("sfp", "assets", ("retirement benefit asset",)),
    "other_assets": ("sfp", "assets", ("other assets",)),
    "total_assets": ("sfp", "total:assets", ("total assets",)),
    # liabilities
    "due_to_cbk": ("sfp", "liabilities", ("balances due to central bank of kenya",)),
    "customer_deposits": ("sfp", "liabilities", ("customer deposits",)),
    "due_to_local_banks": ("sfp", "liabilities", ("deposits and balances due to local banking institutions",)),
    "due_to_abroad_banks": ("sfp", "liabilities", ("deposits and balances due to banking institutions abroad",)),
    "other_money_market": ("sfp", "liabilities", ("other money market deposits",)),
    "borrowed_funds": ("sfp", "liabilities", ("borrowed funds",)),
    "due_to_group_banks": ("sfp", "liabilities", ("balances due to banking institutions in the group",)),
    "tax_payable": ("sfp", "liabilities", ("tax payable",)),
    "dividends_payable": ("sfp", "liabilities", ("dividends payable",)),
    "deferred_tax_liability": ("sfp", "liabilities", ("deferred tax liability",)),
    "retirement_benefit_liability": ("sfp", "liabilities", ("retirement benefit liability",)),
    "other_liabilities": ("sfp", "liabilities", ("other liabilities",)),
    "total_liabilities": ("sfp", "total:liabilities", ("total liabilities",)),
    # shareholders' funds
    "paid_up_capital": ("sfp", "equity", ("paid up assigned capital", "paid up capital")),
    "share_premium": ("sfp", "equity", ("share premium discount", "share premium")),
    "revaluation_reserve": ("sfp", "equity", ("revaluation reserve",)),
    "retained_earnings": ("sfp", "equity", ("retained earnings accumulated losses", "retained earnings")),
    "statutory_loan_loss_reserve": ("sfp", "equity", ("statutory loan loss reserve",)),
    "other_reserves": ("sfp", "equity", ("other reserves",)),
    "proposed_dividends": ("sfp", "equity", ("proposed dividends",)),
    "capital_grants": ("sfp", "equity", ("capital grants",)),
    "total_equity": ("sfp", "total:equity", ("total shareholders funds",)),
    "minority_interest": ("sfp", "nci", ("non controlling interest", "minority interest")),
    "total_liabilities_and_equity": ("sfp", "total:balance", ("total liabilities and shareholders funds",)),
    # II. Statement of comprehensive income
    "ii_loans": ("income", "interest_income", ("loans and advances",)),
    "ii_govt_securities": ("income", "interest_income", ("government securities",)),
    "ii_placements": ("income", "interest_income", ("deposits and placements with banking institutions",)),
    "ii_other": ("income", "interest_income", ("other interest income",)),
    "total_interest_income": ("income", "total:interest_income", ("total interest income",)),
    "ie_deposits": ("income", "interest_expense", ("customer deposits",)),
    "ie_banks": ("income", "interest_expense", ("deposits and placements from banking institutions",)),
    "ie_other": ("income", "interest_expense", ("other interest expenses", "other interest expense")),
    "total_interest_expense": ("income", "total:interest_expense", ("total interest expenses", "total interest expense")),
    "net_interest_income": ("income", "nii", ("net interest income loss", "net interest income")),
    "fees_on_loans": ("income", "non_interest_income", ("fees and commissions on loans and advances",)),
    "other_fees": ("income", "non_interest_income", ("other fees and commissions",)),
    "fx_income": ("income", "non_interest_income", ("foreign exchange trading income loss", "foreign exchange trading income")),
    "dividend_income": ("income", "non_interest_income", ("dividend income",)),
    "other_income": ("income", "non_interest_income", ("other income",)),
    "total_non_interest_income": ("income", "total:non_interest_income", ("total non interest income",)),
    "total_operating_income": ("income", "toi", ("total operating income",)),
    "loan_loss_provision": ("income", "opex", ("loan loss provision",)),
    "staff_costs": ("income", "opex", ("staff costs",)),
    "directors_emoluments": ("income", "opex", ("directors emoluments",)),
    "rental_charges": ("income", "opex", ("rentals charges", "rental charges")),
    "depreciation": ("income", "opex", ("depreciation charge on property and equipment",)),
    "amortisation": ("income", "opex", ("amortisation charges",)),
    "other_opex": ("income", "opex", ("other operating expenses",)),
    "total_opex": ("income", "total:opex", ("total other operating expenses",)),
    "pbt_before_exceptional": ("income", "pbt_exc", ("profit loss before tax and exceptional items",)),
    "exceptional_early_retirement": ("income", "exceptional", ("exceptional items early retirement costs",)),
    "share_of_associates": ("income", "exceptional", ("exceptional items share of profit of associate",)),
    "pbt": ("income", "pbt", ("profit loss before tax",)),
    "current_tax": ("income", "tax", ("current tax",)),
    "deferred_tax": ("income", "tax", ("deferred tax",)),
    "pat": ("income", "pat", ("profit loss after tax and exceptional items",)),
    "oci_fx_translation": ("income", "oci", (
        "gains losses from translating the financial statements of foreign operations",)),
    "oci_fair_value": ("income", "oci", ("fair value changes in available for sale financial assets",)),
    "oci_revaluation": ("income", "oci", ("revaluation surplus on property plant and equipment",)),
    "oci_associates": ("income", "oci", ("share of other comprehensive income of associates",)),
    "oci_tax": ("income", "oci", ("income tax relating to components of other comprehensive income",)),
    "oci_total": ("income", "total:oci", ("other comprehensive income net of tax",)),
    "total_comprehensive_income": ("income", "tci", ("total comprehensive income",)),
    "eps_basic": ("income", "per_share", ("basic earnings per share",)),
    "eps_diluted": ("income", "per_share", ("diluted earnings per share",)),
    "dps": ("income", "per_share", ("dividend per share",)),
    # III. Other disclosures
    "npl_gross": ("other", "npl", ("gross non performing loans and advances",)),
    "npl_interest_in_suspense": ("other", "npl", ("interest in suspense",)),
    "npl_net_of_suspense": ("other", "npl", ("total non performing loans and advances a b",)),
    "npl_provisions": ("other", "npl", ("loan loss provisions",)),
    "npl_net": ("other", "npl", ("net non performing loans c d",)),
    "npl_security_value": ("other", "npl", ("discounted value of securities",)),
    "npl_net_exposure": ("other", "npl", ("net npls exposure e f",)),
    "insider_directors": ("other", "insider", ("directors shareholders and associates",)),
    "insider_employees": ("other", "insider", ("employees",)),
    "insider_total": ("other", "insider", ("total insider loans advances and other facilities",)),
    "obs_lcs_guarantees": ("other", "off_balance", ("letters of credit guarantees acceptances",)),
    "obs_derivatives": ("other", "off_balance", ("forwards swaps and options",)),
    "obs_other": ("other", "off_balance", ("other contingent liabilities",)),
    "obs_total": ("other", "off_balance", ("total contingent liabilities",)),
    "core_capital": ("other", "capital", ("core capital",)),
    "min_statutory_capital": ("other", "capital", ("minimum statutory capital",)),
    "core_capital_excess": ("other", "capital", ("excess deficiency",)),
    "supplementary_capital": ("other", "capital", ("supplementary capital",)),
    "total_capital": ("other", "capital", ("total capital",)),
    "rwa": ("other", "capital", ("total risk weighted assets",)),
    "core_to_deposits": ("other", "capital", ("core capital total deposit liabilities",)),
    "core_to_deposits_min": ("other", "capital", ("minimum statutory ratio",)),
    "core_to_deposits_excess": ("other", "capital", ("excess deficiency",)),
    "core_to_rwa": ("other", "capital", ("core capital total risk weighted assets",)),
    "core_to_rwa_min": ("other", "capital", ("minimum statutory ratio",)),
    "core_to_rwa_excess": ("other", "capital", ("excess deficiency j k",)),
    "total_to_rwa": ("other", "capital", ("total capital total risk weighted assets",)),
    "total_to_rwa_min": ("other", "capital", ("minimum statutory ratio",)),
    "total_to_rwa_excess": ("other", "capital", ("excess deficiency m n",)),
    "liquidity_ratio": ("other", "liquidity", ("liquidity ratio",)),
    "liquidity_min": ("other", "liquidity", ("minimum statutory ratio",)),
    "liquidity_excess": ("other", "liquidity", ("excess deficiency a b",)),
}

# Headings of the parts of section III, normalised.
BLOCKS = {
    "non performing loans and advances": "npl",
    "insider loans and advances": "insider",
    "off balance sheet items": "off_balance",
    "capital strength": "capital",
    "liquidity": "liquidity",
}

_DATE = re.compile(r"^\d{1,2}-[A-Za-z]{3}-\d{2}$")
_FIGURE = re.compile(r"^(\(?[\d,]+(\.\d+)?\)?%?|-|–|—)$")
_LINE_NO = re.compile(r"^\s*(\d+(\.\d+)*(\.[a-z])*\.?|[a-z]\.[a-z]|[a-z]\)|[IVX]+|[A-C])(?=\s|[A-Z]|$)\s*")


class StatementRefused(ValueError):
    pass


@dataclass
class Value:
    value: Optional[Union[int, float]]  # None: the cell is blank on the page
    page: int
    label: str


@dataclass
class Statement:
    bank: str
    entities: list[str]
    periods: list[date]
    # values[entity][line key][period]
    values: dict[str, dict[str, dict[date, Value]]]
    missing: list[str]  # line keys this file does not print
    unmatched: list[str] = field(default_factory=list)  # printed rows no key accepts
    problems: list[str] = field(default_factory=list)
    flags: list[dict] = field(default_factory=list)
    unavailable: dict[str, list[str]] = field(default_factory=dict)

    def get(self, entity: str, key: str, period: date):
        v = self.values.get(entity, {}).get(key, {}).get(period)
        return None if v is None else v.value


def normalise(label: str) -> str:
    s = label.lower().replace("&", " and ").replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def _strip_line_no(text: str) -> str:
    return _LINE_NO.sub("", text, count=1)


def _number(text: str) -> Optional[Union[int, float]]:
    neg = text.startswith("(") and text.rstrip("%").endswith(")")
    v = clean_pdf_number(text.replace("(", "").replace(")", ""))
    if v is None:
        return 0  # a printed dash is nil
    v = -v if neg else v
    return int(v) if v.is_integer() and "." not in text else v


@dataclass
class _Row:
    page: int
    section: str
    block: str
    label: str
    cells: dict[int, str]  # column index -> printed figure


def _lines(page):
    # y_tolerance=1 keeps a wrapped label's lines apart; they sit 3pt from the figures.
    words = sorted(page.extract_words(y_tolerance=1), key=lambda w: (w["top"], w["x0"]))
    lines: list[list[dict]] = []
    for w in words:
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= 1:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _band(line):
    dates = [w for w in line if _DATE.match(w["text"])]
    return dates if len(dates) >= 2 else None


def _rows(pdf):
    if not any(p.chars for p in pdf.pages):
        raise StatementRefused("The PDF has no text layer (a scanned image); it cannot be read.")
    seen, section, block = set(), None, ""
    columns = None  # [(centre, period)], set by each header band
    entity_line = None
    for pno, page in enumerate(pdf.pages, start=1):
        figure_lines, label_lines = [], []
        prev, expect_units = None, False
        for line in _lines(page):
            text = normalise(" ".join(w["text"] for w in line))
            for sec, heading in SECTIONS.items():
                if heading in text:
                    section, block = sec, ""
                    seen.add(sec)
            dates = _band(line)
            if dates:
                columns = [((d["x0"] + d["x1"]) / 2, datetime.strptime(d["text"], "%d-%b-%y").date()) for d in dates]
                entity_line = prev
                yield ("band", pno, columns, entity_line, line)
                prev, expect_units = line, True
                continue
            prev = line
            if expect_units:
                expect_units = False
                if not all("000" in w["text"] for w in line if (w["x0"] + w["x1"]) / 2 > columns[0][0] - 20):
                    raise StatementRefused(
                        f"Page {pno}: the line under the dates does not give every column in thousands (KSHS.'000).")
                continue
            if columns is None or section is None:
                continue
            spacing = (columns[-1][0] - columns[0][0]) / (len(columns) - 1)
            edge = columns[0][0] - spacing / 2
            labels = [w for w in line if (w["x0"] + w["x1"]) / 2 < edge]
            figs = [w for w in line if (w["x0"] + w["x1"]) / 2 >= edge]
            if not all(_FIGURE.match(w["text"]) for w in figs):
                continue  # prose or a header line across the columns, not a table row
            label = " ".join(w["text"] for w in labels)
            if figs:
                cells: dict[int, str] = {}
                for w in figs:
                    c = (w["x0"] + w["x1"]) / 2
                    i = min(range(len(columns)), key=lambda k: abs(columns[k][0] - c))
                    if abs(columns[i][0] - c) > spacing / 2 or i in cells:
                        yield ("problem", f"page {pno}: figure {w['text']!r} at x {c:.0f} has no column of its own")
                        continue
                    cells[i] = w["text"]
                figure_lines.append([line[0]["top"], [label], cells, section, block])
            elif label and normalise(label) != "less":
                if _LINE_NO.match(label) and normalise(_strip_line_no(label)) in BLOCKS:
                    block = BLOCKS[normalise(_strip_line_no(label))]
                elif not _LINE_NO.match(label):
                    label_lines.append((line[0]["top"], label))
                else:
                    block = normalise(_strip_line_no(label))
        # Some cells are printed a few points off their row's line: fold a line with
        # under half the columns into the full row nearest it.
        full = [f for f in figure_lines if 2 * len(f[2]) >= len(columns or [0])]
        for f in [f for f in figure_lines if f not in full]:
            near = min(full, key=lambda g: abs(g[0] - f[0]), default=None)
            if near and abs(near[0] - f[0]) <= 4 and not set(near[2]) & set(f[2]):
                near[2].update(f[2])
                if f[1][0]:
                    near[1].append((f[0], f[1][0]))
                figure_lines.remove(f)
        # A wrapped label's lines sit just above and below its figures.
        for top, label in label_lines:
            near = min(figure_lines, key=lambda f: abs(f[0] - top), default=None)
            if near and abs(near[0] - top) <= 8:
                near[1].append((top, label))
        for top, parts, cells, sec, blk in figure_lines:
            own, extra = parts[0], parts[1:]
            ordered = sorted(extra + [(top, own)], key=lambda p: p[0])
            text = " ".join(_strip_line_no(t) for _, t in ordered).strip()
            yield ("row", _Row(pno, sec, blk, text, cells))
    missing = [h for s, h in SECTIONS.items() if s not in seen]
    if missing:
        raise StatementRefused(
            "Not the CBK 'Financial Statements and Other Disclosures' layout: "
            "no heading " + ", ".join(repr(h.upper()) for h in missing) + ".")


def _entities(entity_line, columns):
    # Column groups restart at the first period; each entity name sits over its group.
    first = columns[0][1]
    starts = [i for i, (_, p) in enumerate(columns) if p == first]
    groups = [list(range(s, e)) for s, e in zip(starts, starts[1:] + [len(columns)])]
    names = [[] for _ in groups]
    for w in entity_line or []:
        c = (w["x0"] + w["x1"]) / 2
        for gi, g in enumerate(groups):
            spacing = (columns[-1][0] - columns[0][0]) / (len(columns) - 1)
            if columns[g[0]][0] - spacing / 2 <= c <= columns[g[-1]][0] + spacing / 2:
                names[gi].append(w["text"])
    return [" ".join(n) for n in names], groups


def read_statement(path: Union[str, Path], bank: str) -> Statement:
    with pdfplumber.open(str(path)) as pdf:
        events = list(_rows(pdf))
    problems = [e[1] for e in events if e[0] == "problem"]
    bands = [e for e in events if e[0] == "band"]
    if not bands:
        raise StatementRefused("No row of period dates (e.g. 30-Sep-26) was found over the figures.")
    entities, periods, groups = None, None, None
    values: dict[str, dict[str, dict[date, Value]]] = {}
    unmatched: list[str] = []
    found: set[str] = set()
    used: dict[tuple, set] = {}
    for e in events:
        if e[0] == "band":
            _, pno, columns, entity_line, _ = e
            names, grp = _entities(entity_line, columns)
            per = [columns[i][1] for i in grp[0]]
            if any([columns[i][1] for i in g] != per for g in grp) or any(not n for n in names):
                raise StatementRefused(f"Page {pno}: the column headers do not repeat the same dates under each entity name.")
            if entities is None:
                entities, periods = names, per
                values = {n: {} for n in names}
            elif names != entities or per != periods:
                raise StatementRefused(f"Page {pno}: the entities or dates differ from the first page's.")
            groups = grp
            continue
        if e[0] != "row":
            continue
        row: _Row = e[1]
        key = _match(row, used)
        if key is None:
            if row.label:
                unmatched.append(f"page {row.page}: {row.label}")
            continue
        found.add(key)
        for gi, name in enumerate(entities):
            for pi, col in enumerate(groups[gi]):
                text = row.cells.get(col)
                values[name].setdefault(key, {})[periods[pi]] = Value(
                    None if text is None else _number(text), row.page, row.label)
    missing = [k for k in LINES if k not in found]
    st = Statement(bank, entities, periods, values, missing, unmatched, problems)
    check(st)
    return st


def _match(row: _Row, used: dict) -> Optional[str]:
    label = normalise(row.label)
    for key, (sec, _, spellings) in LINES.items():
        if sec != row.section or label not in spellings:
            continue
        if sec == "other" and LINES[key][1] != row.block:
            continue
        taken = used.setdefault((sec, row.block), set())
        if key in taken:
            continue
        taken.add(key)
        return key
    return None


# (total line, part whose lines add up to it)
_SUMS = [
    ("total_assets", "assets"),
    ("total_liabilities", "liabilities"),
    ("total_equity", "equity"),
    ("total_interest_income", "interest_income"),
    ("total_interest_expense", "interest_expense"),
    ("total_non_interest_income", "non_interest_income"),
    ("total_opex", "opex"),
]
_BALANCE = "total assets = total liabilities + shareholders' funds + non-controlling interest"


def check(st: Statement) -> list[dict]:
    """Every total against its own lines, exact on the printed integers, for every
    entity and period. Sets st.flags and st.unavailable and returns the flags."""
    st.flags, st.unavailable = [], {}
    for entity in st.entities:
        for p in st.periods:
            def g(key):
                return st.get(entity, key, p)

            def part(name):
                return [g(k) for k, (_, prt, _) in LINES.items() if prt == name]

            def add(*vals):
                return None if any(v is None for v in vals) else sum(vals)

            tests = [(f"{part_name} lines add up to the total", total, sum(v for v in part(part_name) if v is not None))
                     for total, part_name in _SUMS]
            nci = g("minority_interest") or 0  # blank or dash: no non-controlling interest
            tests += [
                (_BALANCE, "total_assets", add(g("total_liabilities"), g("total_equity"), nci)),
                ("printed total liabilities and shareholders' funds", "total_liabilities_and_equity",
                 add(g("total_liabilities"), g("total_equity"), nci)),
                ("net interest income = interest income - interest expense", "net_interest_income",
                 add(g("total_interest_income"), None if g("total_interest_expense") is None else -g("total_interest_expense"))),
                ("total operating income = net interest income + non-interest income", "total_operating_income",
                 add(g("net_interest_income"), g("total_non_interest_income"))),
                ("profit before exceptional items = operating income - operating expenses", "pbt_before_exceptional",
                 add(g("total_operating_income"), None if g("total_opex") is None else -g("total_opex"))),
                ("profit before tax = profit before exceptional items + exceptional items", "pbt",
                 add(g("pbt_before_exceptional"), sum(v for v in part("exceptional") if v is not None))),
                ("profit after tax = profit before tax - current tax - deferred tax", "pat",
                 add(g("pbt"), -sum(v for v in part("tax") if v is not None))),
            ]
            for name, key, computed in tests:
                printed = g(key)
                if printed == computed and printed is not None:
                    continue
                v = st.values.get(entity, {}).get(key, {}).get(p)
                st.flags.append({
                    "kind": SOURCE_DISAGREES if printed is not None and computed is not None else "cannot check",
                    "entity": entity, "period": p, "check": name, "line": key,
                    "label": v.label if v else None, "page": v.page if v else None,
                    "printed": printed, "computed": computed,
                })
                if name == _BALANCE:
                    st.unavailable.setdefault(entity, []).append(
                        f"{p:%d %b %Y}: total assets {printed} against liabilities and shareholders' funds {computed}")
    return st.flags
