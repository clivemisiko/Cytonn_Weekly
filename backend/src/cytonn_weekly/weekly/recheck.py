"""Fix a review from one of its items: re-read the figures an uploaded input feeds, and keep everything else.

A flagged item can come from a missing, refused or wrong input file.  After the reviewer uploads the file, this module
rebuilds the section *offline* from the stored inputs and takes over only the blocks that file feeds (``SLOT_MAP``);
every other block (public sources, drafted text, carried-forward text, the charts) stays exactly as the earlier review
had it.  The result is a new, undecided review; the earlier one is never touched.

Why a static map: a saved review does not record which input each item was read from, and a section builder mixes
uploaded inputs with things it fetches (CBK, NSE, cytonnreport.com) and with the model.  Neither may run here, so
only blocks that are built from stored inputs alone are listed as ``readable``.  The others say why they are not.

How the network and the model are kept out: the builders are given fetchers that record any call and fail it (the
builders turn a failed fetch into a note, so a block that did need one would show up as missing, which is why the
unreadable blocks are never merged), and a drafting function that returns no pieces and calls nothing.  Reading an
uploaded file, including OCR, is local and allowed.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, fields
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from cytonn_weekly.charts import store as chart_store
from cytonn_weekly.common.review import COMPUTED_FIGURE, UNAVAILABLE_PART, build_review, check_section, numbered
from cytonn_weekly.digital_payments.coordinator_review import TABLE_ROW, CoordinatorReview, ReviewItem
from cytonn_weekly.weekly import inputs as wi
from cytonn_weekly.weekly.week import Week

FIXED_INCOME, EQUITIES = "fixed_income", "equities"
_WARNING_PREFIX = "Weekly analyst inputs:"   # the lines of the section's warnings that come from the form against the workbook


@dataclass(frozen=True)
class Entry:
    prefix: str                  # a block id, or the start of one ("eurobonds" also covers "eurobonds_table")
    slots: tuple[str, ...]       # the uploads this block is built from
    readable: bool               # False: the block needs something fetched or drafted, so it is never re-read here
    why_not: str = ""


_BOTH = (wi.CBK_BULLETIN, wi.FI_WORKBOOK)

SLOT_MAP: dict[str, tuple[Entry, ...]] = {
    FIXED_INCOME: (
        Entry("tbills", _BOTH, True),
        Entry("tbonds", (), False, "CBK's T-bond result files are fetched"),
        Entry("bidding_range", (), False, "it is built from CBK's T-bond results, which are fetched"),
        Entry("money_market", (wi.FI_WORKBOOK, wi.CBK_BULLETIN), True),
        Entry("liquidity", _BOTH, True),
        Entry("eurobonds", _BOTH, True),
        Entry("shilling", (), False, "CBK's daily rates and the previous issue are fetched"),
        Entry("borrowing", (), False, "CBK's auction result files are fetched"),
    ),
    EQUITIES: (
        Entry("indices", (), False, "the NSE daily price lists are downloaded before they are read"),
        Entry("banking", (), False, "the NSE daily price lists are downloaded before they are read"),
        Entry("large_caps", (wi.KCB_WEEKLY, wi.EQUITIES_WORKBOOK), True),
        Entry("turnover", (), False, "CBK's daily dollar rates are fetched"),
        Entry("foreign", (), False, "CBK's daily dollar rates are fetched"),
        Entry("valuation", (wi.EQUITIES_WORKBOOK,), True),
        Entry("chart", (), False, "the charts are kept as drawn; drawing them again is not part of a re-check"),
        Entry("universe_of_coverage", (wi.EQUITIES_WORKBOOK, wi.KCB_WEEKLY), True),
    ),
}


def entry_for(section: str, block_id: str) -> Optional[Entry]:
    """The map's entry for a block id (the longest matching prefix), or None for a block the map does not list."""
    best = None
    for e in SLOT_MAP.get(section, ()):
        if (block_id == e.prefix or block_id.startswith(e.prefix + "_")) and (best is None or len(e.prefix) > len(best.prefix)):
            best = e
    return best


_KIND_OF = {"table": TABLE_ROW, "computed": COMPUTED_FIGURE, "unavailable": UNAVAILABLE_PART}


def _blocks_of(content: dict[str, Any], item: ReviewItem) -> list[dict[str, Any]]:
    """The block(s) an item came from, found by the title its ref starts with (a review does not store the link)."""
    return [b for b in content.get("blocks", [])
            if b.get("title") and _KIND_OF.get(b["kind"]) == item.kind
            and (item.ref.startswith(b["title"] + ": ") or item.ref.startswith(b["title"] + " ("))]


