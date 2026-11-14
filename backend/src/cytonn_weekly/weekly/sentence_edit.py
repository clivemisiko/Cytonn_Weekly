from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from cytonn_weekly.common.review import CARRIED_TEXT, CLAIM, ROMAN, build_review, check_section, numbered
from cytonn_weekly.digital_payments.coordinator_review import FLAGGED, HIGHLIGHT_CLAIM, CoordinatorReview, ReviewItem
from cytonn_weekly.weekly.recheck import EQUITIES, FIXED_INCOME, _module, carry_marks, copy_chart_files

MAX_CHARS = 600
# The longest carried block in the test fixtures is a few hundred characters; a real closing outlook runs to about a thousand.
MAX_PARAGRAPH_CHARS = 1200
MAX_STANDING_CHARS = 4000   # Real Estate's standing REITs text: a paragraph and its list, a line each
EDIT, REMOVE, PARAGRAPH, FINDING = "edit", "remove", "paragraph", "finding"


class SentenceError(ValueError):
    """The message is the plain sentence the reviewer reads; nothing was changed."""


class NotPossible(SentenceError):
    pass


class NotFound(SentenceError):
    pass


class TextRefused(SentenceError):
    pass


NOT_A_SENTENCE = ("Only a flagged sentence of a drafted piece can be edited or removed here, and this item is not one. "
                  "Open the item again, or reject the draft.")
NOT_A_FINDING = ("Only a finding the model drafted can be removed here, and this item is not part of one. Open the review "
                 "again, or reject the draft.")
FINDING_NOT_FOUND = ("The finding this item belongs to could not be found in the draft, so nothing was changed. Open the "
                     "review again, or reject the draft.")
FINDING_SAVE_FAILED = ("The finding could not be removed, so nothing was changed. The earlier version is still there. Try "
                       "again; if it happens again, report it with the section name.")
CARRIED_PIECE = ("This sentence is carried from another section's approved review, so it cannot be changed here. "
                 "Change it in that section, then compose this summary again.")
WOULD_EMPTY = ("Removing this sentence would leave the piece with no text. Edit the sentence instead, or reject the draft.")
NOT_FOUND = ("The sentence could not be found exactly once in the text of its piece (it may run across a link or a line "
             "break, or appear twice), so nothing was changed. Remove the whole finding, or reject the draft.")
EMPTY_TEXT = "Type the new sentence. To take the sentence out of the draft, use Remove this sentence instead."
SAME_TEXT = "The sentence is the same as before, so nothing was saved. Change it, or cancel."
NOT_PLAIN = ("Type plain text only. The characters [ ] < > * ` and \\ are not allowed, and the sentence cannot start with "
             "#, + or -, or with a number and a full stop. Remove them and save again.")
CHECK_FAILED = ("The new text could not be checked, so nothing was changed. The earlier version is still there. Try again; "
                "if it happens again, report it with the section name.")
SAVE_FAILED = ("The new version could not be saved, so nothing was changed. The earlier version is still there. Try again; "
               "if it happens again, report it with the section name.")

NOT_A_PARAGRAPH = ("Only a carried-forward paragraph can be rewritten here, and this item is not one. Open the item again, "
                   "or reject the draft.")
PARAGRAPH_NOT_FOUND = ("This carried-forward paragraph could not be found exactly once in the section, so nothing was "
                       "changed. Reject the draft instead.")
EMPTY_PARAGRAPH = "Type the new paragraph. To leave the carried text as it is, cancel."
SAME_PARAGRAPH = "The paragraph is the same as before, so nothing was saved. Change it, or cancel."
NOT_PLAIN_PARAGRAPH = ("Type plain text only. The characters [ ] < > * ` and \\ are not allowed, and the paragraph cannot "
                       "start with #, + or -, or with a number and a full stop. Remove them and save again.")

_NOT_PLAIN =re.compile(r"[\[\]<>`*\\\x00-\x1f\x7f]|\A(?:[#+-]|\d+[.)])")


@dataclass
class Edited:
    review: CoordinatorReview
    action: str
    changed_items: int


