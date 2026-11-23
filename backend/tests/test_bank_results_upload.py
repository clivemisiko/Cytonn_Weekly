import json
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.agent import readiness
from cytonn_weekly.equities import companies
from cytonn_weekly.equities.results import statement, upload
from cytonn_weekly.weekly import inputs
from cytonn_weekly.weekly.week import Week

SOURCES = Path(__file__).parent / "fixtures" / "sources"
COOP, EQUITY, KCB = (SOURCES / f"results_{b}_2026-09-30.pdf" for b in ("coop", "equity", "kcb"))
WEEK = Week(date(2026, 11, 20))


@pytest.fixture(autouse=True)
def season(monkeypatch):
    monkeypatch.setattr(inputs, "RESULTS_SEASON_ENABLED", True)


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=tmp_path / "weekly"))


def _slot(status):
    return next(s for s in status["slots"] if s["slug"] == inputs.BANK_RESULTS)


def _pdf(content: bytes) -> bytes:
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Contents 4 0 R >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


def test_the_three_public_statements_are_read_and_identified(client):
    for path in (COOP, EQUITY, KCB):
        r = client.put(f"/api/inputs/weekly/{WEEK.ending}/bank_results?filename={path.name}", content=path.read_bytes())
        assert r.status_code == 200, r.text
    files = _slot(r.json())["files"]
    got = {f["read"]["bank"]: (f["read_date"], f["read"]["checks_passed"], f["read"]["flag_count"]) for f in files}
    assert got == {"Co-operative Bank of Kenya": ("2026-09-30", False, 28), "Equity Group Holdings": ("2026-09-30", True, 0),
                   "KCB Group": ("2026-09-30", True, 0)}
    kcb = next(f for f in files if f["read"]["ticker"] == "KCB")
    assert kcb["stored_name"] == "bank_results_kcb.pdf"
    assert kcb["read"]["group_entity"] == "KCB GROUP PLC CONSOLIDATED" and len(kcb["read"]["entities"]) == 3
    coop = next(f for f in files if f["read"]["ticker"] == "COOP")
    assert len(coop["read"]["flags"]) == 28 and all(statement.SOURCE_DISAGREES not in n for n in coop["read"]["flags"])
    assert _slot(r.json())["warning"] is None


def test_the_slot_is_optional_never_blocks_and_lists_several_files(tmp_path):
    root = tmp_path / "w"
    for p in (COOP, KCB):
        inputs.store(WEEK, inputs.BANK_RESULTS, p.read_bytes(), p.name, root)
    manifest = inputs.read_manifest(WEEK, root)
    assert {"bank_results_coop.pdf", "bank_results_kcb.pdf"} <= set(manifest)
    assert manifest["bank_results_kcb.pdf"]["read"]["period"] == "2026-09-30"
    got = readiness.classify("equities", inputs.status(WEEK, root), None)
    entry = next(e for g in got["groups"].values() for e in g if e["key"] == inputs.BANK_RESULTS)
    assert entry == {"kind": "upload", "key": "bank_results", "label": inputs.RESULTS_SLOT.title, "why": "2 files uploaded", "many": True}
    empty = readiness.classify("equities", inputs.status(Week(date(2026, 11, 27)), root), None)
    assert [e["key"] for e in empty["groups"]["optional"]] == ["bank_results"]
    assert all(e["key"] != "bank_results" for e in empty["groups"]["needs_analyst"])


def test_a_second_file_for_the_same_bank_replaces_the_first_and_says_so(tmp_path):
    root = tmp_path / "w"
    first = inputs.store(WEEK, inputs.BANK_RESULTS, KCB.read_bytes(), "kcb-first.pdf", root)
    assert first["read"]["replaced"] is None
    again = inputs.store(WEEK, inputs.BANK_RESULTS, KCB.read_bytes(), "kcb-second.pdf", root)
    assert again["read"]["replaced"] == "kcb-first.pdf"
    files = _slot(inputs.status(WEEK, root))["files"]
    assert [f["original_name"] for f in files] == ["kcb-second.pdf"]


def test_mixed_periods_are_accepted_with_a_warning(tmp_path):
    root = tmp_path / "w"
    inputs.store(WEEK, inputs.BANK_RESULTS, COOP.read_bytes(), "coop.pdf", root)
    inputs.store(WEEK, inputs.BANK_RESULTS, EQUITY.read_bytes(), "equity.pdf", root)
    path = inputs.week_dir(WEEK, root) / "manifest.json"
    m = json.loads(path.read_text())
    m["bank_results_eqty.pdf"]["read_date"] = "2026-06-30"   # as a June file would be stored
    path.write_text(json.dumps(m))
    slot = _slot(inputs.status(WEEK, root))
    assert len(slot["files"]) == 2
    assert slot["warning"].startswith("The files are not all for the same period (") and "30 Jun 2026" in slot["warning"]


