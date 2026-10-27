from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from cytonn_weekly.common.review import CLAIM, build_review, check_section
from cytonn_weekly.digital_payments.coordinator_review import FLAGGED, CoordinatorReview
from cytonn_weekly.weekly.recheck import carry_marks, copy_chart_files

MAX_CHARS = 600
EDIT, REMOVE = "edit", "remove"


class SentenceError(ValueError):
    """The message is the plain sentence the reviewer reads; nothing was changed."""


class NotPossible(SentenceError):
    pass


class NotFound(SentenceError):
    pass


class TextRefused(SentenceError):
    pass


NOT_A_SENTENCE = ("Only a flagged sentence of a drafted piece can be edited or removed here, and this item is not one. "
                  "Open the item again, or mark it Fix needed.")
CARRIED_PIECE = ("This sentence is carried from another section's approved review, so it cannot be changed here. "
                 "Change it in that section, then compose this summary again.")
WOULD_EMPTY = ("Removing this sentence would leave the piece with no text. Edit the sentence instead, or reject the draft.")
NOT_FOUND = ("The sentence could not be found exactly once in the text of its piece (it may run across a link or a line "
             "break, or appear twice), so nothing was changed. Mark the item Fix needed with a note, or reject the draft.")
EMPTY_TEXT = "Type the new sentence. To take the sentence out of the draft, use Remove this sentence instead."
SAME_TEXT = "The sentence is the same as before, so nothing was saved. Change it, or cancel."
NOT_PLAIN = ("Type plain text only. The characters [ ] < > * ` and \\ are not allowed, and the sentence cannot start with "
             "#, + or -, or with a number and a full stop. Remove them and save again.")
CHECK_FAILED = ("The new text could not be checked, so nothing was changed. The earlier version is still there. Try again; "
                "if it happens again, report it with the section name.")
SAVE_FAILED = ("The new version could not be saved, so nothing was changed. The earlier version is still there. Try again; "
               "if it happens again, report it with the section name.")

_NOT_PLAIN = re.compile(r"[\[\]<>`*\\\x00-\x1f\x7f]|\A(?:[#+-]|\d+[.)])")


@dataclass
class Edited:
    review: CoordinatorReview
    action: str
    changed_items: int


def plain(text: Optional[str]) -> str:
    """The typed sentence as it will be stored: one line, single spaces, plain text, 1 to MAX_CHARS characters."""
    t = " ".join((text or "").split())
    if not t:
        raise TextRefused(EMPTY_TEXT)
    if len(t) > MAX_CHARS:
        raise TextRefused(f"The sentence is {len(t)} characters; the limit is {MAX_CHARS}. Shorten it and save again.")
    if _NOT_PLAIN.search(t):
        raise TextRefused(NOT_PLAIN)
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
    new = build_review(content, check_section(content))
    new.report_type, new.period = old.report_type, old.period
    copy_chart_files(old, new, charts_root)
    return Edited(new, action, carry_marks(old, new))
