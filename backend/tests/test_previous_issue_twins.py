"""previous_issue skips a stripped twin of a published issue.

cytonnreport.com holds copies of some issues with the charts stripped out (and sometimes a section or two), and the stripped copy
can have the higher id: 850 for 849, 889 for 888, 841 for 840. Walking down from the newest id used to land on it. A candidate is
now skipped only if BOTH hold: its Fixed Income and Equities sections together hold fewer than STRIPPED_BELOW_IMAGES images, AND
an issue with more images in those two sections was published within TWIN_WINDOW_DAYS before it. A stripped candidate with no such
twin is returned as before (a genuine image-light issue is kept), and nothing falls back to an older full issue. Reviews are not
skipped. The 12-id walk limit applies to the look-ahead too.

The cases use previous_issue_fixture: metadata of the real issues (id, date, slugs, image counts) and a fake site with tiny bodies.
"""

from datetime import date, timedelta

import pytest

from cytonn_weekly.weekly import previous_issue
from tests import previous_issue_fixture as fx

A = date(2026, 3, 1)  # a Sunday: the day of the full issue in the synthetic cases
ISSUES = fx.ISSUES


def lookup(friday, issues=ISSUES, newest=None, asked=None):
    newest = newest if newest is not None else fx.newest_as_of(issues, friday)
    return previous_issue.find_previous_issue(friday, fx.site(issues, newest, asked))


def pair(days_apart, full_images=(7, 2), stripped_images=(0, 0)):
    """Two synthetic weeklies: 10 is full, 11 is ``days_apart`` days later with the given Fixed Income and Equities images."""
    return {10: fx.weekly_issue(A.isoformat(), *full_images),
            11: fx.weekly_issue((A + timedelta(days=days_apart)).isoformat(), *stripped_images)}


# -- the two numbers ---------------------------------------------------------------------------------------------------------

def test_the_two_constants_are_named_and_hold_the_documented_numbers():
    assert previous_issue.STRIPPED_BELOW_IMAGES == 4
    assert previous_issue.TWIN_WINDOW_DAYS == 6


def test_the_fixture_matches_what_the_rule_rests_on():
    """The real numbers behind 4 and 6: full weeklies have at least 8 images in the two sections, stripped copies fewer than 4."""
    stripped = {841, 850, 860, 875, 876, 889, 890}
    images = {i: row[3] + row[4] for i, row in ISSUES.items() if row is not None}
    assert all(images[i] < previous_issue.STRIPPED_BELOW_IMAGES for i in stripped)
    full_weeklies = [i for i, row in ISSUES.items() if row is not None and row[1] == "weekly" and i not in stripped]
    assert len(full_weeklies) == 35 and all(ISSUES[i][3] >= 6 and ISSUES[i][4] >= 2 for i in full_weeklies)
    for later, earlier in ((850, 849), (889, 888), (841, 840)):  # each stripped twin was published 5, 1 and 1 days after its full copy
        gap = (date.fromisoformat(ISSUES[later][0]) - date.fromisoformat(ISSUES[earlier][0])).days
        assert 0 <= gap <= previous_issue.TWIN_WINDOW_DAYS


# -- 1. the three twins whose stripped copy has the higher id ---------------------------------------------------------------------

@pytest.mark.parametrize("friday, stripped, full", [
    (date(2026, 2, 27), 850, 849),   # published 27 and 22 February
    (date(2026, 9, 25), 889, 888),   # 21 and 20 September
    (date(2026, 1, 9), 841, 840),    # 5 and 4 January
])
def test_a_stripped_twin_with_the_higher_id_is_skipped_for_the_full_copy(friday, stripped, full):
    issue = lookup(friday)
    assert issue.issue_id == full
    assert issue.skipped_twins == [stripped]  # said on the issue, for the reviewer to see


# -- 2. unchanged ----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("friday, expected", [
    (date(2026, 4, 17), 861),   # 860/861: the stripped copy has the LOWER id, so the walk never meets it
    (date(2026, 7, 10), 877),   # 875/876/877, the H1 review: the full copy has the highest id
    (date(2026, 10, 2), 891),   # 890/891: the same
])
def test_the_other_twins_return_the_same_ids_as_before(friday, expected):
    issue = lookup(friday)
    assert issue.issue_id == expected and issue.skipped_twins == []


def test_the_existing_assertions_for_2_and_9_october_stay():
    assert lookup(date(2026, 10, 2)).issue_id == 891  # 892 is this week's own issue
    review = lookup(date(2026, 10, 9))
    assert review.issue_id == 892 and review.kind == "review" and review.skipped_twins == []  # reviews are not skipped


# -- 3 and 4. a stripped candidate is skipped only for a twin within 6 days before it ---------------------------------------------------

@pytest.mark.parametrize("days_apart, expected, why", [
    (0, 10, "a fuller issue the same day is a twin"),
    (1, 10, "one day"),
    (6, 10, "six days is still inside the window"),
    (7, 11, "a fuller issue seven days earlier is last week's, not a twin: the stripped candidate is kept"),
    (13, 11, "and so is one two weeks earlier"),
])
def test_a_stripped_candidate_is_skipped_only_for_a_fuller_issue_within_six_days_before_it(days_apart, expected, why):
    issue = lookup(A + timedelta(days=20), pair(days_apart))
    assert issue.issue_id == expected, why
    assert issue.skipped_twins == ([11] if expected == 10 else [])


