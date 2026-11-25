import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from cytonn_weekly.history import store
from cytonn_weekly.weekly import analyst, fund_snip
from tests import weekly_helpers as wh

WEEK = wh.WEEK
PNG = b"\x89PNG\r\n\x1a\n" + b"invented image bytes"
LIST = ["Alpha Money Market Fund", "Beta Money Market Fund", "Gamma Money Market Fund", "Delta Money Market Fund", "Omega Money Market Fund",
        "Cytonn Money Market Fund ( Dial *809# or download Cytonn App)"]


def row(i, name, currency="KES", rate="9.5", **kw):
    return {"id": i, "name": name, "currency": currency, "rate": rate, "once": False, "unresolved": [], **kw}


PAGE = [row(0, "Alpha Money Market Fund", rate="10.5"), row(1, "BetaMMF", rate="10.5"), row(2, "Gamma Money Market Fund", rate="9.0"),
        row(3, "Cytonn Money Market", rate="11.0"), row(4, "Zeta Fixed Income Fund", rate="12.0"), row(5, "Zeta Special Fund"),
        row(6, "Zeta Equity Fund"), row(7, "Zeta Balanced Fund"), row(8, "Zeta Bond Fund"), row(9, "Alpha Dollar Fund", "USD", None),
        row(10, "Zeta Money Market Fund", rate="8.0"), row(11, "Alpha Kenya Shillings Fund", rate="7.0")]


@pytest.fixture
def api(tmp_path):
    pages = {"rows": PAGE}
    client = TestClient(create_app(db_path=tmp_path / "app.db", load_dotenv=False, inputs_root=tmp_path / "weekly",
                                   read_fund_snip=lambda data: pages["rows"]))
    client.pages, client.db = pages, tmp_path / "app.db"
    client.put("/api/settings/fund-list", json={"include": LIST})
    return client


URL = "/api/inputs/weekly/2026-10-02/fund-snip"


def ready(api):
    assert api.put(URL, content=PNG).status_code == 200
    assert api.post(URL + "/read").status_code == 200


def test_names_are_matched_without_spaces_case_brackets_or_the_word_fund():
    k = fund_snip.match_key
    assert k("Cytonn Money Market Fund ( Dial *809# or download Cytonn App)") == k("CytonnMoneyMarket") == "cytonnmoneymarket"
    assert k("Beta MMF") == k("Beta Money Market Fund") == k("BetaMoneyMarketFund Kenya Shilling")
    assert k("Alpha Kenya Shillings Fund") != k("Alpha Money Market Fund")


def test_a_page_row_is_usd_kept_left_out_by_the_analyst_left_out_by_its_name_or_new():
    s = {"include": ["Alpha Money Market Fund"], "exclude": ["Zeta Gold Fund"], "aliases": {"AMMF": "Alpha Money Market Fund"}}
    c = fund_snip.classify
    assert c("Alpha Money Market Fund", "USD", s) == ("usd", None)
    assert c("alpha money market", "KES", s) == ("keep", "Alpha Money Market Fund")
    assert c("AMMF", "KES", s) == ("keep", "Alpha Money Market Fund")
    assert c("Zeta Gold Fund", "KES", s) == ("excluded", None)
    assert [c(f"Zeta {w} Fund", "KES", s)[0] for w in ("Fixed Income", "Special", "Equity", "Balanced", "Bond")] == ["auto"] * 5
    assert c("Zeta Money Market Fund", "KES", s) == ("new", None)


def words(rows, scale=1.0, flip=None):
    out = []
    for n, (name, cur, rate) in enumerate(rows):
        y = (100 + 20 * n) * scale
        rate = flip[1] if flip and flip[0] == n else rate
        out += [(10 * scale, y, 200 * scale, y + 10 * scale, name), (260 * scale, y, 300 * scale, y + 10 * scale, cur),
                (310 * scale, y, 340 * scale, y + 10 * scale, "0.03"), (400 * scale, y, 430 * scale, y + 10 * scale, rate)]   # the Daily Yield, then the Annual Rate
    return out


def unscaled(ws, scale):
    return [(x / scale, y / scale, a / scale, b / scale, t) for x, y, a, b, t in ws]


