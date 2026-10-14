"""The web-link detector for supplied text (common/links.py): text analysis only, nothing fetched.

Hidden and look-alike characters are written as chr(...) so none sits invisibly in this file.
"""

import pytest

from cytonn_weekly.common.links import EMAIL, LINK, MISSING, POSSIBLE, URL, find_links
from cytonn_weekly.common.review import LINK_FLAG, POSSIBLE_LINK_FLAG, SUPPLIED_NOTE, SUPPLIED_TEXT, build_review, check_section
from cytonn_weekly.digital_payments.coordinator_review import FLAGGED, NOT_AUTO_VERIFIED
from cytonn_weekly.weekly.company_updates import build_company_updates_weekly_review

ZWSP, CYRILLIC_ES = chr(0x200B), chr(0x0441)


def hits(text):
    return [(f.text, f.confidence, f.kind) for f in find_links(text)]


@pytest.mark.parametrize("text, expected", [
    ("Rates at https://cytonn.com/cmmf today", [("https://cytonn.com/cmmf", LINK, URL)]),
    ("Old site http://example.org", [("http://example.org", LINK, URL)]),
    ("See www.cytonn.com for more", [("www.cytonn.com", LINK, URL)]),
    ("Read [the note](https://cytonn.com/n) now", [("[the note](https://cytonn.com/n)", LINK, URL)]),
    ('Read <a href="https://cytonn.com/n">here</a>', [('<a href="https://cytonn.com/n">', LINK, URL)]),
    ("Short: bit.ly/3xYz and lnkd.in/abc", [("bit.ly/3xYz", LINK, URL), ("lnkd.in/abc", LINK, URL)]),
    ("Query: example.co.ke/news?id=3", [("example.co.ke/news?id=3", LINK, URL)]),
    ("Prices on nse.co.ke as usual", [("nse.co.ke", POSSIBLE, URL)]),
    ("Prices on nse.co.ke/news", [("nse.co.ke/news", POSSIBLE, URL)]),
    ("Write to info@cytonn.com today", [("info@cytonn.com", POSSIBLE, EMAIL)]),
    ("To apply, click here.", [("click here", POSSIBLE, MISSING)]),
])
def test_what_is_found_and_how_sure(text, expected):
    assert hits(text) == expected


def test_click_here_is_flagged_only_when_the_text_holds_no_link():
    assert hits("Click here: https://cytonn.com/apply") == [("https://cytonn.com/apply", LINK, URL)]
    assert hits("Visit our website for the rates.") == [("Visit our website", POSSIBLE, MISSING)]


def test_a_full_stop_or_bracket_after_a_link_is_not_part_of_it():
    assert hits("Rates at https://cytonn.com/rates.") == [("https://cytonn.com/rates", LINK, URL)]
    assert hits("(see https://cytonn.com/rates)") == [("https://cytonn.com/rates", LINK, URL)]
    assert hits("on nse.co.ke.") == [("nse.co.ke", POSSIBLE, URL)]
    assert hits("https://en.wikipedia.org/wiki/Nairobi_(city)") == [("https://en.wikipedia.org/wiki/Nairobi_(city)", LINK, URL)]


def test_uppercase_is_found_and_kept_as_written():
    assert hits("SEE WWW.CYTONN.COM AND HTTPS://NSE.CO.KE") == [("WWW.CYTONN.COM", LINK, URL), ("HTTPS://NSE.CO.KE", LINK, URL)]
    assert hits("NSE.CO.KE") == [("NSE.CO.KE", POSSIBLE, URL)]


def test_hidden_and_look_alike_characters_are_named():
    text = f"Rates on nse.co{ZWSP}.ke today"
    [hit] = find_links(text)
    assert (hit.text, hit.confidence, hit.position) == ("nse.co.ke", POSSIBLE, 10)
    assert "hidden characters (U+200B)" in hit.reason
    [hit] = find_links(f"https://{CYRILLIC_ES}ytonn.com/x")
    assert hit.confidence == LINK and "non-Latin letters" in hit.reason and "U+0441" in hit.reason


def test_the_position_is_the_1_based_character_in_the_text_given():
    [hit] = find_links("abc https://x.com")
    assert hit.position == 5 and hit.message == "Link: https://x.com (a web address starting http:// or https://), position 5"


@pytest.mark.parametrize("text", [
    "The fund returned 2.5% against 14.3% last year.",
    "Turnover rose to KES 1.2bn, up from KES 0.9bn.",
    "Products, e.g. pensions, i.e. retirement plans.",
    "Cytonn Investments Ltd. and Acme Inc. with Mr. Kamau.",
    "The full report.pdf is attached.",
    "It was the end.Next week we open.",
    "A dotted name like Cysuites.Hotels stays as it is.",
    "Version 2.0.1 of the tool.",
])
def test_not_a_link(text):
    assert find_links(text) == []


def test_a_file_after_a_domain_is_part_of_the_address():
    assert hits("Download cytonn.com/report.pdf") == [("cytonn.com/report.pdf", POSSIBLE, URL)]


# -- the review item -----------------------------------------------------------

def company_item(text):
    review = build_company_updates_weekly_review(text)
    [item] = [i for i in review.review_items if i.kind == SUPPLIED_TEXT]
    return review, item


def test_a_link_flags_the_item_with_one_line_per_hit_and_does_not_change_the_text():
    text = "Investment Updates:\nRead https://cytonn.com/rates. Prices on nse.co.ke."
    review, item = company_item(text)
    assert item.status == FLAGGED
    assert [(f.kind, f.message) for f in item.detail] == [
        (LINK_FLAG, "Link: https://cytonn.com/rates (a web address starting http:// or https://), position 26"),
        (POSSIBLE_LINK_FLAG, "Possible link: nse.co.ke (a domain without http), position 62"),
    ]
    assert review.section["blocks"][0]["body_md"] == text and item.context["text"] == text
    # it asks for a look, never blocks: accepted, the section can be approved
    item.resolve("accept")
    assert review.is_approvable


def test_only_possible_hits_leave_the_item_not_auto_verified_with_the_lines_under_the_note():
    _, item = company_item("Investment Updates: rates on nse.co.ke; write to info@cytonn.com.")
    assert item.status == NOT_AUTO_VERIFIED
    assert item.detail == "\n".join([
        SUPPLIED_NOTE,
        "Possible link: nse.co.ke (a domain without http), position 30",
        "Possible email address: info@cytonn.com (an email address), position 50",
    ])


def test_text_with_no_link_carries_nothing_new():
    _, item = company_item("Investment Updates: the fund closed at 11.0%, e.g. ahead of KES 1.2bn. Cysuites Ltd. offers.")
    assert item.status == NOT_AUTO_VERIFIED and item.detail == SUPPLIED_NOTE


def test_every_supplied_block_is_checked_the_same_way():
    """The Markets Reviews' Company Updates is the same supplied block, so it is flagged the same way."""
    from tests import periodic_helpers as ph
    item = next(i for i in ph.company_updates_review(text="See https://cytonn.com/q3").review_items if i.kind == SUPPLIED_TEXT)
    assert item.status == FLAGGED and item.detail[0].message.startswith("Link: https://cytonn.com/q3")
    content = {"section": "x", "blocks": [{"kind": "supplied", "id": "s", "title": "T", "body_md": "plain"}]}
    assert build_review(content, check_section(content)).review_items[0].detail == SUPPLIED_NOTE
