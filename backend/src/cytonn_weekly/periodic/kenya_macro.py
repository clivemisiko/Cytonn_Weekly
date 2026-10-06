"""Kenya Macro Economic Review in the quarterly, half-year and annual Markets Reviews.

Real structure (read 2026-10-05):

* Q3'2026: GDP (KNBS quarterly GDP report) with the "Kenya 2026 Growth Projections" table;
  Stanbic Bank's August 2026 Purchasing Manager's Index (PMI); Inflation; September 2026
  Inflation with the "Major Inflation Changes - September 2026" table; The Kenyan Shilling
  (with forex reserves and months of import cover); Monetary Policy; Fiscal Policy with the
  "Comparison between FY'2026/2027 and FY'2025/2026 Budgets Estimates" table.
* H1'2026: the same, with the PMI for May and the June inflation table.
* FY'2025: Economic Growth; Kenyan Shilling; Inflation; December 2025 Inflation; Monetary
  Policy (2025 Key Highlights); FY'2025/2026 National Budget; Credit Facilities Extended to
  Kenya; FY'2024/2025 KRA Revenue Performance; Balance of Payments; Current account; Credit
  Ratings (table); 2025 Returns by Various Asset Classes (chart); and the "Macro-Economic &
  Business Environment Outlook" table.

Built here: the Major Inflation Changes table from KNBS's own CPI release, and a cited
narrative for each subsection a public source covers.  The table's columns follow the
issues ("Broad Commodity Group", "Price change m/m (<month>/<previous month>)", "Price
change y/y (<month>/<month a year earlier>)"), with the divisions KNBS's release itself
names as the main drivers, then "Overall Inflation": Q3'2026's rows (Food and Non-Alcoholic
Beverages 0.9% / 9.5%, Transport (0.4%) / 15.6%, Housing, Water, Electricity, Gas and
Other Fuels 0.1% / 3.2%, Overall 0.4% / 6.8%) are exactly KNBS's Table 1 for September 2026.
The issues' fourth column, "Reason", is analysis of KNBS's retail prices; it is asked of
the inflation narrative (with citations) rather than written into the table.
"""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Any, Callable, Optional

import pdfplumber

from cytonn_weekly.common.formatting import PCT, TEXT
from cytonn_weekly.common.http import http_get
from cytonn_weekly.common.review import build_review, check_section, narrative_block, table_block
from cytonn_weekly.common.run_events import Observer, fetch_source, report_blocks
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.narrative.base import NarrativeProvider
from cytonn_weekly.periodic.common import PeriodContext, Stub, compose, draft_period, period_brief
from cytonn_weekly.report_types import ANNUAL, HALF_YEAR, QUARTERLY

SECTION = "kenya_macro"
TITLE = "Kenya Macro Economic Review"

Getter = Callable[[str], bytes]

CHARTS = {
    QUARTERLY: (
        "Kenya's Purchasing Manager's Index for the Last 24 Months",
        "5-Year Inflation Rates (y/y)",
        "Kshs vs USD",
        "Kenya months of import cover and Forex reserves",
        "Untitled chart after the commercial banks' lending-rates paragraph (no caption in the text layer)",
    ),
    HALF_YEAR: (
        "Kenya's Purchasing Manager's Index for the Last 24 Months",
        "5-Year Inflation Rates (y/y)",
        "Kshs vs USD",
        "Kenya months of import cover and Forex reserves",
        "Private Sector Credit Growth",
    ),
    ANNUAL: (
        "Kenya's Purchasing Manager's Index for the Last 24 Months",
        "Kshs vs USD",
        "Kenya months of import cover and Forex reserves",
        "5-Year Inflation Rates (y/y)",
        "Central Bank Rate (CBR) against its 5-year average (legend text; no caption in the text layer)",
        "2025 Asset Class Returns",
    ),
}

# ---------------------------------------------------------------------------
# KNBS CPI release
# ---------------------------------------------------------------------------

KNBS_CPI_URL = ("https://www.knbs.or.ke/wp-content/uploads/{folder:%Y}/{folder:%m}/"
                "Kenya-Consumer-Price-Indices-and-Inflation-Rates-{month:%B}-{month:%Y}.pdf")

CPI_COLUMNS_TEMPLATE = [
    {"key": "group", "label": "Broad Commodity Group", "fmt": TEXT},
    {"key": "mm_pct", "label": "Price change m/m ({cur}/{prev})", "fmt": PCT, "decimals": 1},
    {"key": "yy_pct", "label": "Price change y/y ({cur}/{ago})", "fmt": PCT, "decimals": 1},
]