def test_a_cell_is_kept_only_when_both_readings_agree_and_the_rest_are_named():
    rows = [("Alpha Money Market Fund", "Kenya Shilling", "10.50%"), ("Beta Money Market Fund", "USD", "4.10%"), ("Gamma Fund", "Kenya Shilling", "9.00%")]
    got = fund_snip.rows_from_readings([words(rows), unscaled(words(rows, 3.0), 3.0)], 500)
    assert [(r["name"], r["currency"], r["rate"], r["unresolved"]) for r in got] == [
        ("Alpha Money Market Fund", "KES", "10.50", []), ("Beta Money Market Fund", "USD", "4.10", []), ("Gamma Fund", "KES", "9.00", [])]
    split = fund_snip.rows_from_readings([words(rows), unscaled(words(rows, 3.0, flip=(2, "9.60%")), 3.0)], 500)
    assert split[2]["rate"] is None and split[2]["unresolved"] == ["rate"] and split[0]["rate"] == "10.50"
    lone = fund_snip.rows_from_readings([words(rows), unscaled(words(rows[:2], 3.0), 3.0)], 500)
    assert lone[2]["once"] and lone[2]["unresolved"] == ["name", "currency", "rate"]


def test_a_page_with_no_fund_rows_is_refused_with_the_reason():
    with pytest.raises(ValueError, match="no fund row"):
        fund_snip.rows_from_readings([[(0, 0, 9, 9, "nothing here")]] * 2, 100)


def test_the_page_is_read_from_its_currency_column_and_the_left_columns_are_cut_off():
    rows = [("Alpha Money Market Fund", "Kenya Shilling", "10.50%")] * 6
    base = words(rows) + [(0, 100 + 20 * n, 8, 110 + 20 * n, "Left column text") for n in range(6)]

    def engine(image):
        s = image.shape[1] / 500
        return [(x * s, y * s, a * s, b * s, t) for x, y, a, b, t in base if x >= 9 or image.shape[1] == 500]

    import cv2
    png = cv2.imencode(".png", np.zeros((300, 500, 3), np.uint8))[1].tobytes()
    got = fund_snip.read_page(png, engine)
    assert len(got) == 6 and {r["name"] for r in got} == {"Alpha Money Market Fund"} and all(r["rate"] == "10.50" for r in got)


def test_an_image_is_judged_by_its_first_bytes_and_replaces_the_last(tmp_path):
    for bad, why in ((b"", "empty"), (b"GIF89a....", "PNG or JPEG"), (PNG + b"0" * fund_snip.MAX_BYTES, "limit")):
        with pytest.raises(fund_snip.InputError, match=why):
            fund_snip.store(WEEK, bad, tmp_path)
    first = fund_snip.store(WEEK, PNG, tmp_path)
    second = fund_snip.store(WEEK, PNG + b"2", tmp_path)
    assert first["sha256"] != second["sha256"] and len(list((tmp_path / "2026-10-02" / "fund_snip").glob("*.png"))) == 1
    assert fund_snip.image(WEEK, tmp_path)[0] == PNG + b"2"


def test_settings_refuse_a_double_listing_a_match_to_an_unlisted_fund_and_a_long_name(api):
    bad = api.put("/api/settings/fund-list", json={"include": ["A Fund", "a  fund"], "aliases": {"X": "Not listed"}})
    assert bad.status_code == 422 and "listed twice" in bad.json()["detail"] and "not on the list" in bad.json()["detail"]
    assert api.put("/api/settings/fund-list", json={"exclude": ["x" * 200]}).status_code == 422
    assert api.get("/api/settings/fund-list").json()["include"] == LIST   # nothing was kept from the refused ones


def test_the_card_groups_rows_counts_what_needs_a_decision_and_lists_the_funds_the_page_lacks(api):
    ready(api)
    s = api.get(URL).json()
    assert s["usd"] == 1 and len(s["left_out"]) == 5 and {x["why"] for x in s["left_out"]} == {"by its name"}
    assert {r["name"]: r["group"] for r in s["rows"]} == {"Alpha Money Market Fund": "keep", "BetaMMF": "keep", "Gamma Money Market Fund": "keep",
                                                          "Cytonn Money Market": "keep", "Zeta Money Market Fund": "new", "Alpha Kenya Shillings Fund": "new"}
    assert s["new"] == 2 and s["kept"] == 4 and s["not_on_page"] == ["Delta Money Market Fund", "Omega Money Market Fund"]