def plain(text: Optional[str], paragraph: bool = False) -> str:
    """The typed text as it will be stored: one line, single spaces (line breaks become spaces), plain text.

    A sentence is 1 to MAX_CHARS characters, a paragraph 1 to MAX_PARAGRAPH_CHARS.
    """
    t = " ".join((text or "").split())
    if not t:
        raise TextRefused(EMPTY_PARAGRAPH if paragraph else EMPTY_TEXT)
    limit = MAX_PARAGRAPH_CHARS if paragraph else MAX_CHARS
    if len(t) > limit:
        raise TextRefused(f"The {'paragraph' if paragraph else 'sentence'} is {len(t)} characters; the limit is {limit}. "
                          "Shorten it and save again.")
    if _NOT_PLAIN.search(t):
        raise TextRefused(NOT_PLAIN_PARAGRAPH if paragraph else NOT_PLAIN)
    return t


def plain_lines(text: Optional[str]) -> str:
    """Like ``plain`` for a paragraph, but each line stays a line (the standing text's list items stay separate)."""
    lines = [" ".join(line.split()) for line in (text or "").splitlines()]
    t = "\n".join(line for line in lines if line)
    if not t:
        raise TextRefused(EMPTY_PARAGRAPH)
    if len(t) > MAX_STANDING_CHARS:
        raise TextRefused(f"The text is {len(t)} characters; the limit is {MAX_STANDING_CHARS}. Shorten it and save again.")
    if any(_NOT_PLAIN.search(line) for line in t.splitlines()):
        raise TextRefused(NOT_PLAIN_PARAGRAPH)
    return t


def _where(review: CoordinatorReview, index: int) -> tuple[int, int]:
    """(block position, claim position) of the claim a flagged item stands for.

    A saved item does not record its claim, so it is found by the claim's text: the k-th item with that text is the
    k-th claim with that text, in block order (the order build_review makes items in).
    """
    items = review.review_items
    if "blocks" not in review.section or not 0 <= index < len(items):
        raise NotPossible(NOT_A_SENTENCE)
    item = items[index]
    text = item.context.get("text")
    if item.kind != CLAIM or item.status != FLAGGED or not text or "removed_at" in item.context:
        raise NotPossible(NOT_A_SENTENCE)
    found = [(bi, n) for bi, b in enumerate(review.section["blocks"]) if b.get("kind") == "narrative"
             for n, c in enumerate(b.get("claims") or []) if c.get("text") == text]
    earlier = sum(1 for i in items[:index] if i.kind == CLAIM and i.context.get("text") == text and "removed_at" not in i.context)
    if earlier >= len(found):
        raise NotPossible(NOT_A_SENTENCE)
    bi, n = found[earlier]
    if review.section["blocks"][bi].get("source_run_id") is not None:
        raise NotPossible(CARRIED_PIECE)
    return bi, n


def can_edit(review: CoordinatorReview, index: int) -> bool:
    try:
        _where(review, index)
    except NotPossible:
        return False
    return True


def _cut(text: str, piece: str) -> str:
    i = text.index(piece)
    j = i + len(piece)
    if text[j:j + 1] == " ":
        j += 1
    elif i and text[i - 1] == " ":
        i -= 1
    return re.sub(r"\n{3,}", "\n\n", (text[:i] + text[j:]).strip())


