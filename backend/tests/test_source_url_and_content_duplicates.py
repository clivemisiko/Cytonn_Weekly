import json
import time
from datetime import date

from cytonn_weekly.common import gather
from cytonn_weekly.common import run_events as ev
from cytonn_weekly.common import sources as src
from cytonn_weekly.source_pieces import Piece

FRIDAY = date(2026, 11, 20)
BODY = " The authority approved new collective investment schemes during the week under review." * 8
TEXT_A = "Nairobi, 17th November 2026 - CMA notice A." + BODY
TEXT_B = "Nairobi, 18th November 2026 - CMA notice B." + BODY
PIECE = Piece("T-bills", FRIDAY, domains=("centralbank.go.ke",), section="fixed_income")


def run(tmp_path, pages, enough=10):
    """Gather PIECE from one search answer; each page is 'fetched' by keeping its synthetic text as a found source."""
    events, searched = [], []

    def search(q, start, domains):
        searched.append(q)
        return [{"url": u, "title": u, "publishedDate": "2026-11-18", "text": ""} for u in pages]

    def fetch(url, subject, end, *, root, origin, window):
        return src.from_paste(url, "2026-11-18", pages[url], subject, end, root=root, origin=origin)

    saved = gather.gather_piece(PIECE, search=search, fetch=fetch, root=tmp_path,
                                limits=gather.Limits(enough=enough, max_queries=1, max_pages=10),
                                deadline=time.monotonic() + 100,
                                on_event=lambda kind, label, detail=None, counts=None: events.append((kind, detail)))
    return saved, [d for k, d in events if k == ev.SOURCE_LEFT_OUT], searched


def test_url_key_ignores_case_www_slash_tracking_fragment_and_default_port():
    base = src.url_key("https://centralbank.go.ke/notice?id=1")
    for u in ("HTTPS://WWW.CentralBank.go.ke/notice/?id=1", "https://centralbank.go.ke:443/notice?id=1&utm_source=x#top",
              "https://www.centralbank.go.ke/notice?fbclid=a&id=1&gclid=b&mc_cid=c&mc_eid=d&ref=e"):
        assert src.url_key(u) == base
    assert src.url_key("https://centralbank.go.ke/notice?id=2") != base


def test_the_same_text_under_url_variants_is_saved_once_and_the_left_out_event_says_why(tmp_path):
    pages = {"https://www.centralbank.go.ke/n": TEXT_A, "https://centralbank.go.ke/n/": TEXT_A,
             "https://centralbank.go.ke/n?utm_source=news": TEXT_A, "https://centralbank.go.ke/other": TEXT_A}
    saved, left, _ = run(tmp_path, pages)
    assert len(saved) == 1 and len(src.list_for("T-bills", FRIDAY, tmp_path)) == 1
    assert left == [f"{src.SAME_CONTENT} ({saved[0].id})"]   # the last address differs, its text does not


def test_two_different_texts_are_both_saved(tmp_path):
    saved, left, _ = run(tmp_path, {"https://centralbank.go.ke/a": TEXT_A, "https://centralbank.go.ke/b": TEXT_B})
    assert len(saved) == 2 and left == []


def test_a_skipped_duplicate_does_not_count_toward_enough(tmp_path):
    run(tmp_path, {"https://centralbank.go.ke/a": TEXT_A, "https://centralbank.go.ke/a2": TEXT_A})
    _, _, searched = run(tmp_path, {"https://centralbank.go.ke/b": TEXT_B}, enough=2)
    assert searched and len(src.list_for("T-bills", FRIDAY, tmp_path)) == 2


def test_a_dismissed_url_stays_dismissed_under_a_variant_and_its_text_under_a_new_url(tmp_path):
    saved, _, _ = run(tmp_path, {"https://centralbank.go.ke/a": TEXT_A})
    assert src.remove(saved[0].id, tmp_path)
    again, _, _ = run(tmp_path, {"https://WWW.centralbank.go.ke/a/?utm_medium=x": TEXT_A})
    assert again == []
    moved, left, _ = run(tmp_path, {"https://centralbank.go.ke/moved": TEXT_A})
    assert moved == [] and left == [src.SAME_AS_REMOVED]


def test_an_old_dismissed_file_with_only_urls_still_loads_and_matches_variants(tmp_path):
    folder = tmp_path / FRIDAY.isoformat()
    folder.mkdir()
    (folder / "dismissed.json").write_text(json.dumps([{"subject": "t-bills", "url": "https://www.centralbank.go.ke/a/"}]))
    assert src.dismissed("T-bills", FRIDAY, tmp_path) == {src.url_key("https://centralbank.go.ke/a")}
    saved, _, _ = run(tmp_path, {"https://centralbank.go.ke/a": TEXT_A, "https://centralbank.go.ke/b": TEXT_B})
    assert [s.url for s in saved] == ["https://centralbank.go.ke/b"]


def test_a_found_source_with_the_text_of_an_analyst_paste_in_the_same_piece_is_refused(tmp_path):
    kept = src.from_paste("https://centralbank.go.ke/pasted", "2026-11-18", TEXT_A, "T-bills", FRIDAY, root=tmp_path)
    saved, left, _ = run(tmp_path, {"https://centralbank.go.ke/found": TEXT_A})
    assert saved == [] and left == [f"{src.SAME_CONTENT} ({kept.id})"]
