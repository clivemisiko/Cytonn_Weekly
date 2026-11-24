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
# Every "excess" line accepts every printed form; their print order in the block tells them apart.
_EXCESS = ("excess deficiency", "excess deficiency a b", "excess deficiency g h", "excess deficiency j k",
           "excess deficiency m n", "excess", "excess a b", "excess j k", "excess m n")

LINES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    # I. Statement of financial position: assets
    "cash": ("sfp", "assets", ("cash local and foreign", "cash both local and foreign", "cash")),
    "cbk_balances": ("sfp", "assets", ("balances due from central bank of kenya",)),
    "govt_securities_dealing": ("sfp", "assets", (
        "kenya government and other securities held for dealing purposes",)),
    "fvtpl": ("sfp", "assets", ("financial assets at fair value through profit and loss fvtpl",
                                "financial assets at fair value through profit and loss",
                                "financial assets at fair value through profit or loss")),
    # subtotals some banks print over the four lines below
    "investment_securities": ("sfp", "subtotal", ("investment securities",)),
    "amortised_cost_securities": ("sfp", "subtotal", ("amortised cost",)),
    "govt_securities_amortised": ("sfp", "assets", (
        "investment securities held at amortised cost kenya government securities", "kenya government securities")),
    "other_securities_amortised": ("sfp", "assets", (
        "investment securities held at amortised cost other securities", "other securities")),
    "fvoci_securities": ("sfp", "subtotal", ("fair value through other comprehensive income fvoci",)),
    "govt_securities_fvoci": ("sfp", "assets", (
        "investment securities fair value through other comprehensive income fvoci kenya government securities",
        "kenya government securities")),
    "other_securities_fvoci": ("sfp", "assets", (
        "investment securities fair value through other comprehensive income fvoci other securities", "other securities")),
    "due_from_local_banks": ("sfp", "assets", (
        "deposits and balances due from local banking institutions",)),
    "due_from_abroad_banks": ("sfp", "assets", (
        "deposits and balances due from banking institutions abroad",)),
    "tax_recoverable": ("sfp", "assets", ("tax recoverable",)),
    "loans": ("sfp", "assets", ("loans and advances to customers net",)),
    "due_from_group_banks": ("sfp", "assets", ("balances due from banking institutions in the group",
                                                     "balances due from group companies")),
    "associates": ("sfp", "assets", ("investments in associates",)),
    "subsidiaries": ("sfp", "assets", ("investments in subsidiary companies",)),
    "joint_ventures": ("sfp", "assets", ("investment in joint ventures", "investments in joint ventures")),
    "investment_properties": ("sfp", "assets", ("investment in properties", "investment properties")),
    "ppe": ("sfp", "assets", ("property plant and equipment", "property and equipment")),
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
    "due_to_abroad_banks": ("sfp", "liabilities", ("deposits and balances due to banking institutions abroad",
                                                         "deposits and balances due to foreign banking institutions")),
    "other_money_market": ("sfp", "liabilities", ("other money market deposits",)),
    "borrowed_funds": ("sfp", "liabilities", ("borrowed funds",)),
    "due_to_group_banks": ("sfp", "liabilities", ("balances due to banking institutions in the group",
                                                   "balances due to group companies")),
    "tax_payable": ("sfp", "liabilities", ("tax payable",)),
    "dividends_payable": ("sfp", "liabilities", ("dividends payable",)),
    "deferred_tax_liability": ("sfp", "liabilities", ("deferred tax liability",)),
    "retirement_benefit_liability": ("sfp", "liabilities", ("retirement benefit liability",)),
    "other_liabilities": ("sfp", "liabilities", ("other liabilities",)),
    "total_liabilities": ("sfp", "total:liabilities", ("total liabilities",)),
    # shareholders' funds
    "paid_up_capital": ("sfp", "equity", ("paid up assigned capital", "paid up capital")),
    "share_premium": ("sfp", "equity", ("share premium discount", "share premium")),
    "revaluation_reserve": ("sfp", "equity", ("revaluation reserve", "revaluation reserves")),
    "retained_earnings": ("sfp", "equity", ("retained earnings accumulated losses", "retained earnings")),
    "statutory_loan_loss_reserve": ("sfp", "equity", ("statutory loan loss reserve",)),
    "other_reserves": ("sfp", "equity", ("other reserves",
                                         "other reserves re measurement of defined benefit asset liabiliy")),
    "proposed_dividends": ("sfp", "equity", ("proposed dividends",)),
    "capital_grants": ("sfp", "equity", ("capital grants",)),
    "total_equity": ("sfp", "total:equity", ("total shareholders funds", "total share holders funds")),
    # Counted in total shareholders' funds when printed above that total (see check()).
    "minority_interest": ("sfp", "nci", ("non controlling interest", "non controlling interests", "minority interest")),
    "total_liabilities_and_equity": ("sfp", "total:balance", ("total liabilities and shareholders funds",)),
    # II. Statement of comprehensive income
    "ii_loans": ("income", "interest_income", ("loans and advances",)),
    "ii_govt_securities": ("income", "interest_income", ("government securities",)),
    "ii_placements": ("income", "interest_income", ("deposits and placements with banking institutions",)),
    "ii_other": ("income", "interest_income", ("other interest income",)),
    "total_interest_income": ("income", "total:interest_income", ("total interest income", "t otal interest income")),
    "ie_deposits": ("income", "interest_expense", ("customer deposits",)),
    "ie_banks": ("income", "interest_expense", ("deposits and placements from banking institutions",
                                                            "deposits and placement from banking institutions")),
    "ie_other": ("income", "interest_expense", ("other interest expenses", "other interest expense")),
    "total_interest_expense": ("income", "total:interest_expense", ("total interest expenses", "total interest expense")),
    "net_interest_income": ("income", "nii", ("net interest income loss", "net interest income")),
    "fees_on_loans": ("income", "non_interest_income", ("fees and commissions on loans and advances",
                                                                  "fees and commissions income on loans and advances")),
    "other_fees": ("income", "non_interest_income", ("other fees and commissions", "other fees and commissions income")),
    "fx_income": ("income", "non_interest_income", ("foreign exchange trading income loss", "foreign exchange trading income")),
    "dividend_income": ("income", "non_interest_income", ("dividend income",)),
    "other_income": ("income", "non_interest_income", ("other income",)),
    "total_non_interest_income": ("income", "total:non_interest_income", ("total non interest income", "total other operating income")),
    "total_operating_income": ("income", "toi", ("total operating income",)),
    "loan_loss_provision": ("income", "opex", ("loan loss provision",)),
    "staff_costs": ("income", "opex", ("staff costs",)),
    "directors_emoluments": ("income", "opex", ("directors emoluments",)),
    "rental_charges": ("income", "opex", ("rentals charges", "rental charges")),
    "depreciation": ("income", "opex", ("depreciation charge on property and equipment",
                                                  "depreciation on property and equipment")),
    "amortisation": ("income", "opex", ("amortisation charges",)),
    "other_opex": ("income", "opex", ("other operating expenses",)),
    "total_opex": ("income", "total:opex", ("total other operating expenses", "total operating expenses")),
    "pbt_before_exceptional": ("income", "pbt_exc", ("profit loss before tax and exceptional items",)),
    "exceptional_items": ("income", "exceptional", ("exceptional items",)),
    "exceptional_early_retirement": ("income", "exceptional", ("exceptional items early retirement costs",)),
    "share_of_associates": ("income", "exceptional", ("exceptional items share of profit of associate",)),
    "pbt": ("income", "pbt", ("profit loss before tax", "profit loss after exceptional items")),
    "current_tax": ("income", "tax", ("current tax",)),
    "deferred_tax": ("income", "tax", ("deferred tax",)),
    "pat": ("income", "pat", ("profit loss after tax and exceptional items",)),
    "pat_nci": ("income", "attribution", ("minority interest", "non controlling interest")),
    "pat_owners": ("income", "attribution", ("profit loss after tax and exceptional items and minority interest",)),
    "oci_fx_translation": ("income", "oci", (
        "gains losses from translating the financial statements of foreign operations",)),
    "oci_fair_value": ("income", "oci", ("fair value changes in available for sale financial assets",
                                             "fair value changes in fvoci",
                                             "gain loss from fair value re measurement of financial assets through other comprehensive income")),
    "oci_remeasurement": ("income", "oci", ("remeasurement of defined benefit obligation",
                                            "re measurement of defined benefit pension fund")),
    "oci_revaluation": ("income", "oci", ("revaluation surplus on property plant and equipment",)),
    "oci_associates": ("income", "oci", ("share of other comprehensive income of associates",)),
    "oci_tax": ("income", "oci", ("income tax relating to components of other comprehensive income",)),
    "oci_total": ("income", "total:oci", ("other comprehensive income net of tax", "for the year net of tax",
                                           "other comprehensive income for the year net of tax")),
    "total_comprehensive_income": ("income", "tci", ("total comprehensive income", "total comprehensive income for the year")),
    "eps_basic": ("income", "per_share", ("basic earnings per share", "earnings per share basic and diluted",
                                          "earnings per share diluted and basic kshs")),
    "eps_diluted": ("income", "per_share", ("diluted earnings per share",)),
    "dps": ("income", "per_share", ("dividend per share", "dividend per share declared", "dividend per share declared kshs")),
    # III. Other disclosures
    "npl_gross": ("other", "npl", ("gross non performing loans and advances",)),
    "npl_interest_in_suspense": ("other", "npl", ("interest in suspense", "less interest in suspense")),
    "npl_net_of_suspense": ("other", "npl", ("total non performing loans and advances a b",)),
    "npl_provisions": ("other", "npl", ("loan loss provisions", "less loan loss provision")),
    "npl_net": ("other", "npl", ("net non performing loans c d", "net non performing loans and advances c d")),
    "npl_security_value": ("other", "npl", ("discounted value of securities",)),
    "npl_net_exposure": ("other", "npl", ("net npls exposure e f",)),
    "insider_directors": ("other", "insider", ("directors shareholders and associates",)),
    "insider_employees": ("other", "insider", ("employees",)),
    "insider_total": ("other", "insider", ("total insider loans advances and other facilities",
                                                         "total insider loans and advances and other facilities")),
    "obs_lcs_guarantees": ("other", "off_balance", ("letters of credit guarantees acceptances",
                                                         "letter of credit guarantees and acceptances")),
    "obs_derivatives": ("other", "off_balance", ("forwards swaps and options",)),
    "obs_other": ("other", "off_balance", ("other contingent liabilities",)),
    "obs_total": ("other", "off_balance", ("total contingent liabilities",)),
    "core_capital": ("other", "capital", ("core capital",)),
    "min_statutory_capital": ("other", "capital", ("minimum statutory capital",)),
    "core_capital_excess": ("other", "capital", _EXCESS),
    "supplementary_capital": ("other", "capital", ("supplementary capital",)),
    "total_capital": ("other", "capital", ("total capital", "total capital a d")),
    "rwa": ("other", "capital", ("total risk weighted assets",)),
    "core_to_deposits": ("other", "capital", ("core capital total deposit liabilities", "core capital total deposits liabilities")),
    "core_to_deposits_min": ("other", "capital", ("minimum statutory ratio",)),
    "core_to_deposits_excess": ("other", "capital", _EXCESS),
    "core_to_rwa": ("other", "capital", ("core capital total risk weighted assets",)),
    "core_to_rwa_min": ("other", "capital", ("minimum statutory ratio",)),
    "core_to_rwa_excess": ("other", "capital", _EXCESS),
    "total_to_rwa": ("other", "capital", ("total capital total risk weighted assets",)),
    "total_to_rwa_min": ("other", "capital", ("minimum statutory ratio",)),
    "total_to_rwa_excess": ("other", "capital", _EXCESS),
    "liquidity_ratio": ("other", "liquidity", ("liquidity ratio",)),
    "liquidity_min": ("other", "liquidity", ("minimum statutory ratio",)),
    "liquidity_excess": ("other", "liquidity", _EXCESS),
}

