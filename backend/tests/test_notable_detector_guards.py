"""Two guards on the detector library, checked on its source rather than by its behaviour.

1. Isolation: the library imports only the standard library, the notable shape and the few house helpers it needs by name, and
   nothing that reaches a database, a file reader, a fetcher, the export or a model. It opens no file and runs no code it builds.
2. Independence: the verifier shares no code with the detectors it checks (no import of the library, the wording or the series
   modules), so a mistake in a detector's arithmetic or wording cannot be repeated in the check on it.

The scanner is itself tested on small invented sources, so each guard is shown able to fail.
"""

import ast
import sys
from pathlib import Path

import pytest

from cytonn_weekly.notable import detectors

DIR = Path(detectors.__file__).parent
STDLIB = set(sys.stdlib_module_names)
# Standard-library modules that reach a file, a database, a network, a process or another thread of execution.
REACHES_OUT = {"sqlite3", "socket", "ssl", "urllib", "http", "ftplib", "smtplib", "poplib", "imaplib", "xmlrpc", "subprocess", "os",
               "pathlib", "shutil", "tempfile", "glob", "io", "pickle", "shelve", "dbm", "csv", "zipfile", "tarfile", "gzip", "ctypes",
               "multiprocessing", "threading", "asyncio", "webbrowser", "importlib", "runpy"}
BANNED_CALLS = {"open", "eval", "exec", "compile", "__import__", "input"}

# What the detectors may take from the rest of the code base, by module and by name (None: anything from that module).
LIBRARY_MAY_IMPORT = {
    "cytonn_weekly.common.formatting": {"round_half_up", "fmt_value", "PCT", "NUMBER", "MULTIPLE", "PRICE"},
    "cytonn_weekly.common.computed": {"show", "BPS", "POINTS", "PLAIN_PCT"},
    "cytonn_weekly.equities.weekly": {"recommendation"},  # the Universe of Coverage's band rule: called, never copied
    "cytonn_weekly.fixed_income.net_borrowing": {"Log"},  # its day count, called with plain dates
    "cytonn_weekly.notable.suggestion": None,
    "cytonn_weekly.notable.detectors.series": None,
    "cytonn_weekly.notable.detectors.wording": None,
    "cytonn_weekly.notable.detectors.verify": None,
    "cytonn_weekly.notable.detectors.library": None,
}
# The verifier may take less, and nothing of the detectors' own.
VERIFIER_MAY_IMPORT = {
    "cytonn_weekly.common.formatting": {"round_half_up"},
    "cytonn_weekly.equities.weekly": {"recommendation"},
    "cytonn_weekly.notable.suggestion": None,
}


def violations(source: str, may_import: dict, *, library: bool) -> list[str]:
    """Every import or call in ``source`` that the rules forbid, as short messages."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for a in node.names:
                root = a.name.split(".")[0]
                if root not in STDLIB or root in REACHES_OUT:
                    found.append(f"import {a.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                found.append(f"relative import from {'.' * node.level}{module}")
            elif module.split(".")[0] in STDLIB:
                if module.split(".")[0] in REACHES_OUT:
                    found.append(f"from {module} import ...")
            elif module in may_import:
                allowed = may_import[module]
                bad = [a.name for a in node.names if allowed is not None and a.name not in allowed]
                if bad:
                    found.append(f"from {module} import {', '.join(bad)}")
            else:
                found.append(f"from {module} import ...")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BANNED_CALLS:
            found.append(f"call to {node.func.id}()")
    return found


def source_files():
    files = sorted(DIR.glob("*.py"))
    assert {f.name for f in files} >= {"__init__.py", "series.py", "wording.py", "library.py", "verify.py"}
    return files


# -- the guards hold on the real code ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", source_files(), ids=lambda p: p.name)
def test_the_detector_package_imports_only_what_it_may_and_reaches_nothing_out(path):
    if path.name == "verify.py":
        may = VERIFIER_MAY_IMPORT
    else:
        may = LIBRARY_MAY_IMPORT
    assert violations(path.read_text(encoding="utf-8"), may, library=path.name != "verify.py") == []


def test_the_verifier_imports_nothing_from_the_detectors_it_checks():
    text = (DIR / "verify.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + \
              [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    own = [m for m in modules if m.startswith("cytonn_weekly.notable.detectors")]
    assert own == [], own
    imported_names = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not imported_names & {"library", "wording", "series", "streak", "since", "trailing_compare", "threshold_cross",
                                 "expected_range", "pace", "drift", "Series", "fmt", "TEMPLATES"}


def test_no_other_module_imports_the_verifier_except_the_library():
    for path in source_files():
        text = path.read_text(encoding="utf-8")
        imports_verifier = "notable.detectors.verify" in text
        assert imports_verifier == (path.name in ("library.py", "__init__.py")), path.name


# -- the guards are shown able to fail ---------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "import httpx",
        "import requests",
        "import urllib.request",
        "import sqlite3",
        "import os",
        "from pathlib import Path",
        "import socket",
        "import subprocess",
        "from cytonn_weekly.weekly import inputs",
        "from cytonn_weekly.digital_payments import review_store",
        "from cytonn_weekly.equities.weekly import build_equities_weekly_review",
        "from cytonn_weekly.common.formatting import clean_pdf_number",
        "from cytonn_weekly.weekly import export",
        "from cytonn_weekly.notable import store",
        "from . import library",
        "x = open('history.csv')",
        "exec('1+1')",
    ],
)
def test_the_scanner_refuses_a_forbidden_import_or_call(source):
    assert violations(source, LIBRARY_MAY_IMPORT, library=True), source


@pytest.mark.parametrize(
    "source",
    [
        "import decimal\nfrom datetime import date\nimport re, math, statistics",
        "from cytonn_weekly.common.formatting import fmt_value, round_half_up, PCT",
        "from cytonn_weekly.equities.weekly import recommendation",
        "from cytonn_weekly.fixed_income.net_borrowing import Log",
        "from cytonn_weekly.notable.suggestion import Suggestion",
        "from cytonn_weekly.notable.detectors.series import Series",
        "from cytonn_weekly.notable.detectors.verify import verify",
    ],
)
def test_the_scanner_accepts_what_the_library_is_allowed(source):
    assert violations(source, LIBRARY_MAY_IMPORT, library=True) == []


def test_an_import_inside_a_function_is_found_too():
    assert violations("def f():\n    import httpx\n", LIBRARY_MAY_IMPORT, library=True) == ["import httpx"]
    assert violations("def f():\n    from cytonn_weekly.equities.weekly import recommendation\n", LIBRARY_MAY_IMPORT, library=True) == []


@pytest.mark.parametrize(
    "source",
    [
        "from cytonn_weekly.notable.detectors.library import streak",
        "from cytonn_weekly.notable.detectors import library",
        "from cytonn_weekly.notable.detectors.wording import fmt",
        "from cytonn_weekly.notable.detectors.series import Series",
        "import cytonn_weekly.notable.detectors.wording",
    ],
)
def test_the_verifier_scanner_refuses_any_import_of_the_detectors(source):
    assert violations(source, VERIFIER_MAY_IMPORT, library=False), source


def test_the_verifier_may_not_use_the_detectors_day_count_or_formatting_helpers():
    assert violations("from cytonn_weekly.fixed_income.net_borrowing import Log", VERIFIER_MAY_IMPORT, library=False)
    assert violations("from cytonn_weekly.common.computed import show", VERIFIER_MAY_IMPORT, library=False)
    assert violations("from cytonn_weekly.common.formatting import fmt_value", VERIFIER_MAY_IMPORT, library=False)
