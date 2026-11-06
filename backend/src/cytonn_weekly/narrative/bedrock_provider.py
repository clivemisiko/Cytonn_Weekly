from __future__ import annotations

import copy
import importlib.util
import json
import logging
import os
import random
import re
import threading
import time
from datetime import date
from typing import Any, Callable, Optional, Sequence

import anthropic

from cytonn_weekly.common import run_events
from cytonn_weekly.common import sources as source_store
from cytonn_weekly.common.checks import check_sourced_claim
from cytonn_weekly.common.run_events import frames
from cytonn_weekly.digital_payments.providers.base import (
    OUTLOOK_SYSTEM,
    DraftingProvider,
    HighlightResult,
    OutlookResult,
    outlook_user_message,
    strip_links,
)
from cytonn_weekly.digital_payments.providers.drafting import (
    HIGHLIGHT_SYSTEM,
    RESPONSE_SCHEMA,
    ClaimReader,
    highlight_from_reply,
    narrative_system,
    piece_from_reply,
    results_message,
)
from cytonn_weekly.narrative.base import NarrativeBrief, NarrativeProvider

logger = logging.getLogger(__name__)

MODEL_ENV_VAR = "BEDROCK_MODEL_ID"
DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-6"
REGION_VARS = ("AWS_REGION", "AWS_DEFAULT_REGION")
BEARER_VAR = "AWS_BEARER_TOKEN_BEDROCK"
KEY_VARS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
TOKEN_VAR = "AWS_SESSION_TOKEN"
# Sonnet 4.6 allows far more output than any piece needs. A highlight's JSON reply (paragraph plus claims) is about
# 1,000 tokens and a Markets Review brief about 950; 4096 leaves room. A brief's own cap (Focus: 2000 a section, 600
# the lead) and the outlook's 800 (as on the Anthropic path) replace it.
MAX_TOKENS = 4096
OUTLOOK_MAX_TOKENS = 800
DRAFT_TOOL = "submit_draft"  # a client-side function tool, used only to get the reply as JSON; not a server tool
SCOPE_SUPPLIED = "supplied"
WHERE_SUPPLIED = "supplied sources"   # how a warning names the material the model was shown

RECREATE = "Changes to .env reach the api container only when it is recreated (docker compose up -d --force-recreate api)."
REGION_MISSING = (f"Drafting with Amazon Bedrock needs an AWS region, and none is set. Set {REGION_VARS[0]} (us-east-1 for the "
                  f"inference profile {DEFAULT_MODEL}) in .env. {RECREATE}")
CREDENTIALS_MISSING = ("Drafting with Amazon Bedrock needs AWS credentials, and none are set. Set AWS_ACCESS_KEY_ID and "
                       f"AWS_SECRET_ACCESS_KEY (plus {TOKEN_VAR} for temporary keys), or {BEARER_VAR}, in .env. {RECREATE} "
                       "A role or profile on the host is not looked for.")
BOTO3_MISSING = (f"Signing Bedrock requests with access keys needs boto3, which is not installed in this build. Use {BEARER_VAR}, "
                 "or rebuild the image from the current pyproject.toml.")
NO_SOURCES = "No sources were supplied for this piece, so nothing was drafted. Supply the pages to read."
NO_VERIFIED_CLAIMS = ("No claim in the draft held up against the supplied sources (each failed claim is listed in the "
                      "warnings), so nothing was kept. Check the pages, or supply others.")
SOURCE_CHARS = 12_000   # the most of one source's text the model is shown; the quote check reads the whole saved text

# The shared prompts end their claim step with "the exact URL of the search result that supports it". Here the reply
# cites a saved source by its id and quotes it, and code checks both (common/checks.check_sourced_claim).
_STEP3 = re.compile(r"Step 3 - [^\n]*(?:\n(?!\n)[^\n]*)*")
SOURCED_STEP3 = (
    "Step 3 - claims: list every factual claim in your text. For each give text (the claim as you wrote it), quote (a "
    "passage copied word for word from ONE supplied source, long enough to hold every figure and name in the claim, "
    "never reworded and never joined from two places) and source_id (the Source id of that source, exactly as given). "
    "Every number in a claim must appear in its quote, and your text must contain no number that is not inside one of "
    "your quotes. Leave out of the text, and out of the claims, anything you cannot quote word for word.")