# Block headings, normalised: (section the heading belongs to, block). A heading is
# recognised when the recent lines without figures end with it, so it may wrap.
BLOCKS = {
    "assets": ("sfp", "assets"),
    "liabilities": ("sfp", "liabilities"),
    "shareholders funds": ("sfp", "equity"),
    "interest income": ("income", "interest_income"),
    "interest expense": ("income", "interest_expense"),
    "interest expenses": ("income", "interest_expense"),
    "non interest income": ("income", "non_interest_income"),
    "other operating income": ("income", "non_interest_income"),
    "operating expenses": ("income", "opex"),
    "non performing loans and advances": ("other", "npl"),
    "insider loans and advances": ("other", "insider"),
    "off balance sheet items": ("other", "off_balance"),
    "capital strength": ("other", "capital"),
    "ratios": ("other", "capital"),
    "liquidity": ("other", "liquidity"),
}

_DATE = re.compile(r"^\d{1,2}-[A-Za-z]{3}-\d{2}$")
_FIGURE = re.compile(r"^(\(?[\d,]+(\.\d+)?\)?%?|-|–|—)$")
# A printed line number: "5.a.a", "a.b", "a)", "a.", "2)", "43.1", "21TOTAL", or a
# roman or capital heading letter standing alone ("II", "A.").
_LINE_NO = re.compile(
    r"^\s*(?:(?:\d+(?:\.\d+)*(?:\.[a-z])*\.?|\d+\)|[a-z]\.[a-z]|[a-z][.)])(?=\s|[A-Z]|$)"
    r"|(?:[IVX]+|[A-C])\.?(?=\s|$))\s*")


