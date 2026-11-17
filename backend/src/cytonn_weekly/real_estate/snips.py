from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from cytonn_weekly import paths
from cytonn_weekly.common import atomic
from cytonn_weekly.common import sources as source_store
from cytonn_weekly.common.checks import normalise_quote
from cytonn_weekly.weekly.week import latest_friday

SECTORS = (("industry", "Industry reports"), ("residential", "Residential sector"), ("land", "Land"),
           ("hospitality", "Hospitality and Tourism"), ("reits", "REITs"))
LABELS = dict(SECTORS)
MAX_BYTES = 5 * 1024 * 1024
MAX_PER_SECTOR = 6
MAX_TEXT_CHARS = 20_000
UNCLEAR = re.compile(r"\[unclear[^\]]*\]", re.I)
PDF_MAX_BYTES = 20 * 1024 * 1024
PDF_MAX_PAGES = 60
OCR_BELOW_CHARS = 30      # a page with less selectable text than this is read by OCR instead
CHUNK_CHARS = 80_000      # page text per model call, about 20k tokens, so a call stays near 25k input tokens with the prompt
OCR_NOTE = "read by OCR, check the text"


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


_DEFAULT_ROOT: Optional[Path] = None   # tests point this at a temp folder, as the sources and charts stores do


def _root(root: Optional[Path]) -> Path:
    return Path(root) if root is not None else _DEFAULT_ROOT or paths.DATA_DIR / "inputs" / "snips"


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


NEIGHBOUR_DAYS = 14   # a folder this close to the draft's Friday is named when it holds snips the draft will not read


def _name(e: dict[str, Any]) -> str:
    return f"\"{e.get('filename') or e['hash'][:8]}\""


def unconfirmed_lines(items: list[dict[str, Any]]) -> list[str]:
    """One line per snip that is uploaded and not confirmed: a draft does not read it."""
    return [f"{LABELS[e['sector']]}: the snip {_name(e)} is uploaded but not confirmed, so this draft does not use it. "
            "Read and confirm it on the start screen, then draft again." for e in items if not e["confirmed"]]


def misfiled_lines(week_end: date, root: Optional[Path] = None, sources_root: Optional[Path] = None) -> list[str]:
    """Snips the draft will not read although they exist: filed under another Friday within two weeks, and confirmed snips whose
    saved source is not filed under their sector this week (so that sector's draft does not see them)."""
    friday = latest_friday(week_end)
    lines = []
    base = _root(root)
    for folder in sorted(base.iterdir()) if base.is_dir() else []:
        try:
            other = date.fromisoformat(folder.name)
        except ValueError:
            continue
        if other != friday and abs((other - friday).days) <= NEIGHBOUR_DAYS:
            held = _load(folder)
            if held:
                lines.append(f"{len(held)} {'snip is' if len(held) == 1 else 'snips are'} filed under the week ending {other.isoformat()} "
                             f"({', '.join(sorted({LABELS[e['sector']] for e in held}))}), not this draft's week ending "
                             f"{friday.isoformat()}, so {'it is' if len(held) == 1 else 'they are'} not used.")
    for e in _load(_folder(week_end, root)):
        if e["confirmed"]:
            try:
                saved = {x.id for x in source_store.list_for(LABELS[e["sector"]], friday, sources_root)}
            except source_store.SourceError as exc:   # a saved file changed: said as it stands
                lines.append(f"{LABELS[e['sector']]}: {exc}")
                continue
            if not set(e.get("source_ids") or [e.get("source_id")]) <= saved:
                lines.append(f"{LABELS[e['sector']]}: the confirmed snip {_name(e)} has no saved source filed under this sector for "
                             f"the week ending {friday.isoformat()}, so this draft does not use it. Confirm it again.")
    return lines


def problems(week_end: date, root: Optional[Path] = None, sources_root: Optional[Path] = None) -> list[str]:
    """Every reason an uploaded snip will not be read by the draft for this week; drafting still goes ahead."""
    return [*unconfirmed_lines(_load(_folder(week_end, root))), *misfiled_lines(week_end, root, sources_root)]


def _file_sha(e: dict[str, Any]) -> str:
    """The fingerprint of the stored file: an image's entry hash is its file's; a PDF's entry is per sector (file_sha)."""
    return e.get("file_sha") or e["hash"]


