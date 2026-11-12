from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

from cytonn_weekly import paths
from cytonn_weekly.common import atomic
from cytonn_weekly.common import sources as source_store
from cytonn_weekly.weekly.week import latest_friday

SECTORS = (("industry", "Industry reports"), ("residential", "Residential sector"), ("land", "Land"),
           ("hospitality", "Hospitality and Tourism"), ("reits", "REITs"))
LABELS = dict(SECTORS)
MAX_BYTES = 5 * 1024 * 1024
MAX_PER_SECTOR = 6
MAX_TEXT_CHARS = 20_000
UNCLEAR = re.compile(r"\[unclear[^\]]*\]", re.I)


class SnipError(ValueError):
    """Written for the analyst and shown as it stands."""


def image_type(data: bytes) -> Optional[tuple[str, str]]:
    """(extension, media type) read from the file's first bytes, never its name; None when it is not PNG, JPEG or WebP."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def has_unclear(text: str) -> bool:
    return bool(UNCLEAR.search(text or ""))


def _root(root: Optional[Path]) -> Path:
    return Path(root) if root is not None else paths.DATA_DIR / "inputs" / "snips"


def _folder(week_end: date, root: Optional[Path]) -> Path:
    return _root(root) / latest_friday(week_end).isoformat()


def _load(folder: Path) -> list[dict[str, Any]]:
    try:
        return json.loads((folder / "snips.json").read_text(encoding="utf-8"))["snips"]
    except FileNotFoundError:
        return []
    except (OSError, ValueError, KeyError):
        raise SnipError("The list of snips for this week cannot be read. Its folder is under inputs/snips in the data folder.") from None


def _save(folder: Path, items: list[dict[str, Any]]) -> None:
    atomic.write_atomic(folder / "snips.json", json.dumps({"snips": items}, indent=2))


def _cache(root: Optional[Path], h: str) -> Path:
    return _root(root) / "reads" / f"{h}.txt"


def _entry(items: list[dict[str, Any]], h: str) -> dict[str, Any]:
    found = next((e for e in items if e["hash"] == h), None)
    if found is None:
        raise SnipError("That snip is not in this week's list. Reload the page.")
    return found


def list_snips(week_end: date, root: Optional[Path] = None) -> list[dict[str, Any]]:
    return _load(_folder(week_end, root))


def image_bytes(week_end: date, h: str, root: Optional[Path] = None) -> tuple[bytes, str]:
    folder = _folder(week_end, root)
    e = _entry(_load(folder), h)
    data = (folder / f"{h}.{e['ext']}").read_bytes()
    if hashlib.sha256(data).hexdigest() != h:
        raise SnipError("The saved image no longer matches its fingerprint, so it was not used. Remove it and upload it again.")
    return data, e["media_type"]


@atomic.locked
def add(week_end: date, sector: str, filename: str, data: bytes, root: Optional[Path] = None) -> dict[str, Any]:
    """Keep one uploaded image under its content hash, in the sector the analyst chose. Nothing is read from it here."""
    if sector not in LABELS:
        raise SnipError(f"{sector!r} is not a sector. Choose one of: {', '.join(LABELS.values())}.")
    if not data:
        raise SnipError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise SnipError(f"The image is {len(data) / 1048576:.1f} MB; the limit is {MAX_BYTES // 1048576} MB. Crop it or save it smaller.")
    kind = image_type(data)
    if kind is None:
        raise SnipError("Only PNG, JPG and WebP images are accepted, and this file is none of them (its contents were checked, not its name).")
    folder = _folder(week_end, root)
    items = _load(folder)
    h = hashlib.sha256(data).hexdigest()
    if any(e["hash"] == h for e in items):
        raise SnipError("This image is already uploaded for this week.")
    if sum(e["sector"] == sector for e in items) >= MAX_PER_SECTOR:
        raise SnipError(f"{LABELS[sector]} already has {MAX_PER_SECTOR} snips, the most it takes. Remove one first.")
    atomic.write_atomic(folder / f"{h}.{kind[0]}", data)
    cached = _cache(root, h)
    text = cached.read_text(encoding="utf-8") if cached.is_file() else None   # read once, ever: the same image is not read again
    e = {"hash": h, "ext": kind[0], "media_type": kind[1], "filename": re.sub(r"[^\w .()-]", "_", filename or "")[:120] or h[:8],
         "sector": sector, "text": text, "date": "", "confirmed": False, "source_id": ""}
    _save(folder, items + [e])
    return e


def reading(week_end: date, h: str, text: str, root: Optional[Path] = None) -> dict[str, Any]:
    """Keep the transcription the model returned: in the read cache (by image hash) and on the snip."""
    text = text.strip() or "[unclear]"
    atomic.write_atomic(_cache(root, h), text)
    return _edit(week_end, h, root, lambda e: e.update(text=text))


@atomic.locked
def _edit(week_end: date, h: str, root: Optional[Path], change) -> dict[str, Any]:
    folder = _folder(week_end, root)
    items = _load(folder)
    e = _entry(items, h)
    change(e)
    _save(folder, items)
    return e


def _unconfirm(e: dict[str, Any], sources_root: Optional[Path]) -> None:
    if e["confirmed"]:
        source_store.remove(e["source_id"], sources_root)
        e["confirmed"], e["source_id"] = False, ""


@atomic.locked
def update(week_end: date, h: str, *, text: Optional[str], sector: Optional[str], date_text: Optional[str],
           root: Optional[Path] = None, sources_root: Optional[Path] = None) -> dict[str, Any]:
    """Change a snip's text, sector or date. A confirmed snip goes back to unconfirmed: what was confirmed is not what it says now."""
    folder = _folder(week_end, root)
    items = _load(folder)
    e = _entry(items, h)
    if sector is not None and sector != e["sector"]:
        if sector not in LABELS:
            raise SnipError(f"{sector!r} is not a sector.")
        if sum(x["sector"] == sector for x in items) >= MAX_PER_SECTOR:
            raise SnipError(f"{LABELS[sector]} already has {MAX_PER_SECTOR} snips. Remove one first.")
    if text is not None and len(text) > MAX_TEXT_CHARS:
        raise SnipError(f"The text is longer than {MAX_TEXT_CHARS:,} characters. Crop the snip into smaller ones.")
    if date_text:
        try:
            date.fromisoformat(date_text.strip())
        except ValueError:
            raise SnipError("Write the date as YYYY-MM-DD (for example 2026-11-06), or leave it empty.") from None
    _unconfirm(e, sources_root)
    if sector is not None:
        e["sector"] = sector
    if text is not None and e["text"] is not None:
        e["text"] = text
    if date_text is not None:
        e["date"] = date_text.strip()
    _save(folder, items)
    return e


