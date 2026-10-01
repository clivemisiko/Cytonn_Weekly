"""Loads the repo-root .env file into the process environment.

Generic on purpose: whatever KEY=value pairs .env holds (EXA_API_KEY,
ANTHROPIC_API_KEY, CYTONN_LLM_PROVIDER, ...) become environment variables, so
adding a new secret never needs more wiring.  Variables already set in the shell
win over .env (override=False), so a one-off `EXA_API_KEY=... python ...` still
behaves as expected.

Call load_env() once at the top of an entrypoint (a script, the scheduler, the
Streamlit app), before anything reads os.environ.  Library code under src/ does
not call it itself and just reads os.environ, which keeps tests hermetic: a
developer's real .env can never leak into a test run.

.env is gitignored.  Never print its values, only key names.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ENV_FILE = Path(__file__).parents[2] / ".env"


def load_env(path: Path | None = None, *, quiet: bool = False) -> list[str]:
    """Load .env into os.environ; return the names of the variables it set.

    A name is left out if the shell already defined it (the shell wins).  Prints
    the names only, never the values, unless ``quiet``.  Returns [] if there is
    no .env file.
    """
    env_file = path or ENV_FILE
    if not env_file.is_file():
        return []
    names = [name for name, value in dotenv_values(env_file).items() if value is not None]
    already_set = {name for name in names if name in os.environ}
    load_dotenv(env_file, override=False)
    loaded = [name for name in names if name not in already_set]
    if not quiet:
        if loaded:
            print(f"Loaded from .env: {', '.join(loaded)}")
        if already_set:
            print(f"Already set in shell (kept): {', '.join(sorted(already_set))}")
    return loaded