def image_bytes(week_end: date, h: str, root: Optional[Path] = None) -> tuple[bytes, str]:
    folder = _folder(week_end, root)
    e = _entry(_load(folder), h)
    data = (folder / f"{_file_sha(e)}.{e['ext']}").read_bytes()
    if hashlib.sha256(data).hexdigest() != _file_sha(e):
        raise SnipError("The saved file no longer matches its fingerprint, so it was not used. Remove it and upload it again.")
    return data, e["media_type"]


def _clean_name(filename: str, h: str) -> str:
    return re.sub(r"[^\w .()-]", "_", filename or "")[:120] or h[:8]


def _open_pdf(data: bytes):
    """The PDF opened with pdfplumber (which runs nothing in it and follows no link), or SnipError saying why not."""
    import pdfplumber
    from pdfminer.pdfdocument import PDFPasswordIncorrect

    try:
        pdf = pdfplumber.open(io.BytesIO(data))
        n = len(pdf.pages)
    except PDFPasswordIncorrect:
        raise SnipError("This PDF is password protected. Save a copy without the password and upload that.") from None
    except Exception:  # noqa: BLE001 - pdfminer raises many kinds for a damaged file
        raise SnipError("This PDF is damaged and cannot be read. Save it again from its source and upload the new copy.") from None
    if getattr(pdf.doc, "encryption", None):
        pdf.close()
        raise SnipError("This PDF is encrypted. Save a copy without encryption and upload that.")
    if n == 0:
        pdf.close()
        raise SnipError("This PDF has no pages.")
    if n > PDF_MAX_PAGES:
        pdf.close()
        raise SnipError(f"This PDF has {n} pages; the limit is {PDF_MAX_PAGES}. Upload only the pages about this sector.")
    return pdf


def _add_pdf(week_end: date, sector: str, filename: str, data: bytes, root: Optional[Path]) -> dict[str, Any]:
    if len(data) > PDF_MAX_BYTES:
        raise SnipError(f"The PDF is {len(data) / 1048576:.1f} MB; the limit is {PDF_MAX_BYTES // 1048576} MB.")
    with _open_pdf(data) as pdf:
        pages = len(pdf.pages)
    folder = _folder(week_end, root)
    items = _load(folder)
    sha = hashlib.sha256(data).hexdigest()
    h = hashlib.sha256(f"{sha}:{sector}".encode()).hexdigest()   # one entry per sector: the same PDF may serve two sectors
    if any(e["hash"] == h for e in items):
        raise SnipError(f"This PDF is already uploaded for {LABELS[sector]} this week.")
    if sum(e["sector"] == sector for e in items) >= MAX_PER_SECTOR:
        raise SnipError(f"{LABELS[sector]} already has {MAX_PER_SECTOR} snips, the most it takes. Remove one first.")
    atomic.write_atomic(folder / f"{sha}.pdf", data)
    cached = _cache(root, h).with_suffix(".json")
    read = json.loads(cached.read_text(encoding="utf-8")) if cached.is_file() else None
    e = {"hash": h, "file_sha": sha, "kind": "pdf", "ext": "pdf", "media_type": "application/pdf",
         "filename": _clean_name(filename, sha), "size": len(data), "pages": pages,
         "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sector": sector,
         "text": None, "passages": [], "dropped": 0, "ocr_pages": [], "date": "", "confirmed": False, "source_id": ""}
    if read:
        _apply_pdf_reading(e, read)
    _save(folder, items + [e])
    return e