class StatementRefused(ValueError):
    pass


@dataclass
class Value:
    value: Optional[Union[int, float]]  # None: the cell is blank on the page
    page: int
    label: str
    order: int = 0  # the row's place in print order


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
    # entities with at least one printed cell, for each section ("sfp", "income") and
    # each part of section III ("other:npl", "other:capital", ...)
    block_entities: dict[str, list[str]] = field(default_factory=dict)

    @property
    def group_entity(self) -> Optional[str]:
        """The consolidated column, the one the team's tables print: the entity whose
        name ends with GROUP or CONSOLIDATED. None unless exactly one does."""
        found = [e for e in self.entities if e.split()[-1] in ("GROUP", "CONSOLIDATED")]
        return found[0] if len(found) == 1 else None

    def nci_in_equity(self, entity: str) -> bool:
        """Whether total shareholders' funds includes non-controlling interest: it does
        when the bank prints that line above the total (Equity), not below it (KCB, Co-op)."""
        nci, total = self.values[entity].get("minority_interest"), self.values[entity].get("total_equity")
        if not nci or not total:
            return False
        return next(iter(nci.values())).order < next(iter(total.values())).order

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


_TITLE = re.compile(r"(statements and )?other disclosures for the (period|year|quarter)|statements and other disclosures")
_HEADING_LETTER = re.compile(r"^[A-C][A-Z]")  # "AASSETS", "BLIABILITIES": a glued heading letter
_MONTH = re.compile(r"^(jan|feb|mar|apr|may|jun|june|jul|july|aug|sep|sept|oct|nov|dec)$", re.I)
_CONNECTOR = {"and", "or", "of", "from", "to", "through", "in", "on", "the", "with", "for", "other", "due"}


