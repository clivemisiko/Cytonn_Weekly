"""The problems an API error can carry, in one place.

An error body is ``{"detail": "<the sentence>"}`` as it always was; a failure that stops a whole action, or that
belongs to a part of the screen, adds ``"problems": [{"code", "headline", "target"}]``.  A client that ignores
``problems`` is unchanged.  ``code`` is stable and says what failed; ``headline`` is a short line for a dialog
(the full sentence stays in ``detail``); ``target`` names the part of the screen the failure belongs to
(``TARGETS``), or is null when it belongs to none.  Every ``ProblemError`` in api/main.py names a code from
``PROBLEMS``, and a test holds the table and the call sites together.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

# The parts of the screen a problem can point at (the ids a later step puts on them).
TARGETS = ("inputs-panel", "week-picker", "analyst-form", "start-draft", "review-status-bar", "export-bar")

# code: (headline, target)
PROBLEMS: dict[str, tuple[str, Optional[str]]] = {
    "upload_refused": ("A file was not added", "inputs-panel"),
    "upload_too_big": ("A file is too big", "inputs-panel"),
    "note_refused": ("The note was not saved", "inputs-panel"),
    "week_not_valid": ("That week cannot be used", "week-picker"),
    "analyst_refused": ("Some values were not saved", "analyst-form"),
    "analyst_nothing_to_carry": ("Nothing to start from", "analyst-form"),
    "analyst_suggestion_unavailable": ("No suggestion could be made", "analyst-form"),
    "bulletin_not_published": ("The bulletin is not published yet", "inputs-panel"),
    "bulletin_fetch_failed": ("The bulletin could not be fetched", "inputs-panel"),
    "draft_section_unavailable": ("This section cannot be drafted yet", "start-draft"),
    "draft_topic_missing": ("Type the topic before you start the draft", "start-draft"),
    "draft_topic_invalid": ("The topic is too long", "start-draft"),
    "draft_text_missing": ("Paste the text before you start the draft", "start-draft"),
    "drafting_off": ("Drafting is switched off", "start-draft"),
    "draft_busy": ("Another draft is running", "start-draft"),
    "draft_already_running": ("This section is already being drafted", "start-draft"),
    "draft_mode_changed": ("The drafting mode changed", "start-draft"),
    "draft_discarded": ("The draft was replaced", "start-draft"),
    "draft_sections_not_approved": ("Other sections are not approved yet", "start-draft"),
    "draft_input_invalid": ("This input cannot be drafted: check what you typed", "start-draft"),
    "draft_failed": ("The draft stopped", "start-draft"),
    "review_already_decided": ("This section was already decided", "review-status-bar"),
    "review_not_decidable": ("The decision was not recorded", "review-status-bar"),
    "review_not_found": ("The review was not found", None),
    "run_unknown": ("The draft run is no longer known", None),
    "export_not_ready": ("The report cannot be exported yet", "export-bar"),
}


class ProblemError(HTTPException):
    """An HTTPException whose body also lists the problem.  ``detail`` and the status are exactly as for HTTPException."""

    def __init__(self, status_code: int, detail: str, code: str) -> None:
        headline, target = PROBLEMS[code]   # an unknown code fails when it is written, not when it is first hit
        super().__init__(status_code, detail)
        self.problems = [{"code": code, "headline": headline, "target": target}]


async def problem_handler(request: Request, exc: ProblemError) -> JSONResponse:
    return JSONResponse({"detail": exc.detail, "problems": exc.problems}, status_code=exc.status_code, headers=exc.headers)
