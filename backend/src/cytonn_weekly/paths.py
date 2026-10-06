"""Where the project's folders are, resolved from this file's own location.

The one place path arithmetic lives: the layout is repo root / backend / src /
cytonn_weekly / paths.py, so backend/ is two levels above this file and the repo
root (where .env stays) is three.

DATA_DIR holds everything the tool writes: app.db, exa_cache/ and summaries/.  It is
backend/data unless CYTONN_DATA_DIR names another folder, which is how the Docker image
points it at its volume (/app/data).  The variable is read once, when this module is
imported, so it has to be in the process environment (the shell, or the compose file),
not in .env, which entrypoints load later.
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR_ENV_VAR = "CYTONN_DATA_DIR"

BACKEND_ROOT = Path(__file__).parents[2]
REPO_ROOT = BACKEND_ROOT.parent
DATA_DIR = Path(os.environ.get(DATA_DIR_ENV_VAR) or BACKEND_ROOT / "data")
