from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Union

from pydantic import BaseModel, ConfigDict, ValidationError

log = logging.getLogger(__name__)

MAX_TEXT = 120     # the longest string a tool result may hold: a title or a host, never a paragraph
MAX_ITEMS = 50     # the longest list
MAX_RESULT_CHARS = 8000
TOO_LARGE = "The result was too large to show, so none of it was kept. Ask for one section or one item."
UNKNOWN_TOOL = "There is no such tool."
BAD_INPUT = "The input was refused."
FAILED = "The tool could not finish. Nothing was changed."


class Params(BaseModel):
    """What every tool's input model extends: an input with a field the tool does not name is refused, not ignored."""

    model_config = ConfigDict(extra="forbid")


class Refused(Exception):
    """A tool declines with a sentence of our own wording (never text from a source); the model reads it as the result."""


@dataclass(frozen=True)
class ToolContext:
    """What a tool may read from: the job it runs for, the database and the folders the week's files are kept in.  ``runs`` is the
    API's run registry (api/runs.py), or None where there is none."""

    job: dict[str, Any]
    db_path: Optional[Union[Path, str]] = None
    root: Optional[Path] = None          # the weekly inputs
    sources_dir: Optional[Path] = None
    snips_dir: Optional[Path] = None
    runs: Any = None


@dataclass(frozen=True)
class Tool:
    """One read tool.  ``run`` returns plain data and changes nothing; ``shape`` says which of its keys the model may see."""

    name: str
    description: str
    params: type[Params]
    run: Callable[[Any, ToolContext], Any]
    shape: Any


def schemas(tools: list[Tool]) -> list[dict[str, Any]]:
    """The tool list as the Messages API takes it."""
    return [{"name": t.name, "description": t.description, "input_schema": t.params.model_json_schema()} for t in tools]


def trim(value: Any, shape: Any) -> Any:
    """What a tool result may carry to the model.  ``shape`` is a tuple of the keys kept, or a dict from key to the shape of
    that key's value; a list is trimmed item by item.  A key not named is dropped, so a field added to a payload later reaches
    the model only when someone adds it here.  Strings are cut to MAX_TEXT and lists to MAX_ITEMS; nothing else is changed."""
    if isinstance(value, list):
        return [trim(v, shape) for v in value[:MAX_ITEMS]]
    if isinstance(value, dict):
        keep = shape if isinstance(shape, dict) else {k: None for k in (shape or ())}
        return {k: trim(value[k], keep[k]) for k in keep if k in value}
    if isinstance(value, str):
        return value[:MAX_TEXT]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:MAX_TEXT]   # a date or another plain object, as text


def execute(by_name: dict[str, Tool], name: str, raw_input: Any, ctx: ToolContext) -> dict[str, Any]:
    """Check the call, run the tool, trim its result.  Always returns a dict and never raises: a refusal or a failure is
    ``{"error": ...}`` for the model to read.  A name that is not in ``by_name`` runs nothing."""
    tool = by_name.get(name)
    if tool is None:
        return {"error": UNKNOWN_TOOL}
    try:
        args = tool.params.model_validate(raw_input if isinstance(raw_input, dict) else {})
    except ValidationError as exc:
        return {"error": BAD_INPUT, "problems": [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"[:MAX_TEXT] for e in exc.errors()][:5]}
    try:
        result = trim(tool.run(args, ctx), tool.shape)
    except Refused as exc:
        return {"error": str(exc)}
    except Exception:  # noqa: BLE001 - a tool's failure is the model's to read, not the loop's to crash on
        log.exception("agent tool %s failed", name)
        return {"error": FAILED}
    if len(json.dumps(result)) > MAX_RESULT_CHARS:
        return {"error": TOO_LARGE}
    return result if isinstance(result, dict) else {"result": result}