SOURCED_SCHEMA = copy.deepcopy(RESPONSE_SCHEMA)
SOURCED_SCHEMA["properties"]["claims"]["items"] = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "quote": {"type": "string"}, "source_id": {"type": "string"}},
    "required": ["text", "quote", "source_id"],
}


class BedrockError(RuntimeError):
    """Written for the coordinator and shown as it stands (api/main.failure_message); never holds a secret."""


def _clean(name: str) -> str:
    return (os.environ.get(name) or "").strip()


RETRIES_ENV = "CYTONN_BEDROCK_RETRIES"
RETRY_BASE_ENV = "CYTONN_BEDROCK_RETRY_BASE_SECONDS"
DEFAULT_ATTEMPTS = 5        # calls per request, the first included
DEFAULT_BASE_SECONDS = 2.0  # the first wait; each next one doubles, with jitter
MAX_WAIT_SECONDS = 60.0
COOL_OFF_SECONDS = 5.0      # after a throttle, every new call from any draft waits this long
RETRY_KINDS = ("ThrottlingException", "ModelNotReadyException", "ServiceUnavailableException")
NEVER_RETRY_KINDS = ("AccessDeniedException", "ValidationException", "ExpiredTokenException", "ServiceQuotaExceededException",
                     "UnrecognizedClientException", "InvalidSignatureException")

_cool_lock = threading.Lock()
_cool_until = 0.0   # time.monotonic() before which no new Bedrock call starts; one per process, shared by every draft


def retry_settings() -> tuple[int, float]:
    """(attempts, base seconds) from the environment; a bad value logs one warning and the default is used."""
    def number(name: str, default: float, whole: bool) -> float:
        raw = _clean(name)
        if not raw:
            return default
        try:
            n = int(raw) if whole else float(raw)
        except ValueError:
            n = 0
        if n < 1 if whole else n <= 0:
            logger.warning("%s must be %s; the default %s is used", name, "a whole number of 1 or more" if whole else "above 0", default)
            return default
        return n

    return int(number(RETRIES_ENV, DEFAULT_ATTEMPTS, True)), number(RETRY_BASE_ENV, DEFAULT_BASE_SECONDS, False)


def _retryable(exc: BaseException) -> bool:
    """Throttled (429), not ready or unavailable (503): worth the same call again.  Anything else is a fixed sentence."""
    kind, status = _kind(exc), getattr(exc, "status_code", 0) or 0
    return kind not in NEVER_RETRY_KINDS and (kind in RETRY_KINDS or status in (429, 503))


def _throttled(exc: BaseException) -> bool:
    return _kind(exc) == "ThrottlingException" or getattr(exc, "status_code", 0) == 429


def region() -> str:
    return next((v for v in map(_clean, REGION_VARS) if v), "")


def model_id() -> str:
    """The one setting that chooses the model on this path: BEDROCK_MODEL_ID, else the default.  CYTONN_LLM_MODEL
    (the Anthropic path's) is never read here, so setting it changes nothing for a Bedrock draft."""
    return _clean(MODEL_ENV_VAR) or DEFAULT_MODEL


def boto3_installed() -> bool:
    return importlib.util.find_spec("boto3") is not None


def sources_for(subject: str, week_end: date) -> list[dict[str, Any]]:
    """The pages a piece is written from: dicts with url, title, text and publishedDate (the shape of a search result)
    plus the source's id, sha256, fetched_at, host, origin and flags.

    The one place Bedrock gets its material, and it only reads the saved sources (common/sources.py): no search, no
    fetch and no network call happens here or anywhere on this path. ``subject`` is a brief's label or a company name;
    ``week_end`` is the end of the window the draft gives the provider, filed under the Friday on or before it. A saved
    file that changed since it was saved raises SourceError, which is a plain sentence.
    """
    return [s.as_result() for s in source_store.list_for(subject, week_end)]


