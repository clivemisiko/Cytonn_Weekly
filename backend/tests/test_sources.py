import importlib
import json
import re
import ssl
from datetime import date

import httpx
import pytest

from cytonn_weekly.common import http
from cytonn_weekly.common import sources as src
from cytonn_weekly.equities.review_run import BRIEFS as EQUITIES_BRIEFS
from cytonn_weekly.fixed_income.weekly import BRIEFS as FI_BRIEFS
from cytonn_weekly.periodic.common import PeriodContext
from cytonn_weekly.periodic.digital_payments import other_highlights_brief
from cytonn_weekly.real_estate import review_run as re_run

FRIDAY = date(2026, 11, 6)
OK_URL = "https://www.centralbank.go.ke/press/2026-11-05"
PUBLIC = ["93.184.216.34"]
PARAGRAPH = ("The Central Bank of Kenya said private sector credit grew by 8.75% in the year to September 2026, "
             "compared with 6.1% a year earlier, and that lending to households rose faster than lending to firms. ")


def article(extra_head="", body=PARAGRAPH * 3):
    return (f"<html><head><title> Credit  report </title>{extra_head}</head><body>"
            "<nav><p>Home About Contact</p></nav><header><p>Site banner</p></header>"
            f"<h1>Credit report</h1><p>{body}</p><script>var x = 'not text';</script><style>p {{ color: red }}</style>"
            "<footer><p>Copyright</p></footer></body></html>").encode()


def reply(body=b"", status=200, **headers):
    return http.Reply(status, {k.replace("_", "-"): v for k, v in headers.items()}, body)


class Getter:
    """An http_get that answers from a list of replies and remembers every address it was asked for."""

    def __init__(self, *replies):
        self.replies, self.asked = list(replies), []

    def __call__(self, url, *, max_bytes, **_):
        self.asked.append(url)
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def fetch(getter, url=OK_URL, resolve=lambda host: PUBLIC, root=None, subject="Mortgage lending", **kw):
    return src.fetch_page(url, subject, FRIDAY, http_get=getter, resolve=resolve, root=root, **kw)


def refused(getter, url=OK_URL, resolve=lambda host: PUBLIC, **kw):
    with pytest.raises(src.SourceError) as caught:
        fetch(getter, url, resolve, **kw)
    return str(caught.value)


# --- the approved list ------------------------------------------------------------------------------------------------

def test_the_approved_list_covers_every_domain_the_briefs_prefer():
    wanted = set(re_run.PREFERRED_SITES)
    for brief in list(FI_BRIEFS) + list(EQUITIES_BRIEFS) + list(re_run.BRIEFS):
        wanted |= set(brief.preferred_domains)
    for report_type, period in (("quarterly", "Q3'2026"), ("half_year", "H1'2026"), ("annual", "FY'2025")):
        ctx = PeriodContext.of(report_type, period, today=FRIDAY)
        for name in ("global_markets", "ssa", "kenya_macro", "fixed_income", "equities", "real_estate"):
            for brief in importlib.import_module(f"cytonn_weekly.periodic.{name}").briefs(ctx):
                wanted |= set(brief.preferred_domains)
        wanted |= set(other_highlights_brief(ctx)[0].preferred_domains)
    assert [d for d in sorted(wanted) if not src.is_approved(d)] == []


def test_the_social_list_is_the_one_real_estate_uses():
    assert src.SOCIAL_DOMAINS == tuple(re_run.SOCIAL_DOMAINS)
    assert not [d for d in src.SOCIAL_DOMAINS if src.is_approved(d)]


def test_knight_frank_kenya_is_approved_and_a_look_alike_is_not():
    for url in ("https://www.knightfrank.co.ke/some-page", "https://knightfrank.co.ke/x"):
        assert src.is_approved(src.host_of(url))
    assert not src.is_approved(src.host_of("https://notknightfrank.co.ke"))