_DIVISION = re.compile(r"^(?P<name>[A-Z][A-Za-z ,'&\-]+?)\s+(?P<weight>\d{1,3}\.\d{4})\s+(?P<mm>-?\d+\.\d)\s+(?P<yy>-?\d+\.\d)\s*$",
                       re.M)
_DRIVERS = re.compile(r"driven by a rise in prices of items in the (?P<list>.+?) over the one-year period", re.S | re.I)


def cpi_urls(month: date) -> list[str]:
    """Where KNBS puts the month's release: its own month's upload folder, else the next month's."""
    nxt = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return [KNBS_CPI_URL.format(folder=f, month=month) for f in (month, nxt)]


def _norm(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


def parse_cpi(text: str) -> dict[str, Any]:
    """KNBS's Table 1 (every division's weight, m/m and y/y change, and the Total) and the divisions its overview names."""
    start = text.find("Table 1:")
    table = text[start:] if start >= 0 else ""
    divisions = [{"name": m["name"].strip(), "weight": float(m["weight"]), "mm_pct": float(m["mm"]),
                  "yy_pct": float(m["yy"])} for m in _DIVISION.finditer(table)]
    total = next((d for d in divisions if d["name"] == "Total"), None)
    divisions = [d for d in divisions if d["name"] != "Total"]
    drivers: list[str] = []
    m = _DRIVERS.search(" ".join(text.split()))
    if m:
        # "the Food and Non-Alcoholic Beverages (9.5%); Transport (15.6%), and Housing, Water, ... (3.2%)":
        # names contain "and" and commas themselves, so split on the bracketed figures instead.
        for part in re.findall(r"(.+?)\(\s*-?[\d.]+\s*%\s*\)", m["list"]):
            name = re.sub(r"^(?:and|the)\s+", "", part.strip(" ,;")).strip()
            match = next((d["name"] for d in divisions if _norm(d["name"]) == _norm(name)), None)
            if match and match not in drivers:
                drivers.append(match)
    return {"divisions": divisions, "total": total, "drivers": drivers}


def fetch_cpi(month: date, get: Getter = http_get) -> dict[str, Any]:
    """The month's KNBS CPI release, parsed.  Raises LookupError if neither upload folder has it."""
    errors = []
    for url in cpi_urls(month):
        try:
            data = get(url)
        except Exception as exc:  # noqa: BLE001 - try the next folder, then report both
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
            continue
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages[:8])
        return {"source_url": url, "month": month.isoformat(), **parse_cpi(text)}
    raise LookupError(f"KNBS CPI release for {month:%B %Y} not found: " + "; ".join(errors))


