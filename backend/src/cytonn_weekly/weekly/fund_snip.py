from __future__ import annotations

import hashlib
import json
import re
import statistics
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Optional

from cytonn_weekly.common import atomic
from cytonn_weekly.fixed_income.mmf import MmfYield, rank_mmf_yields
from cytonn_weekly.weekly import nse_price_list as ocr
from cytonn_weekly.weekly.inputs import InputError, inputs_root, week_dir
from cytonn_weekly.weekly.week import Week

MAX_BYTES = 10 * 1024 * 1024
MAGIC = {"png": b"\x89PNG\r\n\x1a\n", "jpeg": b"\xff\xd8\xff"}
EXTENSION = {"png": "png", "jpeg": "jpg"}
MEDIA_TYPE = {"png": "image/png", "jpeg": "image/jpeg"}
SCALES = (2.0, 3.0)   # the cut-out Unit Trusts panel is read twice at these sizes (on the 16 Oct 2026 page every row agreed)
MIN_FUNDS = 5
MAX_NAME = 120
MAX_LIST = 400
AUTO_LEFT_OUT = ("fixedincome", "special", "equity", "balanced", "bond")   # the team's rule: these funds are not in the table
SOURCE_NAME = "Daily Nation, Unit Trusts"

Word = tuple[float, float, float, float, str]
Reader = Callable[[bytes], list[dict[str, Any]]]

_FIGURE = re.compile(r"^\(?-?\d[\d,]*\.\d{1,3}%?\)?\.?$")
_CURRENCY = re.compile(r"(?i)\s*\b(usd|kenya\s*shillings?)\s*$")
_NOISE = re.compile(r"^[%\-–.]+$")


# ---------------------------------------------------------------------------
# The list of funds the report uses: one setting for every week
# ---------------------------------------------------------------------------

def match_key(name: Any) -> str:
    """A fund's name as matched between the list and the page: lower case, letters and digits only, 'MMF' as money market, no 'fund'."""
    s = re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*", "", str(name).lower()))
    s = s.replace("moneymarketfund", "moneymarket").replace("mmf", "moneymarket").replace("fund", "")
    return re.sub(r"\d+$", "", re.sub(r"(kenyashillings?|usd)+$", "", s))   # OCR sometimes joins the currency and a stray figure to the name


def _name(text: Any, what: str) -> str:
    name = " ".join(str(text).split())
    if not name or len(name) > MAX_NAME:
        raise InputError(f"{what}: a fund name is 1 to {MAX_NAME} characters")
    return name


def _settings_file(root: Optional[Path]) -> Path:
    return inputs_root(root).parent / "settings" / "fund_list.json"


def read_settings(root: Optional[Path] = None) -> dict[str, Any]:
    empty: dict[str, Any] = {"include": [], "exclude": [], "aliases": {}}
    try:
        data = json.loads(_settings_file(root).read_text(encoding="utf-8"))
        return {**empty, **{k: data[k] for k in empty if isinstance(data.get(k), type(empty[k]))}}
    except (OSError, ValueError, AttributeError):
        return empty


def check_settings(data: dict[str, Any]) -> dict[str, Any]:
    """The settings cleaned, or InputError listing every reason, one a line."""
    errors: list[str] = []
    out: dict[str, Any] = {"include": [], "exclude": [], "aliases": {}}
    for field, what in (("include", "The list of funds"), ("exclude", "The funds left out")):
        seen: set[str] = set()
        values = data.get(field) or []
        if not isinstance(values, list) or len(values) > MAX_LIST:
            errors.append(f"{what}: send up to {MAX_LIST} names")
            continue
        for raw in values:
            try:
                name = _name(raw, what)
            except InputError as exc:
                errors.append(str(exc))
                continue
            if match_key(name) in seen:
                errors.append(f"{what}: {name} is listed twice")
            seen.add(match_key(name))
            out[field].append(name)
    aliases = data.get("aliases") or {}
    if not isinstance(aliases, dict):
        errors.append("The name matches: send them as page name to list name")
        aliases = {}
    for page, listed in aliases.items():
        if listed not in out["include"]:
            errors.append(f"The name match for {page}: {listed} is not on the list of funds")
        else:
            out["aliases"][_name(page, "The name matches")] = listed
    if errors:
        raise InputError("\n".join(errors[:12]))
    return out