def test_a_host_is_approved_by_name_or_as_a_subdomain_and_never_by_a_look_alike():
    assert src.is_approved("centralbank.go.ke") and src.is_approved("www.centralbank.go.ke")
    assert src.is_approved("content.knightfrank.com") and src.is_approved("uk.knightfrank.com")
    assert not src.is_approved("evilcentralbank.go.ke") and not src.is_approved("centralbank.go.ke.evil.example")
    assert src.is_social("m.facebook.com") and not src.is_social("notfacebook.com")


# --- a page is fetched -------------------------------------------------------------------------------------------------

def test_a_fetched_page_is_read_kept_and_listed(tmp_path):
    body = article('<meta property="article:published_time" content="2026-11-05T08:00:00+03:00">')
    got = Getter(reply(body, content_type="text/html; charset=utf-8"))
    one = fetch(got, root=tmp_path, now=lambda: "2026-11-06T09:00:00+00:00")
    assert got.asked == [OK_URL]
    assert (one.origin, one.host, one.title, one.published_date) == ("fetched", "www.centralbank.go.ke", "Credit report", "2026-11-05")
    assert "8.75%" in one.text and "Home About" not in one.text and "Copyright" not in one.text
    assert "not text" not in one.text and "color: red" not in one.text and "Site banner" not in one.text
    assert one.chars == len(one.text) and one.sha256 == src._sha(body) and one.fetched_at == "2026-11-06T09:00:00+00:00"
    folder = tmp_path / "2026-11-06"
    assert (folder / f"{one.id}.txt").read_bytes() == one.text.encode()
    assert (folder / f"{one.id}.html").read_bytes() == body          # the raw bytes beside the text
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert [m["id"] for m in manifest["sources"]] == [one.id] and "text" not in manifest["sources"][0]
    assert src.list_for("Mortgage lending", FRIDAY, tmp_path) == [one]


def test_the_date_comes_from_a_time_element_when_there_is_no_meta_tag_and_is_empty_when_the_page_says_none(tmp_path):
    dated = article().replace(b"<h1>", b'<time datetime="2026-11-04">4 Nov</time><h1>')
    assert fetch(Getter(reply(dated)), root=tmp_path).published_date == "2026-11-04"
    undated = fetch(Getter(reply(article(body=PARAGRAPH * 4))), root=tmp_path)
    assert undated.published_date == ""            # never guessed; the analyst types it


def test_a_pdf_is_read_with_pdfplumber(tmp_path, monkeypatch):
    monkeypatch.setattr(src, "read_pdf", lambda body: (PARAGRAPH * 3, "A PDF title"))
    one = fetch(Getter(reply(b"%PDF-1.4 not really", content_type="application/pdf")), root=tmp_path)
    assert one.title == "A PDF title" and "8.75%" in one.text
    assert (tmp_path / "2026-11-06" / f"{one.id}.pdf").exists()


def test_the_same_page_fetched_twice_is_one_source(tmp_path):
    first = fetch(Getter(reply(article())), root=tmp_path, now=lambda: "2026-11-06T09:00:00+00:00")
    again = fetch(Getter(reply(article())), root=tmp_path, now=lambda: "2026-11-06T10:00:00+00:00")
    assert again.id == first.id and again.fetched_at == first.fetched_at
    assert len(src.list_all(FRIDAY, tmp_path)) == 1


def test_a_page_is_filed_under_the_friday_on_or_before_the_day_given(tmp_path):
    one = src.fetch_page(OK_URL, "Mortgage lending", date(2026, 11, 8), http_get=Getter(reply(article())),
                         resolve=lambda h: PUBLIC, root=tmp_path)
    assert one.week_end == "2026-11-06" and (tmp_path / "2026-11-06").is_dir()


# --- every refusal -----------------------------------------------------------------------------------------------------

