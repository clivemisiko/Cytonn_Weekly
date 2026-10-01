"""Chooses the drafting provider from the CYTONN_LLM_PROVIDER environment variable.

    (unset) / "anthropic"  -> AnthropicProvider, the production default
    "local"                -> LocalProvider (phi4-mini via Ollama), development only

Selecting "local" prints a conspicuous warning on every call, because its
output must never be published.
"""

from __future__ import annotations

import os

from cytonn_weekly.digital_payments.providers.base import DraftingProvider

ENV_VAR = "CYTONN_LLM_PROVIDER"
LOCAL_WARNING = "*** DEV MODE: drafting with local phi4-mini -- NOT FOR PUBLICATION ***"


def get_provider() -> DraftingProvider:
    name = (os.environ.get(ENV_VAR) or "anthropic").strip().lower()
    if name == "anthropic":
        from cytonn_weekly.digital_payments.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    if name == "local":
        from cytonn_weekly.digital_payments.providers.local_provider import LocalProvider

        banner = "*" * len(LOCAL_WARNING)
        print(f"\n{banner}\n{LOCAL_WARNING}\n{banner}\n", flush=True)
        return LocalProvider()
    raise ValueError(f"Unknown {ENV_VAR} value {name!r}; expected 'anthropic' or 'local'.")
