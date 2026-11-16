"""Chooses the drafting provider from the CYTONN_LLM_PROVIDER environment variable.

    "bedrock"    -> BedrockProvider (Claude on Amazon Bedrock; sources supplied by the analyst
                    or fetched in code from approved sites; no search service), production
    "local"      -> LocalProvider (Ollama + Exa), development only
    (unset or blank) -> refused: the switch must be set on purpose, so a missing variable never
                    silently selects a path with different sourcing guarantees

Selecting "local" prints a conspicuous warning on every call, because its
output must never be published.  Local-only options (ignored by the other providers):

    CYTONN_LOCAL_MODEL=<ollama model>  model to draft with (default phi4-mini),
                                       e.g. gemma4:26b-a4b-it-qat for an A/B run
    CYTONN_EXA_REFRESH=1               ignore cached Exa results and re-query Exa

Local mode caches each company's Exa results in data/exa_cache/ (one file per
company per day) so different models can be compared on identical search
results.  Delete the directory or a file in it, or set CYTONN_EXA_REFRESH=1, to
force a fresh pull.
"""

from __future__ import annotations

import os

from cytonn_weekly.digital_payments.providers.base import DraftingProvider
from cytonn_weekly.paths import DATA_DIR

ENV_VAR = "CYTONN_LLM_PROVIDER"
LOCAL_MODEL_ENV_VAR = "CYTONN_LOCAL_MODEL"
EXA_REFRESH_ENV_VAR = "CYTONN_EXA_REFRESH"
EXA_CACHE_DIR = DATA_DIR / "exa_cache"


NOT_CONFIGURED = (
    f"{ENV_VAR} is not set, so no draft can start. Set it to 'bedrock' or 'local' "
    "(in .env or the shell), then restart the API."
)
ANTHROPIC_REMOVED = f"{ENV_VAR}=anthropic was removed: the direct Anthropic provider no longer exists. Set it to 'bedrock', then restart the API."


def local_warning(model: str) -> str:
    return f"*** DEV MODE: drafting with local {model} -- NOT FOR PUBLICATION ***"


def provider_name() -> str:
    """The chosen provider, lower case.  Unset or blank raises ValueError(NOT_CONFIGURED), "anthropic" ValueError(ANTHROPIC_REMOVED)."""
    name = (os.environ.get(ENV_VAR) or "").strip().lower()
    if not name:
        raise ValueError(NOT_CONFIGURED)
    if name == "anthropic":
        raise ValueError(ANTHROPIC_REMOVED)
    return name


def get_provider() -> DraftingProvider:
    name = provider_name()
    if name == "local":
        from cytonn_weekly.digital_payments.providers.local_provider import MODEL, LocalProvider

        model = (os.environ.get(LOCAL_MODEL_ENV_VAR) or "").strip() or MODEL
        refresh = (os.environ.get(EXA_REFRESH_ENV_VAR) or "").strip().lower() in ("1", "true", "yes")
        warning = local_warning(model)
        banner = "*" * len(warning)
        print(f"\n{banner}\n{warning}\n{banner}\n", flush=True)
        return LocalProvider(model=model, cache_dir=EXA_CACHE_DIR, refresh_cache=refresh)
    if name == "bedrock":
        from cytonn_weekly.narrative.bedrock_provider import BedrockProvider

        return BedrockProvider()
    raise ValueError(f"Unknown {ENV_VAR} value {name!r}; expected 'bedrock' or 'local'.")