@atomic.locked
def write_settings(data: dict[str, Any], root: Optional[Path] = None) -> dict[str, Any]:
    clean = check_settings({**read_settings(root), **data})
    atomic.write_atomic(_settings_file(root), json.dumps(clean, indent=1))
    return clean


@atomic.locked
def decide(page_name: str, decision: str, name: Optional[str] = None, to: Optional[str] = None, root: Optional[Path] = None) -> dict[str, Any]:
    """The analyst's answer for one page fund: put it on the list (as ``name``), leave it out, or say it is a listed fund under another name (``to``)."""
    cur = read_settings(root)
    page, k = _name(page_name, "The fund"), match_key(page_name)
    cur["exclude"] = [n for n in cur["exclude"] if match_key(n) != k]
    cur["aliases"] = {p: v for p, v in cur["aliases"].items() if match_key(p) != k}
    if decision == "exclude":
        cur["exclude"].append(page)
    elif decision == "alias":
        if to not in cur["include"]:
            raise InputError(f"{to!r} is not on the list of funds")
        cur["aliases"][page] = to
    elif decision == "include":
        listed = _name(name or page, "The fund")
        if match_key(listed) not in {match_key(n) for n in cur["include"]}:
            cur["include"].append(listed)
        if match_key(listed) != k:
            cur["aliases"][page] = next(n for n in cur["include"] if match_key(n) == match_key(listed))
    else:
        raise InputError(f"no such decision {decision!r}")
    clean = check_settings(cur)
    atomic.write_atomic(_settings_file(root), json.dumps(clean, indent=1))
    return clean


def classify(name: str, currency: str, settings: dict[str, Any]) -> tuple[str, Optional[str]]:
    """(group, the list's name for it): usd, keep, excluded (by the analyst), auto (by its words) or new (not decided)."""
    if currency == "USD":
        return "usd", None
    k = match_key(name)
    listed = {match_key(n): n for n in settings["include"]}
    listed.update({match_key(p): v for p, v in settings["aliases"].items()})
    if k in listed:
        return "keep", listed[k]
    if k in {match_key(n) for n in settings["exclude"]}:
        return "excluded", None
    return ("auto", None) if any(w in k for w in AUTO_LEFT_OUT) else ("new", None)


# ---------------------------------------------------------------------------
# Reading the page: two readings of the Unit Trusts panel, a cell kept only when they agree
# ---------------------------------------------------------------------------

def _rate(text: Any) -> Optional[str]:
    t = str(text).replace("%", "").replace(",", "").strip().strip("()").rstrip(".")
    try:
        ok = Decimal(t) > 0 and Decimal(t) < 100
    except InvalidOperation:
        return None
    return t if ok else None


