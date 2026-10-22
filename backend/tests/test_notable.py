"""The "Notable this week" panel's backend: the shape of a suggestion, the detector registry, and the analyst's saved decisions.

Detectors here are test-local. The real registry is empty, and nothing a suggestion says reaches a draft, a review item,
the analyst form or the export; the last group of tests proves that on a temporary database.
"""

import ast
import hashlib
import json
import re
import sqlite3
from dataclasses import fields
from datetime import date
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly import db as db_module
from cytonn_weekly import notable, sections
from cytonn_weekly.notable.registry import DetectorContext, run_detectors
from cytonn_weekly.notable.suggestion import InvalidSuggestion, Suggestion
from cytonn_weekly.weekly import export
from tests.test_weekly_export import PERIOD as EXPORT_PERIOD
from tests.test_weekly_export import built, week  # noqa: F401 - fixtures: the approved six-section week

WEEK = "2026-10-09"
SECTION = "fixed_income"
POINTS = [{"date": "2026-10-02", "value": 9.4, "display": "9.4%"}, {"date": WEEK, "value": 9.6, "display": "9.6%"}]
DEMO = {"kind": "demo", "label": "invented demo item"}


def make(**over) -> Suggestion:
    base = dict(
        kind="streak", section=SECTION, week_ending=WEEK, headline="The 91-day yield rose for a third week.",
        figures=[{"label": "91-day yield", "value": 9.6, "display": "9.6%", "unit": "%"}],
        working={"series": "91-day yield", "rule": "Three weekly rises in a row.", "window": "last 12 weeks", "points": POINTS},
        provenance=DEMO, rank=50,
    )
    base.update(over)
    return Suggestion(**base)


# ---------------------------------------------------------------------------
# The shape of a suggestion
# ---------------------------------------------------------------------------

def test_a_valid_suggestion_has_every_field_of_the_shape():
    d = make().to_dict()
    assert set(d) == {"id", "kind", "section", "week_ending", "headline", "figures", "working", "provenance", "rank", "version"}
    assert d["version"] == 1 and set(d["working"]) == {"series", "rule", "window", "points"}
    assert re.fullmatch(r"[0-9a-f]{16}", d["id"])


def test_the_id_is_a_stable_hash_of_kind_section_week_series_and_window():
    a = make()
    assert a.id == make(headline="Another wording of the same finding.", rank=10).id  # wording and rank are not part of it
    assert a.id == make().id
    other_series = {**a.working, "series": "182-day yield"}
    other_window = {**a.working, "window": "last 26 weeks"}
    ids = {
        a.id,
        make(kind="record").id,
        make(section="equities").id,
        make(week_ending="2026-10-02").id,
        make(working=other_series).id,
        make(working=other_window).id,
    }
    assert len(ids) == 6


@pytest.mark.parametrize(
    "over",
    [
        {"headline": ""}, {"headline": "   "}, {"headline": "x" * 301}, {"headline": None},
        {"working": None}, {"working": {}},
        {"working": {"series": "s", "rule": "r", "window": "w", "points": []}},
        {"working": {"series": "s", "rule": "", "window": "w", "points": POINTS}},
        {"working": {"series": " ", "rule": "r", "window": "w", "points": POINTS}},
        {"working": {"series": "s", "rule": "r", "window": "", "points": POINTS}},
        {"working": {"series": "s", "rule": "r", "window": "w", "points": [{"date": "not a date", "value": 1, "display": "1"}]}},
        {"working": {"series": "s", "rule": "r", "window": "w", "points": [{"date": WEEK, "value": 1}]}},
        {"provenance": None}, {"provenance": {}}, {"provenance": {"kind": "demo", "label": ""}},
        {"provenance": {"kind": "guess", "label": "somewhere"}},
        {"provenance": {"kind": "published", "label": ""}},
        {"provenance": {"kind": "demo", "label": "real data"}},  # an invented item must say so
        {"provenance": {"kind": "analyst_workbook", "label": "from the analyst workbook"}},  # and a workbook one must say "not verified"
        {"kind": "hunch"}, {"kind": ""}, {"section": ""}, {"week_ending": "2026-13-40"}, {"week_ending": ""},
        {"rank": -1}, {"rank": 101}, {"rank": True}, {"rank": "high"}, {"version": 2},
        {"figures": [{"label": "x", "value": 1, "display": "1"}]},  # no unit
        {"figures": [{"label": "", "value": 1, "display": "1", "unit": ""}]},
        {"figures": "9.6"},
    ],
)
def test_an_incomplete_or_malformed_suggestion_is_refused(over):
    with pytest.raises(InvalidSuggestion):
        make(**over)


