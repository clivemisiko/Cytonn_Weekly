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
    """Why a kept file is not counted, in plain words: that it is for another week (or has no readable date), what the draft
    does with it, and to upload this week's.  Every date is written with day_text, as the screen writes it."""
    this = f"this report is for the week ending {day_text(date.fromisoformat(ending))}"
    upload = "Upload this week's workbook."
    if not found:
        return f"uploaded, but no date can be read from inside it, so it may be for another week, and {this}. The draft ignores it. {upload}"
    day = date.fromisoformat(found)
    friday = week_ending_of(day)
    # WeeklyInputs.earlier: a draft ignores a workbook for an earlier week; one for a later week, or this week's on a date the
    # slot does not take, is still read, warned
    read = "The draft still reads it, so check every value taken from it."
    if friday.isoformat() == ending:   # in the week, but not a date this slot takes (a holiday week's Friday, say)
        return f"uploaded, but it is dated {day_text(day)}, not a date this week's report takes. {read} {upload}"
    dated = "" if friday == day else f" (dated {day_text(day)})"
    does = "The draft ignores it." if friday.isoformat() < ending else read
    return f"uploaded, but it is for another week: the week ending {day_text(friday)}{dated}, and {this}. {does} {upload}"


def _slot(slot: dict[str, Any], ending: str) -> tuple[str, str, bool]:
    """(group, why, for another week) for one upload."""
    files = _files(slot)
    missing = "optional" if slot["optional"] else "needs_analyst"
    if not slot["received"]:
        return missing, "not received; fetch it or upload it" if slot["fetchable"] else "not uploaded", False
    if slot["per_day"] and not slot["complete"]:
        days = ", ".join(d["weekday"] for d in slot["days"] if not d["received"])
        return missing, f"missing days: {days}", False
    if not slot["per_day"] and not slot["complete"]:
        return missing, _other_week(files[0].get("read_date"), ending), True
    return ("fetched", "fetched by the tool", False) if any(f["fetched_from"] for f in files) else ("in_place", "uploaded", False)


def _item(item: dict[str, Any]) -> tuple[str, str, bool]:
    """(group, why, held for another week) for one form item."""
    filled = (item["rows"] if item["type"] == "table" else item["value"]) not in (None, "", [])
    held = item["workbook_rows"] if item["type"] == "table" else item["workbook"]
    stale = item.get("workbook_stale")
    workbook = None if stale else held   # a workbook for another week covers nothing, though its value is shown
    if item["needs_confirmation"]:
        return "carried_or_suggested", ("carried from last week" if item["carried"] else "suggested") + ", not yet confirmed", False
    if (item["carried"] or {}).get("from") == "fetched" and item["carried"]["whole"]:
        return "fetched", "fetched by the tool", False
    if workbook and item.get("workbook_first"):
        # the fund table: the workbook's is used, and what the form holds is its second reading
        return "in_place", "from the workbook; the form's value is its second reading" if filled else "from the workbook", False
    if (item["carried"] or {}).get("from") == "snip" and item["carried"]["whole"]:
        return "in_place", "read from the Daily Nation page and confirmed", False
    if filled:
        return "in_place", "typed", False
    if workbook:
        return "in_place", "from the workbook", False
    if stale:
        # dates the reader parsed, never the workbook's own text
        expected = " or ".join(day_text(date.fromisoformat(d)) for d in stale["expected"])
        found = stale["found"] and day_text(date.fromisoformat(stale["found"]))
        if held or not stale.get("whole"):
            why = (f"the workbook holds it, but dated {found}; this week needs {expected}" if found
                   else f"the workbook holds it, but its date cannot be read; this week needs {expected}")
        else:
            why = (f"not typed, and the uploaded workbook is dated {found}; this week needs {expected}" if found
                   else f"not typed, and the uploaded workbook's date cannot be read; this week needs {expected}")
        return ("needs_analyst" if item["required"] else "optional"), why, True
    return ("needs_analyst", "nothing typed and no workbook value", False) if item["required"] else ("optional", "not filled", False)


def classify(section: str, inputs: dict[str, Any], form: Optional[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, list[dict[str, Any]]] = {g: [] for g in GROUPS}
    for slot in inputs["slots"]:
        if section in slot["sections"]:
            group, why, other = _slot(slot, inputs["week_ending"])
            # what is kept, by the name the tool stored it under (never the analyst's file name: this check is a model's tool result)
            files = [{"stored_name": f["stored_name"]} for f in _files(slot)]
            out[group].append({"kind": "upload", "key": slot["slug"], "label": slot["title"], "why": why, "files": files, "other_week": other})
    for g in (form or {}).get("groups", []):
        for item in g["items"]:
            group, why, other = _item(item)
            out[group].append({"kind": item["type"], "key": item["key"], "label": item["label"], "why": why, "other_week": other})
    return {"section": section, "week_ending": inputs["week_ending"], "groups": out, "counts": {g: len(v) for g, v in out.items()}}