def _lines(page):
    # A word within 2.6pt of the one before it shares its line: one row's words drift
    # by up to 2.8pt in all, while a wrapped label's lines sit 3pt or more apart.
    words = sorted((p for w in page.extract_words(y_tolerance=1, return_chars=True) for p in _split_glued(w)),
                   key=lambda w: (w["top"], w["x0"]))
    lines: list[list[dict]] = []
    for w in words:
        if lines and w["top"] - lines[-1][-1]["top"] <= 2.6:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


_ONE_FIGURE = re.compile(r"\(?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?%?")


def _split_glued(word):
    """Figures printed too close together come out as one word ("2,036,547,1321,970,
    992,243"). In thousands format the split is forced: after a three-digit group the
    next number starts where a digit, not a comma, follows. Each piece keeps its own
    characters' positions."""
    text = word["text"]
    if "," not in text or _ONE_FIGURE.fullmatch(text) or not re.fullmatch(r"[\d,.()%]+", text):
        return [word]
    pieces, i = [], 0
    while i < len(text):
        m = _ONE_FIGURE.match(text, i)
        if not m:
            return [word]
        pieces.append((m.start(), m.end()))
        i = m.end()
    chars = word["chars"]
    if len(pieces) < 2 or len(chars) != len(text):
        return [word]
    return [{**word, "text": text[a:b], "x0": chars[a]["x0"], "x1": chars[b - 1]["x1"]} for a, b in pieces]