def env_problem() -> Optional[str]:
    """Why a Bedrock draft cannot start, or None.  Checked before a draft takes the slot or fetches anything.

    Only the environment is looked at: calling AWS's credential chain here would reach the instance metadata
    service on every page load.  # ponytail: a host role or profile is not recognised; read the chain if one is used.
    """
    if not region():
        return REGION_MISSING
    if not _clean(BEARER_VAR):
        if not all(map(_clean, KEY_VARS)):
            return CREDENTIALS_MISSING
        if not boto3_installed():
            return BOTO3_MISSING
    return None


def startup_line() -> str:
    """One log line saying which AWS variables are set.  Names only, never a value."""
    names = (*REGION_VARS, BEARER_VAR, *KEY_VARS, TOKEN_VAR)
    on = [n for n in names if _clean(n)]
    chosen = f"{MODEL_ENV_VAR}" if _clean(MODEL_ENV_VAR) else f"the default, {MODEL_ENV_VAR} is not set"
    line = (f"Drafting with Amazon Bedrock, model {model_id()} (from {chosen}). AWS variables set: "
            f"{', '.join(on) or 'none'}; not set: {', '.join(n for n in names if n not in on) or 'none'}.")
    if _clean("CYTONN_LLM_MODEL"):
        line += f" CYTONN_LLM_MODEL is set and is ignored on this path; only {MODEL_ENV_VAR} chooses the model."
    if _clean(BEARER_VAR) and any(map(_clean, (*KEY_VARS, TOKEN_VAR))):
        line += f" Both a bearer token and access keys are set; {BEARER_VAR} is the one used."
    return line


def _kind(exc: BaseException) -> str:
    """AWS's error name (``x-amzn-ErrorType``), else the one the HTTP status implies."""
    response = getattr(exc, "response", None)
    named = response.headers.get("x-amzn-errortype", "") if response is not None else ""
    named = named.split(":")[0].split("#")[-1]
    return named or {400: "ValidationException", 403: "AccessDeniedException", 429: "ThrottlingException"}.get(
        getattr(exc, "status_code", 0), "")


def problem_for(exc: BaseException, model: str, aws_region: str) -> str:
    """A plain sentence for a failed Bedrock call.  Fixed wording: nothing of the library's own text, no secret."""
    kind, said = _kind(exc), str(exc).lower()
    status = getattr(exc, "status_code", 0) or 0
    where = f"{model} in {aws_region}"
    if isinstance(exc, ImportError):
        return BOTO3_MISSING
    if isinstance(exc, anthropic.APIConnectionError):   # includes timeouts
        return (f"This server could not reach Amazon Bedrock in {aws_region} (a network error or a timeout). The draft "
                "stopped; check the server's network, then draft again.")
    if kind == "ExpiredTokenException" or "expired" in said:
        return ("The AWS credentials have expired (the session token or bearer token in .env is out of date). Put fresh "
                f"credentials in .env. {RECREATE} Drafting again will not help until then.")
    if kind in ("UnrecognizedClientException", "InvalidSignatureException") or status == 401 or any(
            s in said for s in ("invalid api key", "security token", "signature")):
        return (f"Amazon Bedrock did not accept the AWS credentials. Check {KEY_VARS[0]}, {KEY_VARS[1]} and {TOKEN_VAR}, or "
                f"{BEARER_VAR}, and that they are for {aws_region}. {RECREATE}")
    if kind == "AccessDeniedException":
        return (f"Amazon Bedrock refused the request (AccessDeniedException). Either model access is not enabled for this "
                f"AWS account in {aws_region}, or the IAM policy does not allow bedrock:InvokeModel on the inference "
                f"profile {model} and on the foundation models in each region it routes to. Enable the model in the "
                "Bedrock console and fix the policy; drafting again will not help until then.")
    if kind == "ValidationException":
        return (f"Amazon Bedrock did not accept the request (ValidationException). The usual cause is the model ID: "
                f"{MODEL_ENV_VAR} is {model}, and a model that is not offered on demand needs an inference profile ID "
                f"such as {DEFAULT_MODEL}, which must exist in {aws_region}. Correct {MODEL_ENV_VAR}. {RECREATE} "
                "Drafting again will not help until then.")
    if kind == "ThrottlingException":
        return (f"Amazon Bedrock is throttling this account (ThrottlingException): too many requests or tokens for "
                f"{where} just now. The draft stopped. Wait a few minutes and draft again, or ask AWS for a higher quota.")
    if kind == "ServiceQuotaExceededException":
        return (f"Amazon Bedrock says a service quota for {where} has been reached (ServiceQuotaExceededException). "
                "Drafting again will not help until AWS raises the quota or it resets.")
    if status >= 500 or kind in ("ModelNotReadyException", "ModelTimeoutException", "ServiceUnavailableException"):
        return (f"Amazon Bedrock could not serve {where} just now (a server-side error or timeout). The draft stopped; "
                "draft again in a few minutes.")
    if isinstance(exc, (RuntimeError, ValueError)) and ("credentials" in said or "region" in said):
        return REGION_MISSING if "region" in said else CREDENTIALS_MISSING
    return (f"Amazon Bedrock returned an error this tool does not recognise ({kind or type(exc).__name__}"
            f"{f', HTTP {status}' if status else ''}). See the server log.")