def test_a_host_off_the_list_is_fetched_and_flagged_off_list(tmp_path):
    for url in ("https://blog.example.com/post", "https://centralbank.go.ke.evil.example/x"):
        one = fetch(Getter(reply(article())), url, root=tmp_path)
        assert one.flags == [src.NOT_ON_LIST] and one.url == url


def test_a_known_site_is_not_flagged(tmp_path):
    assert fetch(Getter(reply(article())), root=tmp_path).flags == []


def test_fetched_and_pasted_sources_share_the_off_list_rule(tmp_path):
    for host in ("www.centralbank.go.ke", "blog.example.com"):
        fetched = fetch(Getter(reply(article())), f"https://{host}/a", root=tmp_path)
        pasted = paste(tmp_path, url=f"https://{host}/b")
        assert fetched.flags == pasted.flags == src.list_flags(host)


@pytest.mark.parametrize("url", ["https://x.com/CBKKenya/status/1", "https://www.facebook.com/page/posts/2",
                                 "http://twitter.com/a/status/3"])
def test_social_media_is_refused_even_over_http(url, tmp_path):
    got = Getter()
    assert "social media is never used as a source" in refused(got, url, root=tmp_path) and got.asked == []


def test_an_http_page_is_fetched_and_flagged_insecure(tmp_path):
    url = "http://blog.example.com/x"
    one = fetch(Getter(reply(article())), url, root=tmp_path)
    assert one.flags == [src.NOT_ON_LIST, src.INSECURE] and one.url == url
    assert fetch(Getter(reply(article())), "http://www.centralbank.go.ke/x", root=tmp_path).flags == [src.INSECURE]


def test_an_https_page_is_not_flagged_insecure(tmp_path):
    assert src.INSECURE not in fetch(Getter(reply(article())), "https://blog.example.com/x", root=tmp_path).flags


@pytest.mark.parametrize("url", ["https://user:pw@www.centralbank.go.ke/x", "http://user@www.centralbank.go.ke/x",
                                 "https://www.centralbank.go.ke:8443/x", "http://www.centralbank.go.ke:8080/x",
                                 "https:///nohost", "ftp://www.centralbank.go.ke/x", "file:///etc/passwd"])
def test_an_address_with_credentials_a_port_or_no_host_is_refused(url, tmp_path):
    got = Getter()
    with pytest.raises(src.SourceError):
        fetch(got, url, root=tmp_path)
    assert got.asked == []


def test_a_redirect_to_another_host_is_refused_and_not_followed(tmp_path):
    got = Getter(reply(status=302, location="https://www.imf.org/else"))
    why = refused(got, root=tmp_path)
    assert "redirects to www.imf.org, a different host" in why and got.asked == [OK_URL]


def test_a_redirect_on_the_same_host_is_followed_and_the_final_address_is_kept(tmp_path):
    got = Getter(reply(status=301, location="/press/final"), reply(article()))
    one = fetch(got, root=tmp_path)
    assert got.asked == [OK_URL, "https://www.centralbank.go.ke/press/final"]
    assert one.url == "https://www.centralbank.go.ke/press/final"


def test_a_redirect_that_downgrades_to_http_is_followed_and_flagged_insecure(tmp_path):
    got = Getter(reply(status=302, location="http://www.centralbank.go.ke/press/final"), reply(article()))
    one = fetch(got, root=tmp_path)
    assert one.url.startswith("http://") and one.flags == [src.INSECURE]


def test_a_redirect_to_a_private_address_is_refused_by_the_same_host_rule(tmp_path):
    hosts = {"www.centralbank.go.ke": PUBLIC}
    got = Getter(reply(status=302, location="https://10.0.0.5/x"))
    assert "a different host" in refused(got, resolve=lambda h: hosts[h], root=tmp_path) and got.asked == [OK_URL]