def _centre(w):
    return (w["x0"] + w["x1"]) / 2


def _band(line, below):
    """Column centres and dates from a header line: one token per date (30-Sep-26,
    possibly kerned apart) or day and month above a line of years. Returns
    (columns, extra lines used) or None."""
    words: list[dict] = []
    for w in line:  # glue a kerned date back together: "3" "0-Sep-26"
        if words and w["x0"] - words[-1]["x1"] < 2 and _DATE.match(words[-1]["text"] + w["text"]):
            words[-1] = {**w, "x0": words[-1]["x0"], "text": words[-1]["text"] + w["text"]}
        else:
            words.append(w)
    dates = [w for w in words if _DATE.match(w["text"])]
    if len(dates) >= 2:
        return [(_centre(d), datetime.strptime(d["text"], "%d-%b-%y").date()) for d in dates], 0
    pairs = [(a, b) for a, b in zip(words, words[1:])
             if a["text"].isdigit() and len(a["text"]) <= 2 and _MONTH.match(b["text"]) and b["x0"] - a["x1"] < 6]
    years = [w for w in below or [] if re.fullmatch(r"\d{4}", w["text"])]
    if len(pairs) < 2 or len(years) != len(pairs):
        return None
    columns = []
    for a, b in pairs:
        y = min(years, key=lambda y: abs(_centre(y) - (a["x0"] + b["x1"]) / 2))
        x0, x1 = min(a["x0"], y["x0"]), max(b["x1"], y["x1"])
        d = datetime.strptime(f'{a["text"]} {b["text"][:3]} {y["text"]}', "%d %b %Y").date()
        columns.append(((x0 + x1) / 2, d))
    return columns, 1


def _heading_text(line, columns=None):
    if columns:  # a header line: only the words left of the columns
        edge = columns[0][0] - (columns[-1][0] - columns[0][0]) / (len(columns) - 1) / 2
        line = [w for w in line if _centre(w) < edge]
    text = normalise(_strip_line_no(" ".join(w["text"] for w in line)))
    return " ".join(t for t in text.split() if not t.isdigit())