def test_removing_a_file(client):
    client.put(f"/api/inputs/weekly/{WEEK.ending}/bank_results", content=EQUITY.read_bytes())
    r = client.delete(f"/api/inputs/weekly/{WEEK.ending}/bank_results_eqty.pdf")
    assert r.status_code == 200 and _slot(r.json())["files"] == [] and _slot(r.json())["received"] is False


def _refused(client, data):
    r = client.put(f"/api/inputs/weekly/{WEEK.ending}/bank_results", content=data)
    assert r.status_code in (413, 422)
    return r.json()["detail"]


def test_refusals(client, monkeypatch):
    title = inputs.RESULTS_SLOT.title
    assert _refused(client, b"PK\x03\x04 a workbook") == f"{title}: this is not a PDF file. Download the document again as a PDF and upload that."
    assert "limit" in _refused(client, b"%PDF" + b"0" * inputs.MAX_BYTES)
    scan = _pdf(b"q 100 0 0 100 0 0 cm BI /W 2 /H 2 /CS /G /BPC 8 ID \x00\xff\xff\x00 EI Q")
    assert _refused(client, scan) == f"{title}: {upload.SCANNED}."
    bulletin = (SOURCES / "cbk_weekly_bulletin_2026-10-02.pdf").read_bytes()
    assert _refused(client, bulletin) == f"{title}: {upload.NOT_CBK}."
    known = [c for c in companies.load() if c.name != "KCB Group"]
    monkeypatch.setattr(companies, "load", lambda: known)
    unknown = _refused(client, KCB.read_bytes())
    assert unknown.startswith(f"{title}: the bank on this page is not one the tool knows (the page names: KCB GROUP PLC")
    assert _slot(client.get(f"/api/inputs/weekly/{WEEK.ending}").json())["files"] == []


def test_status_reads_the_stored_result_and_never_parses(tmp_path, monkeypatch):
    root = tmp_path / "w"
    for p in (COOP, EQUITY, KCB):
        inputs.store(WEEK, inputs.BANK_RESULTS, p.read_bytes(), p.name, root)

    def parse(*a, **k):
        raise AssertionError("a PDF was parsed during status")

    for mod, name in ((upload, "read"), (upload, "read_statement"), (statement, "read_statement"), (upload.pdfplumber, "open")):
        monkeypatch.setattr(mod, name, parse)
    start = time.perf_counter()
    got = _slot(inputs.status(WEEK, root))
    took = time.perf_counter() - start
    assert len(got["files"]) == 3 and took < 0.5, took   # the three statements take about 2.5 s to read


def test_the_slot_is_absent_when_the_switch_is_off(client, monkeypatch):
    monkeypatch.setattr(inputs, "RESULTS_SEASON_ENABLED", False)
    slugs = [s["slug"] for s in client.get(f"/api/inputs/weekly/{WEEK.ending}").json()["slots"]]
    assert inputs.BANK_RESULTS not in slugs
    assert client.put(f"/api/inputs/weekly/{WEEK.ending}/bank_results", content=KCB.read_bytes()).status_code == 404


@pytest.mark.parametrize("kind,data", [("pdf", b"%PDF-1.4 one"), ("xlsx", b"PK\x03\x04 one")])
def test_the_many_flag_works_for_every_slot_kind(tmp_path, monkeypatch, kind, data):
    slot = replace(inputs.RESULTS_SLOT, slug="any_many", kind=kind)
    monkeypatch.setattr(inputs, "active_slots", lambda: inputs.SLOTS + (slot,))
    monkeypatch.setattr(inputs, "identify", lambda s, d, w: {**inputs._found(date(2026, 9, 30), True, f"any_{d[-3:].decode()}.{kind}", ""), "read": {}})
    root = tmp_path / "w"
    for tail in (b"one", b"two", b"two"):
        inputs.store(WEEK, "any_many", data[:-3] + tail, tail.decode(), root)
    view = next(s for s in inputs.status(WEEK, root)["slots"] if s["slug"] == "any_many")
    assert view["many"] is True and [f["stored_name"] for f in view["files"]] == [f"any_one.{kind}", f"any_two.{kind}"]
    assert inputs.remove(WEEK, f"any_one.{kind}", root)
    assert [f["stored_name"] for f in next(s for s in inputs.status(WEEK, root)["slots"] if s["slug"] == "any_many")["files"]] == [f"any_two.{kind}"]
