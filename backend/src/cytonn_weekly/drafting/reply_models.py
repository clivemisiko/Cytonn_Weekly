from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


def _decoded(value: Any, kind: type) -> Any:
    """The model sometimes sends a nested object or list as a JSON string; decode it (twice at most)."""
    for _ in range(2):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return None
    return value if isinstance(value, kind) else None


# Permissive on purpose: every field is Any and extra keys are kept, so a reply the hand-written code accepted today
# is accepted here, with the same warnings from the callers.  The shapes mirror the three hand-written Bedrock schemas
# (prompts.RESPONSE_SCHEMA, bedrock.SOURCED_SCHEMA, bedrock.PDF_SCHEMA), which stay the ones sent to the model.
class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class UrlClaim(_Loose):
    claim: Any = None
    url: Any = None


class SourcedClaim(_Loose):
    text: Any = None
    quote: Any = None
    source_id: Any = None


class DraftReply(_Loose):
    is_genuine_announcement: Any = None
    reasoning: Any = None
    headline: Any = None
    paragraph: Any = None
    claims: Any = []

    @field_validator("claims", mode="before")
    @classmethod
    def _claims_as_dicts(cls, value: Any) -> list[Any]:
        """The claims as a list; a claim that cannot be read as an object is None, for the caller to warn about."""
        return [_decoded(c, dict) for c in _decoded(value or [], list) or []]


class PdfPassage(_Loose):
    page: Any = None
    quote: Any = None


class PdfReply(_Loose):
    passages: Any

    @field_validator("passages", mode="before")
    @classmethod
    def _passages_as_dicts(cls, value: Any) -> list[dict]:
        return [p for p in value if isinstance(p, dict)] if isinstance(value, list) else []
