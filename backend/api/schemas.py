from typing import Any, Literal, Optional
from pydantic import BaseModel, Field
from cytonn_weekly.real_estate import snips as snip_store
from cytonn_weekly.report_types import WEEKLY
from cytonn_weekly.weekly import inputs as weekly_inputs


class JobRequest(BaseModel):
    """The conversation for one section of one report: ``period`` is normalized as for a draft."""

    section: str
    report_type: Literal["weekly", "monthly", "quarterly", "half_year", "annual", "companion"] = "weekly"
    period: Optional[str] = None
    kind: Optional[str] = None


class JobMessage(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class ItemResolution(BaseModel):
    """``resolution`` is required (null clears it).  An omitted ``note`` keeps the item's
    existing note; a present one replaces it (blank or null clears it)."""

    resolution: Optional[Literal["accept", "fix_needed"]]
    note: Optional[str] = Field(default=None, max_length=2000)


class Decision(BaseModel):
    decision: Literal["approved", "rejected"]
    # How many flagged items the caller was shown. Approving a section that has flagged items is refused unless this
    # equals their count now; it is not needed when nothing is flagged, nor to reject.
    acknowledged_flagged: Optional[int] = Field(default=None, ge=0)


class SentenceChange(BaseModel):
    """``text`` is judged by weekly/sentence_edit.plain(), the one place its length and characters are, so the refusal is in our words."""

    action: Literal["edit", "remove", "paragraph"]
    text: Optional[str] = None


class TeamChartBody(BaseModel):
    """``use`` true sets the tool's chart aside for the team's own; false takes that back."""

    use: bool


ReportType = Literal["weekly", "monthly", "quarterly", "half_year", "annual", "companion"]


class DraftRequest(BaseModel):
    """``topic`` is required for Focus of the Week; other sections ignore it.

    ``report_type`` and ``period`` say which report the section belongs to.  The default,
    the weekly report with no period label, is what every draft was before report types.
    """

    # No length here: clean_topic() is the one place a topic's length is judged (resolve_draft calls it),
    # so the API and the pipeline refuse the same topics in the same words.
    topic: Optional[str] = None
    # Focus of the Week: the section titles, one per line. Like the topic, judged by one function (clean_sections).
    sections: Optional[str] = None
    report_type: ReportType = WEEKLY
    period: Optional[str] = Field(default=None, max_length=40)
    kind: Optional[str] = Field(default=None, max_length=40)


class SourceBody(BaseModel):
    """One source for one piece of one section.  With no ``text`` and no ``date`` the page at ``url`` is fetched; with them
    the pasted text is kept.  ``sections`` is the Focus's typed titles, which name its pieces."""

    section: str = Field(max_length=40)
    subject: str = Field(max_length=200)
    report_type: ReportType = WEEKLY
    period: Optional[str] = Field(default=None, max_length=40)
    sections: Optional[str] = Field(default=None, max_length=4000)
    url: str = Field(max_length=2000)
    date: Optional[str] = Field(default=None, max_length=20)
    text: Optional[str] = Field(default=None, max_length=1_000_000)   # source_store.from_paste judges the length, in words
    title: Optional[str] = Field(default=None, max_length=300)


class SnipChange(BaseModel):
    """What the analyst changed on one snip: its text, its sector or its date (YYYY-MM-DD, or empty for the report week)."""

    text: Optional[str] = Field(default=None, max_length=snip_store.MAX_TEXT_CHARS + 1000)
    sector: Optional[str] = Field(default=None, max_length=40)
    date: Optional[str] = Field(default=None, max_length=10)


class GatherBody(BaseModel):
    """Look again for the sources of one piece (the same gather step a draft runs)."""

    section: str = Field(max_length=40)
    subject: str = Field(max_length=200)
    report_type: ReportType = WEEKLY
    period: Optional[str] = Field(default=None, max_length=40)
    sections: Optional[str] = Field(default=None, max_length=4000)


class InputNotes(BaseModel):
    """What the analyst types beside the week's files.  A field left out is kept; blank clears it."""

    bidding_range: Optional[str] = Field(default=None, max_length=weekly_inputs.MAX_NOTE)
    previous_issue: Optional[str] = Field(default=None, max_length=weekly_inputs.MAX_NOTE)
    as_at: Optional[str] = Field(default=None, max_length=10)


class ChartLeadIn(BaseModel):
    """The sentence printed above an uploaded chart.  Blank clears it, and the slot's default sentence is printed instead."""

    lead_in: Optional[str] = Field(default=None, max_length=10_000)


class ChartSource(BaseModel):
    """The text printed as "Source: <text>" under an uploaded chart.  Blank clears it, and nothing is printed."""

    source: Optional[str] = Field(default=None, max_length=10_000)


class FundSnipEdits(BaseModel):
    """The analyst's corrections to the fund snip's reading: ``fixes`` by row id, and the funds typed beside the page."""

    fixes: dict[str, Any] = Field(default_factory=dict)
    typed: list[dict[str, Any]] = Field(default_factory=list)


class FundSnipConfirm(BaseModel):
    published: str = Field(max_length=40)


class FundListSettings(BaseModel):
    include: Optional[list[str]] = None
    exclude: Optional[list[str]] = None
    aliases: Optional[dict[str, str]] = None


class FundDecision(BaseModel):
    page_name: str = Field(max_length=200)
    decision: Literal["include", "exclude", "alias"]
    name: Optional[str] = Field(default=None, max_length=200)
    to: Optional[str] = Field(default=None, max_length=200)


class AnalystInputs(BaseModel):
    """What was typed on the weekly analyst inputs form.  An item left out is kept; null or empty clears it.

    ``fields`` maps a field to its typed value; ``tables`` maps a table to ``{"text": pasted lines}``
    or ``{"rows": [...]}``.  What each may hold is cytonn_weekly/weekly/analyst.py's to judge.
    """

    fields: dict[str, Any] = Field(default_factory=dict)
    tables: dict[str, Any] = Field(default_factory=dict)
    confirm: list[str] = Field(default_factory=list, max_length=60)
    retire: list[dict[str, Any]] = Field(default_factory=list, max_length=20)   # [{point_id, reason}]: stored bond redemptions


class NotableDecision(BaseModel):
    """What the analyst did with one suggestion.  An edit (``edited_headline``) belongs to a selection and a
    ``dismiss_reason`` to a dismissal; the route refuses the other pairings."""

    suggestion_id: str = Field(min_length=1, max_length=64)
    decision: Literal["selected", "dismissed"]
    edited_headline: Optional[str] = None
    dismiss_reason: Optional[Literal["not_relevant", "already_covered", "figures_look_wrong", "other"]] = None


class RunRequest(DraftRequest):
    """POST /api/runs: the draft route's inputs, with the section in the body.

    ``provider`` is optional and only ever a check: the provider the screen told the
    analyst a draft would use ("bedrock" spends API budget, "local" is dev mode).
    If the API is configured for a different one, the run is refused rather than started
    on a provider the analyst did not see.  It never selects the provider; only
    CYTONN_LLM_PROVIDER does.
    """

    section: str = Field(min_length=1, max_length=80)
    provider: Optional[str] = Field(default=None, max_length=40)
