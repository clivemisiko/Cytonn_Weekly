"""Loads the repo-root .env file into the process environment.

Generic on purpose: whatever KEY=value pairs .env holds (EXA_API_KEY,
ANTHROPIC_API_KEY, CYTONN_LLM_PROVIDER, ...) become environment variables, so
adding a new secret never needs more wiring.  Variables already set in the shell
win over .env (override=False), so a one-off `EXA_API_KEY=... python ...` still
behaves as expected.

So an environment variable beats .env.  That bites when an old key lingers in a Windows user
variable: editing .env then changes nothing.  key_override_warnings() names each API key the
environment and .env disagree on (last four characters only), and the API logs it at start.

Call load_env() once at the top of an entrypoint (a script, the scheduler, the
FastAPI app), before anything reads os.environ.  Library code under src/ does
not call it itself and just reads os.environ, which keeps tests hermetic: a
developer's real .env can never leak into a test run.

.env is gitignored.  Never print its values, only key names.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

from cytonn_weekly.paths import REPO_ROOT

ENV_FILE = REPO_ROOT / ".env"


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


# The API keys a stale environment variable can silently override (see the module docstring).
API_KEYS = ("EXA_API_KEY", "ANTHROPIC_API_KEY")


def env_file_value(name: str, path: Path | None = None) -> str | None:
    """What .env itself holds for ``name``, read without touching os.environ.  None if it has none."""
    env_file = path or ENV_FILE
    if not env_file.is_file():
        return None
    return dotenv_values(env_file).get(name) or None


def ending(secret: str) -> str:
    """A key by its last four characters, the most of one that is ever shown or logged."""
    return f"ending ...{secret[-4:]}" if len(secret) >= 12 else "too short to show any of it"


def key_override_warnings(path: Path | None = None, names: tuple[str, ...] = API_KEYS) -> list[str]:
    """One line per key that the process environment and .env both hold, with different values.

    Call it after load_env(): a key only .env holds is by then in the environment too (equal,
    so no line), and a key only the environment holds overrides nothing.
    """
    lines = []
    for name in names:
        in_process, in_file = os.environ.get(name), env_file_value(name, path)
        if in_process and in_file and in_process != in_file:
            lines.append(f"{name}: the process environment (a Windows or shell variable) holds a key {ending(in_process)}, "
                         f"and .env holds a different one {ending(in_file)}. The environment's key is the one used: it "
                         "overrides .env. Update or remove that variable, or correct .env, then restart.")
    return lines
