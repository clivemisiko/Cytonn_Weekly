from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cytonn_weekly.drafting.highlight_contract import BODY_WORDS, GENUINE_ANNOUNCEMENT, NOT_GENUINE, OPENER

if TYPE_CHECKING:
    from cytonn_weekly.drafting.base import NarrativeBrief

CONTEXT_CHARS_PER_RESULT = 3000  # enough text per result to draft from

HIGHLIGHT_SYSTEM = f"""\
You help draft one "Weekly Highlights" item for the Digital Payments section of a \
weekly investment research report (formal, data-forward, third person) from search results.

Step 1 - judge the material. Decide whether the search results contain a GENUINE \
COMPANY ANNOUNCEMENT by {{company}} ({GENUINE_ANNOUNCEMENT}). If the results \
are only {NOT_GENUINE}, that is NOT a genuine \
announcement. Do not force a draft in that case.

Step 2 - only if genuine: write a short headline and ONE paragraph of {BODY_WORDS[0]} to \
{BODY_WORDS[1]} words (no fewer than {BODY_WORDS[0]}, no more than {BODY_WORDS[1]}) that begins \
exactly with "{OPENER} {{company}}". Describe the announcement with concrete stats or \
quotes from the results, then end with 1-2 sentences of relevance or industry implications \
that contain no new figures. Use ONLY facts stated in the search results; never add \
figures, dates, names or claims from your own memory. Embed the source as an inline \
markdown hyperlink on a natural word or short phrase inside the paragraph, e.g. \
"released [new research](https://...)", using only URLs given in the results.

Step 3 - claim mapping: list every factual claim in your paragraph together with the \
exact URL of the single search result that supports it. Use URLs exactly as given. Do \
not invent URLs.

If the material is not a genuine announcement, set is_genuine_announcement to false, \
explain briefly in reasoning, and leave headline and paragraph as empty strings and \
claims as an empty list.

Reply with JSON only."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_genuine_announcement": {"type": "boolean"},
        "reasoning": {"type": "string"},
        "headline": {"type": "string"},
        "paragraph": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"claim": {"type": "string"}, "url": {"type": "string"}},
                "required": ["claim", "url"],
            },
        },
    },
    "required": ["is_genuine_announcement", "reasoning", "headline", "paragraph", "claims"],
}


def results_message(subject: str, results: list[dict[str, Any]], heading: str = "Search results",
                    limit: int = CONTEXT_CHARS_PER_RESULT) -> str:
    """The user message: each source as a numbered block.  The text of each is cut at ``limit``.

    A result with an ``id`` (a saved source) is headed "Source" and names its id, which the reply cites; one without
    (a search result) is headed "Result", exactly as before."""
    blocks = []
    for i, r in enumerate(results, 1):
        text = " ".join((r.get("text") or "").split())[:limit]
        head = f"[Source {i}]\nSource id: {r['id']}" if r.get("id") else f"[Result {i}]"
        blocks.append(
            f"{head}\nTitle: {r.get('title') or '(no title)'}\n"
            f"URL: {r.get('url')}\nPublished: {r.get('publishedDate') or 'n/a'}\nText: {text}"
        )
    return f"Company: {subject}\n\n{heading}:\n\n" + "\n\n".join(blocks)


def findings_system(brief: NarrativeBrief) -> str:
    extra = f"\n\n{brief.context}" if brief.context else ""
    return f"""\
You help collect research findings for the {brief.section} section of a {brief.report} investment research report \
on Kenya from search results. You do not write the report: an analyst does.

Subject: {brief.label}. What qualifies: {brief.focus}{extra}

Step 1 - judge the material. Decide whether the search results contain material that genuinely \
qualifies. Analysis, opinion pieces or unrelated material do not. Do not force a finding.

Step 2 - only if it qualifies: write no prose. Leave paragraph empty and set headline to the subject. \
Every finding goes in claims, and only facts stated in the search results; never add figures, dates, names or \
claims from memory. Give each finding as one plain sentence with its date where the result states one.

Step 3 - list each finding as a claim with the exact URL of the result that supports it.

If nothing qualifies, set is_genuine_announcement to false, explain briefly in reasoning, and leave \
headline and paragraph empty and claims an empty list.

Reply with JSON only."""


def narrative_system(brief: NarrativeBrief) -> str:
    if brief.findings:
        return findings_system(brief)
    opener = f'begins exactly with "{brief.opener}"' if brief.opener else "is formal prose"
    extra = f"\n\n{brief.context}" if brief.context else ""
    head = "a short headline and " if brief.headed else (
        "body paragraphs only, with no heading of any kind (set the headline to the subject, and put no line starting "
        "with # in the paragraph): ")
    if brief.takeouts:
        head = ("a short report title (the publisher, the period and the report, for example \"Hass Consult Q3'2026 Land "
                "Index\"; never a news headline) and ")
        extra += ("\n\nWrite the paragraph as one introductory sentence naming the publisher, what kind of firm it is and the "
                  "report and what it highlights, ending with \"The following are the key take-outs from the report:\". Then "
                  "give three to five key take-outs, each its own paragraph (separated by a blank line) that starts with its "
                  "numeral and a full stop: \"i.\", \"ii.\", \"iii.\" and so on. Write no closing or summary paragraph and no "
                  "comparison, opinion or outlook.")
    return f"""\
You help draft one item for the {brief.section} section of a {brief.report} investment research report \
on Kenya (formal, data-forward, third person) from search results.

Subject: {brief.label}. What qualifies: {brief.focus}{extra}

Step 1 - judge the material. Decide whether the search results contain material that genuinely \
qualifies. Analysis, opinion pieces or unrelated material do not. Do not force a draft.

Step 2 - only if it qualifies: write {head}prose of {brief.words[0]} to \
{brief.words[1]} words that {opener}. Use ONLY facts stated in the search results; never add \
figures, dates, names or claims from memory. Embed sources as inline markdown hyperlinks, using \
only URLs given in the results.

Step 3 - list every factual claim in your text with the exact URL of the result that supports it.

If nothing qualifies, set is_genuine_announcement to false, explain briefly in reasoning, and leave \
headline and paragraph empty and claims an empty list.

Reply with JSON only."""
