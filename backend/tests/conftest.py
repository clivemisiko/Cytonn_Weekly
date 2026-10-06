"""Suite-wide guard: no test may read or write the real data/app.db.

(One deliberate exception: test_report_type_migration copies the file's bytes, when it
exists, to migrate the copy, and checks the original's hash is unchanged.  It never opens
the real file as a database.)

Code that takes ``db_path=None`` falls back to sections._DEFAULT_DB, and the
review API (api/main.py) does unless it is given a path.  Pointing that default at a per-test temp
file means a test that forgets to pass its own path still cannot touch real data.
"""

import pytest

from cytonn_weekly import sections


@pytest.fixture(autouse=True)
def fake_anthropic_key(monkeypatch):
    """The review API refuses to draft in anthropic mode without a key (api.main.provider_problem).

    Every test fakes the pipeline, so a placeholder lets those drafts run; it also replaces any
    real key from the developer's shell, so no test could spend budget even by mistake.  Tests of
    the missing-key refusal delete it themselves.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder-not-a-real-key")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)


# Settings a developer's shell may carry, and that the Docker container always carries
# (docker-compose.yml passes the repo-root .env to it).  The suite assumes none is set:
# a test that needs one sets it itself.
_AMBIENT_SETTINGS = (
    "CYTONN_LLM_PROVIDER",
    "CYTONN_LOCAL_MODEL",
    "CYTONN_OLLAMA_URL",
    "CYTONN_EXA_REFRESH",
    "CYTONN_LOCAL_MAX_SEARCH_RESULTS",
    "CYTONN_LOCAL_RESULT_CHARS",
    "CYTONN_LOCAL_NUM_THREAD",
    "CYTONN_LOCAL_NUM_PREDICT",
    "EXA_API_KEY",
    "CYTONN_WEB_ORIGINS",
    "CYTONN_SMTP_HOST",
    "CYTONN_SMTP_PORT",
    "CYTONN_SMTP_USER",
    "CYTONN_SMTP_PASSWORD",
    "CYTONN_SMTP_FROM",
    "CYTONN_SUMMARY_RECIPIENTS",
)


@pytest.fixture(autouse=True)
def no_ambient_settings(monkeypatch):
    """No test sees the real provider switch, search key or mail settings, so none can reach a real service."""
    for name in _AMBIENT_SETTINGS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def isolated_default_db(tmp_path, monkeypatch):
    monkeypatch.setattr(sections, "_DEFAULT_DB", tmp_path / "default_app.db")
