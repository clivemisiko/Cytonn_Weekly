from __future__ import annotations

from datetime import date
from typing import Any, Optional

from cytonn_weekly.weekly.week import day_text, week_ending_of

# The week-status classifier: a pure function over what weekly.inputs.status and weekly.analyst.status already say.  It holds no
# rule about which section needs what: that is each slot's `sections` and each item's `required`.  Every `why` is a sentence
# written here, never text from a file, a workbook or a person.

GROUPS = ("fetched", "carried_or_suggested", "needs_analyst", "optional", "in_place")


def _files(slot: dict[str, Any]) -> list[dict[str, Any]]:
    got = [d["file"] for d in slot["days"]] if slot["per_day"] else [slot["file"]]
    return [f for f in got if f]


def _other_week(found: Optional[str], ending: str) -> str:
    """Why a kept file is not counted: the week its own date falls in and the report's week, or that it has no readable date."""
    this = f"this report is for the week ending {day_text(date.fromisoformat(ending))}"
    if not found:
        return f"uploaded, but no date can be read from inside it, and {this}. It is kept, and not counted as this week's"
    day = date.fromisoformat(found)
    friday = week_ending_of(day)
    if friday.isoformat() == ending:   # in the week, but not a date this slot takes (a holiday week's Friday, say)
        return f"uploaded, but it is dated {day_text(day)}, not a date this week's report takes. It is kept, and not counted as this week's"
    dated = "" if friday == day else f" (dated {day_text(day)})"
    return f"uploaded, but it is for the week ending {day_text(friday)}{dated}, and {this}. It is kept, and not counted as this week's"


def _slot(slot: dict[str, Any], ending: str) -> tuple[str, str]:
    """(group, why) for one upload."""
    files = _files(slot)
    missing = "optional" if slot["optional"] else "needs_analyst"
    if not slot["received"]:
        return missing, "not received; fetch it or upload it" if slot["fetchable"] else "not uploaded"
    if slot["per_day"] and not slot["complete"]:
        days = ", ".join(d["weekday"] for d in slot["days"] if not d["received"])
        return missing, f"missing days: {days}"
    if not slot["per_day"] and not slot["complete"]:
        return missing, _other_week(files[0].get("read_date"), ending)
    return ("fetched", "fetched by the tool") if any(f["fetched_from"] for f in files) else ("in_place", "uploaded")


def _item(item: dict[str, Any]) -> tuple[str, str]:
    """(group, why) for one form item."""
    filled = (item["rows"] if item["type"] == "table" else item["value"]) not in (None, "", [])
    held = item["workbook_rows"] if item["type"] == "table" else item["workbook"]
    stale = item.get("workbook_stale")
    workbook = None if stale else held   # a workbook for another week covers nothing, though its value is shown
    if item["needs_confirmation"]:
        return "carried_or_suggested", ("carried from last week" if item["carried"] else "suggested") + ", not yet confirmed"
    if (item["carried"] or {}).get("from") == "fetched" and item["carried"]["whole"]:
        return "fetched", "fetched by the tool"
    if workbook and item.get("workbook_first"):
        # the fund table: the workbook's is used, and what the form holds is its second reading
        return "in_place", "from the workbook; the form's value is its second reading" if filled else "from the workbook"
    if (item["carried"] or {}).get("from") == "snip" and item["carried"]["whole"]:
        return "in_place", "read from the Daily Nation page and confirmed"
    if filled:
        return "in_place", "typed"
    if workbook:
        return "in_place", "from the workbook"
    if stale:
        # dates the reader parsed, never the workbook's own text
        expected = " or ".join(stale["expected"])
        if held or not stale.get("whole"):
            why = (f"the workbook holds it, but dated {stale['found']}; this week needs {expected}" if stale["found"]
                   else f"the workbook holds it, but its date cannot be read; this week needs {expected}")
        else:
            why = (f"not typed, and the uploaded workbook is dated {stale['found']}; this week needs {expected}" if stale["found"]
                   else f"not typed, and the uploaded workbook's date cannot be read; this week needs {expected}")
        return ("needs_analyst" if item["required"] else "optional"), why
    return ("needs_analyst", "nothing typed and no workbook value") if item["required"] else ("optional", "not filled")


def classify(section: str, inputs: dict[str, Any], form: Optional[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, list[dict[str, str]]] = {g: [] for g in GROUPS}
    for slot in inputs["slots"]:
        if section in slot["sections"]:
            group, why = _slot(slot, inputs["week_ending"])
            # what is kept, by the name the tool stored it under (never the analyst's file name: this check is a model's tool result)
            files = [{"stored_name": f["stored_name"]} for f in _files(slot)]
            out[group].append({"kind": "upload", "key": slot["slug"], "label": slot["title"], "why": why, "files": files})
    for g in (form or {}).get("groups", []):
        for item in g["items"]:
            group, why = _item(item)
            out[group].append({"kind": item["type"], "key": item["key"], "label": item["label"], "why": why})
    return {"section": section, "week_ending": inputs["week_ending"], "groups": out, "counts": {g: len(v) for g, v in out.items()}}
