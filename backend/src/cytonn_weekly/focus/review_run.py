from __future__ import annotations

import re
from collections import Counter
from datetime import date
from typing import Any, Callable, Optional, Sequence

from cytonn_weekly.review.blocks import ROMAN, build_review, check_section, narrative_block, unavailable_block
from cytonn_weekly.common.computed import carried_block
from cytonn_weekly.common.run_events import PART_SKIPPED, PIECE_FINISHED, PIECE_STARTED, Observer, emit
from cytonn_weekly.review.model import CoordinatorReview
from cytonn_weekly.drafting.base import NarrativeBrief, NarrativeProvider, NothingDrafted
from cytonn_weekly.drafting.drafter import draft_pieces
from cytonn_weekly.drafting.factory import get_narrative_provider
from cytonn_weekly.weekly import previous_issue as previous_issue_mod
from cytonn_weekly.weekly.prose import try_fetch

SECTION = "focus"
TITLE = "Focus of the Week"
# The one topic length limit, counted after whitespace is normalized.  The API (api/main.py)
# refuses a longer topic through clean_topic(), and the web form's MAX_TOPIC
# (frontend/src/lib/topic.ts) is the same number, counted the same way.
MAX_TOPIC_CHARS = 500
# The same for the section titles (clean_sections; frontend MAX_SECTIONS, MAX_SECTION_TITLE, sectionTitles()).
MAX_SECTIONS = 8
MAX_SECTION_TITLE = 120
# The caps that bound a draft's cost (see CLAUDE.md, Focus of the Week).
SECTION_SEARCHES = 5
SECTION_MAX_TOKENS = 3000   # findings only: each claim and its quote, no paragraph
OUTLINE_TITLES = (4, 6)
OUTLINE_MAX_TOKENS = 300

GUIDE_NOTE = ("Research notes for the analyst to write this section from. They are not report text and are not "
              "exported; Cytonn's own tables, charts and recommendations are the analyst's.")
CONTENTS_LABEL = "Contents"
DISCLAIMER_LABEL = "Disclaimer"
CLOSING_RE = re.compile(r"conclusion|recommendation", re.I)
_SECTION_PREFIX = re.compile(r"^\s*section\s+(?:\d+|[ivxlcdm]+)\s*[:.\-\u2013\u2014]\s*", re.I)


def clean_topic(topic: Optional[str]) -> str:
    """The topic, whitespace-normalized; ValueError if blank or too long."""
    t = " ".join((topic or "").split())
    if not t:
        raise ValueError("a Focus of the Week draft needs a topic")
    if len(t) > MAX_TOPIC_CHARS:
        raise ValueError(f"the topic is {len(t)} characters; the limit is {MAX_TOPIC_CHARS}")
    return t


def clean_title(line: str) -> str:
    """One section title: whitespace-normalized, a typed "Section N:" prefix dropped (the tool numbers the sections)."""
    return " ".join(_SECTION_PREFIX.sub("", " ".join(line.split()), count=1).split())


def clean_sections(text: Optional[str]) -> list[str]:
    """The section titles typed one per line: blank lines dropped, each title cleaned; ValueError with the reason if there
    are more than MAX_SECTIONS, one is empty after cleaning or longer than MAX_SECTION_TITLE characters.  Nothing is cut."""
    titles = []
    for n, line in enumerate((ln for ln in (text or "").splitlines() if ln.strip()), 1):
        title = clean_title(line)
        if not title:
            raise ValueError(f"section title {n} is empty once its \"Section N:\" prefix is removed")
        if len(title) > MAX_SECTION_TITLE:
            raise ValueError(f"section title {n} is {len(title)} characters; the limit is {MAX_SECTION_TITLE}")
        titles.append(title)
    if len(titles) > MAX_SECTIONS:
        raise ValueError(f"{len(titles)} section titles; the limit is {MAX_SECTIONS}")
    return titles


def heading(index: int, title: str) -> str:
    return f"Section {ROMAN[index]}: {title}"


def is_closing(title: str) -> bool:
    return bool(CLOSING_RE.search(title))


# ---------------------------------------------------------------------------
# The outline
# ---------------------------------------------------------------------------

OUTLINE_SYSTEM = f"""\
You propose the section titles of a "Focus of the Week" investment research report on Kenya.

Reply with {OUTLINE_TITLES[0]} to {OUTLINE_TITLES[1]} titles, one per line. Titles only: no numbering, no bullets, no \
"Section" prefix, no prose, no commentary. Each title is at most {MAX_SECTION_TITLE} characters.
- The first title is an overview, background or introduction to the topic.
- The last title is "Recommendations and Conclusion".
- The titles between them are specific to the topic and do not overlap.
"""


