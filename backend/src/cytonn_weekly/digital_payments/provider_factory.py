"""Chooses the drafting provider from the CYTONN_LLM_PROVIDER environment variable.

    (unset) / "anthropic"  -> AnthropicProvider, the production default
    "local"                -> LocalProvider (Ollama + Exa), development only

Selecting "local" prints a conspicuous warning on every call, because its
output must never be published.  Local-only options (ignored by "anthropic"):

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


def local_warning(model: str) -> str:
    return f"*** DEV MODE: drafting with local {model} -- NOT FOR PUBLICATION ***"


def get_provider() -> DraftingProvider:
    name = (os.environ.get(ENV_VAR) or "anthropic").strip().lower()
    if name == "anthropic":
        from cytonn_weekly.digital_payments.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    if name == "local":
        from cytonn_weekly.digital_payments.providers.local_provider import MODEL, LocalProvider

        model = (os.environ.get(LOCAL_MODEL_ENV_VAR) or "").strip() or MODEL
        refresh = (os.environ.get(EXA_REFRESH_ENV_VAR) or "").strip().lower() in ("1", "true", "yes")
        warning = local_warning(model)
        banner = "*" * len(warning)
        print(f"\n{banner}\n{warning}\n{banner}\n", flush=True)
        return LocalProvider(model=model, cache_dir=EXA_CACHE_DIR, refresh_cache=refresh)
    raise ValueError(f"Unknown {ENV_VAR} value {name!r}; expected 'anthropic' or 'local'.")