def fix_slots(section: str, content: dict[str, Any], item: ReviewItem) -> list[str]:
    """The uploads that can fix this item (empty when none can).  Only a flagged item of a re-readable block has any."""
    if section not in SLOT_MAP or item.status != "flagged":
        return []
    found = _blocks_of(content, item)
    entries = [entry_for(section, b["id"]) for b in found]
    if not found or any(e is None or not e.readable for e in entries):
        return []
    slots = set(entries[0].slots)
    for e in entries[1:]:
        slots &= set(e.slots)
    return [s for s in entries[0].slots if s in slots]


class OfflineGuard(Exception):
    """A fetch or a model call that a re-check must never make."""


def _guarded(calls: list[str]):
    def build(cls):
        def refuse(name: str):
            def call(*args: Any, **kw: Any) -> Any:
                calls.append(name)
                raise OfflineGuard(f"{name} is not available while a file is re-checked")
            return call
        return cls(**{f.name: refuse(f.name) for f in fields(cls)})
    return build


def _no_model(briefs: Any, target: Any, **kw: Any) -> dict[str, Any]:
    # The builders call their drafting function unconditionally, so it cannot raise; it returns nothing and calls nothing.
    return {"pieces": [], "week_start": "", "week_end": "", "shortfall": [], "warnings": []}


@dataclass
class Rechecked:
    review: CoordinatorReview
    changes: list[dict[str, str]]       # {"block", "label", "old", "new"}
    kept: list[str]                     # titles of the blocks that were not re-read
    changed_items: int


def _facts(b: dict[str, Any]) -> dict[str, str]:
    if b["kind"] == "computed":
        return {f["label"]: str(f.get("display", "")) for f in b.get("figures", [])}
    if b["kind"] == "table":
        name = b.get("label_field") or b["key_field"]
        return {f"{row.get(name, row.get(b['key_field']))}: {c['label']}": str(row.get(c["key"], ""))
                for row in b.get("rows", []) for c in b.get("columns", []) if c["key"] != b["key_field"]}
    return {}


def _changes(old: Optional[dict[str, Any]], new: Optional[dict[str, Any]]) -> list[dict[str, str]]:
    title = (new or old or {}).get("title", "")
    if old is None or old["kind"] == "unavailable":
        return [{"block": title, "label": k, "old": "Not available", "new": v} for k, v in _facts(new or {}).items()]
    if new is None or new["kind"] == "unavailable":
        return [{"block": title, "label": "This part", "old": "Worked out", "new": "Not available"}]
    before, after = _facts(old), _facts(new)
    return [{"block": title, "label": k, "old": before.get(k, "None"), "new": after.get(k, "None")}
            for k in [*before, *(k for k in after if k not in before)] if before.get(k) != after.get(k)]