def parse_outline(reply: str) -> list[str]:
    """The titles in a model's outline reply; ValueError, saying why, if it is not an outline (prose, the wrong number of
    titles, a title too long, no overview first or no recommendations and conclusion last)."""
    titles = []
    for line in (ln for ln in (reply or "").splitlines() if ln.strip()):
        line = re.sub(r"^\s*(?:[-*\u2022]+|\d+[.)])\s*", "", line.replace("**", ""))
        titles.append(clean_title(line))
    lo, hi = OUTLINE_TITLES
    if not lo <= len(titles) <= hi:
        raise ValueError(f"it returned {len(titles)} lines, not {lo} to {hi} titles")
    for t in titles:
        if not t or len(t) > MAX_SECTION_TITLE or len(t.split()) > 16:
            raise ValueError("a line is prose, not a title")
    if not re.search(r"overview|background|introduction", titles[0], re.I):
        raise ValueError(f"the first title, {titles[0]!r}, is not an overview, background or introduction")
    if not is_closing(titles[-1]):
        raise ValueError(f"the last title, {titles[-1]!r}, is not a recommendations and conclusion part")
    return titles


def propose_outline(provider: NarrativeProvider, topic: str, on_event: Optional[Observer] = None) -> list[str]:
    emit(on_event, PIECE_STARTED, "Section titles")
    reply = provider.complete(OUTLINE_SYSTEM, f"Topic: {topic}", max_tokens=OUTLINE_MAX_TOKENS)
    try:
        titles = parse_outline(reply)
    except ValueError as exc:
        raise ValueError(f"The section titles the model proposed could not be used ({exc}). Type the section titles "
                         "yourself under \"Sections\" and draft again.") from exc
    emit(on_event, PIECE_FINISHED, "Section titles", detail="; ".join(titles))
    return titles


# ---------------------------------------------------------------------------
# The sections
# ---------------------------------------------------------------------------

def section_brief(topic: str, titles: Sequence[str], index: int) -> NarrativeBrief:
    """The brief of section ``index``: findings only (claim, verified quote, source), no prose.  The whole title list is in
    the prompt so the sections do not repeat each other."""
    listing = "\n".join(heading(i, t) for i, t in enumerate(titles))
    return NarrativeBrief(
        id=f"focus_section_{index + 1}", section=TITLE, label=titles[index],
        focus=(f"recent, sourced data and developments on: {topic}, for the section \"{titles[index]}\". Material may be "
               "published before the report week if it is the latest available data on the topic; say when each figure "
               "dates from"),
        words=(0, 0), opener=None, max_searches=SECTION_SEARCHES, headed=False, max_tokens=SECTION_MAX_TOKENS, findings=True,
        context=("These findings feed one section of a longer report on the topic. The report's sections, in order:\n"
                 f"{listing}\nCollect findings only for {heading(index, titles[index])}; do not repeat what the other "
                 "sections cover. Give 5 to 12 findings and keep each quote no longer than its figures need, so the whole "
                 "reply is complete."),
    )


# ---------------------------------------------------------------------------
# The contents list and the disclaimer
# ---------------------------------------------------------------------------

def contents_block(titles: Sequence[str]) -> dict[str, Any]:
    """The contents list, built by code from the titles: no model, no claims, no figures."""
    return {"kind": "computed", "id": "focus_contents", "role": "contents", "numeral": "", "title": CONTENTS_LABEL,
            "body_md": "\n\n".join(heading(i, t) for i, t in enumerate(titles)), "figures": [], "sources": [], "notes": []}


def _is_focus(slug: str, sec: dict[str, str]) -> bool:
    """The Focus of the Week of an issue; its slug varies (focus-of-the-week, fotw-<title>)."""
    return slug == "focus-of-the-week" or slug.startswith("fotw") or sec["name"].lower().startswith(("focus of the week", "fotw"))


def disclaimer_block(issue: Optional[previous_issue_mod.Issue], problem: str = "") -> dict[str, Any]:
    """The disclaimer, copied word for word from the previous issue (the paragraph starting "Disclaimer:") and always flagged as
    carried text; unavailable, with the reason, when the previous issue cannot be read or holds none.  Never model-written."""
    paste = "Paste the disclaimer in by hand: the tool never writes it."
    if issue is None:
        return {**unavailable_block("focus_disclaimer", DISCLAIMER_LABEL,
                                    "The previous issue could not be read from cytonnreport.com, so there is no disclaimer to "
                                    f"carry forward.{' ' + problem if problem else ''}", paste), "role": "disclaimer", "numeral": "", "guide": True}
    items = sorted(issue.sections.items(), key=lambda i: not _is_focus(*i))   # the Focus first, then any other section
    for slug, sec in items:
        text = next((p for p in previous_issue_mod.html_paragraphs(sec["body"]) if p.lower().startswith("disclaimer:")), None)
        if not text:
            continue
        source = {"issue_id": issue.issue_id, "url": issue.url, "published": issue.published.isoformat() if issue.published else None}
        if issue.skipped_twins or issue.kind != "weekly":
            source["kind"] = issue.kind
        if issue.skipped_twins:
            source["skipped"] = list(issue.skipped_twins)
        if not _is_focus(slug, sec):
            source["section"] = slug
            source["note"] = f"taken from the {sec['name'] or slug} section of issue {issue.issue_id}, not from its Focus of the Week"
        return {**carried_block("focus_disclaimer", DISCLAIMER_LABEL, text, source), "role": "disclaimer", "numeral": "", "guide": True}
    return {**unavailable_block("focus_disclaimer", DISCLAIMER_LABEL,
                                f"The previous issue (cytonnreport.com issue {issue.issue_id}) has no paragraph starting "
                                "\"Disclaimer:\".", paste), "role": "disclaimer", "numeral": "", "guide": True}