def test_the_two_fixed_provenance_labels_are_accepted_as_written():
    make(provenance={"kind": "analyst_workbook", "label": "from the analyst workbook, not verified"})
    make(provenance={"kind": "published", "label": "CBK weekly bulletin"})
    make(provenance={"kind": "approved_review", "label": "approved Fixed Income review, week ending 2026-10-02"})
    make(provenance={"kind": "typed", "label": "typed on the weekly analyst inputs form"})


# ---------------------------------------------------------------------------
# The registry: every detector alone
# ---------------------------------------------------------------------------

CTX = DetectorContext(week_ending=date.fromisoformat(WEEK))


def test_a_detector_is_given_the_week_and_nothing_else():
    assert [f.name for f in fields(DetectorContext)] == ["week_ending"]
    seen = []
    run_detectors({SECTION: [lambda ctx: seen.append(ctx) or []]}, SECTION, CTX)
    assert seen == [CTX]


def test_one_detector_raising_does_not_stop_the_others():
    def boom(ctx):
        raise RuntimeError("secret detail: /home/someone/file.csv")

    good = make()
    found, failed = run_detectors({SECTION: [lambda c: [good], boom, lambda c: [make(kind="record", rank=80)]]}, SECTION, CTX)
    assert failed == 1
    assert [s.kind for s in found] == ["record", "streak"]  # the survivors, highest rank first


@pytest.mark.parametrize(
    "bad",
    [
        lambda ctx: [{"headline": "a dict, not a Suggestion"}],
        lambda ctx: "not a list",
        lambda ctx: [make(section="equities")],  # a detector for Fixed Income that returns another section's finding
        lambda ctx: [make(week_ending="2026-10-02")],  # or another week's
        lambda ctx: None,
    ],
)
def test_a_detector_that_returns_the_wrong_thing_counts_as_failed_and_adds_nothing(bad):
    found, failed = run_detectors({SECTION: [bad, lambda c: [make()]]}, SECTION, CTX)
    assert failed == 1 and len(found) == 1


def test_duplicates_are_kept_once_and_the_result_is_ordered_by_rank_then_id():
    a, b, c = make(rank=10), make(kind="record", rank=90), make(kind="since", rank=90)
    found, failed = run_detectors({SECTION: [lambda x: [a, b], lambda x: [a, c]]}, SECTION, CTX)
    assert failed == 0 and len(found) == 3
    assert [s.rank for s in found] == [90, 90, 10]
    assert [s.id for s in found[:2]] == sorted([b.id, c.id])


def test_a_section_with_no_detectors_gives_nothing_and_no_failure():
    assert run_detectors({}, SECTION, CTX) == ([], 0)
    assert run_detectors({"equities": [lambda c: [make(section="equities")]]}, SECTION, CTX) == ([], 0)


def test_the_real_registry_is_empty():
    assert notable.REGISTRY == {}


# ---------------------------------------------------------------------------
# The API and the saved decisions
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    return tmp_path / "app.db"


S1 = make()
S2 = make(kind="record", headline="The 91-day yield is the highest this year.", rank=80)
FAIL_SECTION = "equities"


def boom(ctx):
    raise RuntimeError("secret detail: C:/Users/someone/private.csv")


def registry():
    return {SECTION: [lambda ctx: [S1, S2]], FAIL_SECTION: [boom, lambda ctx: [make(section=FAIL_SECTION, kind="since", rank=20)]]}