def pdf_pages(week_end: date, h: str, root: Optional[Path] = None,
              ocr: Optional[Callable[[Any], list]] = None) -> tuple[list[str], list[int]]:
    """Each page's text (pdfplumber), and the pages read by OCR because they held under OCR_BELOW_CHARS selectable
    characters. Kept by the file's hash in the read cache, so a PDF is extracted once."""
    data, _ = image_bytes(week_end, h, root)
    cached = _root(root) / "reads" / f"{hashlib.sha256(data).hexdigest()}.pages.json"
    if cached.is_file():
        got = json.loads(cached.read_text(encoding="utf-8"))
        return got["pages"], got["ocr_pages"]
    texts, ocr_pages = [], []
    with _open_pdf(data) as pdf:
        for n, page in enumerate(pdf.pages, 1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception:  # noqa: BLE001 - pdfminer finds some damage only when it reads a page
                raise SnipError(f"Page {n} of this PDF is damaged and cannot be read. Save it again from its source and "
                                "upload the new copy.") from None
            if len(text) < OCR_BELOW_CHARS:
                try:
                    text = _ocr_page(page, ocr)
                except Exception:  # noqa: BLE001 - the OCR package missing, or a page it cannot render
                    raise SnipError(f"Page {n} has no selectable text and the OCR could not read it. Upload the other pages, "
                                    "or a snip of that page.") from None
                ocr_pages.append(n)
            texts.append(text)
    atomic.write_atomic(cached, json.dumps({"pages": texts, "ocr_pages": ocr_pages}))
    return texts, ocr_pages


def _ocr_page(page: Any, ocr: Optional[Callable[[Any], list]]) -> str:
    """One page through the project's OCR (RapidOCR, as for the NSE price list), its words joined line by line."""
    import numpy as np

    from cytonn_weekly.weekly.nse_price_list import DPI, rapidocr_engine

    image = np.array(page.to_image(resolution=DPI).original.convert("RGB"))[:, :, ::-1].copy()
    words = sorted((ocr or rapidocr_engine())(image), key=lambda w: (round(w[1] / 15), w[0]))   # ponytail: rows by 15px bands
    lines: dict[int, list[str]] = {}
    for x0, y0, _x1, _y1, text in words:
        lines.setdefault(round(y0 / 15), []).append(text)
    return "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))


def pdf_chunks(pages: list[str]) -> list[str]:
    """The page texts as page-labelled chunks of at most CHUNK_CHARS (a longer page is a chunk of its own)."""
    chunks, current = [], ""
    for n, text in enumerate(pages, 1):
        part = f"[Page {n}]\n{text}\n\n"
        if current and len(current) + len(part) > CHUNK_CHARS:
            chunks.append(current)
            current = ""
        current += part
    return chunks + [current] if current else chunks


def check_passages(found: list[dict[str, Any]], pages: list[str]) -> tuple[list[dict[str, Any]], int]:
    """Keep only passages whose quote is word for word on the page they name (the quote check's normalising); count the rest."""
    kept, dropped, seen = [], 0, set()
    for p in found:
        quote, page = " ".join(str(p.get("quote") or "").split()), p.get("page")
        ok = isinstance(page, int) and 1 <= page <= len(pages) and quote and normalise_quote(quote) in normalise_quote(" ".join(pages[page - 1].split()))
        if not ok:
            dropped += 1
        elif (page, quote) not in seen:
            seen.add((page, quote))
            kept.append({"page": page, "quote": quote})
    return sorted(kept, key=lambda p: p["page"]), dropped


def _apply_pdf_reading(e: dict[str, Any], read: dict[str, Any]) -> None:
    e["passages"], e["dropped"], e["ocr_pages"] = read["passages"], read["dropped"], read["ocr_pages"]
    e["text"] = "\n\n".join(f"Page {p['page']}: {p['quote']}" for p in read["passages"])   # "" when nothing was found


def pdf_reading(week_end: date, h: str, read: dict[str, Any], root: Optional[Path] = None) -> dict[str, Any]:
    """Keep the checked passages: in the read cache (by entry hash) and on the snip."""
    atomic.write_atomic(_cache(root, h).with_suffix(".json"), json.dumps(read))
    return _edit(week_end, h, root, lambda e: _apply_pdf_reading(e, read))


@atomic.locked
def add(week_end: date, sector: str, filename: str, data: bytes, root: Optional[Path] = None) -> dict[str, Any]:
    """Keep one uploaded image (under its content hash) or PDF, in the sector the analyst chose. Nothing is read from it here."""
    if sector not in LABELS:
        raise SnipError(f"{sector!r} is not a sector. Choose one of: {', '.join(LABELS.values())}.")
    if not data:
        raise SnipError("The file is empty.")
    if data.startswith(b"%PDF-"):
        return _add_pdf(week_end, sector, filename, data, root)
    if len(data) > MAX_BYTES:
        raise SnipError(f"The image is {len(data) / 1048576:.1f} MB; the limit is {MAX_BYTES // 1048576} MB. Crop it or save it smaller.")
    kind = image_type(data)
    if kind is None:
        raise SnipError("Only PNG, JPG and WebP images and PDFs are accepted, and this file is none of them (its contents were checked, not its name).")
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
        for sid in e.get("source_ids") or [e["source_id"]]:   # a PDF is one source per page with passages
            source_store.remove(sid, sources_root)
        e["confirmed"], e["source_id"], e["source_ids"] = False, "", []


@atomic.locked
def update(week_end: date, h: str, *, text: Optional[str], sector: Optional[str], date_text: Optional[str],
           root: Optional[Path] = None, sources_root: Optional[Path] = None) -> dict[str, Any]:
    """Change a snip's text, sector or date. A confirmed snip goes back to unconfirmed: what was confirmed is not what it says now."""
    folder = _folder(week_end, root)
    items = _load(folder)
    e = _entry(items, h)
    if e.get("kind") == "pdf" and text is not None and text != e["text"]:
        raise SnipError("A PDF's passages are quoted word for word from it and cannot be edited. Remove the PDF if they are wrong.")
    if e.get("kind") == "pdf" and sector is not None and sector != e["sector"]:
        raise SnipError("A PDF is read for the sector it was uploaded to. Upload it again under the other sector instead.")
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
    if e.get("kind") == "pdf":
        return _confirm_pdf(week_end, folder, items, e, root, sources_root)
    if not (e["text"] or "").strip():
        raise SnipError("This snip has not been read yet.")
    if has_unclear(e["text"]):
        raise SnipError("Resolve every [unclear] mark in the text (type what the image shows, or delete the mark), then confirm.")
    _unconfirm(e, sources_root)
    data, _ = image_bytes(week_end, h, root)
    # With no typed date the snip is saved with the report Friday, so it counts as dated: a draft's date window
    # (bedrock_provider.within_window) judges it by that day and never flags it "No date on this source".
    src = source_store.from_snip(data, "." + e["ext"], e["text"], LABELS[e["sector"]], week_end,
                                 e["date"] or latest_friday(week_end).isoformat(), e["filename"], root=sources_root,
                                 typed_date=bool(e["date"]))
    e["confirmed"], e["source_id"] = True, src.id
    _save(folder, items)
    return e


def _confirm_pdf(week_end: date, folder: Path, items: list[dict[str, Any]], e: dict[str, Any],
                 root: Optional[Path], sources_root: Optional[Path]) -> dict[str, Any]:
    """One saved source (origin "snip") per page that has passages, labelled "uploaded PDF, page N", so a claim's citation
    names its page. The source's text is that page's passages, each word for word from the page."""
    if e["text"] is None:
        raise SnipError("This PDF has not been read yet.")
    if not e["passages"]:
        raise SnipError(f"No passage about {LABELS[e['sector']]} was found in this PDF, so there is nothing to confirm. Remove it.")
    _unconfirm(e, sources_root)
    image_bytes(week_end, e["hash"], root)   # the stored file still matches its fingerprint
    by_page: dict[int, list[str]] = {}
    for p in e["passages"]:
        by_page.setdefault(p["page"], []).append(p["quote"])
    ids = [source_store.from_snip(None, "", "\n\n".join(quotes), LABELS[e["sector"]], week_end,
                                  e["date"] or latest_friday(week_end).isoformat(), f"{e['filename']}, uploaded PDF, page {n}",
                                  page=n, file_sha=e["file_sha"], root=sources_root, typed_date=bool(e["date"])).id
           for n, quotes in sorted(by_page.items())]
    e["confirmed"], e["source_id"], e["source_ids"] = True, ids[0], ids
    _save(folder, items)
    return e


@atomic.locked
def remove(week_end: date, h: str, root: Optional[Path] = None, sources_root: Optional[Path] = None) -> None:
    folder = _folder(week_end, root)
    items = _load(folder)
    e = _entry(items, h)
    _unconfirm(e, sources_root)
    rest = [x for x in items if x["hash"] != h]
    if not any(_file_sha(x) == _file_sha(e) for x in rest):   # the same PDF may still serve another sector
        (folder / f"{_file_sha(e)}.{e['ext']}").unlink(missing_ok=True)
    _save(folder, rest)