def _rows(pdf):
    if not any(p.chars for p in pdf.pages):
        raise StatementRefused("The PDF has no text layer (a scanned image); it cannot be read.")
    seen, section, block = set(), None, ""
    columns = None  # [(centre, period)], set by each header band
    for pno, page in enumerate(pdf.pages, start=1):
        lines = _lines(page)
        figure_rows: list[dict] = []
        label_lines: list[dict] = []
        window: list[tuple[str, Optional[dict], bool]] = []  # recent lines without figures, numbered?
        units_due = 0
        i = 0
        while i < len(lines):
            line = lines[i]
            prev = lines[i - 1] if i else None
            i += 1
            band = _band(line, lines[i] if i < len(lines) else None)
            if band:
                columns, extra = band
                header = line + (lines[i] if extra else [])
                i += extra
                yield ("band", pno, columns, prev)
                window.append((_heading_text(header, columns), None, False))
                units_due = 3
            elif units_due:
                spacing = (columns[-1][0] - columns[0][0]) / (len(columns) - 1)
                zone = " ".join(w["text"] for w in line if _centre(w) > columns[0][0] - spacing / 2)
                window.append((_heading_text(line, columns), None, False))
                if zone.count("000") >= len(columns):
                    units_due = 0
                else:
                    units_due -= 1
                    if not units_due:
                        raise StatementRefused(
                            f"Page {pno}: no line under the dates gives every column in thousands ('000).")
            elif columns is not None:
                spacing = (columns[-1][0] - columns[0][0]) / (len(columns) - 1)
                edge = columns[0][0] - spacing / 2
                labels = [w for w in line if _centre(w) < edge]
                figs = [w for w in line if _centre(w) >= edge]
                label = " ".join(w["text"] for w in labels)
                if figs and all(_FIGURE.match(w["text"]) for w in figs):
                    window = []
                    if section is None:
                        continue
                    cells: dict[int, str] = {}
                    for w in figs:
                        c = _centre(w)
                        k = min(range(len(columns)), key=lambda k: abs(columns[k][0] - c))
                        if abs(columns[k][0] - c) > spacing / 2 or k in cells:
                            yield ("problem", f"page {pno}: figure {w['text']!r} at x {c:.0f} has no column of its own")
                            continue
                        cells[k] = w["text"]
                    figure_rows.append({"top": line[0]["top"], "parts": [(line[0]["top"], label)],
                                        "cells": cells, "section": section, "block": block})
                    continue
                if figs:
                    continue  # prose across the columns, not a table row
                ref = None
                numbered = bool(_LINE_NO.match(label) or _HEADING_LETTER.match(label))
                # A line ending with ":" is a heading's, never a row's.
                if label and normalise(label) != "less" and not _LINE_NO.match(label) and not (
                        label.endswith(":") and not label[:1].islower()):
                    ref = {"top": line[0]["top"], "text": label}
                    label_lines.append(ref)
                if not label[:1].islower():  # a heading never starts in lower case
                    window.append((_heading_text(line), ref, numbered))
                if not ref and label and _LINE_NO.match(label) and section:
                    block = normalise(_strip_line_no(label))
            else:
                window.append((_heading_text(line), None, False))
            window = window[-4:]
            # The CBK title "Financial Statements and Other Disclosures" heads every page.
            joined = _TITLE.sub("", " ".join(t for t, _, _ in window if t)).strip()
            hit = next((sec for sec, h in SECTIONS.items() if h in joined), None)
            if hit:
                section, block = hit, ""
                seen.add(hit)
            # A block heading is numbered on one of its lines; the longest match wins.
            blk = next((b for h, (sec, b) in sorted(BLOCKS.items(), key=lambda kv: -len(kv[0]))
                        if sec == section and joined.endswith(h)), None) if any(n for *_, n in window) else None
            if blk:
                block = blk
            if hit or blk:
                # the heading's own lines are the shortest run at the end that holds it
                h = SECTIONS[hit] if hit else next(h for h, (_, b) in BLOCKS.items() if b == blk and joined.endswith(h))
                k = len(window) - 1
                while k > 0 and h not in _TITLE.sub("", " ".join(t for t, _, _ in window[k:] if t)):
                    k -= 1
                for _, ref, _ in window[k:]:
                    if ref in label_lines:
                        label_lines.remove(ref)
                window = []
        # A cell printed a little off its row's line: fold the smaller line into the
        # nearest line within 4pt whose cells it does not overlap.
        for f in sorted(figure_rows, key=lambda f: len(f["cells"])):
            near = [g for g in figure_rows if g is not f and abs(g["top"] - f["top"]) <= 4
                    and not set(g["cells"]) & set(f["cells"])]
            if near:
                g = min(near, key=lambda g: (abs(g["top"] - f["top"]), -len(g["cells"])))
                g["cells"].update(f["cells"])
                g["parts"] += f["parts"]
                figure_rows.remove(f)
        # A wrapped label line joins the row it continues: a line starting in lower
        # case or with a connecting word, or under a row whose own label ends with
        # one, continues the row above; one ending with a connecting word the row
        # below; any other the nearer, taking the row above unless the one below is
        # 2pt nearer (some banks wrap downward, 7pt under the row).
        last = None  # (top, row) of the previous label line placed
        for ref in sorted(label_lines, key=lambda r: r["top"]):
            words = normalise(ref["text"]).split()
            up = max((f for f in figure_rows if 0 < ref["top"] - f["top"] <= 12), key=lambda f: f["top"], default=None)
            down = min((f for f in figure_rows if 0 < f["top"] - ref["top"] <= 12), key=lambda f: f["top"], default=None)
            up_words = normalise(up["parts"][0][1]).split() if up else []
            if ref["text"][:1].islower() or (words and words[0] in _CONNECTOR) or (
                    up_words and up_words[-1] in _CONNECTOR):
                # a run of continuation lines follows the line above it
                target = last[1] if last and ref["top"] - last[0] <= 8 and (not up or last[0] > up["top"]) else up
            elif words and words[-1] in _CONNECTOR:
                target = down
            elif up and down:
                target = up if ref["top"] - up["top"] <= down["top"] - ref["top"] + 2 else down
            else:
                target = up or down
            if target:
                target["parts"].append((ref["top"], ref["text"]))
                last = (ref["top"], target)
        for f in figure_rows:
            text = " ".join(_strip_line_no(t) for _, t in sorted(f["parts"], key=lambda p: p[0]) if t).strip()
            yield ("row", _Row(pno, f["section"], f["block"], text, f["cells"]))
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
    blocks: dict[str, set] = {}
    order = 0
    for e in events:
        if e[0] == "band":
            _, pno, columns, entity_line = e
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
        order += 1
        block = row.section if row.section != "other" else f"other:{LINES[key][1]}"
        for gi, name in enumerate(entities):
            for pi, col in enumerate(groups[gi]):
                text = row.cells.get(col)
                values[name].setdefault(key, {})[periods[pi]] = Value(
                    None if text is None else _number(text), row.page, row.label, order)
                if text is not None:
                    blocks.setdefault(block, set()).add(name)
    missing = [k for k in LINES if k not in found]
    st = Statement(bank, entities, periods, values, missing, unmatched, problems,
                   block_entities={b: [e for e in entities if e in n] for b, n in blocks.items()})
    check(st)
    return st