def app_for(db, tmp_path, reg=None):
    return TestClient(create_app(db_path=db, load_dotenv=False, inputs_root=tmp_path / "weekly", notable_registry=reg))


@pytest.fixture
def client(db, tmp_path):
    return app_for(db, tmp_path, registry())


def get(client, section=SECTION, week=WEEK, **params):
    return client.get(f"/api/notable/{section}", params={"week_ending": week, **params})


def post(client, sid, decision="selected", **body):
    return client.post(f"/api/notable/{SECTION}/decisions", params={"week_ending": WEEK},
                       json={"suggestion_id": sid, "decision": decision, **body})


def rows(db, sql="SELECT * FROM suggestion_decisions ORDER BY suggestion_id"):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def test_the_default_app_shows_nothing_for_any_weekly_section(db, tmp_path):
    plain = app_for(db, tmp_path)  # no registry argument: the real one
    for slug in ("company_updates", "fixed_income", "equities", "real_estate", "digital_payments", "focus"):
        body = get(plain, slug).json()
        assert body["suggestions"] == [] and body["failed_checks"] == 0 and body["section"] == slug and body["week_ending"] == WEEK


def test_get_returns_the_suggestions_by_rank_each_with_no_decision_yet(client):
    body = get(client).json()
    assert [s["id"] for s in body["suggestions"]] == [S2.id, S1.id]
    assert all(s["decision"] is None for s in body["suggestions"])
    assert body["suggestions"][0]["working"]["points"] == POINTS
    assert body["failed_checks"] == 0


def test_a_failing_detector_is_a_count_and_never_a_stack_trace(client):
    r = get(client, FAIL_SECTION)
    assert r.status_code == 200
    body = r.json()
    assert body["failed_checks"] == 1 and len(body["suggestions"]) == 1
    assert "Traceback" not in r.text and "secret detail" not in r.text and "private.csv" not in r.text


def test_accept_selects_it(client, db):
    r = post(client, S1.id)
    assert r.status_code == 200
    chosen = {s["id"]: s["decision"] for s in r.json()["suggestions"]}
    assert chosen[S1.id]["decision"] == "selected" and chosen[S1.id]["edited_headline"] is None
    assert chosen[S2.id] is None
    assert get(client).json()["suggestions"][1]["decision"]["decision"] == "selected"
    assert len(rows(db)) == 1 and rows(db)[0]["decided_at"]


def test_edit_keeps_the_original_and_selects(client):
    r = post(client, S1.id, edited_headline="  Yield up three weeks running.  ")
    s = next(s for s in r.json()["suggestions"] if s["id"] == S1.id)
    assert s["headline"] == S1.headline  # the original is untouched
    assert (s["decision"]["decision"], s["decision"]["edited_headline"]) == ("selected", "Yield up three weeks running.")


def test_editing_to_the_same_words_or_to_nothing(client):
    same = post(client, S1.id, edited_headline=S1.headline).json()
    assert next(s for s in same["suggestions"] if s["id"] == S1.id)["decision"]["edited_headline"] is None
    assert post(client, S1.id, edited_headline="   ").status_code == 422
    assert post(client, S1.id, edited_headline="x" * 301).status_code == 422


def test_dismiss_with_an_optional_reason_then_restore(client, db):
    for reason in ("not_relevant", "already_covered", "figures_look_wrong", "other", None):
        r = post(client, S1.id, "dismissed", dismiss_reason=reason)
        assert r.status_code == 200
        d = next(s for s in r.json()["suggestions"] if s["id"] == S1.id)["decision"]
        assert (d["decision"], d["dismiss_reason"]) == ("dismissed", reason)
    assert post(client, S1.id, "dismissed", dismiss_reason="boring").status_code == 422
    assert post(client, S1.id, "selected", dismiss_reason="other").status_code == 422  # a reason belongs to a dismissal
    assert post(client, S1.id, "dismissed", edited_headline="x").status_code == 422  # and an edit to a selection

    restored = client.delete(f"/api/notable/{SECTION}/decisions/{S1.id}", params={"week_ending": WEEK})
    assert restored.status_code == 200
    assert all(s["decision"] is None for s in restored.json()["suggestions"]) and rows(db) == []
    assert client.delete(f"/api/notable/{SECTION}/decisions/{S1.id}", params={"week_ending": WEEK}).status_code == 404