def _lines(words: list[Word], tol: float) -> list[list[Word]]:
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: w[1] + w[3]):
        cy = (w[1] + w[3]) / 2
        if lines and cy - sum((v[1] + v[3]) / 2 for v in lines[-1]) / len(lines[-1]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return lines


def _rows_of(words: list[Word], width: float) -> list[dict[str, Any]]:
    """Fund rows of one reading, each with its height on the page: name, currency (USD or KES) and the Annual Rate, as read.

    The Annual Rate column is the one the right-most figure of the rows that state a currency sits in; a row whose only
    figure is elsewhere (the Daily Yield) has no rate.
    """
    words = [w for w in words if not _NOISE.match(w[4].strip())]
    if not words:
        raise ValueError("no text was read from the Unit Trusts list")
    lines = []
    for line in _lines(words, max(3.0, 0.5 * statistics.median(w[3] - w[1] for w in words))):
        line.sort(key=lambda w: w[0])
        figures = [w for w in line if _FIGURE.match(w[4].strip())]
        body = " ".join(w[4].strip() for w in line if w not in figures)
        lines.append((line, figures, body, _CURRENCY.search(body)))
    edges = [max(f[2] for f in figures) for _, figures, _, m in lines if m and figures]
    if not edges:
        raise ValueError("no fund row with a currency (Kenya Shilling or USD) and a rate was found on the page")
    edge, out = statistics.median(edges), []
    for line, figures, body, m in lines:
        annual = min((w for w in figures if abs(w[2] - edge) <= 0.08 * width), key=lambda w: abs(w[2] - edge), default=None)
        name = re.sub(r"^\d{1,3}\s+", "", (body[: m.start()] if m else body).strip())   # a neighbouring cell's figure can lead the name
        if (m or annual) and re.search(r"[A-Za-z]{3}", name):
            out.append({"y": sum((w[1] + w[3]) / 2 for w in line) / len(line), "name": name.strip(),
                        "currency": ("USD" if m.group(1).lower() == "usd" else "KES") if m else "", "rate": _rate(annual[4]) if annual else None})
    return out


def rows_from_readings(readings: list[list[Word]], width: float) -> list[dict[str, Any]]:
    """The rows both readings found, a cell kept only when they agree; any other cell is unresolved (None or empty) and named."""
    a, b = (_rows_of(w, width) for w in readings)
    gaps = [y2["y"] - y1["y"] for y1, y2 in zip(a, a[1:])]
    tol = 0.4 * statistics.median(gaps) if gaps else 6.0
    rows, i, j = [], 0, 0
    while i < len(a) or j < len(b):
        x = a[i] if i < len(a) else None
        y = b[j] if j < len(b) else None
        if x and y and abs(x["y"] - y["y"]) <= tol:
            same = {"name": match_key(x["name"]) == match_key(y["name"]), "currency": x["currency"] == y["currency"],
                    "rate": x["rate"] == y["rate"]}
            row = {"name": max(x["name"], y["name"], key=lambda s: s.count(" ")) if same["name"] else x["name"],
                   "currency": x["currency"] if same["currency"] else "", "rate": x["rate"] if same["rate"] else None, "once": False}
            row["unresolved"] = [k for k, ok in same.items() if not ok or not row[k]]
            i, j = i + 1, j + 1
        else:
            lone, i, j = (x, i + 1, j) if x and (not y or x["y"] < y["y"]) else (y, i, j + 1)
            row = {"name": lone["name"], "currency": "", "rate": None, "once": True, "unresolved": ["name", "currency", "rate"]}
        rows.append(row)
    return [{"id": n, **r} for n, r in enumerate(rows)]


def _decode(data: bytes) -> Any:
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("the image could not be opened")
    return image


def _panel(image: Any, words: list[Word]) -> Any:
    """The Unit Trusts rows cut out of a whole page, found by the currency column; the image itself when it has no such column (a cropped snip)."""
    tokens = [w for w in words if re.fullmatch(r"(?i)\s*(usd|kenya\s*shillings?)\s*", w[4])]
    if len(tokens) < 5:
        return image
    height = statistics.median(w[3] - w[1] for w in tokens)
    starts = [max((w for w in words if abs((w[1] + w[3]) / 2 - (t[1] + t[3]) / 2) <= 0.6 * height and w[2] <= t[0] + 1 and not _FIGURE.match(w[4].strip())),
                  key=lambda w: w[0], default=t)[0] for t in tokens]   # the name is the last box before the currency; the names are left-aligned
    left, width = int(statistics.median(starts) - 0.01 * image.shape[1]), image.shape[1]
    return image[max(0, int(min(t[1] for t in tokens) - 4 * height)): int(max(t[3] for t in tokens) + 2 * height), max(0, left):width]


def read_page(data: bytes, engine: Optional[ocr.Engine] = None) -> list[dict[str, Any]]:
    """The fund rows of a Daily Nation page (or of a snip cut to its Unit Trusts list).  ValueError, saying why, when no fund row is found."""
    engine = engine or ocr.rapidocr_engine()
    image = _decode(data)
    panel = _panel(image, engine(image))
    readings = [[(x0 / s, y0 / s, x1 / s, y1 / s, t) for x0, y0, x1, y1, t in engine(ocr._enlarge(panel, s))] for s in SCALES]
    return rows_from_readings(readings, panel.shape[1])


# ---------------------------------------------------------------------------
# The week's image, its reading and the analyst's corrections
# ---------------------------------------------------------------------------

def _dir(week: Week, root: Optional[Path]) -> Path:
    return week_dir(week, root) / "fund_snip"


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _entry(week: Week, root: Optional[Path]) -> Optional[dict[str, Any]]:
    entry = _json(_dir(week, root) / "snip.json")
    ok = isinstance(entry, dict) and entry.get("type") in EXTENSION and re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256")))
    return entry if ok and (_dir(week, root) / f"{entry['sha256']}.{EXTENSION[entry['type']]}").is_file() else None


@atomic.locked
def store(week: Week, data: bytes, root: Optional[Path] = None) -> dict[str, Any]:
    """Keep the week's page image (judged by its first bytes), replacing an earlier one and its reading and corrections."""
    kind = next((k for k, magic in MAGIC.items() if data.startswith(magic)), None)
    if not data:
        raise InputError("The file is empty. Choose the page's image file again.")
    if len(data) > MAX_BYTES:
        raise InputError(f"The image is over the {MAX_BYTES // 1_048_576} MB limit. Save a smaller copy and upload that.")
    if kind is None:
        raise InputError("This is not a PNG or JPEG image. Save the page as a PNG or JPEG and upload that.")
    folder = _dir(week, root)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.iterdir():
        old.unlink(missing_ok=True)
    sha = hashlib.sha256(data).hexdigest()
    atomic.write_atomic(folder / f"{sha}.{EXTENSION[kind]}", data)
    entry = {"sha256": sha, "type": kind, "size": len(data), "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    atomic.write_atomic(folder / "snip.json", json.dumps(entry))
    return entry


def image(week: Week, root: Optional[Path] = None) -> Optional[tuple[bytes, str]]:
    entry = _entry(week, root)
    return ((_dir(week, root) / f"{entry['sha256']}.{EXTENSION[entry['type']]}").read_bytes(), entry["type"]) if entry else None


@atomic.locked
def remove(week: Week, root: Optional[Path] = None) -> bool:
    had = _entry(week, root) is not None
    for old in _dir(week, root).glob("*") if _dir(week, root).is_dir() else []:
        old.unlink(missing_ok=True)
    return had


def read(week: Week, root: Optional[Path] = None, reader: Reader = read_page) -> None:
    """Read the stored image (slow: OCR) and keep the reading beside it, by the image's hash.  The corrections start empty."""
    found = image(week, root)
    if found is None:
        raise InputError("No page image has been uploaded for this week.")
    rows = reader(found[0])   # outside the lock: it takes about a minute
    sha = _entry(week, root)["sha256"]
    atomic.write_atomic(_dir(week, root) / f"{sha}.read.json", json.dumps(rows))
    (_dir(week, root) / f"{sha}.edits.json").unlink(missing_ok=True)


def _edits(week: Week, entry: dict[str, Any], root: Optional[Path]) -> dict[str, Any]:
    data = _json(_dir(week, root) / f"{entry['sha256']}.edits.json")
    return data if isinstance(data, dict) else {"fixes": {}, "typed": []}


@atomic.locked
def set_edits(week: Week, fixes: dict[str, Any], typed: list[dict[str, Any]], root: Optional[Path] = None) -> None:
    """Keep the analyst's corrections to cells (by row id: name, currency, rate, or ignore the row) and the funds typed beside the page."""
    entry = _entry(week, root)
    if entry is None or not (_dir(week, root) / f"{entry['sha256']}.read.json").is_file():
        raise InputError("Read the page before correcting it.")
    errors, clean_fixes, clean_typed = [], {}, []
    for rid, fix in (fixes or {}).items():
        if not str(rid).isdigit() or not isinstance(fix, dict):
            errors.append(f"row {rid!r} is not a row of the page")
            continue
        one: dict[str, Any] = {}
        for k, v in fix.items():
            if k == "ignore":
                one["ignore"] = bool(v)
            elif k == "currency" and v in ("USD", "KES"):
                one[k] = v
            elif k == "name" and str(v).strip():
                one[k] = _name(v, f"Row {rid}")
            elif k == "rate" and _rate(v):
                one[k] = _rate(v)
            else:
                errors.append(f"row {rid}: {k} {v!r} is not usable (a rate is a percentage above 0 and below 100)")
        clean_fixes[str(rid)] = one
    listed = {match_key(n) for n in read_settings(root)["include"]}
    seen: set[str] = set()
    for t in typed or []:
        fund, rate = " ".join(str((t or {}).get("fund", "")).split()), _rate((t or {}).get("rate", ""))
        if match_key(fund) not in listed:
            errors.append(f"{fund or 'a typed fund'} is not on the list of funds")
        elif match_key(fund) in seen:
            errors.append(f"{fund} is typed twice")
        elif rate is None:
            errors.append(f"{fund}: the rate must be a percentage above 0 and below 100")
        else:
            seen.add(match_key(fund))
            clean_typed.append({"fund": fund, "rate": rate})
    if errors:
        raise InputError("\n".join(errors[:12]))
    atomic.write_atomic(_dir(week, root) / f"{entry['sha256']}.edits.json", json.dumps({"fixes": clean_fixes, "typed": clean_typed}))


# ---------------------------------------------------------------------------
# What the card shows, and what confirming keeps
# ---------------------------------------------------------------------------

def state(week: Week, root: Optional[Path] = None) -> dict[str, Any]:
    """The page as the card shows it: rows by group, counts, the list's funds the page lacks, and the analyst's typed rows."""
    settings, entry = read_settings(root), _entry(week, root)
    out: dict[str, Any] = {"image": entry, "read": False, "rows": [], "left_out": [], "usd": 0, "typed": [], "not_on_page": [], "unresolved": 0,
                           "new": 0, "kept": 0, "settings": settings, "fixes": {}, "ignored": []}
    rows = _json(_dir(week, root) / f"{entry['sha256']}.read.json") if entry else None
    if not isinstance(rows, list):
        return out
    edits = _edits(week, entry, root)
    out["read"], out["fixes"], kept = True, edits["fixes"], {}
    for row in rows:
        fix = edits["fixes"].get(str(row["id"]), {})
        if fix.get("ignore"):
            out["ignored"].append({"id": row["id"], "name": row["name"]})
            continue
        row = {**row, **{k: fix[k] for k in ("name", "currency", "rate") if k in fix}}
        row["unresolved"] = [k for k in ("name", "currency", "rate") if not row.get(k) and not (k == "rate" and row.get("currency") == "USD")]
        group, listed = classify(row["name"], row["currency"], settings) if row["name"] and row["currency"] else ("pending", None)
        if group == "usd":
            out["usd"] += 1
        elif group in ("excluded", "auto"):
            out["left_out"].append({"id": row["id"], "name": row["name"], "why": "by you" if group == "excluded" else "by its name"})
        else:
            row.update(group=group, list_name=listed, duplicate=False)
            if listed and listed in kept:
                row["duplicate"], kept[listed]["duplicate"] = True, True
            elif listed:
                kept[listed] = row
            out["rows"].append(row)
            out["unresolved"] += bool(row["unresolved"])
            out["new"] += group == "new"
    out["kept"] = len(kept)
    page_keys = {match_key(n) for n in kept}
    out["typed"] = [t for t in edits["typed"] if match_key(t["fund"]) not in page_keys]
    typed_keys = {match_key(t["fund"]) for t in out["typed"]}
    out["not_on_page"] = [n for n in settings["include"] if match_key(n) not in page_keys and match_key(n) not in typed_keys]
    return out


def confirmed_rows(week: Week, root: Optional[Path] = None) -> tuple[list[dict[str, Any]], list[str], str]:
    """The ranked fund rows for the form, the funds typed beside the page, and the note naming the image: or InputError, why not yet."""
    s, errors = state(week, root), []
    if not s["read"]:
        errors.append("Read the page first.")
    if s["unresolved"]:
        errors.append(f"{s['unresolved']} row{'s' if s['unresolved'] != 1 else ''} still have a cell that could not be read twice the same way; type it or ignore the row.")
    if s["new"]:
        errors.append(f"{s['new']} fund{'s' if s['new'] != 1 else ''} not on the list must be decided: include it or leave it out.")
    dups = sorted({r["list_name"] for r in s["rows"] if r["duplicate"]})
    if dups:
        errors.append(f"{', '.join(dups)} appear more than once on the page; ignore the extra rows.")
    if errors:
        raise InputError("\n".join(errors))
    funds = [(r["list_name"], r["rate"]) for r in s["rows"] if r["group"] == "keep"] + [(t["fund"], t["rate"]) for t in s["typed"]]
    ranked = rank_mmf_yields([MmfYield(f, float(rate)) for f, rate in funds])
    rate_of = dict(funds)
    rows = [{"rank": r["rank"], "fund": r["fund"], "rate": rate_of[r["fund"]]} for r in ranked]
    return rows, [t["fund"] for t in s["typed"]], f"{SOURCE_NAME}, image sha256 {s['image']['sha256']}"
