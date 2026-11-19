import logging
import threading
from typing import Any, Callable, Optional

from fastapi import HTTPException

from cytonn_weekly import jobs, report_sections
from cytonn_weekly.agent import loop
from cytonn_weekly.agent.read_tools import READ_TOOLS
from cytonn_weekly.agent.tools import ToolContext, execute
from cytonn_weekly.common.run_events import safe_describe
from cytonn_weekly.drafting.bedrock import BedrockAgent, BedrockError

from api.draft_slot import _whole

log = logging.getLogger(__name__)

CONCURRENCY_ENV = "CYTONN_CHAT_CONCURRENCY"
DEFAULT_CONCURRENCY = 2
FAILED = "I could not answer just now. Send your message again in a moment."
BY_NAME = {t.name: t for t in READ_TOOLS}


def chat_concurrency() -> int:
    return _whole(CONCURRENCY_ENV, DEFAULT_CONCURRENCY, 1, 6)


class Chat:
    """The analyst chat's share of the API: its own answer seats (not the drafting seats), the worker thread that runs the loop, and
    the two cards code posts into a conversation.  ``make_agent`` builds the model client for one answer (tests pass a scripted one)."""

    def __init__(self, d: Any, make_agent: Optional[Callable[[], Any]] = None):
        self.d = d
        self.make_agent = make_agent or BedrockAgent
        self.seats = threading.Semaphore(chat_concurrency())
        # The conversations this process has seen, by report key, so a finished draft finds its job without a database read (a draft
        # of a section nobody is chatting about costs nothing).  A conversation is added on any job route, so one open in a browser
        # across a restart is back in here with its next poll.
        self.known: dict[tuple[str, str, str], int] = {}

    def touch(self, job: dict[str, Any]) -> None:
        self.known[(job["report_type"], job["period"], job["section"])] = job["job_id"]

    def context(self, job: dict[str, Any]) -> ToolContext:
        return ToolContext(job=job, db_path=self.d.db_path, **self.paths())

    def paths(self) -> dict[str, Any]:
        return {"root": self.d.root, "sources_dir": self.d.sources_dir, "snips_dir": self.d.snips_dir, "runs": self.d.runs}

    def title(self, job: dict[str, Any]) -> str:
        spec = report_sections.spec_for(job["report_type"], job["section"])
        return spec.title if spec else job["section"]

    # --- the cards code posts ---------------------------------------------------------------------

    def post_readiness(self, job: dict[str, Any]) -> None:
        """First open of a weekly conversation: what the section needs, worked out by code before the model says anything.  A report
        with no week has no readiness check, so it gets no card."""
        got = execute(BY_NAME, "week_status", {}, self.context(job))
        if "error" in got:
            return
        jobs.add_message(self.d.db_path, job["job_id"], "assistant",
                         f"This is what {self.title(job)} still needs for the week ending {got['week_ending']}.",
                         cards=[{"type": "readiness", "data": got}])

    def run_finished(self, key: tuple[str, str, str], review_id: int, is_dev_draft: bool) -> None:
        """A draft was saved: if someone is chatting about that section and week, put its review summary in the conversation.  Never
        raises: the draft is already saved and must finish whatever happens here."""
        job_id = self.known.get(key)
        if job_id is None:
            return
        try:
            job = jobs.get_job(self.d.db_path, job_id)
            got = execute(BY_NAME, "review_summary", {}, self.context(job))
            if "error" in got or got["review_id"] != review_id:   # a newer draft has already replaced this one
                return
            c = got["counts"]
            jobs.add_message(
                self.d.db_path, job_id, "assistant",
                f"The draft of {self.title(job)} is saved: {c['flagged']} flagged, {c['not_auto_verified']} not automatically "
                f"verified and {c['clean']} clean.",
                cards=[{"type": "review_summary", "review_id": review_id, "is_dev_draft": is_dev_draft, "data": got}])
        except Exception as exc:  # noqa: BLE001
            log.warning("the review card for job %s was not saved: %s", job_id, safe_describe(exc))

    # --- answering --------------------------------------------------------------------------------

    def send(self, job: dict[str, Any], text: str) -> int:
        """Take the job, save the analyst's message and start the answer in a thread; return the message's number.  409 while the job
        is working or has stopped at a budget, 429 when every chat seat is taken.  Nothing is saved unless the answer will start."""
        if job["status"] == jobs.PAUSED and job["paused_reason"] in jobs.BUDGET_REASONS:
            raise HTTPException(409, "This conversation has used up its budget. Give it more with the button, then send your message again.")
        if not jobs.begin(self.d.db_path, job["job_id"]):
            raise HTTPException(409, "The assistant is still answering the last message. Wait for it, then send yours.")
        if not self.seats.acquire(blocking=False):
            jobs.finish(self.d.db_path, job["job_id"])
            raise HTTPException(429, "The assistant is busy with other conversations. Try again in a moment.")
        try:
            seq = jobs.add_message(self.d.db_path, job["job_id"], "user", text)
        except BaseException:
            self.seats.release()
            jobs.finish(self.d.db_path, job["job_id"])
            raise
        threading.Thread(target=self.work, args=(job["job_id"],), name=f"chat-{job['job_id']}", daemon=True).start()
        return seq

    def work(self, job_id: int) -> None:
        """One answer's thread.  Whatever happens, the job ends idle (or paused by the loop) and the chat seat goes back."""
        def observe(kind: str, label: str = "", detail: Optional[str] = None, counts: Optional[dict] = None) -> None:
            log.info("job %s: %s %s %s", job_id, kind, label, detail or "")

        try:
            loop.answer(self.d.db_path, job_id, self.make_agent(), READ_TOOLS, paths=self.paths(), on_event=observe, claimed=True)
        except Exception as exc:  # noqa: BLE001 - the analyst gets a sentence, the log gets the class
            log.warning("chat answer for job %s failed: %s", job_id, safe_describe(exc))
            try:
                jobs.add_message(self.d.db_path, job_id, "assistant", str(exc) if isinstance(exc, BedrockError) else FAILED)
                jobs.finish(self.d.db_path, job_id)
            except Exception as again:  # noqa: BLE001
                log.warning("job %s could not be left idle: %s", job_id, safe_describe(again))
        finally:
            self.seats.release()