def test_one_row_per_week_section_and_suggestion(client, db):
    post(client, S1.id)
    post(client, S1.id, edited_headline="Reworded.")
    post(client, S1.id, "dismissed", dismiss_reason="other")
    assert [(r["decision"], r["edited_headline"], r["dismiss_reason"]) for r in rows(db)] == [("dismissed", None, "other")]
    conn = sqlite3.connect(db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO suggestion_decisions (week_ending, section, suggestion_id, decision, decided_at) VALUES (?,?,?,?,?)",
                     (WEEK, SECTION, S1.id, "selected", "2026-10-09T00:00:00Z"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO suggestion_decisions (week_ending, section, suggestion_id, decision, decided_at) VALUES (?,?,?,?,?)",
                     (WEEK, SECTION, "other-id", "maybe", "2026-10-09T00:00:00Z"))
    conn.close()


def test_a_decision_belongs_to_its_week(client):
    post(client, S1.id)
    # The same suggestion id in another week is a different suggestion (the id hashes the week), so it is refused there...
    assert client.post(f"/api/notable/{SECTION}/decisions", params={"week_ending": "2026-10-02"},
                       json={"suggestion_id": S1.id, "decision": "selected"}).status_code == 404
    # ...and the other week's list shows nothing of it.
    assert get(client, week="2026-10-02").json()["suggestions"] == []


def test_decisions_survive_a_restart(db, tmp_path):
    first = app_for(db, tmp_path, registry())
    post(first, S1.id, edited_headline="Kept across a restart.")
    post(first, S2.id, "dismissed", dismiss_reason="already_covered")
    again = app_for(db, tmp_path, registry())  # a new app over the same file, as after a restart
    by_id = {s["id"]: s["decision"] for s in get(again).json()["suggestions"]}
    assert by_id[S1.id]["edited_headline"] == "Kept across a restart."
    assert (by_id[S2.id]["decision"], by_id[S2.id]["dismiss_reason"]) == ("dismissed", "already_covered")


def test_unknown_sections_suggestions_and_weeks_are_refused_in_plain_words(client):
    assert get(client, "no_such_section").status_code == 404
    assert "no_such_section" in get(client, "no_such_section").json()["detail"]
    assert client.post("/api/notable/no_such_section/decisions", params={"week_ending": WEEK},
                       json={"suggestion_id": "x", "decision": "selected"}).status_code == 404
    r = post(client, "0123456789abcdef")
    assert r.status_code == 404 and "0123456789abcdef" in r.json()["detail"]
    assert get(client, week="2026-10-10").status_code == 422  # a Saturday
    assert get(client, week="soon").status_code == 422
    assert client.get(f"/api/notable/{SECTION}").status_code == 422  # a weekly report needs its week
    assert post(client, S1.id, "perhaps").status_code == 422


def test_other_report_types_return_an_empty_list_for_now(client):
    for report_type in ("quarterly", "half_year", "annual", "companion"):
        r = client.get(f"/api/notable/{SECTION}", params={"report_type": report_type})
        assert r.status_code == 200 and r.json()["suggestions"] == [] and r.json()["failed_checks"] == 0
    assert client.get(f"/api/notable/{SECTION}", params={"report_type": "monthly"}).status_code == 422


# ---------------------------------------------------------------------------
# The table, and what a decision can and cannot touch
# ---------------------------------------------------------------------------

def strip_new_table(schema: str) -> str:
    """schema.sql as it stood before this feature: everything except the suggestion_decisions statements."""
    kept = [stmt for stmt in re.split(r";\s*\n", schema) if "suggestion_decisions" not in stmt]
    return ";\n".join(kept) + ";\n"


def snapshot(path):
    conn = sqlite3.connect(path)
    try:
        ddl = conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND tbl_name != 'suggestion_decisions' ORDER BY name").fetchall()
        data = {t: conn.execute(f"SELECT * FROM {t}").fetchall() for t in ("sections", "coordinator_reviews")}
        info = {t: conn.execute(f"PRAGMA table_info({t})").fetchall() for t in ("sections", "coordinator_reviews")}
        return ddl, data, info
    finally:
        conn.close()


# The definitions of everything that existed before this feature (sections, coordinator_reviews, their indexes), as schema.sql
# and the migration build them, fixed here so no later change to schema.sql can alter them unnoticed.  Computed from the
# schema.sql committed before the feature, with line endings normalized.
EXISTING_TABLES_SHA256 = "c652b66365634e9d460f7c5ea2982b19b3dda4b2dee61141820601c24e309886"


def fingerprint(path) -> str:
    ddl, _, info = snapshot(path)
    return hashlib.sha256(repr(([(t, n, tn, (s or "").replace("\r\n", "\n")) for t, n, tn, s in ddl], info)).encode()).hexdigest()


def test_the_definitions_of_the_existing_tables_are_exactly_what_they_were(tmp_path):
    sections.init_db(tmp_path / "fresh.db")
    assert fingerprint(tmp_path / "fresh.db") == EXISTING_TABLES_SHA256


def test_the_new_table_is_added_beside_the_others_and_changes_none_of_them(tmp_path):
    old = tmp_path / "old.db"
    schema = db_module._SCHEMA_SQL.read_text(encoding="utf-8")
    assert "suggestion_decisions" in schema and "CREATE TABLE IF NOT EXISTS suggestion_decisions" in schema
    conn = db_module.connect(old)
    conn.run_script(strip_new_table(schema))
    with conn.transaction():
        db_module._migrate(conn)  # the existing migration step, which init_db also runs; the only difference left is the new table
    conn.close()
    assert "suggestion_decisions" not in {r["name"] for r in rows(old, "SELECT name FROM sqlite_master")}
    before = snapshot(old)
    sections.init_db(old)
    sections.init_db(old)  # and again: idempotent
    assert snapshot(old) == before
    cols = [(r["name"], r["notnull"]) for r in rows(old, "PRAGMA table_info(suggestion_decisions)")]
    assert cols == [("week_ending", 1), ("section", 1), ("suggestion_id", 1), ("decision", 1), ("edited_headline", 0), ("dismiss_reason", 0), ("decided_at", 1)]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_saving_a_decision_changes_no_review_no_analyst_form_and_nothing_the_export_reads(db, tmp_path):
    client = app_for(db, tmp_path, registry())
    root = tmp_path / "weekly"
    # Real state to compare: a drafted section (no provider needed), a typed analyst figure, and the export's and overview's views of both.
    drafted = client.post("/api/sections/company_updates/draft", json={"text": "Investment Updates:\nSYNTHETIC text.", "period": f"Week ending {WEEK}"})
    assert drafted.status_code == 200, drafted.text
    run_id = drafted.json()["run_id"]
    typed = client.put(f"/api/inputs/weekly/{WEEK}/analyst", params={"section": SECTION}, json={"fields": {"placements": "9.5"}})
    assert typed.status_code == 200, typed.text

    def state():
        return {
            "reviews": rows(db, "SELECT * FROM coordinator_reviews ORDER BY run_id"),
            "sections": rows(db, "SELECT * FROM sections ORDER BY name"),
            "review": client.get(f"/api/reviews/{run_id}").json(),
            "overview": client.get("/api/sections", params={"report_type": "weekly", "period": f"Week ending {WEEK}"}).json(),
            "export": client.get("/api/export/weekly", params={"period": f"Week ending {WEEK}"}).json(),
            "analyst": client.get(f"/api/inputs/weekly/{WEEK}/analyst", params={"section": SECTION}).json(),
            "inputs": client.get(f"/api/inputs/weekly/{WEEK}").json(),
            "files": sorted((str(p.relative_to(root)), sha(p)) for p in root.rglob("*") if p.is_file()),
        }

    before = state()
    assert before["files"], "the analyst form file should exist"
    for body in (
        dict(suggestion_id=S1.id, decision="selected"),
        dict(suggestion_id=S1.id, decision="selected", edited_headline="Reworded for the worklist."),
        dict(suggestion_id=S2.id, decision="dismissed", dismiss_reason="figures_look_wrong"),
    ):
        assert client.post(f"/api/notable/{SECTION}/decisions", params={"week_ending": WEEK}, json=body).status_code == 200
    assert client.delete(f"/api/notable/{SECTION}/decisions/{S2.id}", params={"week_ending": WEEK}).status_code == 200
    after = state()
    assert len(rows(db)) == 1  # the decisions were really saved...
    assert after == before  # ...and nothing else moved


def test_the_word_export_is_identical_after_decisions(week, tmp_path):
    """The real six-section export (tests/test_weekly_export.py's approved week), written before and after the decisions."""
    reg = {s: [lambda ctx, s=s: [make(section=s, week_ending=ctx.week_ending.isoformat())]] for s in ("fixed_income", "equities", "focus")}
    client = TestClient(create_app(db_path=week, load_dotenv=False, inputs_root=tmp_path / "w", notable_registry=reg))

    def body(name):
        return Document(str(export.write_weekly_report(week, EXPORT_PERIOD, tmp_path / name))).element.body.xml

    before = body("before")
    assert len(before) > 5_000
    for s in reg:
        found = client.get(f"/api/notable/{s}", params={"week_ending": "2026-10-02"}).json()["suggestions"]
        assert len(found) == 1
        args = dict(params={"week_ending": "2026-10-02"}, json={"suggestion_id": found[0]["id"], "decision": "selected", "edited_headline": "Reworded."})
        assert client.post(f"/api/notable/{s}/decisions", **args).status_code == 200
    assert body("after") == before


# The package cannot reach what it must not touch: checked on its source, not by its behaviour.
NOTABLE_DIR = Path(notable.__file__).parent
FORBIDDEN = ("digital_payments", "common", "weekly", "periodic", "fixed_income", "equities", "focus", "narrative", "real_estate",
             "httpx", "requests", "urllib", "socket", "anthropic", "openai", "yfinance", "smtplib", "docx", "subprocess", "playwright")


def imported_names(path: Path) -> set[str]:
    """Every module-path segment and imported name in the file's import statements."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.update(a.name.split("."))
        elif isinstance(node, ast.ImportFrom):
            out.update((node.module or "").split("."))
            out.update(n.name for n in node.names)
    return out


def test_the_notable_package_imports_nothing_that_drafts_checks_exports_fetches_or_calls_a_model():
    files = sorted(NOTABLE_DIR.glob("*.py"))
    assert {f.name for f in files} >= {"suggestion.py", "registry.py", "store.py"}
    for f in files:
        assert not (imported_names(f) & set(FORBIDDEN)), f"{f.name} imports {imported_names(f) & set(FORBIDDEN)}"


def test_the_notable_store_touches_only_its_own_table():
    sql = (NOTABLE_DIR / "store.py").read_text(encoding="utf-8")
    touched = set(re.findall(r"(?:FROM|INTO|UPDATE|JOIN)\s+([a-z_]+)", sql))  # SQL is upper case here; Python's own "from" is not
    assert touched == {"suggestion_decisions"}


def test_an_invented_item_can_only_come_from_code_that_passes_a_demo_registry():
    """The real server builds create_app() with no registry; the word 'demo' as a provenance exists in the validator alone."""
    root = Path(notable.__file__).parents[2]  # backend/src
    hits = [p.relative_to(root.parent).as_posix() for p in list(root.rglob("*.py")) + list((root.parent / "api").rglob("*.py"))
            if re.search(r"invented demo item|['\"]demo['\"]", p.read_text(encoding="utf-8"))]
    assert hits == ["src/cytonn_weekly/notable/suggestion.py"]