def _match(row: _Row, used: dict) -> Optional[str]:
    label = normalise(row.label)
    for key, (sec, _, spellings) in LINES.items():
        if sec != row.section or label not in spellings:
            continue
        if sec == "other" and LINES[key][1] != row.block:
            continue
        taken = used.setdefault((sec, row.block if sec == "other" else ""), set())
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
    # Some banks print tax as a positive charge to subtract (Co-op), others as a signed
    # amount to add (Equity, KCB). The file's current tax lines decide, by majority.
    # Known limit: one convention per file; a file mixing both would be flagged, not read.
    current = [v.value for e in st.entities for v in st.values[e].get("current_tax", {}).values() if v.value]
    tax_sign = 1 if sum(v < 0 for v in current) > len(current) / 2 else -1
    for entity in st.entities:
        in_equity = st.nci_in_equity(entity)
        for p in st.periods:
            def g(key):
                return st.get(entity, key, p)

            def part(name):
                return [g(k) for k, (_, prt, _) in LINES.items() if prt == name]

            def add(*vals):
                return None if any(v is None for v in vals) else sum(vals)

            tests = [(f"{part_name} lines add up to the total", total, sum(v for v in part(part_name) if v is not None))
                     for total, part_name in _SUMS]
            if in_equity:
                tests[2] = (tests[2][0], "total_equity",
                            sum(v for v in part("equity") + [g("minority_interest")] if v is not None))
            nci = 0 if in_equity else (g("minority_interest") or 0)  # blank or dash: none
            # Subtotals, checked where the bank prints them.
            children = {"amortised_cost_securities": ("govt_securities_amortised", "other_securities_amortised"),
                        "fvoci_securities": ("govt_securities_fvoci", "other_securities_fvoci")}
            for sub, kids in children.items():
                if g(sub) is not None:
                    tests.append((f"{sub} = its two lines", sub, sum(g(k) or 0 for k in kids)))
            if g("investment_securities") is not None:
                tests.append(("investment securities = the securities lines under it", "investment_securities",
                              sum(g(k) or 0 for kids in children.values() for k in kids)))
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
                ("profit after tax = profit before tax less current and deferred tax", "pat",
                 add(g("pbt"), tax_sign * sum(v for v in part("tax") if v is not None))),
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
