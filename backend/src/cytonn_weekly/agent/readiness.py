from __future__ import annotations

from typing import Any, Optional

# The week-status classifier: a pure function over what weekly.inputs.status and weekly.analyst.status already say.  It holds no
# rule about which section needs what: that is each slot's `sections` and each item's `required`.  Every `why` is a sentence
# written here, never text from a file, a workbook or a person.

GROUPS = ("fetched", "carried_or_suggested", "needs_analyst", "optional", "in_place")


def _files(slot: dict[str, Any]) -> list[dict[str, Any]]:
    got = slot["files"] if slot.get("many") else [d["file"] for d in slot["days"]] if slot["per_day"] else [slot["file"]]
    return [f for f in got if f]


def _slot(slot: dict[str, Any]) -> tuple[str, str]:
    """(group, why) for one upload."""
    files = _files(slot)
    missing = "optional" if slot["optional"] else "needs_analyst"
    if not slot["received"]:
        return missing, "not received; fetch it or upload it" if slot["fetchable"] else "not uploaded"
    if slot.get("many"):
        return "in_place", f"{len(files)} {'file' if len(files) == 1 else 'files'} uploaded"
    if slot["per_day"] and not slot["complete"]:
        days = ", ".join(d["weekday"] for d in slot["days"] if not d["received"])
        return missing, f"missing days: {days}"
    if not slot["per_day"] and not slot["complete"]:
        return missing, "dated for another week"
    return ("fetched", "fetched by the tool") if any(f["fetched_from"] for f in files) else ("in_place", "uploaded")


def _item(item: dict[str, Any]) -> tuple[str, str]:
    """(group, why) for one form item."""
    filled = (item["rows"] if item["type"] == "table" else item["value"]) not in (None, "", [])
    workbook = item["workbook_rows"] if item["type"] == "table" else item["workbook"]
    if item["needs_confirmation"]:
        return "carried_or_suggested", ("carried from last week" if item["carried"] else "suggested") + ", not yet confirmed"
    if (item["carried"] or {}).get("from") == "fetched" and item["carried"]["whole"]:
        return "fetched", "fetched by the tool"
    if (item["carried"] or {}).get("from") == "snip" and item["carried"]["whole"]:
        return "in_place", "read from the Daily Nation page and confirmed"
    if filled:
        return "in_place", "typed"
    if workbook:
        return "in_place", "from the workbook"
    return ("needs_analyst", "nothing typed and no workbook value") if item["required"] else ("optional", "not filled")


def classify(section: str, inputs: dict[str, Any], form: Optional[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, list[dict[str, str]]] = {g: [] for g in GROUPS}
    for slot in inputs["slots"]:
        if section in slot["sections"]:
            group, why = _slot(slot)
            out[group].append({"kind": "upload", "key": slot["slug"], "label": slot["title"], "why": why,
                               **({"many": True} if slot.get("many") else {})})
    for g in (form or {}).get("groups", []):
        for item in g["items"]:
            group, why = _item(item)
            out[group].append({"kind": item["type"], "key": item["key"], "label": item["label"], "why": why})
    return {"section": section, "week_ending": inputs["week_ending"], "groups": out, "counts": {g: len(v) for g, v in out.items()}}