def _merge(section: str, slot: str, old: list[dict[str, Any]], rebuilt: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The earlier blocks, with each block this slot feeds replaced by its re-read twin (added or dropped as the rebuild says)."""
    def mapped(b: dict[str, Any]) -> bool:
        e = entry_for(section, b["id"])
        return bool(e and e.readable and slot in e.slots)

    fresh = {b["id"]: b for b in rebuilt if mapped(b)}
    out = [fresh.pop(b["id"]) if b["id"] in fresh else b for b in old if not mapped(b) or b["id"] in fresh]
    ids = [b["id"] for b in rebuilt]
    for r in rebuilt:        # a block that exists only now goes after the nearest block before it in the rebuilt section
        if r["id"] in fresh:
            before = set(ids[:ids.index(r["id"])])
            at = next((i + 1 for i in range(len(out) - 1, -1, -1) if out[i]["id"] in before), 0)
            out.insert(at, fresh.pop(r["id"]))
    return out


def _carry(old: CoordinatorReview, new: CoordinatorReview) -> int:
    """Notes and marks go to the items that did not change; a changed item starts undecided.  Returns how many changed."""
    pool: dict[tuple[str, str], list[ReviewItem]] = {}
    for i in old.review_items:
        pool.setdefault((i.kind, i.ref), []).append(i)
    changed = 0
    for item in new.review_items:
        earlier = (pool.get((item.kind, item.ref)) or [None]).pop(0)
        same = earlier is not None and (earlier.status, earlier.to_dict()["detail"], earlier.context) == (item.status, item.to_dict()["detail"], item.context)
        if same:
            item.resolve(earlier.resolution, earlier.resolution_note)
        else:
            changed += 1
    return changed


def _copy_chart_files(old: CoordinatorReview, new: CoordinatorReview, charts_root: Optional[Path]) -> None:
    """A drawn chart's files live under its review's run id; the new review gets a checked copy of each."""
    files: dict[str, dict[str, bytes]] = {}
    for b in new.section.get("blocks", []):
        if b.get("kind") == "chart" and b.get("png_sha256"):
            files[b["chart_id"]] = {"png": chart_store.read_png(old.run_id, b["chart_id"], b["png_sha256"], charts_root)}
            if b.get("series_sha256"):   # a drawn chart can have no stored series; then there is no file to copy
                files[b["chart_id"]]["json"] = chart_store.read_series(old.run_id, b["chart_id"], b["series_sha256"], charts_root)
    chart_store.attach(new, files)


def recheck(old: CoordinatorReview, slot: str, data: bytes, filename: str, root: Optional[Path],
            charts_root: Optional[Path] = None) -> Rechecked:
    """Re-read what ``slot`` feeds, as if ``data`` were in it.  Nothing real is changed: it works on a copy of the week's inputs.

    wi.InputError if the file is refused.  The caller stores the file for real once this has returned.
    """
    section = old.section.get("section")
    if section not in SLOT_MAP:
        raise ValueError("this section cannot be re-checked from a file")
    week = Week(date.fromisoformat(old.section["week_ending"]))
    base = wi.inputs_root(root)
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp) / "inputs" / "weekly"
        for w in (week, week.previous):
            if (base / w.ending.isoformat()).is_dir():
                shutil.copytree(base / w.ending.isoformat(), sandbox / w.ending.isoformat())
        wi.store(week, slot, data, filename, sandbox)
        rebuilt = _rebuild(section, week, sandbox)
    blocks = _merge(section, slot, old.section["blocks"], rebuilt.section["blocks"])
    content = {**old.section, "blocks": numbered(blocks)}
    content["warnings"] = [w for w in old.section.get("warnings", []) if not w.startswith(_WARNING_PREFIX)] + \
        [w for w in rebuilt.section.get("warnings", []) if w.startswith(_WARNING_PREFIX)]
    if slot == wi.CBK_BULLETIN:   # the refused-table notes belong to the bulletin that was just replaced
        stale = {n["text"] for n in old.section.get("notices", [])}
        fresh = rebuilt.section.get("notices", [])
        content["notices"] = fresh
        content["warnings"] = [w for w in content["warnings"] if w not in stale] + [n["text"] for n in fresh]
    content["summary"] = _module(section).compose_summary(blocks)
    new = build_review(content, check_section(content))
    new.report_type, new.period = old.report_type, old.period
    before = {b["id"]: b for b in old.section["blocks"]}
    after = {b["id"]: b for b in content["blocks"]}
    changes = [c for i in [*before, *(i for i in after if i not in before)] if before.get(i) != after.get(i)
               for c in _changes(before.get(i), after.get(i))]
    rebuilt_ids = {b["id"] for b in rebuilt.section["blocks"] if (entry_for(section, b["id"]) or Entry("", (), False)).readable
                   and slot in entry_for(section, b["id"]).slots}
    kept = [b.get("title") or b.get("headline") for b in content["blocks"] if b["id"] not in rebuilt_ids and (b.get("title") or b.get("headline"))]
    _copy_chart_files(old, new, charts_root)
    return Rechecked(new, changes, kept, _carry(old, new))


def _module(section: str):
    if section == FIXED_INCOME:
        from cytonn_weekly.fixed_income import weekly
    else:
        from cytonn_weekly.equities import weekly   # imported here: it pulls in the OCR reader
    return weekly


def _rebuild(section: str, week: Week, sandbox: Path) -> CoordinatorReview:
    module = _module(section)
    inputs = wi.WeeklyInputs(week, sandbox)
    fetchers = _guarded([])(module.Fetchers)
    if section == FIXED_INCOME:
        return module.build_fixed_income_review(week.ending, inputs=inputs, fetchers=fetchers, draft=_no_model, inputs_root=sandbox)
    # A day past the weekend keeps the builder from asking afx for its page.
    return module.build_equities_weekly_review(week.ending, today=week.ending + timedelta(days=3), inputs=inputs,
                                               fetchers=fetchers, draft=_no_model, inputs_root=sandbox)