def test_a_redirect_whose_host_now_resolves_to_a_private_address_is_refused(tmp_path):
    answers = iter([PUBLIC, ["10.0.0.5"]])
    got = Getter(reply(status=302, location="/internal"))
    assert "private or internal address" in refused(got, resolve=lambda h: next(answers), root=tmp_path)
    assert got.asked == [OK_URL]


def test_a_redirect_loop_stops(tmp_path):
    got = Getter(*[reply(status=302, location="/again")] * 10)
    assert "redirected more than 3 times" in refused(got, root=tmp_path) and len(got.asked) == 4


@pytest.mark.parametrize("address", ["10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.9", "::1", "0.0.0.0",
                                     "224.0.0.1", "fe80::1"])
def test_an_address_that_is_private_loopback_or_link_local_is_refused(address, tmp_path):
    got = Getter()
    assert "private or internal address" in refused(got, resolve=lambda host: [address], root=tmp_path)
    assert got.asked == []


@pytest.mark.parametrize("url", ["https://127.0.0.1/x", "http://169.254.169.254/latest/meta-data", "http://[::1]/x",
                                 "https://10.1.2.3/x", "http://0.0.0.0/x", "https://[fe80::1]/x"])
def test_an_address_typed_as_the_host_is_checked_as_it_stands(url, tmp_path):
    got = Getter()
    assert "private or internal address" in refused(got, url, resolve=lambda h: PUBLIC, root=tmp_path) and got.asked == []


def test_a_certificate_that_cannot_be_verified_gives_the_clear_message(tmp_path):
    inner = ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")
    outer = ConnectionError("connect failed")
    outer.__cause__ = inner
    why = refused(Getter(outer), root=tmp_path)
    assert "certificate of www.centralbank.go.ke could not be verified" in why
    assert "Paste the text" in why and "http:// version" in why
    assert "could not be fetched" in refused(Getter(ConnectionError("reset")), root=tmp_path)    # other errors keep their message


def test_a_page_that_is_neither_html_nor_a_pdf_is_refused(tmp_path):
    why = refused(Getter(reply(b"not a page", content_type="image/png")), root=tmp_path)
    assert "web page or a PDF (image/png)" in why


def test_one_private_answer_among_public_ones_refuses(tmp_path):
    assert "private or internal" in refused(Getter(), resolve=lambda host: PUBLIC + ["10.1.1.1"], root=tmp_path)


def test_a_host_that_cannot_be_looked_up_is_refused(tmp_path):
    def down(host):
        raise OSError("no such host")

    assert "could not be looked up" in refused(Getter(), resolve=down, root=tmp_path)
    assert "could not be looked up" in refused(Getter(), resolve=lambda host: [], root=tmp_path)


def test_a_page_over_the_size_limit_is_refused(tmp_path):
    why = refused(Getter(http.TooLarge(OK_URL)), root=tmp_path)
    assert "larger than 5 MB" in why and "Paste the part you need" in why


def test_the_fetch_is_asked_for_no_more_than_the_limit(tmp_path):
    seen = {}

    def get(url, *, max_bytes, **_):
        seen["max"] = max_bytes
        return reply(article())

    fetch(get, root=tmp_path)
    assert seen["max"] == src.MAX_BYTES == 5 * 1024 * 1024


def test_an_empty_page_is_refused(tmp_path):
    why = refused(Getter(reply(b"<html><body><script>1</script></body></html>")), root=tmp_path)
    assert "no readable text" in why and "Paste the text" in why


def test_a_page_too_short_to_be_an_article_is_refused(tmp_path):
    why = refused(Getter(reply(article(body="Not found, sorry."))), root=tmp_path)
    assert "too short to be an article" in why and "characters of text" in why


@pytest.mark.parametrize("prompt", ["Subscribe to continue reading this article.", "Please sign in to read the full story."])
def test_a_login_or_paywall_page_is_refused(prompt, tmp_path):
    why = refused(Getter(reply(article(body=prompt + " " + PARAGRAPH))), root=tmp_path)
    assert "login or subscription prompt" in why


