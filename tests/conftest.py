"""Suite-wide guard: no test may read or write the real data/app.db.

Code that takes ``db_path=None`` falls back to sections._DEFAULT_DB, and the
Streamlit review screen always does.  Pointing that default at a per-test temp
file means a test that forgets to pass its own path still cannot touch real data.
"""

import pytest

from cytonn_weekly import sections


@pytest.fixture(autouse=True)
def isolated_default_db(tmp_path, monkeypatch):
    monkeypatch.setattr(sections, "_DEFAULT_DB", tmp_path / "default_app.db")
