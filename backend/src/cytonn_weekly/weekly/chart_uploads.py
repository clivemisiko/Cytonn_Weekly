from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from cytonn_weekly.weekly.inputs import InputError, week_dir
from cytonn_weekly.weekly.week import Week

MAX_BYTES = 5 * 1024 * 1024
MAX_LEAD_IN = 600
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
# Printed above an uploaded chart when the analyst typed no sentence of their own. The captions are not used here:
# some are notes for the team ("uncaptioned chart under ...") that must never reach the Word file.
DEFAULT_LEAD_INS = {
    "tbill_91_growth": "The chart below shows the change in the monthly average 91-day T-bill yield.",
    "tbill_yields": "The chart below shows the 91-day, 182-day and 364-day T-bill yields.",
    "tbill_subscription": "The chart below shows T-bill subscription rates.",
    "money_market": "The chart below shows money market yields.",
    "interbank": "The chart below shows interbank rates.",
    "import_cover": "The chart below shows months of import cover.",
    "nasi_pe": "The chart below shows the NASI price to earnings ratio.",
    "nasi_yield": "The chart below shows the NASI dividend yield.",
}


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


def store(week: Week, key: str, data: bytes, root: Optional[Path] = None) -> None:
    """Keep the image as ``<key>.png`` or ``<key>.jpg``, replacing the slot's earlier image."""
    _known(key)
    kind = image_type(data)
    folder = _folder(week, root)
    folder.mkdir(parents=True, exist_ok=True)
    for ext in EXTENSION.values():
        (folder / f"{key}.{ext}").unlink(missing_ok=True)
    (folder / f"{key}.{EXTENSION[kind]}").write_bytes(data)
    meta = _read(week, root)
    meta[key] = {**meta.get(key, {}), "type": kind, "size": len(data),
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


def status(week: Week, root: Optional[Path] = None) -> list[dict[str, Any]]:
    meta = _read(week, root)
    out = []
    for s in slots():
        stored = _stored(week, s["key"], meta, root)
        out.append({"key": s["key"], "section": s["section"], "title": s["title"], "default_lead_in": DEFAULT_LEAD_INS[s["key"]],
                    "lead_in": meta.get(s["key"], {}).get("lead_in", ""), "has_image": stored is not None,
                    "type": stored[1] if stored else None, "size": stored[0].stat().st_size if stored else None})
    return out


def missing(week: Optional[Week], root: Optional[Path] = None) -> int:
    """Slots with no image; with no week named, none can be used, so every slot."""
    return len(KEYS) if week is None else sum(not s["has_image"] for s in status(week, root))