def test_a_password_form_page_is_refused(tmp_path):
    page = (b"<html><body><p>" + PARAGRAPH.encode() + b"</p><form><input type=\"password\"></form></body></html>")
    assert "login or subscription prompt" in refused(Getter(reply(page)), root=tmp_path)


def test_a_long_article_that_mentions_subscribing_is_not_taken_for_a_paywall(tmp_path):
    long_body = PARAGRAPH * 40 + " Readers can subscribe to continue receiving our alerts."
    assert fetch(Getter(reply(article(body=long_body))), root=tmp_path).chars > 2500


@pytest.mark.parametrize("status,word", [(404, "No page was found"), (410, "No page was found"),
                                         (401, "login or a subscription"), (403, "login or a subscription"),
                                         (402, "login or a subscription"), (451, "login or a subscription"),
                                         (500, "answered with an error"), (503, "answered with an error")])
def test_an_error_status_is_a_plain_sentence(status, word, tmp_path):
    why = refused(Getter(reply(status=status)), root=tmp_path)
    assert word in why and f"HTTP {status}" in why


def test_a_network_error_is_a_plain_sentence_with_no_library_text(tmp_path):
    why = refused(Getter(OSError("secret internals /tmp/x.py line 9")), root=tmp_path)
    assert "(a network error)" in why and "internals" not in why and "OSError" not in why


def test_a_timeout_has_its_own_sentence(tmp_path):
    why = refused(Getter(httpx.ReadTimeout("slow")), root=tmp_path)
    assert "did not answer in time" in why and "network error" not in why


def test_a_429_has_its_own_sentence_and_is_logged_with_its_status(tmp_path, caplog):
    caplog.set_level("WARNING", logger=src.log.name)
    why = refused(Getter(reply(status=429)), root=tmp_path)
    assert "slow down" in why and "HTTP 429" in why
    assert "refused: HTTP 429" in caplog.text and "www.centralbank.go.ke" in caplog.text


def test_an_unexpected_error_is_not_called_a_network_error_and_its_message_is_not_logged(tmp_path, monkeypatch, caplog):
    caplog.set_level("WARNING", logger=src.log.name)

    def explode(body, content_type=""):
        raise KeyError("secret internals /tmp/x.py line 9")

    monkeypatch.setattr(src, "read_html", explode)
    why = refused(Getter(reply(article(), content_type="text/html")), url=OK_URL + "?token=abc123", root=tmp_path)
    assert why == src.UNREADABLE.format(host="www.centralbank.go.ke")
    assert "network error" not in why and "Paste its text instead" in why
    line = next(r.getMessage() for r in caplog.records if "unexpectedly" in r.getMessage())
    assert "www.centralbank.go.ke" in line and "KeyError" in line and "common/sources.py" in line and "_read_page" in line
    assert "secret internals" not in caplog.text and "token=abc123" not in caplog.text and "text/html" not in caplog.text
    assert src.list_all(FRIDAY, tmp_path) == []


# --- replies with a missing or odd header ----------------------------------------------------------------------------------

def test_a_reply_with_no_content_type_is_taken_for_a_page_when_its_body_is_html(tmp_path):
    one = fetch(Getter(reply(article())), root=tmp_path)
    assert one.chars > 0 and "8.75%" in one.text


def test_a_reply_with_no_content_type_and_a_body_that_is_not_html_is_refused(tmp_path):
    why = refused(Getter(reply(b"\x89PNG\r\n\x1a\n not a page at all")), root=tmp_path)
    assert "web page or a PDF (no type stated)" in why


def test_a_reply_with_no_content_type_and_a_pdf_body_is_read_as_a_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(src, "read_pdf", lambda body: (PARAGRAPH * 3, "A PDF title"))
    assert fetch(Getter(reply(b"%PDF-1.4 not really")), root=tmp_path).title == "A PDF title"


