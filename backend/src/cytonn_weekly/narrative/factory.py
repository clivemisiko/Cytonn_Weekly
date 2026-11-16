"""Chooses the narrative provider from the same CYTONN_LLM_PROVIDER switch Digital Payments uses.

    "bedrock"    -> BedrockNarrativeProvider (Claude on Amazon Bedrock; sources supplied by the analyst
                    or fetched in code from approved sites; no search service), production
    "local"      -> LocalNarrativeProvider (Ollama + Exa), development only
    (unset or blank) -> ValueError, as in the Digital Payments factory

"local" prints the same conspicuous DEV MODE banner as the Digital Payments
factory, and honours CYTONN_LOCAL_MODEL the same way.
"""

from __future__ import annotations

import os

from cytonn_weekly.digital_payments.provider_factory import ENV_VAR, LOCAL_MODEL_ENV_VAR, local_warning, provider_name
from cytonn_weekly.narrative.base import NarrativeProvider


def get_narrative_provider() -> NarrativeProvider:
    name = provider_name()
    if name == "local":
        from cytonn_weekly.digital_payments.providers.local_provider import MODEL
        from cytonn_weekly.narrative.local_provider import LocalNarrativeProvider

        model = (os.environ.get(LOCAL_MODEL_ENV_VAR) or "").strip() or MODEL
        warning = local_warning(model)
        print(f"\n{'*' * len(warning)}\n{warning}\n{'*' * len(warning)}\n", flush=True)
        return LocalNarrativeProvider(model=model)
    if name == "bedrock":
        from cytonn_weekly.narrative.bedrock_provider import BedrockNarrativeProvider

        return BedrockNarrativeProvider()
    raise ValueError(f"Unknown {ENV_VAR} value {name!r}; expected 'bedrock' or 'local'.")
