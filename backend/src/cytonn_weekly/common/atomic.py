from __future__ import annotations

import functools
import os
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar, Union

F = TypeVar("F", bound=Callable[..., Any])

# One lock for every read-modify-write of a small shared file (a manifest, a form, a cache index). Those are quick and
# nothing waits on the network inside them, so one lock is enough; it is re-entrant because one save calls another.
# ponytail: one lock for all of them, a lock per file if a long save ever sits in one.
GUARD = threading.RLock()


_KEYS: dict[str, threading.Lock] = {}
_KEYS_GUARD = threading.Lock()


def key_lock(key: str) -> threading.Lock:
    """One lock per key, for work that is slow and should be done once (an OCR reading of one PDF)."""
    with _KEYS_GUARD:
        return _KEYS.setdefault(key, threading.Lock())


def locked(fn: F) -> F:
    @functools.wraps(fn)
    def inner(*args: Any, **kwargs: Any) -> Any:
        with GUARD:
            return fn(*args, **kwargs)

    return inner  # type: ignore[return-value]


def write_atomic(path: Path, data: Union[str, bytes]) -> None:
    """Write beside the file, then replace it, so a reader sees the whole old file or the whole new one, never half."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        if isinstance(data, bytes):
            tmp.write_bytes(data)
        else:
            tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