def test_a_reply_with_an_empty_body_is_refused_as_empty(tmp_path):
    assert "no readable text" in refused(Getter(reply(b"", content_type="text/html")), root=tmp_path)
    assert "no readable text" in refused(Getter(reply(b"")), root=tmp_path)


def test_a_reply_with_headers_in_any_casing_is_read(tmp_path):
    odd = http.Reply(200, {"Content-Type": "text/html; charset=UTF-8", "CONTENT-LENGTH": "9"}, article())
    assert "8.75%" in fetch(Getter(odd), root=tmp_path).text
    pdf = http.Reply(200, {"CONTENT-TYPE": "image/png"}, b"x")
    assert "web page or a PDF (image/png)" in refused(Getter(pdf), root=tmp_path)
    moved = http.Reply(302, {"LOCATION": "/final"}, b"")
    assert fetch(Getter(moved, reply(article())), root=tmp_path).url == "https://www.centralbank.go.ke/final"


def test_a_reply_with_no_headers_at_all_does_not_raise(tmp_path):
    assert "8.75%" in fetch(Getter(http.Reply(200, None, article())), root=tmp_path).text


def test_a_redirect_with_no_location_is_refused_with_its_own_sentence(tmp_path):
    for moved in (reply(status=302), reply(status=301, location=""), reply(status=307, location="   ")):
        why = refused(Getter(moved), root=tmp_path)
        assert "without saying where to" in why and "network error" not in why


def test_a_redirect_to_a_relative_address_is_followed_on_the_same_host(tmp_path):
    got = Getter(reply(status=301, location="final/page"), reply(status=302, location="../other"), reply(article()))
    one = fetch(got, root=tmp_path)
    assert got.asked == [OK_URL, "https://www.centralbank.go.ke/press/final/page", "https://www.centralbank.go.ke/press/other"]
    assert one.url == "https://www.centralbank.go.ke/press/other"


def test_a_status_that_is_neither_a_page_nor_a_redirect_is_refused(tmp_path):
    for status in (100, 300, 304):
        assert f"HTTP {status}" in refused(Getter(reply(article(), status=status)), root=tmp_path)
    assert "no readable text" in refused(Getter(reply(b"", status=204)), root=tmp_path)


def test_http_get_once_copes_with_a_reply_that_states_no_content_length(monkeypatch):
    real = httpx.Client

    def handler(request):
        return httpx.Response(200, content=iter([b"<html><body>", b"<p>hello</p></body></html>"]),
                              headers={"Content-Type": "text/html"})

    monkeypatch.setattr(http.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    got = http.http_get_once("https://example.org/news", max_bytes=1000)
    assert "content-length" not in got.headers and got.status == 200 and got.body.endswith(b"</body></html>")
    with pytest.raises(http.TooLarge):                 # the body's own length still counts without the header
        http.http_get_once("https://example.org/news", max_bytes=10)


def test_http_get_once_still_refuses_a_page_that_states_it_is_too_large(monkeypatch):
    real = httpx.Client
    monkeypatch.setattr(http.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"x" * 50, headers={"Content-Length": "50"})), **kw))
    with pytest.raises(http.TooLarge):
        http.http_get_once("https://example.org/news", max_bytes=10)


def test_a_saved_source_whose_list_entry_lacks_a_key_is_a_sentence_not_a_key_error(tmp_path):
    fetch(Getter(reply(article())), root=tmp_path)
    manifest = tmp_path / "2026-11-06" / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    del data["sources"][0]["host"]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(src.SourceError, match="missing details"):
        src.list_for("Mortgage lending", FRIDAY, tmp_path)


def test_a_refused_fetch_keeps_nothing(tmp_path):
    for getter in (Getter(reply(status=404)), Getter(reply(b"<p>tiny</p>")), Getter(http.TooLarge("x"))):
        refused(getter, root=tmp_path)
    assert src.list_all(FRIDAY, tmp_path) == []