# ---------------------------------------------------------------------------
# The review
# ---------------------------------------------------------------------------

def compose(topic: str, titles: Sequence[str], outline: str, draft: dict[str, Any], blocks: list[dict[str, Any]],
            expected: int, calls: dict[str, Optional[int]]) -> dict[str, Any]:
    found = sum(1 for b in blocks if b["kind"] == "narrative")
    return {
        "section": SECTION, "title": TITLE, "topic": topic, "week_start": draft["week_start"],
        "week_end": draft["week_end"], "blocks": blocks, "pieces_found": found, "pieces_expected": expected,
        "shortfall": expected - found, "warnings": list(draft["warnings"]),
        "outline": {"titles": list(titles), "source": outline}, "model_calls": calls["model_calls"],
        "api_requests": calls["api_requests"],
    }


def _default_previous(day: date) -> previous_issue_mod.Issue:
    return previous_issue_mod.find_previous_issue(day)


def build_focus_review(topic: str, provider: Optional[NarrativeProvider] = None,
                       today: Optional[date] = None, on_event: Optional[Observer] = None, *,
                       sections: Optional[Sequence[str] | str] = None,
                       previous_issue: Optional[Callable[[date], previous_issue_mod.Issue]] = None) -> CoordinatorReview:
    """Draft and check the Focus on ``topic``, under ``sections`` (titles as typed, or blank for the model to propose).

    Raises ValueError for a blank topic, unusable titles or an outline the model got wrong, and LookupError when the
    search found nothing usable in any section, rather than saving an empty review.  ``on_event``
    (common/run_events.py) is told each step as it happens.  The model calls made are counted on the review.
    """
    topic = clean_topic(topic)
    typed = clean_sections(sections) if isinstance(sections, str) else [clean_title(t) for t in (sections or [])]
    provider = provider or get_narrative_provider()
    today = today or date.today()
    requests_before = getattr(provider, "requests", None)
    model_calls = 0

    titles, outline = typed, "typed"
    if not titles:
        titles, outline, model_calls = propose_outline(provider, topic, on_event), "proposed", 1

    closing = is_closing(titles[-1])
    searched = titles[:-1] if closing else titles
    draft = draft_pieces([section_brief(topic, titles, i) for i in range(len(searched))], len(searched), provider=provider,
                         today=today, on_event=on_event)
    model_calls += len(searched)
    drafted = {p["brief_id"]: p for p in draft["pieces"]}
    skipped = draft.get("skipped", {})
    if not drafted:   # each section's own reason (no sources, cut off, nothing passed the checks), counted
        why = Counter(skipped.get(f"focus_section_{i + 1}") or "the model found nothing in the material that qualified."
                      for i in range(len(searched)))
        raise NothingDrafted("No section produced a sourced draft, so nothing was saved. "
                             + " ".join(f"{n} of {len(searched)} sections: {r}" for r, n in why.items()))

    blocks: list[dict[str, Any]] = []
    for i, title in enumerate(searched):
        head = {"numeral": ROMAN[i], "group_heading": heading(i, title)}
        piece = drafted.get(f"focus_section_{i + 1}")
        if piece:
            blocks.append(narrative_block(f"focus_section_{i + 1}", {**piece, **head, "role": "findings", "guide": True, "headline": title,
                                                                     "analyst_note": GUIDE_NOTE}))
        else:
            reason = skipped.get(f"focus_section_{i + 1}") or f"Nothing qualifying was found for \"{title}\"."
            blocks.append({**unavailable_block(f"focus_section_{i + 1}", title, reason,
                                               "Write the section by hand, or draft again with other section titles."),
                           "role": "section", "guide": True, **head})

    problems: list[str] = []
    issue = try_fetch(on_event, "Previous issue on cytonnreport.com", previous_issue or _default_previous, today, problems=problems)
    blocks = [contents_block(titles), *blocks, disclaimer_block(issue, problems[0] if problems else "")]
    api_requests = None if requests_before is None else getattr(provider, "requests", 0) - requests_before
    content = compose(topic, titles, outline, draft, blocks, len(searched),
                      {"model_calls": model_calls, "api_requests": api_requests})
    emit(on_event, PIECE_FINISHED, CONTENTS_LABEL)
    for b in blocks:   # a section with nothing to draft was reported by draft_pieces; these parts were not
        if b["kind"] == "unavailable" and b["role"] != "section":
            emit(on_event, PART_SKIPPED, b["title"], detail=b["reason"])
    return build_review(content, check_section(content, on_event))
