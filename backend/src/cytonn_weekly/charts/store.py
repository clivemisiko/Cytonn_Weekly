"""The chart files of a saved review: ``<data dir>/charts/<run_id>/<chart_id>.png`` and ``.json``.

A section builder renders each chart before the review exists, so the bytes ride on the review
object (``attach``) and are written once the first save has given it a run id (``persist``).  Each
file is created exclusively: a file that is already there is never replaced, so what an approved
review shows can only change by someone editing the folder, and that is caught on every read,
because the block holds the PNG's SHA-256 and ``read_png`` checks it each time.  Drafting the
section again makes a new review with a new run id, and so a new folder; the old one stays with
its review.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional, Union

from cytonn_weekly import paths
from cytonn_weekly.charts.specs import SPECS

_DEFAULT_ROOT = paths.DATA_DIR / "charts"
_FILES = "_chart_files"     # attribute on a CoordinatorReview: {chart_id: {"png": bytes, "json": bytes}}


class ChartFileError(Exception):
    """A chart file that cannot be served; ``status`` is the HTTP status the API answers with."""

    status = 404


class UnknownChart(ChartFileError):
    pass


class ChartFileMissing(ChartFileError):
    pass


class ChartFileChanged(ChartFileError):
    status = 409


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def root_dir(root: Optional[Union[Path, str]] = None) -> Path:
    return Path(root) if root is not None else _DEFAULT_ROOT


def attach(review: Any, files: dict[str, dict[str, bytes]]) -> None:
    """Keep the rendered files on the review until it is saved.  They are never part of its saved content."""
    setattr(review, _FILES, dict(files))


def persist(review: Any, root: Optional[Union[Path, str]] = None) -> list[Path]:
    """Write the attached files under the review's run id, once.  Raises FileExistsError rather than overwrite."""
    files: dict[str, dict[str, bytes]] = getattr(review, _FILES, None) or {}
    if not files:
        return []
    if review.run_id is None:
        raise ValueError("the review has no run id yet: save it first")
    folder = root_dir(root) / str(int(review.run_id))
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for chart_id, parts in files.items():
        _known(chart_id)
        for ext, data in parts.items():
            path = folder / f"{chart_id}.{ext}"
            with open(path, "xb") as f:      # exclusive: an existing file is never replaced
                f.write(data)
            written.append(path)
    setattr(review, _FILES, {})
    return written


def _known(chart_id: str) -> str:
    if chart_id not in SPECS:
        raise UnknownChart(f"no chart {chart_id!r}; known charts: {', '.join(sorted(SPECS))}")
    return chart_id


def read_png(run_id: int, chart_id: str, expected_sha256: Optional[str], root: Optional[Union[Path, str]] = None) -> bytes:
    """The PNG of one drawn chart of a saved review, after checking it is still the file the review recorded."""
    _known(chart_id)
    if not expected_sha256:
        raise ChartFileMissing(f"run {run_id} has no drawn chart {chart_id!r}")
    path = root_dir(root) / str(int(run_id)) / f"{chart_id}.png"
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise ChartFileMissing(f"the image file of chart {chart_id!r} for run {run_id} is missing; draft the section again") from None
    if sha256(data) != expected_sha256:
        raise ChartFileChanged(f"the image file of chart {chart_id!r} for run {run_id} is not the one this review recorded "
                               "(its SHA-256 differs); it was changed after the draft and is not served")
    return data
