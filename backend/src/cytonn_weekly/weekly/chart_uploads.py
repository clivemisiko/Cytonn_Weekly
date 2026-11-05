from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from cytonn_weekly.weekly.inputs import InputError, week_dir
from cytonn_weekly.weekly.week import Week, ordinal

MAX_BYTES = 5 * 1024 * 1024
MAX_LEAD_IN = 600
MAX_SOURCE = 120
# The type is judged by the first bytes alone; the image is never decoded here.
MAGIC = {"png": b"\x89PNG\r\n\x1a\n", "jpeg": b"\xff\xd8\xff"}
EXTENSION = {"png": "png", "jpeg": "jpg"}
MEDIA_TYPE = {"png": "image/png", "jpeg": "image/jpeg"}

# (key, section, short name, index into that section's CHARTS)
_SLOTS = (
    ("tbill_91_growth", "fixed_income", "91-day T-bill yield growth", 0),
    ("tbill_yields", "fixed_income", "T-bill yields", 1),
    ("tbill_subscription", "fixed_income", "T-bill subscription rates", 2),
    ("money_market", "fixed_income", "Money market yields", 3),
    ("interbank", "fixed_income", "Interbank rates", 4),
    ("import_cover", "fixed_income", "Months of import cover", 5),
    ("nasi_pe", "equities", "NASI P/E", 0),
    ("nasi_yield", "equities", "NASI dividend yield", 1),
)
KEYS = tuple(s[0] for s in _SLOTS)
SECTION_OF = {s[0]: s[1] for s in _SLOTS}
# The published sentence above the two NASI charts (#38.2026), printed once above the pair.
NASI_PAIR = "The charts below indicate the historical P/E and dividend yields of the market"


