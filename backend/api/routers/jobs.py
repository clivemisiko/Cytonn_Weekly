import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from cytonn_weekly import jobs as job_store
from cytonn_weekly import report_sections
from cytonn_weekly.agent.tools import execute
from api.chat import BY_NAME
from api.deps import Deps, chosen_report, configured_provider, provider_problem
from api.schemas import JobMessage, JobRequest

log = logging.getLogger(__name__)

JOB_KEYS = ("job_id", "report_type", "period", "section", "status", "paused_reason", "calls_used", "call_budget", "input_tokens",
            "output_tokens", "token_budget", "max_tool_calls", "budget_raises", "created_at")
CHAT_NEEDS_BEDROCK = "The assistant answers through Amazon Bedrock, and this copy of the tool is not set up for it ({mode})."


def view(job: dict[str, Any]) -> dict[str, Any]:
    return {k: job[k] for k in JOB_KEYS}


def message_view(m: dict[str, Any]) -> dict[str, Any]:
    """What a screen may show of one saved message: a tool turn is only its name, and the model's usage is left out."""
    return {"seq": m["seq"], "role": m["role"], "content": "" if m["role"] == "tool" else m["content"],
            "tool_name": m["tool_name"] if m["role"] == "tool" else None, "cards": json.loads(m["cards"]) if m["cards"] else None,
            "created_at": m["created_at"]}


def make_router(d: Deps) -> APIRouter:
    router = APIRouter()

    def find(job_id: int) -> dict[str, Any]:
        try:
            job = job_store.get_job(d.db_path, job_id)
        except LookupError:
            raise HTTPException(404, f"There is no conversation number {job_id}. Open the section's chat again.")
        d.chat.touch(job)
        return job

    @router.post("/api/jobs")
    def open_job(body: JobRequest) -> dict:
        """Open the conversation for one section of one report and period, or return the one that exists.  The first time, code
        posts the readiness card (what the week still needs) before the model says anything."""
        period, kind = chosen_report(body.report_type, body.period, body.kind)
        spec = report_sections.spec_for(body.report_type, body.section, kind)
        if spec is None:
            raise HTTPException(404, f"There is no section {body.section!r} in that report.")
        if not spec.available:
            raise HTTPException(409, f"{spec.title} cannot be drafted yet, so there is nothing to talk about. {spec.reason}")
        job, created = job_store.open_or_create(d.db_path, body.report_type, period, body.section)
        d.chat.touch(job)
        if created:
            d.chat.post_readiness(job)
        return {"job": view(job), "created": created}

    @router.get("/api/jobs/{job_id}")
    def get_job(job_id: int) -> dict:
        return {"job": view(find(job_id))}

    @router.post("/api/jobs/{job_id}/messages", status_code=202)
    def send_message(job_id: int, body: JobMessage) -> dict:
        """Save the analyst's message and answer it in a worker thread, never in this request.  202 with the message's number; the
        answer arrives through GET .../messages.  409 while the assistant is answering or the conversation is out of budget, 429
        when every chat seat is taken."""
        job = find(job_id)
        text = body.content.strip()
        if not text:
            raise HTTPException(422, "Type a message first.")
        if configured_provider() != "bedrock":
            raise HTTPException(409, CHAT_NEEDS_BEDROCK.format(mode=configured_provider() or "not configured"))
        problem = provider_problem()
        if problem:
            raise HTTPException(409, problem)
        seq = d.chat.send(job, text)
        return {"seq": seq, "job": view(job_store.get_job(d.db_path, job_id))}

    @router.get("/api/jobs/{job_id}/messages")
    def list_messages(job_id: int, after: int = Query(default=0, ge=0)) -> dict:
        """The messages numbered above ``after`` (0 for all), and the job's state, so a poll sees an answer start and end.  A model
        turn that only called tools has no text and is left out; its tool rows show as the tool's name."""
        job = find(job_id)
        rows = job_store.messages(d.db_path, job_id, after)
        return {"job": view(job), "messages": [message_view(m) for m in rows if m["content"] or m["cards"] or m["role"] == "tool"]}

    @router.get("/api/jobs/{job_id}/readiness")
    def readiness(job_id: int) -> dict:
        """What the section needs for the week, worked out now: the check the first-open card was made from, run again so the cards that
        carry buttons never show a state that has changed.  Code runs it, never the model; 409 when the conversation has no weekly check."""
        job = find(job_id)
        got = execute(BY_NAME, "week_status", {}, d.chat.context(job))
        if "error" in got:
            raise HTTPException(409, got["error"])
        return {"readiness": got}

    @router.post("/api/jobs/{job_id}/raise-budget")
    def raise_budget(job_id: int) -> dict:
        """Add a fixed amount to this one job's call and token budgets.  409 unless the job stopped at a budget."""
        find(job_id)

        def log_event(kind: str, label: str = "", detail: Any = None, counts: Any = None) -> None:
            log.info("%s %s: %s", kind, label, detail)

        try:
            job = job_store.raise_budget(d.db_path, job_id, on_event=log_event)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        job_store.add_message(d.db_path, job_id, "assistant",
                              f"The budget was raised by {job_store.RAISE_CALLS} model calls and {job_store.RAISE_TOKENS} tokens. "
                              "Send your message again.")
        return {"job": view(job)}

    return router
