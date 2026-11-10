from pathlib import Path

import pytest

from cytonn_weekly.common import atomic


def test_write_atomic_retries_a_transient_replace_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    destination = tmp_path / "notes.json"
    destination.write_text("old", encoding="utf-8")
    replace = atomic.os.replace
    attempts = 0

    def replace_after_lock(source, target):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("temporarily locked")
        replace(source, target)

    monkeypatch.setattr(atomic.os, "replace", replace_after_lock)
    monkeypatch.setattr(atomic.time, "sleep", lambda _: None)

    atomic.write_atomic(destination, "new")

    assert attempts == 3
    assert destination.read_text(encoding="utf-8") == "new"
    assert list(tmp_path.iterdir()) == [destination]


def test_write_atomic_raises_and_cleans_up_after_persistent_replace_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    destination = tmp_path / "notes.json"
    destination.write_text("old", encoding="utf-8")
    attempts = 0

    def locked_replace(_source, _target):
        nonlocal attempts
        attempts += 1
        raise PermissionError("still locked")

    monkeypatch.setattr(atomic.os, "replace", locked_replace)
    monkeypatch.setattr(atomic.time, "sleep", lambda _: None)

    with pytest.raises(PermissionError, match="still locked"):
        atomic.write_atomic(destination, "new")

    assert attempts == atomic._REPLACE_ATTEMPTS
    assert destination.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [destination]