def test_the_analysts_decisions_are_remembered_for_the_next_week(api):
    ready(api)
    api.post("/api/settings/fund-list/decide", json={"page_name": "Zeta Money Market Fund", "decision": "exclude"})
    api.post("/api/settings/fund-list/decide", json={"page_name": "Alpha Kenya Shillings Fund", "decision": "alias", "to": "Delta Money Market Fund"})
    s = api.get(URL).json()
    assert s["new"] == 0 and s["kept"] == 5 and {x["name"] for x in s["left_out"]} >= {"Zeta Money Market Fund"}
    assert api.put("/api/inputs/weekly/2026-10-09/fund-snip", content=PNG).status_code == 200
    api.post("/api/inputs/weekly/2026-10-09/fund-snip/read")
    assert api.get("/api/inputs/weekly/2026-10-09/fund-snip").json()["new"] == 0
    assert api.post("/api/settings/fund-list/decide", json={"page_name": "Q", "decision": "alias", "to": "Not listed"}).status_code == 422
    api.post("/api/settings/fund-list/decide", json={"page_name": "Zeta Money Market Fund", "decision": "include"})
    assert "Zeta Money Market Fund" in api.get("/api/settings/fund-list").json()["include"]
    assert api.get("/api/settings/fund-list").json()["exclude"] == []


def test_a_fund_the_page_lacks_can_be_typed_and_a_listed_one_it_has_is_not_used_twice(api):
    ready(api)
    ok = api.put(URL + "/edits", json={"typed": [{"fund": "Delta Money Market Fund", "rate": "8.8"}]})
    assert ok.status_code == 200 and ok.json()["typed"] == [{"fund": "Delta Money Market Fund", "rate": "8.8"}]
    assert ok.json()["not_on_page"] == ["Omega Money Market Fund"]
    for typed, why in (([{"fund": "Unlisted Fund", "rate": "8"}], "not on the list"), ([{"fund": "Omega Money Market Fund", "rate": "120"}], "percentage"),
                       ([{"fund": "Omega Money Market Fund", "rate": "8"}, {"fund": "omega money market", "rate": "9"}], "twice")):
        bad = api.put(URL + "/edits", json={"typed": typed})
        assert bad.status_code == 422 and why in bad.json()["detail"]
    assert api.put(URL + "/edits", json={"fixes": {"abc": {}}}).status_code == 422
    twice = api.put(URL + "/edits", json={"typed": [{"fund": "Alpha Money Market Fund", "rate": "5"}]}).json()   # the page has it: the typed one is not used
    assert twice["typed"] == [] and twice["kept"] == 4


def test_confirming_is_refused_while_a_cell_or_a_fund_is_open_and_lists_each_reason(api):
    api.pages["rows"] = PAGE + [row(12, "Alpha Money Market Fund", rate="1.0"), row(13, "", "", None, unresolved=["name", "currency", "rate"], once=True)]
    ready(api)
    r = api.post(URL + "/confirm", json={"published": "2026-10-02"})
    detail = r.json()["detail"]
    assert r.status_code == 422 and "could not be read twice" in detail and "must be decided" in detail and "more than once" in detail
    assert store.current(api.db, "fi.mmf.rate", None) == []


def test_confirming_keeps_ranked_rows_with_shared_ranks_and_writes_the_history_with_the_image_as_source(api):
    ready(api)
    api.put(URL + "/edits", json={"fixes": {"10": {"ignore": True}, "11": {"ignore": True}}, "typed": [{"fund": "Delta Money Market Fund", "rate": "10.5"}]})
    r = api.post(URL + "/confirm?section=fixed_income", json={"published": "2026-10-02"})
    assert r.status_code == 200
    table = next(i for g in r.json()["groups"] for i in g["items"] if i["key"] == "mmf")
    assert [(x["rank"], x["fund"], x["rate"]) for x in table["rows"]] == [
        ("1", "Cytonn Money Market Fund ( Dial *809# or download Cytonn App)", "11.0"), ("2", "Alpha Money Market Fund", "10.5"),
        ("2", "Beta Money Market Fund", "10.5"), ("2", "Delta Money Market Fund", "10.5"), ("5", "Gamma Money Market Fund", "9.0")]
    assert table["carried"]["from"] == "snip" and not table["needs_confirmation"]
    sha = json.loads(next((api.db.parent / "weekly" / "2026-10-02" / "fund_snip").glob("snip.json")).read_text())["sha256"]
    points = {p["subject"]: p for p in store.current(api.db, "fi.mmf.rate", None)}
    assert len(points) == 5 and {p["as_of"] for p in points.values()} == {"2026-10-02"}
    assert points["alpha money market fund"]["origin"] == "typed" and points["alpha money market fund"]["source_kind"] == "source"
    assert sha in points["alpha money market fund"]["source_ref"]
    assert points["delta money market fund"]["source_kind"] == "form_field" and "typed beside" in points["delta money market fund"]["source_ref"]
    again = api.post(URL + "/confirm?section=fixed_income", json={"published": "2026-10-02"})   # the same again adds nothing
    assert again.status_code == 200 and len(store.current(api.db, "fi.mmf.rate", None)) == 5