def _years_back(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:   # 29 February
        return day.replace(year=day.year - years, day=28)


def template(key: str, week: Week) -> str:
    """The sentence printed above a chart when the analyst typed none: the section's CHARTS caption with its dates worked out
    from the report week.  The money market chart has no published caption, so its sentence names the week only."""
    e, y = week.ending, week.ending.year
    return {
        "tbill_91_growth": f"The chart below shows the yield growth rate for the 91-day paper over the last year, from "
                           f"{ordinal(_years_back(e, 1))} to {ordinal(e)}:",
        "tbill_yields": f"The chart below shows the performance of the 91-day, 182-day and 364-day papers over the last two "
                        f"years, from {ordinal(_years_back(e, 2))} to {ordinal(e)}:",
        "tbill_subscription": f"The chart below compares the overall average T-bill subscription rates obtained in {y - 3}, "
                              f"{y - 2}, {y - 1} and {y} Year-to-date (YTD):",
        "money_market": f"The chart below shows the money market yields as at {ordinal(e)}:",
        "interbank": f"The chart below shows the interbank rates in the market over the years, up to {ordinal(e)}:",
        "import_cover": f"The chart below summarizes the evolution of Kenya's months of import cover over the last two "
                        f"years, from {ordinal(_years_back(e, 2))} to {ordinal(e)}:",
        "nasi_pe": NASI_PAIR,
        "nasi_yield": NASI_PAIR,
    }[key]


def slots() -> list[dict[str, str]]:
    """The eight slots, each with the caption its section's CHARTS list holds (the key the export places it by)."""
    # Imported here: both section modules import weekly.inputs, which reads this module lazily.
    from cytonn_weekly.equities import weekly as equities
    from cytonn_weekly.fixed_income import weekly as fixed_income
    charts = {"fixed_income": fixed_income.CHARTS, "equities": equities.CHARTS}
    return [{"key": key, "section": section, "title": title, "caption": charts[section][i]}
            for key, section, title, i in _SLOTS]


def _folder(week: Week, root: Optional[Path]) -> Path:
    return week_dir(week, root) / "charts"


def _read(week: Week, root: Optional[Path]) -> dict[str, dict[str, Any]]:
    path = _folder(week, root) / "charts.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return {k: v for k, v in data.items() if k in KEYS and isinstance(v, dict)} if isinstance(data, dict) else {}


def _write(week: Week, root: Optional[Path], data: dict[str, dict[str, Any]]) -> None:
    folder = _folder(week, root)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "charts.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def _known(key: str) -> None:
    if key not in KEYS:
        raise KeyError(key)


def image_type(data: bytes) -> str:
    if not data:
        raise InputError("The file is empty. Choose the chart's image file again.")
    if len(data) > MAX_BYTES:
        raise InputError(f"The image is over the {MAX_BYTES // 1_048_576} MB limit. Save a smaller copy and upload that.")
    for kind, magic in MAGIC.items():
        if data.startswith(magic):
            return kind
    raise InputError("This is not a PNG or JPEG image. Save the chart as a PNG or JPEG and upload that.")


def store(week: Week, key: str, data: bytes, root: Optional[Path] = None, filename: str = "") -> None:
    """Keep the image as ``<key>.png`` or ``<key>.jpg``, replacing the slot's earlier image."""
    _known(key)
    kind = image_type(data)
    folder = _folder(week, root)
    folder.mkdir(parents=True, exist_ok=True)
    for ext in EXTENSION.values():
        (folder / f"{key}.{ext}").unlink(missing_ok=True)
    (folder / f"{key}.{EXTENSION[kind]}").write_bytes(data)
    meta = _read(week, root)
    meta[key] = {**meta.get(key, {}), "type": kind, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                 "file_name": Path(filename.replace("\\", "/")).name[:200] or f"{key}.{EXTENSION[kind]}",
                 "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _write(week, root, meta)


def _stored(week: Week, key: str, meta: dict, root: Optional[Path]) -> Optional[tuple[Path, str]]:
    kind = meta.get(key, {}).get("type")
    path = _folder(week, root) / f"{key}.{EXTENSION.get(kind, '')}"
    return (path, kind) if kind in EXTENSION and path.is_file() else None


def image(week: Week, key: str, root: Optional[Path] = None) -> Optional[tuple[bytes, str]]:
    """The stored bytes and their type, or None when the slot has no image."""
    _known(key)
    found = _stored(week, key, _read(week, root), root)
    return (found[0].read_bytes(), found[1]) if found else None


def remove(week: Week, key: str, root: Optional[Path] = None) -> bool:
    _known(key)
    meta = _read(week, root)
    had = _stored(week, key, meta, root) is not None
    for ext in EXTENSION.values():
        (_folder(week, root) / f"{key}.{ext}").unlink(missing_ok=True)
    entry = {k: v for k, v in meta.get(key, {}).items() if k == "lead_in"}
    if entry:
        meta[key] = entry
    else:
        meta.pop(key, None)
    _write(week, root, meta)
    return had


def set_lead_in(week: Week, key: str, text: Optional[str], root: Optional[Path] = None) -> None:
    _known(key)
    clean = " ".join((text or "").split())
    if len(clean) > MAX_LEAD_IN:
        raise InputError(f"The lead-in is {len(clean)} characters and the limit is {MAX_LEAD_IN}. "
                         f"Shorten it by {len(clean) - MAX_LEAD_IN}.")
    meta = _read(week, root)
    entry = {k: v for k, v in meta.get(key, {}).items() if k != "lead_in"}
    if clean:
        entry["lead_in"] = clean
    if entry:
        meta[key] = entry
    else:
        meta.pop(key, None)
    _write(week, root, meta)


def lead_in(week: Week, key: str, root: Optional[Path] = None) -> str:
    return _read(week, root).get(key, {}).get("lead_in", "")


def set_source(week: Week, key: str, text: Optional[str], root: Optional[Path] = None) -> None:
    """The line printed as "Source: <text>" under the image, stored as typed but trimmed.  Blank clears it."""
    _known(key)
    raw = text or ""
    clean = raw.strip()
    if "".join(raw.splitlines()) != raw:
        raise InputError("The source line must be one line. Remove the line break.")
    if len(clean) > MAX_SOURCE:
        raise InputError(f"The source line is {len(clean)} characters and the limit is {MAX_SOURCE}. "
                         f"Shorten it by {len(clean) - MAX_SOURCE}.")
    meta = _read(week, root)
    entry = {k: v for k, v in meta.get(key, {}).items() if k != "source"}
    if clean:
        entry["source"] = clean
    if entry:
        meta[key] = entry
    else:
        meta.pop(key, None)
    _write(week, root, meta)


def source(week: Week, key: str, root: Optional[Path] = None) -> str:
    return _read(week, root).get(key, {}).get("source", "")


def status(week: Week, root: Optional[Path] = None) -> list[dict[str, Any]]:
    meta = _read(week, root)
    out = []
    for s in slots():
        stored = _stored(week, s["key"], meta, root)
        entry = meta.get(s["key"], {})
        out.append({"key": s["key"], "section": s["section"], "title": s["title"], "template_lead_in": template(s["key"], week),
                    "lead_in": entry.get("lead_in", ""), "source": entry.get("source", ""),
                    "has_image": stored is not None, "file_name": entry.get("file_name") if stored else None,
                    "type": stored[1] if stored else None, "size": stored[0].stat().st_size if stored else None})
    return out


def missing(week: Optional[Week], root: Optional[Path] = None, drawn: frozenset[str] = frozenset()) -> int:
    """Slots that will print a placeholder: no uploaded image and not a chart the tool drew (``drawn``: slot keys).
    With no week named, none can be used, so every slot."""
    if week is None:
        return len(KEYS)
    return sum(not s["has_image"] and s["key"] not in drawn for s in status(week, root))


# ---------------------------------------------------------------------------
# The charts in the review: one "chart_slot" block per slot of the section (an upload, a drawn chart, or none)
# ---------------------------------------------------------------------------

SLOT_KIND = "chart_slot"   # charts/block.SLOT_KIND
UPLOADED, DRAWN, NOT_DRAWN, MISSING = "uploaded", "drawn", "not_drawn", "missing"
UPLOAD_FLAG, NO_CHART_FLAG = "uploaded_chart", "no_chart"
NO_CHART = "No chart: the Word file will show a placeholder"


def _drawn_states(blocks: list[dict[str, Any]]) -> dict[str, str]:
    """{chart id: "drawn" | "not_drawn"} of the tool's own chart blocks; a chart with no workbook is absent."""
    return {b["chart_id"]: b["status"] for b in blocks if b.get("kind") == "chart" and b["status"] in (DRAWN, NOT_DRAWN)}


def slot_blocks(section: str, week: Week, root: Optional[Path], blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The section's chart slots as review blocks, from the stored uploads and the section's own chart ``blocks``.

    An uploaded image is a flagged item (the analyst's picture, never verified here); a slot with no image and no drawn
    chart is a flagged "no chart" item the reviewer accepts.  A drawn chart has no slot item (its own items say what was
    checked), and nor has one the tool could not draw (its "not drawn" items already hold the section up).
    """
    from cytonn_weekly.charts.block import CHART_SCOPE   # imported here: charts pulls in the workbook readers

    meta, tool = _read(week, root), _drawn_states(blocks)
    out = []
    for s in slots():
        if s["section"] != section:
            continue
        key, entry = s["key"], meta.get(s["key"], {})
        typed = entry.get("lead_in", "")
        block = {"kind": SLOT_KIND, "id": f"{SLOT_KIND}_{key}", "key": key, "title": s["title"], "caption": s["caption"],
                 "week_ending": week.ending.isoformat(), "export": False,
                 "lead_in": typed or template(key, week), "lead_in_from": "typed" if typed else "template"}
        if _stored(week, key, meta, root):
            block.update(state=UPLOADED, file_name=entry.get("file_name") or key, sha256=entry.get("sha256"),
                         source=entry.get("source", ""), replaces_drawn=tool.get(key) == DRAWN)
            sentence = "the sentence the analyst typed" if typed else "template sentence used"
            message = (f"{s['title']}: chart image uploaded by the analyst ({block['file_name']}, SHA-256 "
                       f"{(block['sha256'] or '')[:12]}), not verified by the tool. "
                       + ("It replaces the chart the tool drew from the equities workbook. " if block["replaces_drawn"] else "")
                       + f"Sentence printed above it ({sentence}): \"{block['lead_in']}\""
                       + (f" Source line under it: \"{block['source']}\"." if block["source"] else ""))
            flag_kind, ref = UPLOAD_FLAG, f"{s['title']} chart: uploaded image"
        elif key in tool:
            block["state"] = tool[key]
            out.append(block)
            continue
        else:
            block["state"] = MISSING
            message = (f"{NO_CHART}. {s['title']}: no image was uploaded"
                       + (" and the tool drew none" if section == "equities" else "") + ". Accept to export the section without it.")
            flag_kind, ref = NO_CHART_FLAG, f"{s['title']} chart: no chart"
        block["ref"] = ref
        block["checks"] = [{"kind": flag_kind, "scope": CHART_SCOPE, "subject": f"{block['id']}#slot", "field": None,
                            "message": message, "drafted": None, "expected": None, "source_value": None, "sources": []}]
        out.append(block)
    return out


def _state_of(blocks: list[dict[str, Any]]) -> dict[str, tuple]:
    """What decides the Word file, slot by slot: what is there, and for an upload its picture, sentence and source line."""
    return {b["key"]: (b["state"], b.get("sha256"), b["lead_in"] if b["state"] == UPLOADED else None, b.get("source"))
            for b in blocks if b.get("kind") == SLOT_KIND}


def changed_slots(review: Any, root: Optional[Path]) -> list[str]:
    """Titles of the slots whose stored uploads no longer match what the review recorded (empty for other sections).

    A review saved before chart slots existed records none: it differs only where an image has since been uploaded."""
    section = review.section.get("section")
    if section not in SECTION_OF.values() or not review.section.get("week_ending"):
        return []
    week = Week(date.fromisoformat(review.section["week_ending"]))
    recorded = _state_of(review.section.get("blocks", []))
    now = slot_blocks(section, week, root, review.section.get("blocks", []))
    if not recorded:
        return [b["title"] for b in now if b["state"] == UPLOADED]
    return [b["title"] for b in now if _state_of([b])[b["key"]] != recorded.get(b["key"])]


def refresh(old: Any, root: Optional[Path], charts_root: Optional[Path], reason: str) -> Optional[Any]:
    """A NEW undecided review with the section's chart slots read again, or None when nothing the Word file prints changed.

    The way a sentence edit or a file fix works: the earlier review (approved or not) is never touched, items that did
    not change keep their marks, and the reason is recorded in the new review's ``revisions``."""
    from cytonn_weekly.common.review import build_review, check_section
    from cytonn_weekly.weekly.recheck import carry_marks, copy_chart_files

    if not changed_slots(old, root) and _state_of(old.section.get("blocks", [])):
        return None
    week = Week(date.fromisoformat(old.section["week_ending"]))
    others = [b for b in old.section["blocks"] if b.get("kind") != SLOT_KIND]
    revisions = [*old.section.get("revisions", []),
                 {"from_run_id": old.run_id, "was_approved": old.decision == "approved", "reason": reason,
                  "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}]
    content = {**old.section, "blocks": others + slot_blocks(old.section["section"], week, root, others), "revisions": revisions}
    new = build_review(content, check_section(content))
    new.report_type, new.period = old.report_type, old.period
    carry_marks(old, new)
    copy_chart_files(old, new, charts_root)
    return new