class _Chat:
    """The one call both providers make: Claude on Bedrock, no tool but the forced reply function."""

    WHO = "Bedrock model"
    LABEL = "Bedrock provider"

    def __init__(self, client: Any = None, model: Optional[str] = None, sleep: Callable[[float], None] = time.sleep):
        self.model = model or model_id()
        self.drafted_by = f"bedrock:{self.model}"
        self._client = client
        self._sleep = sleep   # injectable, so a test waits for nothing
        self.requests = 0   # Bedrock calls made, a retry of one call not counted; the Focus review shows it

    @property
    def client(self) -> Any:
        if self._client is None:
            if not region():
                raise BedrockError(REGION_MISSING)
            # The bearer token (AWS_BEARER_TOKEN_BEDROCK) is read by the client itself and wins when set; otherwise
            # boto3's chain signs the request with AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and AWS_SESSION_TOKEN.
            # max_retries=0: the SDK's own retries would stack on ours (_create), so only ours happen.
            self._client = anthropic.AnthropicBedrock(aws_region=region(), max_retries=0)
        return self._client

    def _create(self, **request: Any) -> Any:
        """``messages.create`` with backoff on a throttle (429) or a service not ready (503).  Waits are exponential with
        jitter, each one reported as a ``retrying`` run event; a call that returned is never made again; every other
        error goes up at once to be turned into its fixed sentence.  After any throttle every new call, from any draft,
        first waits ``COOL_OFF_SECONDS``, so drafts running together do not all hit the limit at the same moment."""
        global _cool_until
        attempts, base = retry_settings()
        for attempt in range(1, attempts + 1):
            with _cool_lock:
                pause = _cool_until - time.monotonic()
            if pause > 0:
                self._sleep(pause)
            try:
                return self.client.messages.create(**request)
            except BedrockError:
                raise
            except Exception as exc:
                if not _retryable(exc) or attempt == attempts:
                    raise
                if _throttled(exc):
                    with _cool_lock:
                        _cool_until = max(_cool_until, time.monotonic() + COOL_OFF_SECONDS)
                wait = min(MAX_WAIT_SECONDS, base * 2 ** (attempt - 1)) * random.uniform(0.5, 1.0)
                why = "throttling this account" if _throttled(exc) else "not ready"
                run_events.emit(run_events.current_observer.get(), run_events.RETRYING, "Amazon Bedrock is busy",
                                detail=f"It is {why}. Waiting {wait:.0f} seconds, then trying again (attempt {attempt + 1} of {attempts}).")
                logger.warning("Bedrock call %d throttled or not ready (aws error %r, HTTP %s); attempt %d of %d, waiting %.1fs",
                               self.requests, _kind(exc), getattr(exc, "status_code", None), attempt + 1, attempts, wait)
                self._sleep(wait)
        raise AssertionError("unreachable")   # the last attempt returns or raises above

    def _chat(self, messages: list[dict[str, str]], schema: Optional[dict] = None, max_tokens: Optional[int] = None) -> str:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        extra: dict[str, Any] = {"system": system} if system else {}
        if schema:   # the reply as a forced function call, so it arrives as JSON; the same text the local path parses
            extra["tools"] = [{"name": DRAFT_TOOL, "description": "Submit the draft.", "input_schema": schema}]
            extra["tool_choice"] = {"type": "tool", "name": DRAFT_TOOL}
        self.requests += 1
        try:
            resp = self._create(
                model=self.model, max_tokens=max_tokens or MAX_TOKENS,
                messages=[m for m in messages if m["role"] != "system"], **extra)
        except BedrockError:
            raise
        except Exception as exc:
            logger.warning("Bedrock call failed: %s (aws error %r, HTTP %s)", type(exc).__name__, _kind(exc),
                           getattr(exc, "status_code", None))
            raise BedrockError(problem_for(exc, self.model, region())) from None
        usage = getattr(resp, "usage", None)   # at WARNING so it shows with no logging set up; counts only, never text
        logger.warning("Bedrock request %d: %s, %s input tokens, %s output tokens, stop reason %s", self.requests, self.model,
                       getattr(usage, "input_tokens", "unknown"), getattr(usage, "output_tokens", "unknown"), resp.stop_reason)
        if schema:   # a reply cut off at max_tokens is half a JSON object: "" is read as invalid JSON and discarded
            call = next((b for b in resp.content if b.type == "tool_use"), None)
            return json.dumps(call.input) if call is not None and resp.stop_reason != "max_tokens" else ""
        return "".join(b.text for b in resp.content if b.type == "text")

    def _written_by(self) -> str:
        return f"Written by Amazon Bedrock ({self.model}) from the supplied sources."

    def _write(self, empty: HighlightResult, label: str, system: str, results: list[dict[str, Any]],
               max_tokens: Optional[int],
               parse: Callable[[str, list[str], ClaimReader], Optional[HighlightResult]]) -> HighlightResult:
        """The call both drafting providers make once they hold sources: the draft, or ``empty`` saying why not."""
        warnings = [f"{label}: only the first {SOURCE_CHARS:,} characters of {r['host']} were shown to the model"
                    for r in results if len(" ".join(r["text"].split())) > SOURCE_CHARS]
        raw = self._chat(
            [{"role": "system", "content": _sourced(system)},
             {"role": "user", "content": results_message(label, results, "Supplied sources", SOURCE_CHARS)}],
            SOURCED_SCHEMA, max_tokens)
        try:
            res = parse(raw, warnings, _sourced_reader(results))
        except (AttributeError, TypeError, KeyError, ValueError) as exc:   # a field of the reply was not in a usable shape
            logger.warning("%s: the model's reply could not be read: %s", label, frames(exc))
            empty.draft_warnings = warnings
            empty.reason = "The model's reply for this piece was not in a form that could be read, so nothing was drafted. Draft again."
            return empty
        if res is None:
            empty.draft_warnings = warnings
            return empty
        if not res.claims:   # nothing in it traces to a quote, so none of it is kept
            empty.draft_warnings = warnings + res.warnings + [f"{label}: {NO_VERIFIED_CLAIMS}"]
            empty.reason = NO_VERIFIED_CLAIMS
            return empty
        res.warnings.append(self._written_by())
        res.draft_warnings = warnings
        return res