def test_a_publish_date_outside_the_week_is_refused_and_nothing_is_kept(api):
    ready(api)
    api.put(URL + "/edits", json={"fixes": {"10": {"ignore": True}, "11": {"ignore": True}}})
    r = api.post(URL + "/confirm", json={"published": "2026-09-01"})
    assert r.status_code == 422 and store.current(api.db, "fi.mmf.rate", None) == []


def test_a_page_the_reader_cannot_read_says_so_and_asks_to_type_it(tmp_path):
    def broken(data):
        raise ValueError("the Annual Rate column was not found")

    c = TestClient(create_app(db_path=tmp_path / "a.db", load_dotenv=False, inputs_root=tmp_path / "w", read_fund_snip=broken))
    assert c.post(URL + "/read").status_code == 409
    c.put(URL, content=PNG)
    r = c.post(URL + "/read")
    assert r.status_code == 422 and "Annual Rate column" in r.json()["detail"] and "Type the fund table" in r.json()["detail"]


def test_a_non_image_and_a_missing_page_are_refused(api):
    assert api.put(URL, content=b"not an image").status_code == 422
    assert api.get(URL + "/image").status_code == 404 and api.delete(URL).status_code == 404
    api.put(URL, content=PNG)
    assert api.get(URL + "/image").content == PNG and api.delete(URL).status_code == 200 and api.get(URL).json()["image"] is None


def test_the_form_accepts_equal_rates_sharing_a_rank_and_still_refuses_a_skipped_rank():
    tied = [{"rank": "1", "fund": "A", "rate": "10.5"}, {"rank": "1", "fund": "B", "rate": "10.5"}, {"rank": "3", "fund": "C", "rate": "9.0"},
            {"rank": "4", "fund": "D", "rate": "8.0"}, {"rank": "5", "fund": "E", "rate": "7.0"}]
    errors: list = []
    analyst._check_table(analyst.TABLES["mmf"], tied, WEEK, errors)
    assert errors == []
    for bad in ([{"rank": "1", "fund": "A", "rate": "10.5"}, {"rank": "1", "fund": "B", "rate": "9.0"}],
                [{"rank": "1", "fund": "A", "rate": "10.5"}, {"rank": "3", "fund": "B", "rate": "9.0"}]):
        errors = []
        analyst._check_table(analyst.TABLES["mmf"], bad, WEEK, errors)
        assert errors and "ranks must run" in errors[0]


def test_a_saturday_publish_date_is_kept_as_its_friday_with_a_note_and_a_sunday_is_refused(api):
    ready(api)
    api.put(URL + "/edits", json={"fixes": {"10": {"ignore": True}, "11": {"ignore": True}}})
    assert api.post(URL + "/confirm", json={"published": "2026-10-04"}).status_code == 422          # a Sunday
    assert api.post(URL + "/confirm", json={"published": "2026-09-26"}).status_code == 422          # another week's Saturday
    r = api.post(URL + "/confirm?section=fixed_income", json={"published": "2026-10-03"})
    assert r.status_code == 200
    published = next(i for g in r.json()["groups"] for i in g["items"] if i["key"] == "mmf_published")
    assert published["value"] == "2026-10-02"
    assert published["notice"] == "Saturday 3 Oct 2026 is entered as Friday 2 Oct 2026: the Saturday issue prints Friday's rates."