@atomic.locked
def confirm(week_end: date, h: str, root: Optional[Path] = None, sources_root: Optional[Path] = None) -> dict[str, Any]:
    """Make the snip a saved source (origin "snip") for its sector. Refused while it is unread, empty or has an [unclear] mark."""
    folder = _folder(week_end, root)
    items = _load(folder)
    e = _entry(items, h)
    if not (e["text"] or "").strip():
        raise SnipError("This snip has not been read yet.")
    if has_unclear(e["text"]):
        raise SnipError("Resolve every [unclear] mark in the text (type what the image shows, or delete the mark), then confirm.")
    _unconfirm(e, sources_root)
    data, _ = image_bytes(week_end, h, root)
    src = source_store.from_snip(data, "." + e["ext"], e["text"], LABELS[e["sector"]], week_end,
                                 e["date"] or latest_friday(week_end).isoformat(), e["filename"], root=sources_root)
    e["confirmed"], e["source_id"] = True, src.id
    _save(folder, items)
    return e


@atomic.locked
def remove(week_end: date, h: str, root: Optional[Path] = None, sources_root: Optional[Path] = None) -> None:
    folder = _folder(week_end, root)
    items = _load(folder)
    e = _entry(items, h)
    _unconfirm(e, sources_root)
    (folder / f"{h}.{e['ext']}").unlink(missing_ok=True)
    _save(folder, [x for x in items if x["hash"] != h])