def apply(old: CoordinatorReview, index: int, action: str, text: Optional[str], charts_root: Optional[Path] = None,
          now: Optional[datetime] = None) -> Edited:
    """A new, undecided review in which one flagged sentence is rewritten or removed; ``old`` is never touched.

    The figures are checked again offline with the same checker that made the first review (no model, no network).
    SentenceError, with the reason, when the change cannot be made; nothing is saved here.
    """
    if action not in (EDIT, REMOVE):
        raise NotPossible(NOT_A_SENTENCE)
    bi, n = _where(old, index)
    new_text = plain(text) if action == EDIT else None
    content = copy.deepcopy(old.section)
    block = content["blocks"][bi]
    was = block["claims"][n]["text"]
    body_md, body = block.get("body_md") or "", block.get("body")
    if body_md.count(was) != 1 or (body is not None and body.count(was) != 1):
        raise NotFound(NOT_FOUND)
    if new_text == was:
        raise TextRefused(SAME_TEXT)
    at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    edits = block.setdefault("edits", [])
    earlier = next((e for e in edits if e["kind"] == "edited" and e["now"] == was), None)
    if earlier:
        edits.remove(earlier)
    if action == EDIT:
        block["body_md"] = body_md.replace(was, new_text)
        if body is not None:
            block["body"] = body.replace(was, new_text)
        block["claims"][n].update(text=new_text, edited_at=at, was=earlier["was"] if earlier else was)
        edits.append({"kind": "edited", "at": at, "was": earlier["was"] if earlier else was, "now": new_text})
    else:
        cut_md = _cut(body_md, was)
        if not cut_md.strip():
            raise NotPossible(WOULD_EMPTY)
        block["body_md"] = cut_md
        if body is not None:
            block["body"] = _cut(body, was)
        del block["claims"][n]
        edits.append({"kind": "removed", "at": at, "was": was})
    return _rebuilt(old, content, action, charts_root)


def _rebuilt(old: CoordinatorReview, content: dict[str, Any], action: str, charts_root: Optional[Path]) -> Edited:
    section = content.get("section")
    if section in (FIXED_INCOME, EQUITIES):   # their summary is stored when built; the other sections compose theirs at export
        content["summary"] = _module(section).compose_summary(content["blocks"])
    new = build_review(content, check_section(content))
    new.report_type, new.period = old.report_type, old.period
    copy_chart_files(old, new, charts_root)
    return Edited(new, action, carry_marks(old, new))


def _carried_at(review: CoordinatorReview, index: int) -> int:
    """Position of the carried block a CARRIED_TEXT item stands for, found by its title (the item's ref), which must be unique."""
    items = review.review_items
    if "blocks" not in review.section or not 0 <= index < len(items) or items[index].kind != CARRIED_TEXT:
        raise NotPossible(NOT_A_PARAGRAPH)
    found = [bi for bi, b in enumerate(review.section["blocks"])
             if b.get("kind") == "carried" and f"{b.get('title')} (carried forward)" == items[index].ref]
    if len(found) != 1:
        raise NotFound(PARAGRAPH_NOT_FOUND)
    if review.section["blocks"][found[0]].get("source_run_id") is not None:
        raise NotPossible(CARRIED_PIECE)
    return found[0]


def can_edit_paragraph(review: CoordinatorReview, index: int) -> bool:
    try:
        _carried_at(review, index)
    except SentenceError:
        return False
    return True


_HIGHLIGHT_REF = re.compile(r"Highlight (\S+) \(")


def _finding_at(review: CoordinatorReview, index: int) -> int:
    """Position, in ``blocks`` (or Digital Payments' ``items``), of the drafted piece a claim item belongs to.

    Found as ``_where`` finds a claim (the k-th item with a claim's text is the k-th claim with it); a piece with no claim
    has one item named after the piece.  Digital Payments' items are named "Highlight <numeral> (<company>)".
    """
    items = review.review_items
    if not 0 <= index < len(items):
        raise NotPossible(NOT_A_FINDING)
    item = items[index]
    if "blocks" not in review.section:
        m = _HIGHLIGHT_REF.match(item.ref)
        if item.kind != HIGHLIGHT_CLAIM or not m:
            raise NotPossible(NOT_A_FINDING)
        found = [n for n, it in enumerate(review.section.get("items", []))
                 if it.get("kind") == "highlight" and it.get("numeral") == m.group(1)]
        if len(found) != 1:
            raise NotFound(FINDING_NOT_FOUND)
        return found[0]
    if item.kind != CLAIM or "removed_at" in item.context:
        raise NotPossible(NOT_A_FINDING)
    blocks = review.section["blocks"]
    text = item.context.get("text")
    if text:
        found = [bi for bi, b in enumerate(blocks) if b.get("kind") == "narrative"
                 for c in b.get("claims") or [] if c.get("text") == text]
        earlier = sum(1 for i in items[:index] if i.kind == CLAIM and i.context.get("text") == text and "removed_at" not in i.context)
        if earlier >= len(found):
            raise NotFound(FINDING_NOT_FOUND)
        bi = found[earlier]
    else:   # a piece that records no cited claim has one item, named after the piece
        found = [bi for bi, b in enumerate(blocks) if b.get("kind") == "narrative" and not b.get("claims")
                 and f"{b.get('numeral', '')} {b.get('headline', '')}".strip() == item.ref]
        if len(found) != 1:
            raise NotFound(FINDING_NOT_FOUND)
        bi = found[0]
    if blocks[bi].get("source_run_id") is not None:
        raise NotPossible(CARRIED_PIECE)
    return bi


