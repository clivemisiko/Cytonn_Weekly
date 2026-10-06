"""Chooses the narrative provider from the same CYTONN_LLM_PROVIDER switch Digital Payments uses.

    (unset) / "anthropic"  -> AnthropicNarrativeProvider, the production default
    "local"                -> LocalNarrativeProvider (Ollama + Exa), development only

"local" prints the same conspicuous DEV MODE banner as the Digital Payments
factory, and honours CYTONN_LOCAL_MODEL the same way.
"""

from __future__ import annotations

import os

from cytonn_weekly.digital_payments.provider_factory import ENV_VAR, LOCAL_MODEL_ENV_VAR, local_warning
from cytonn_weekly.narrative.base import NarrativeProvider


def get_narrative_provider() -> NarrativeProvider:
    name = (os.environ.get(ENV_VAR) or "anthropic").strip().lower()
    if name == "anthropic":
        from cytonn_weekly.narrative.anthropic_provider import AnthropicNarrativeProvider

        return AnthropicNarrativeProvider()
    if name == "local":
        from cytonn_weekly.digital_payments.providers.local_provider import MODEL
        from cytonn_weekly.narrative.local_provider import LocalNarrativeProvider

        model = (os.environ.get(LOCAL_MODEL_ENV_VAR) or "").strip() or MODEL
        warning = local_warning(model)
        print(f"\n{'*' * len(warning)}\n{warning}\n{'*' * len(warning)}\n", flush=True)
        return LocalNarrativeProvider(model=model)
    raise ValueError(f"Unknown {ENV_VAR} value {name!r}; expected 'anthropic' or 'local'.")