def inflation_table(ctx: PeriodContext, fetch: Callable[[date], dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """"Major Inflation Changes - <month>": KNBS's named drivers, then Overall Inflation."""
    month = date(ctx.end.year, ctx.end.month, 1)
    prev = date(month.year - (month.month == 1), (month.month - 2) % 12 + 1, 1)
    labels = {"cur": f"{month:%B}-{month:%Y}", "prev": f"{prev:%B}-{prev:%Y}", "ago": f"{month:%B}-{month.year - 1}"}
    columns = [{**c, "label": c["label"].format(**labels)} for c in CPI_COLUMNS_TEMPLATE]
    title = f"Major Inflation Changes – {month:%B %Y}"
    warnings: list[str] = []
    try:
        cpi = fetch(month)
    except Exception as exc:  # noqa: BLE001 - the table shows the failure instead of disappearing
        rows = [{"group": "Overall Inflation", "error": f"{type(exc).__name__}: {exc}"}]
        return table_block("major_inflation_changes", title, columns, rows, "group", "group",
                           {"name": "Kenya National Bureau of Statistics (KNBS)", "url": cpi_urls(month)[0],
                            "as_of": month.isoformat()}), warnings
    by_name = {d["name"]: d for d in cpi["divisions"]}
    rows = [{"group": n, "mm_pct": by_name[n]["mm_pct"], "yy_pct": by_name[n]["yy_pct"], "error": None}
            for n in cpi["drivers"]]
    if not rows:
        warnings.append("KNBS's overview names no driving divisions in a form the parser recognises; only the overall row is shown")
    total = cpi["total"]
    rows.append({"group": "Overall Inflation", "mm_pct": total and total["mm_pct"], "yy_pct": total and total["yy_pct"],
                 "error": None if total else "the Total row of KNBS's Table 1 was not found"})
    return table_block("major_inflation_changes", title, columns, rows, "group", "group",
                       {"name": "Kenya National Bureau of Statistics (KNBS)", "url": cpi["source_url"],
                        "as_of": month.isoformat()}), warnings

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

GROWTH_PROJECTIONS_BLOCKED_REASON = (
    "The Growth Projections table sets each organisation's earlier and revised GDP projection side by side "
    "(IMF, National Treasury, World Bank, Fitch Solutions) and includes Cytonn's own projection, which is "
    "Cytonn's research, not a public figure; the \"earlier\" column is also Cytonn's record from its previous review."
)
GROWTH_PROJECTIONS_UNBLOCK = "Cytonn's research team supplying its own projection and its earlier/revised record each period."

PMI_BLOCKED_REASON = (
    "The Stanbic Bank Kenya PMI is compiled and released by S&P Global; its 24-month series (behind the chart) "
    "is S&P Global's data, and no free machine-readable release has been verified. The issues attribute the "
    "figures to \"Stanbic Bank\" in the text and print no source line under the chart (Q3'2026 and H1'2026, read "
    "2026-10-06)."
)
PMI_UNBLOCK = (
    "The analysts saying where they read the PMI (Stanbic's emailed release, S&P Global's PMI feed, or a press "
    "report), then access to that release for a parser."
)

BUDGET_BLOCKED_REASON = (
    "The budget comparison table sets two years' estimates side by side line by line. Its source line reads "
    "\"National Treasury of Kenya, www.parliament.go.ke\" and names no document: which one (Budget Statement, "
    "Estimates, Appropriation Act) the analysts use has not been confirmed, and its layout has not been inspected."
)
BUDGET_UNBLOCK = (
    "The analysts naming the exact National Treasury or parliament.go.ke document behind the table, then a parser "
    "written against a real copy."
)

CREDIT_RATINGS_BLOCKED_REASON = (
    "Kenya's sovereign ratings table (Fitch, S&P Global, Moody's) needs each agency's current rating and outlook; "
    "the agencies' rating pages need registration and no free machine-readable source has been verified."
)
CREDIT_RATINGS_UNBLOCK = "Ratings supplied by the analysts each year, or access to the agencies' rating pages."

ASSET_RETURNS_BLOCKED_REASON = (
    "\"Returns by Various Asset Classes\" compares Cytonn's own measures across equities, bonds, money market "
    "funds, real estate and others; the basis for each asset class is Cytonn's research, not one public source."
)
ASSET_RETURNS_UNBLOCK = "Cytonn's research team supplying the asset-class return figures and their basis."

OUTLOOK_BLOCKED_REASON = (
    "The Macro-Economic & Business Environment Outlook table is Cytonn's own view (positive, neutral or negative) "
    "per indicator; the tool never writes an opinion."
)
OUTLOOK_UNBLOCK = "Nothing to unblock: this is the analysts' call, written by them."


def fetch_growth_projections(ctx: PeriodContext) -> Any:
    # TODO: needs Cytonn's own projection supplied (GROWTH_PROJECTIONS_UNBLOCK).
    raise NotImplementedError(GROWTH_PROJECTIONS_BLOCKED_REASON)


def fetch_pmi(ctx: PeriodContext) -> Any:
    # TODO: needs access to the PMI release (PMI_UNBLOCK).
    raise NotImplementedError(PMI_BLOCKED_REASON)


def fetch_budget_comparison(ctx: PeriodContext) -> Any:
    # TODO: needs the source document confirmed and a real copy (BUDGET_UNBLOCK).
    raise NotImplementedError(BUDGET_BLOCKED_REASON)


def fetch_credit_ratings(ctx: PeriodContext) -> Any:
    # TODO: needs a ratings source (CREDIT_RATINGS_UNBLOCK).
    raise NotImplementedError(CREDIT_RATINGS_BLOCKED_REASON)


def fetch_asset_class_returns(ctx: PeriodContext) -> Any:
    # TODO: needs Cytonn's own figures (ASSET_RETURNS_UNBLOCK).
    raise NotImplementedError(ASSET_RETURNS_BLOCKED_REASON)


def fetch_macro_outlook(ctx: PeriodContext) -> Any:
    # TODO: Cytonn's own view; never drafted by the tool (OUTLOOK_UNBLOCK).
    raise NotImplementedError(OUTLOOK_BLOCKED_REASON)


STUBS = (
    Stub("growth_projections", "Kenya GDP Growth Projections table", GROWTH_PROJECTIONS_BLOCKED_REASON,
         GROWTH_PROJECTIONS_UNBLOCK, fetch_growth_projections),
    Stub("pmi", "Stanbic Bank's Purchasing Manager's Index (PMI)", PMI_BLOCKED_REASON, PMI_UNBLOCK, fetch_pmi),
    Stub("budget_comparison", "Fiscal Policy: budget estimates comparison table", BUDGET_BLOCKED_REASON,
         BUDGET_UNBLOCK, fetch_budget_comparison),
    Stub("credit_ratings", "Credit Ratings table", CREDIT_RATINGS_BLOCKED_REASON, CREDIT_RATINGS_UNBLOCK,
         fetch_credit_ratings),
    Stub("asset_class_returns", "Returns by Various Asset Classes", ASSET_RETURNS_BLOCKED_REASON,
         ASSET_RETURNS_UNBLOCK, fetch_asset_class_returns),
    Stub("macro_outlook", "Macro-Economic & Business Environment Outlook table", OUTLOOK_BLOCKED_REASON,
         OUTLOOK_UNBLOCK, fetch_macro_outlook),
)
ANNUAL_ONLY = ("credit_ratings", "asset_class_returns", "macro_outlook")


def briefs(ctx: PeriodContext):
    b = [
        period_brief(ctx, "gdp", TITLE, "Economic growth",
                     "Kenya's real GDP growth as published by the Kenya National Bureau of Statistics (quarterly GDP "
                     "report or Economic Survey), with the sectors that drove it", preferred_domains=("knbs.or.ke",)),
        period_brief(ctx, "inflation", TITLE, "Inflation",
                     "Kenya's year-on-year inflation for the period's months and the latest month, as published by "
                     "KNBS, with the price movements KNBS gives for food, transport and housing/energy",
                     preferred_domains=("knbs.or.ke",)),
        period_brief(ctx, "shilling", TITLE, "The Kenyan Shilling",
                     "the Kenya Shilling's exchange rate against the US Dollar over the period, and the Central Bank "
                     "of Kenya's usable foreign exchange reserves and months of import cover",
                     preferred_domains=("centralbank.go.ke",)),
        period_brief(ctx, "monetary_policy", TITLE, "Monetary Policy",
                     "the Central Bank of Kenya Monetary Policy Committee's decisions on the Central Bank Rate, and "
                     "what the CBK reported on private sector credit growth and commercial bank lending rates",
                     preferred_domains=("centralbank.go.ke",)),
        period_brief(ctx, "fiscal_policy", TITLE, "Fiscal Policy",
                     "the National Treasury's budget, revenue collection or borrowing developments (budget estimates, "
                     "Finance Bill, KRA revenue performance, supplementary budgets)",
                     preferred_domains=("treasury.go.ke", "parliament.go.ke", "kra.go.ke")),
    ]
    if ctx.report_type == ANNUAL:
        b.append(period_brief(ctx, "balance_of_payments", TITLE, "Balance of Payments and credit facilities",
                              "Kenya's balance of payments and current account position, and new credit facilities "
                              "extended to Kenya (IMF, World Bank, other lenders)",
                              preferred_domains=("centralbank.go.ke", "imf.org", "worldbank.org")))
    return b


def build_kenya_macro_review(
    ctx: PeriodContext,
    provider: Optional[NarrativeProvider] = None,
    fetch_inflation: Callable[[date], dict[str, Any]] = fetch_cpi,
    on_event: Optional[Observer] = None,
) -> CoordinatorReview:
    """KNBS's inflation table, a cited narrative per subsection, the rest stubs.

    ``on_event`` (common/run_events.py) is told each step as it happens.  A CPI release that
    cannot be fetched is reported as a failed source, and the draft goes on with a flagged table.
    """

    def observed_fetch(month: date) -> dict[str, Any]:
        return fetch_source(on_event, f"KNBS consumer price index release, {month:%B %Y}", fetch_inflation, month)

    table, warnings = inflation_table(ctx, fetch_inflation if on_event is None else observed_fetch)
    bs = briefs(ctx)
    draft = draft_period(bs, len(bs), ctx, provider, on_event)
    pieces = {p["brief_id"]: narrative_block(f"subsection_{p['brief_id']}", p) for p in draft["pieces"]}
    stubs = {s.id: s.block() for s in STUBS}
    order = ["gdp", stubs["growth_projections"], stubs["pmi"], "inflation", table, "shilling", "monetary_policy",
             "fiscal_policy"]
    if ctx.report_type != ANNUAL:  # FY'2025 has no budget comparison table; Q3'2026 and H1'2026 do
        order.append(stubs["budget_comparison"])
    else:
        order += ["balance_of_payments", stubs["credit_ratings"], stubs["asset_class_returns"], stubs["macro_outlook"]]
    blocks = [pieces[o] if isinstance(o, str) else o for o in order if not isinstance(o, str) or o in pieces]
    content = compose(SECTION, TITLE, ctx, blocks, draft=draft, expected=len(bs), warnings=warnings, charts=CHARTS)
    report_blocks(on_event, content)
    return build_review(content, check_section(content, on_event))