def can_remove_finding(review: CoordinatorReview, index: int) -> bool:
    try:
        _finding_at(review, index)
    except SentenceError:
        return False
    return True


def remove_finding(old: CoordinatorReview, index: int, charts_root: Optional[Path] = None,
                   now: Optional[datetime] = None) -> Edited:
    """A new, undecided review without one whole drafted piece (its text, claims and sources); ``old`` is never touched.

    The piece is recorded in ``removed_findings`` (headline and time) so the review can say something was taken out.  The
    pieces after it are numbered again when the section was numbered in order.
    """
    pos = _finding_at(old, index)
    at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    content = copy.deepcopy(old.section)
    if "blocks" not in content:
        return _dp_without(old, content, pos, at)
    blocks = content["blocks"]
    in_order = [b.get("numeral") for b in blocks] == ROMAN[:len(blocks)]
    gone = blocks.pop(pos)
    if in_order:
        content["blocks"] = numbered(blocks)
    content.setdefault("removed_findings", []).append(
        {"headline": gone.get("headline") or gone.get("topic") or gone.get("id", ""), "at": at})
    return _rebuilt(old, content, FINDING, charts_root)


def _dp_without(old: CoordinatorReview, content: dict[str, Any], pos: int, at: str) -> Edited:
    """Digital Payments' own shape: drop the highlight and its items, number the rest (and the table) again, keep every other item and its marks.

    Nothing is re-checked: a highlight's claims are never checked against anything, and the table and outlook do not change.
    """
    gone = content["items"].pop(pos)
    renamed = {}
    for n, it in enumerate(content["items"]):
        if it.get("kind") == "highlight":
            renamed[it["numeral"]] = ROMAN[n]
        it["numeral"] = ROMAN[n]
    content.setdefault("removed_findings", []).append({"headline": gone.get("headline", ""), "at": at})
    items = []
    for i in old.review_items:
        m = _HIGHLIGHT_REF.match(i.ref) if i.kind == HIGHLIGHT_CLAIM else None
        if m and m.group(1) == gone["numeral"]:
            continue
        item = ReviewItem.from_dict(copy.deepcopy(i.to_dict()))
        if m and m.group(1) in renamed:
            item.ref = f"Highlight {renamed[m.group(1)]}{i.ref[m.end(1):]}"
        items.append(item)
    new = CoordinatorReview(section=content, review_items=items, report_type=old.report_type, period=old.period)
    return Edited(new, FINDING, 0)


def apply_paragraph(old: CoordinatorReview, index: int, text: Optional[str], charts_root: Optional[Path] = None,
                    now: Optional[datetime] = None) -> Edited:
    """A new, undecided review in which one carried-forward paragraph is replaced by the reviewer's own text.

    The checker has no source for typed text, so the item becomes "not auto-verified" and the carried flag goes;
    nothing typed is compared with anything.  ``old`` is never touched.
    """
    bi = _carried_at(old, index)
    content = copy.deepcopy(old.section)
    block = content["blocks"][bi]
    standing = block.get("role") == "standing"
    new_text = plain_lines(text) if standing else plain(text, paragraph=True)
    current = block.get("body_md") or ""
    if (current.strip() if standing else " ".join(current.split())) == new_text:
        raise TextRefused(SAME_PARAGRAPH)
    at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    edits = block.setdefault("edits", [])
    edits.append({"kind": "edited", "at": at, "was": edits[0]["was"] if edits else current, "now": new_text})
    block["body_md"] = new_text
    return _rebuilt(old, content, PARAGRAPH, charts_root)