def test_a_fetch_needs_a_subject(tmp_path):
    with pytest.raises(src.SourceError, match="Say which piece"):
        src.fetch_page(OK_URL, "  ", FRIDAY, http_get=Getter(), resolve=lambda h: PUBLIC, root=tmp_path)


# --- text is pasted ----------------------------------------------------------------------------------------------------

def paste(root, url="https://www.centralbank.go.ke/press/x", when="2026-11-05", text=PARAGRAPH, subject="Mortgage lending",
          **kw):
    return src.from_paste(url, when, text, subject, FRIDAY, root=root, now=lambda: "2026-11-06T09:00:00+00:00", **kw)


def test_pasted_text_is_kept_exactly_as_given(tmp_path):
    text = "  Line one with  two spaces\r\n\r\n“quoted” – and a non‑breaking space.\n  "
    one = paste(tmp_path, text=text, title="  My   title ")
    assert one.text == text and one.origin == "pasted" and one.title == "My title" and one.flags == []
    assert one.sha256 == src._sha(text.encode()) and one.chars == len(text)
    assert src.get(one.id, tmp_path).text == text           # read back byte for byte, line endings included
    assert not list((tmp_path / "2026-11-06").glob("*.html"))   # no raw file for pasted text


def test_a_paste_needs_a_url_a_date_and_text(tmp_path):
    for kw, word in ((dict(url=""), "address (URL)"), (dict(when=""), "date of the page"), (dict(text=" \n "), "Paste the text"),
                     (dict(subject=" "), "Say which piece")):
        with pytest.raises(src.SourceError, match=re.escape(word)):
            paste(tmp_path, **kw)
    assert src.list_all(FRIDAY, tmp_path) == []


@pytest.mark.parametrize("when", ["5 Nov 2026", "2026-13-01", "2026-02-30", "05/11/2026", "yesterday"])
def test_a_paste_with_a_date_that_is_not_a_date_is_refused(when, tmp_path):
    with pytest.raises(src.SourceError, match="not a date"):
        paste(tmp_path, when=when)


@pytest.mark.parametrize("url", ["https://x.com/a/status/1", "https://twitter.com/a", "http://www.instagram.com/p/9"])
def test_a_paste_from_social_media_is_refused(url, tmp_path):
    with pytest.raises(src.SourceError, match="social media is never used"):
        paste(tmp_path, url=url)


@pytest.mark.parametrize("url", ["www.centralbank.go.ke/x", "ftp://www.centralbank.go.ke/x", "https://"])
def test_a_paste_whose_address_is_not_a_web_address_is_refused(url, tmp_path):
    with pytest.raises(src.SourceError, match="not a web address"):
        paste(tmp_path, url=url)


def test_a_paste_from_a_host_off_the_list_is_kept_with_a_flag(tmp_path):
    one = paste(tmp_path, url="https://blog.example.com/post")
    assert one.flags == [src.NOT_ON_LIST] == ["host not on the approved list"]
    assert src.list_for("Mortgage lending", FRIDAY, tmp_path)[0].flags == [src.NOT_ON_LIST]
    assert paste(tmp_path, url="http://www.centralbank.go.ke/other").flags == []     # http is allowed for a paste


def test_a_paste_over_the_limit_is_refused(tmp_path):
    with pytest.raises(src.SourceError, match="longer than 200,000"):
        paste(tmp_path, text="a" * (src.MAX_PASTE_CHARS + 1))
    assert paste(tmp_path, text="a" * src.MAX_PASTE_CHARS).chars == src.MAX_PASTE_CHARS


def test_the_same_paste_twice_is_one_source_and_changed_text_is_another(tmp_path):
    a, b = paste(tmp_path), paste(tmp_path)
    assert a.id == b.id and len(src.list_all(FRIDAY, tmp_path)) == 1
    assert paste(tmp_path, text=PARAGRAPH + "More.").id != a.id and len(src.list_all(FRIDAY, tmp_path)) == 2