def test_a_stripped_candidate_with_no_fuller_issue_before_it_is_returned_as_today():
    only = {11: fx.weekly_issue(A.isoformat(), 0, 0)}
    assert lookup(A + timedelta(days=3), only).issue_id == 11


def test_a_genuine_image_light_weekly_is_kept_even_with_a_full_issue_seven_days_before_it():
    issues = pair(7, stripped_images=(2, 0))  # a weekly with two charts that week
    issue = lookup(A + timedelta(days=20), issues)
    assert issue.issue_id == 11 and issue.skipped_twins == []
    assert issue.published == A + timedelta(days=7)


def test_a_stripped_candidate_never_falls_back_to_an_older_full_issue_when_it_has_no_twin():
    issues = {9: fx.weekly_issue((A - timedelta(days=7)).isoformat(), 8, 2), 10: fx.weekly_issue(A.isoformat(), 7, 2),
              11: fx.weekly_issue((A + timedelta(days=7)).isoformat(), 0, 0)}
    assert lookup(A + timedelta(days=20), issues).issue_id == 11


# the image threshold (condition a)

@pytest.mark.parametrize("images, expected", [((3, 1), 11), ((2, 1), 10), ((0, 3), 10), ((1, 2), 10)])
def test_four_images_in_the_two_sections_together_is_enough_to_be_kept_and_three_is_stripped(images, expected):
    # (3, 1) is four images: not fewer than four, so kept; the rest are three: stripped, and a fuller issue is three days before
    issue = lookup(A + timedelta(days=20), pair(3, stripped_images=images))
    assert issue.issue_id == expected


def test_an_issue_with_plenty_of_images_is_kept_even_when_another_issue_a_few_days_before_has_more():
    assert lookup(A + timedelta(days=20), pair(3, full_images=(14, 5), stripped_images=(8, 2))).issue_id == 11


def test_an_issue_is_not_skipped_for_one_with_the_same_number_of_images():
    assert lookup(A + timedelta(days=20), pair(2, full_images=(1, 1), stripped_images=(1, 1))).issue_id == 11


# -- 5. empty ids and the 12-id limit ----------------------------------------------------------------------------------------------

def test_an_empty_id_is_skipped_and_the_walk_goes_on():
    assert ISSUES[846] is None and ISSUES[854] is None
    assert lookup(date(2026, 2, 6), newest=846).issue_id == 845   # the newest id is empty
    assert lookup(date(2026, 3, 20), newest=854).issue_id == 853


def synthetic_run(n, published, rows=None):
    """Ids 100 to 100 + n - 1, all published ``published`` unless a row is given: {id: row}."""
    issues = {i: fx.weekly_issue(published, 7, 2) for i in range(100, 100 + n)}
    issues.update(rows or {})
    return issues


def test_the_twelve_id_limit_still_raises():
    issues = synthetic_run(13, "2026-05-01", {100: fx.weekly_issue("2026-01-01", 7, 2)})
    # the only issue old enough is id 100, the 13th from the newest (112): out of reach
    with pytest.raises(previous_issue.PreviousIssueError, match="no issue published on or before 2026-02-01"):
        lookup(date(2026, 2, 1), issues, newest=112)
    assert lookup(date(2026, 2, 1), issues, newest=111).issue_id == 100  # 12 ids from 111: reached


def test_the_look_ahead_for_a_twin_stays_inside_the_twelve_ids():
    friday = date(2026, 2, 1)
    asked = []
    outside = synthetic_run(14, "2026-06-01", {
        101: fx.weekly_issue("2026-01-20", 0, 0),   # the 12th id from the newest (112): stripped
        100: fx.weekly_issue("2026-01-18", 8, 2),   # its twin, one id too far
    })
    issue = lookup(friday, outside, newest=112, asked=asked)
    assert issue.issue_id == 101 and issue.skipped_twins == []   # the twin is out of reach, so the candidate stands
    assert min(asked) >= 101 and 100 not in asked
    inside = synthetic_run(14, "2026-06-01", {
        102: fx.weekly_issue("2026-01-21", 0, 0),   # the 11th id: stripped
        101: fx.weekly_issue("2026-01-18", 8, 2),   # its twin, the 12th: in reach
    })
    issue = lookup(friday, inside, newest=112)
    assert issue.issue_id == 101 and issue.skipped_twins == [102]


# -- the 37 weeks replayed over the real metadata --------------------------------------------------------------------------------------

@pytest.mark.parametrize("friday, expected", [(date.fromisoformat(d), i) for d, i in fx.WEEKS])
def test_every_replayed_week_returns_its_expected_id(friday, expected):
    assert lookup(friday).issue_id == expected


def test_exactly_three_of_the_37_weeks_skip_a_twin():
    skipped = {d: lookup(date.fromisoformat(d)).skipped_twins for d, _ in fx.WEEKS}
    assert {d: s for d, s in skipped.items() if s} == {"2026-01-09": [841], "2026-02-27": [850], "2026-09-25": [889]}
    assert len(fx.WEEKS) == 37 and sum(1 for s in skipped.values() if not s) == 34


# -- what kind of issue it is -------------------------------------------------------------------------------------------------

def test_an_issue_says_whether_it_is_a_weekly_or_a_review():
    assert lookup(date(2026, 2, 27)).kind == "weekly"   # 849
    assert lookup(date(2026, 1, 9)).kind == "review"    # 840, the FY'2025 review
    assert lookup(date(2026, 7, 10)).kind == "review"   # 877, the H1 review