def _sourced(system: str) -> str:
    """A shared drafting prompt made to speak of supplied sources, with the claim step that asks for a quote."""
    system, n = _STEP3.subn(lambda _m: SOURCED_STEP3, system)
    if n != 1:
        raise RuntimeError("the shared drafting prompt no longer has exactly one claim step to replace")
    return system.replace("search results", "supplied sources")


def _sourced_reader(results: list[dict[str, Any]]) -> ClaimReader:
    """Reads a claim of the reply only if it holds against the source it cites; otherwise drops it, saying why."""
    by_id = {r["id"]: r for r in results if r.get("id")}
    texts = {i: r["text"] for i, r in by_id.items()}

    def read(c: dict[str, Any], by_url: dict[str, dict[str, Any]], hl: list[str]) -> Optional[dict[str, Any]]:
        text = strip_links((c.get("text") or c.get("claim") or "").strip())
        if not text:
            return None
        quote = " ".join(str(c.get("quote") or "").split())
        sid = str(c.get("source_id") or "").strip().strip("[]").casefold()
        why = check_sourced_claim(text, quote, sid, texts)
        if why:
            hl.append(f"claim dropped, {why}: {text[:90]}")
            return None
        r = by_id[sid]
        return {"text": text, "url": r["url"], "title": r.get("title") or "", "cited_text": quote, "source_id": sid,
                "sha256": r.get("sha256", ""), "fetched_at": r.get("fetched_at", ""), "host": r.get("host", ""),
                "published_date": r.get("publishedDate") or "", "origin": r.get("origin", ""),
                "source_flags": list(r.get("flags") or [])}

    return read