# --- the store ---------------------------------------------------------------------------------------------------------

def test_list_for_matches_a_subject_ignoring_case_and_spacing_and_keeps_pieces_apart(tmp_path):
    a = paste(tmp_path, subject="Mortgage lending")
    paste(tmp_path, subject="Affordable housing")
    found = src.list_for("  mortgage   LENDING ", FRIDAY, tmp_path)
    assert [s.id for s in found] == [a.id]
    assert [s.subject for s in src.list_all(FRIDAY, tmp_path)] == ["Mortgage lending", "Affordable housing"]


def test_sources_are_filed_per_friday(tmp_path):
    paste(tmp_path)
    assert src.list_for("Mortgage lending", date(2026, 11, 13), tmp_path) == []
    assert len(src.list_for("Mortgage lending", date(2026, 11, 10), tmp_path)) == 1    # a Tuesday files under 6 Nov


def test_get_and_remove_find_a_source_without_its_week(tmp_path):
    one = paste(tmp_path)
    assert src.get(one.id, tmp_path) == one and src.get("zzzzzzzz", tmp_path) is None
    assert src.remove(one.id, tmp_path) is True
    assert src.get(one.id, tmp_path) is None and src.list_all(FRIDAY, tmp_path) == []
    assert src.remove(one.id, tmp_path) is False
    assert not list((tmp_path / "2026-11-06").glob(f"{one.id}*"))


def test_removing_a_fetched_source_removes_its_raw_file_too(tmp_path):
    one = fetch(Getter(reply(article())), root=tmp_path)
    assert (tmp_path / "2026-11-06" / f"{one.id}.html").exists()
    src.remove(one.id, tmp_path)
    assert not list((tmp_path / "2026-11-06").glob(f"{one.id}*"))


def test_a_saved_text_that_was_changed_is_refused_with_a_plain_sentence(tmp_path):
    one = paste(tmp_path)
    (tmp_path / "2026-11-06" / f"{one.id}.txt").write_bytes(b"edited by hand")
    for call in (lambda: src.list_for("Mortgage lending", FRIDAY, tmp_path), lambda: src.get(one.id, tmp_path)):
        with pytest.raises(src.SourceError, match="no longer matches the fingerprint"):
            call()


def test_a_fetched_raw_file_that_was_changed_is_refused(tmp_path):
    one = fetch(Getter(reply(article())), root=tmp_path)
    (tmp_path / "2026-11-06" / f"{one.id}.html").write_bytes(b"<p>other</p>")
    with pytest.raises(src.SourceError, match="no longer matches"):
        src.get(one.id, tmp_path)


def test_a_missing_file_and_a_broken_manifest_are_plain_sentences(tmp_path):
    one = paste(tmp_path)
    (tmp_path / "2026-11-06" / f"{one.id}.txt").unlink()
    with pytest.raises(src.SourceError, match="missing its file"):
        src.get(one.id, tmp_path)
    (tmp_path / "2026-11-06" / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(src.SourceError, match="cannot be read"):
        src.list_all(FRIDAY, tmp_path)


def test_as_result_has_the_search_result_shape_plus_what_the_check_needs(tmp_path):
    one = paste(tmp_path, title="T")
    r = one.as_result()
    assert r == {"id": one.id, "url": one.url, "title": "T", "text": PARAGRAPH, "publishedDate": "2026-11-05",
                 "sha256": one.sha256, "fetched_at": "2026-11-06T09:00:00+00:00", "host": "www.centralbank.go.ke",
                 "origin": "pasted", "flags": []}
    assert "text" not in one.meta() and one.meta()["id"] == one.id


def test_the_default_folder_is_under_the_data_dir_and_the_test_fixture_redirects_it(tmp_path):
    assert src.sources_root() == tmp_path / "inputs" / "sources"
    assert src.sources_root(tmp_path / "other") == tmp_path / "other"
