from __future__ import annotations

import importlib.util
import json
import logging
import os
from typing import Any, Optional

import anthropic

from cytonn_weekly.digital_payments.providers import local_provider as dp_local
from cytonn_weekly.digital_payments.providers.base import HighlightResult
from cytonn_weekly.narrative.local_provider import LocalNarrativeProvider

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

RECREATE = "Changes to .env reach the api container only when it is recreated (docker compose up -d --force-recreate api)."
REGION_MISSING = (f"Drafting with Amazon Bedrock needs an AWS region, and none is set. Set {REGION_VARS[0]} (us-east-1 for the "
                  f"inference profile {DEFAULT_MODEL}) in .env. {RECREATE}")
CREDENTIALS_MISSING = ("Drafting with Amazon Bedrock needs AWS credentials, and none are set. Set AWS_ACCESS_KEY_ID and "
                       f"AWS_SECRET_ACCESS_KEY (plus {TOKEN_VAR} for temporary keys), or {BEARER_VAR}, in .env. {RECREATE} "
                       "A role or profile on the host is not looked for.")
BOTO3_MISSING = (f"Signing Bedrock requests with access keys needs boto3, which is not installed in this build. Use {BEARER_VAR}, "
                 "or rebuild the image from the current pyproject.toml.")
EXA_MISSING = (f"Web search needs {dp_local.EXA_KEY_ENV_VAR}, and none is set (in .env or the environment). Drafting with Amazon "
               f"Bedrock searches with Exa and only writes from what it finds. Add the key to .env. {RECREATE}")


class BedrockError(RuntimeError):
    """Written for the coordinator and shown as it stands (api/main.failure_message); never holds a secret."""


def _clean(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def region() -> str:
    return next((v for v in map(_clean, REGION_VARS) if v), "")


def model_id() -> str:
    return _clean(MODEL_ENV_VAR) or DEFAULT_MODEL


def boto3_installed() -> bool:
    return importlib.util.find_spec("boto3") is not None


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
    if not _clean(dp_local.EXA_KEY_ENV_VAR):
        return EXA_MISSING
    return None


def startup_line() -> str:
    """One log line saying which AWS variables are set.  Names only, never a value."""
    names = (*REGION_VARS, BEARER_VAR, *KEY_VARS, TOKEN_VAR)
    on = [n for n in names if _clean(n)]
    line = (f"Drafting with Amazon Bedrock ({model_id()}); search by Exa. AWS variables set: {', '.join(on) or 'none'}; "
            f"not set: {', '.join(n for n in names if n not in on) or 'none'}.")
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


class _Bedrock:
    """The chat call, for either local provider: Claude on Bedrock in place of Ollama."""

    WHO = "Bedrock model"
    LABEL = "Bedrock provider"

    def __init__(self, client: Any = None, model: Optional[str] = None, **kwargs: Any):
        super().__init__(model=model or model_id(), **kwargs)  # type: ignore[call-arg]
        self.drafted_by = f"bedrock:{self.model}"
        self.settings = dp_local.LocalSettings()  # the dev speed settings (CYTONN_LOCAL_*) are for Ollama only
        self._client = client
        self.requests = 0   # Bedrock calls made; the Focus review shows it

    @property
    def client(self) -> Any:
        if self._client is None:
            if not region():
                raise BedrockError(REGION_MISSING)
            # The bearer token (AWS_BEARER_TOKEN_BEDROCK) is read by the client itself and wins when set; otherwise
            # boto3's chain signs the request with AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and AWS_SESSION_TOKEN.
            self._client = anthropic.AnthropicBedrock(aws_region=region())
        return self._client

    def _ensure_model(self) -> None:
        return None   # no local model to find

    def _exa_key(self) -> str:
        key = self._exa_api_key or _clean(dp_local.EXA_KEY_ENV_VAR)
        if not key:
            raise dp_local.SearchKeyError(EXA_MISSING)
        return key

    def _chat(self, messages: list[dict[str, str]], schema: Optional[dict] = None, max_tokens: Optional[int] = None) -> str:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        extra: dict[str, Any] = {"system": system} if system else {}
        if schema:   # the reply as a forced function call, so it arrives as JSON; the same text the local path parses
            extra["tools"] = [{"name": DRAFT_TOOL, "description": "Submit the draft.", "input_schema": schema}]
            extra["tool_choice"] = {"type": "tool", "name": DRAFT_TOOL}
        self.requests += 1
        try:
            resp = self.client.messages.create(
                model=self.model, max_tokens=max_tokens or MAX_TOKENS,
                messages=[m for m in messages if m["role"] != "system"], **extra)
        except BedrockError:
            raise
        except Exception as exc:
            logger.warning("Bedrock call failed: %s (aws error %r, HTTP %s)", type(exc).__name__, _kind(exc),
                           getattr(exc, "status_code", None))
            raise BedrockError(problem_for(exc, self.model, region())) from None
        if schema:   # a reply cut off at max_tokens is half a JSON object: "" is read as invalid JSON and discarded
            call = next((b for b in resp.content if b.type == "tool_use"), None)
            return json.dumps(call.input) if call is not None and resp.stop_reason != "max_tokens" else ""
        return "".join(b.text for b in resp.content if b.type == "text")

    def _noted(self, res: HighlightResult) -> HighlightResult:
        if not res.no_story:
            res.warnings.append(f"Searched with Exa, written by Amazon Bedrock ({self.model}).")
        return res


class BedrockProvider(_Bedrock, dp_local.LocalProvider):
    """Digital Payments highlights and outlook."""

    def find_highlight(self, *args: Any, **kwargs: Any) -> HighlightResult:
        return self._noted(super().find_highlight(*args, **kwargs))


class BedrockNarrativeProvider(_Bedrock, LocalNarrativeProvider):
    """Every other section's pieces, and the Focus outline, lead and conclusion."""

    def draft_piece(self, *args: Any, **kwargs: Any) -> HighlightResult:
        return self._noted(super().draft_piece(*args, **kwargs))