class BedrockProvider(_Chat, DraftingProvider):
    """Digital Payments highlights and outlook."""

    def find_highlight(
        self, company: str, ir_domain: str, *, start: date, end: date, today: date,
        aliases: Optional[Sequence[str]] = None, style_examples: str = "",
    ) -> HighlightResult:
        empty = HighlightResult(company=company, search_scope=None, ir_domain=ir_domain,
                                drafted_by=self.drafted_by, no_story=True)
        results = sources_for(company, end)
        if not results:
            empty.draft_warnings = [f"{company}: {NO_SOURCES}"]
            empty.reason = NO_SOURCES
            return empty
        return self._write(
            empty, company, HIGHLIGHT_SYSTEM.replace("{company}", company), results, None,
            lambda raw, warnings, read: highlight_from_reply(
                raw, company, ir_domain, SCOPE_SUPPLIED, list(aliases or [company]), results, warnings, who=self.WHO,
                label=self.LABEL, drafted_by=self.drafted_by, where=WHERE_SUPPLIED, read_claim=read))

    def draft_outlook(self, table_stats: dict[str, Any], highlights: list[dict[str, Any]]) -> OutlookResult:
        text = self._chat(
            [{"role": "system", "content": OUTLOOK_SYSTEM},
             {"role": "user", "content": outlook_user_message(table_stats, highlights)}],
            max_tokens=OUTLOOK_MAX_TOKENS).strip()
        return OutlookResult(text=text, stats=table_stats, drafted_by=self.drafted_by)


class BedrockNarrativeProvider(_Chat, NarrativeProvider):
    """Every other section's pieces, and the Focus outline, lead and conclusion."""

    def draft_piece(self, brief: NarrativeBrief, *, start: date, end: date, today: date) -> HighlightResult:
        empty = HighlightResult(company=brief.label, search_scope=None, ir_domain=", ".join(brief.preferred_domains),
                                drafted_by=self.drafted_by, no_story=True)
        results = sources_for(brief.label, end)
        if not results:
            empty.draft_warnings = [f"{brief.label}: {NO_SOURCES}"]
            empty.reason = NO_SOURCES
            return empty
        return self._write(
            empty, brief.label, narrative_system(brief), results, brief.max_tokens,
            lambda raw, warnings, read: piece_from_reply(
                raw, brief, SCOPE_SUPPLIED, results, warnings, who=self.WHO, label=self.LABEL,
                drafted_by=self.drafted_by, where=WHERE_SUPPLIED, read_claim=read))

    def complete(self, system: str, prompt: str, *, max_tokens: int) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        return self._chat(messages, max_tokens=max_tokens).strip()
