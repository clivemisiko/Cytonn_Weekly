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


@pytest.fixture(autouse=True)
def isolated_weekly_inputs(tmp_path, monkeypatch):
    """The weekly inputs (uploaded workbooks and reports) default to a folder under the real data
    directory; no test may read or write there, so the default is a per-test temp folder."""
    from cytonn_weekly.weekly import inputs

    monkeypatch.setattr(inputs, "_DEFAULT_ROOT", tmp_path / "inputs" / "weekly")


_LOCAL_HOSTS = ("127.0.0.1", "::1", "localhost")


def _block_network() -> None:
    """No test reaches a real site, for the whole session and from every thread.

    The weekly Fixed Income and Equities builders fetch from CBK, NSE and cytonnreport.com, and
    every drafting provider calls its model over HTTP, unless a test replaces them.  A test that
    forgets to gets a refused connection (which the builders report as a source that did not
    answer), never a live request.

    It is done at the socket, because the HTTP clients differ (the fetchers use httpx; the
    Anthropic SDK brings its own transport), and it is set once, when conftest is imported, and
    never undone: a per-test patch is removed when the test ends, while a run started through
    POST /api/runs keeps working in its own thread after that.  On 2026-10-09 such a thread
    reached the Anthropic API with the placeholder key and was refused; this is what stops it.
    FastAPI's TestClient opens no socket and is unaffected; loopback stays open.
    """
    import socket

    real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo

    def connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host in _LOCAL_HOSTS:
            return real_connect(self, address, *args, **kwargs)
        raise ConnectionRefusedError(f"network access in a test: {address!r}")

    def getaddrinfo(host, *args, **kwargs):
        if host in _LOCAL_HOSTS or host is None:
            return real_getaddrinfo(host, *args, **kwargs)
        raise socket.gaierror(f"network access in a test: {host!r}")

    socket.socket.connect = connect
    socket.getaddrinfo = getaddrinfo


_block_network()
