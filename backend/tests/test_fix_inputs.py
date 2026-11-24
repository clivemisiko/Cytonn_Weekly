import re
from pathlib import Path

import pytest

from cytonn_weekly.review.blocks import COMPUTED_FIGURE, UNAVAILABLE_PART, unavailable_block
from cytonn_weekly.review.model import TABLE_ROW, WORKBOOK_QUARTER, ReviewItem
from cytonn_weekly.weekly import inputs as wi, recheck
from cytonn_weekly.weekly.analyst import FIELDS, TABLES

SRC = Path(recheck.__file__).resolve().parents[1]
BUILDERS = {recheck.FIXED_INCOME: SRC / "fixed_income" / "weekly.py", recheck.EQUITIES: SRC / "equities" / "weekly.py"}


def _block_ids(section: str) -> set[str]:
    # Every literal block id the builder passes as the first argument of a block constructor.
    text = BUILDERS[section].read_text(encoding="utf-8")
    ids = set(re.findall(r'_block\(\s*"([a-z_0-9]+)"', text)) | set(re.findall(r'"id":\s*"([a-z_0-9]+)"', text))
    if section == recheck.EQUITIES and 'bid = series.spec, f"chart_{series.spec.id}"' in (SRC / "charts" / "block.py").read_text(encoding="utf-8"):
        ids.add("chart_drawn")   # the tool-drawn charts' ids are "chart_<spec id>" (charts/block.py)
    return ids


def _matches(prefix: str, ids: set[str]) -> bool:
    return any(i == prefix or i.startswith(prefix + "_") for i in ids)


@pytest.mark.parametrize("section", sorted(BUILDERS))
def test_every_slot_map_prefix_is_a_real_block_id(section):
    ids = _block_ids(section)
    missing = [e.prefix for e in recheck.SLOT_MAP[section] if not _matches(e.prefix, ids)]
    assert not missing, f"SLOT_MAP prefixes no builder makes any more: {missing}"


@pytest.mark.parametrize("section", sorted(BUILDERS))
def test_every_field_map_prefix_is_a_real_block_id_and_its_keys_are_form_items(section):
    ids = _block_ids(section)
    for prefix, keys in recheck.FIELD_MAP[section].items():
        assert _matches(prefix, ids), f"{prefix} is not a block id of {BUILDERS[section].name}"
        for key in keys:
            assert key in FIELDS or key in TABLES, f"{key} is not a field or table of the analyst form"


@pytest.mark.parametrize("section", sorted(BUILDERS))
def test_every_field_map_prefix_has_an_unavailable_block_built_from_why(section):
    text = BUILDERS[section].read_text(encoding="utf-8")
    for prefix in recheck.FIELD_MAP[section]:
        assert f'unavailable_block("{prefix}"' in text or f"unavailable_block('{prefix}'" in text, prefix


def test_the_snip_sector_and_the_dp_slot_are_what_the_start_screen_has():
    rr = (SRC / "real_estate" / "review_run.py").read_text(encoding="utf-8")
    assert '"sector": brief.id' in rr
    assert wi.DP_WORKBOOK in wi.BY_SLUG


def _unavailable(block_id, title, **extra):
    return {**unavailable_block(block_id, title, "Demo reason.", "Demo unblock."), **extra}


def test_an_unavailable_fixed_income_part_names_its_form_keys():
    content = {"blocks": [_unavailable("money_market", "Money Market Performance")]}
    item = ReviewItem(UNAVAILABLE_PART, "Money Market Performance (not available yet)", "flagged")
    assert recheck.fix_inputs(recheck.FIXED_INCOME, content, item) == [
        {"panel": "analyst-form", "key": "mmf"}, {"panel": "analyst-form", "key": "placements"}]


def test_a_typed_computed_figure_names_the_key_its_input_came_from():
    label = FIELDS["pe"].label
    item = ReviewItem(COMPUTED_FIGURE, "Market Performance: valuation: P/E", "not_auto_verified", context={"inputs": {
        "x": {"value": 9.9, "origin": "analyst_input", "source": f"analyst input typed on the weekly form ({label}; source: Demo)"},
        "y": {"value": 1.0, "origin": "ocr", "source": "Demo page"}}})
    assert recheck.fix_inputs(recheck.EQUITIES, {"blocks": []}, item) == [{"panel": "analyst-form", "key": "pe"}]


def test_a_workbook_cell_input_and_a_clean_item_have_no_fix_input():
    wb = ReviewItem(TABLE_ROW, "Demo: row", "flagged", context={"inputs": {
        "pe": {"value": 1, "origin": "analyst_input", "source": "analyst input from the demo workbook Sheet!A1"}}})
    assert recheck.fix_inputs(recheck.EQUITIES, {"blocks": []}, wb) == []
    clean = ReviewItem(UNAVAILABLE_PART, "Money Market Performance (not available yet)", "clean")
    assert recheck.fix_inputs(recheck.FIXED_INCOME, {"blocks": [_unavailable("money_market", "Money Market Performance")]}, clean) == []


def test_real_estate_goes_to_the_sector_and_digital_payments_to_its_workbook():
    content = {"blocks": [_unavailable("land", "Land", sector="land")]}
    item = ReviewItem(UNAVAILABLE_PART, "Land (not available yet)", "flagged")
    assert recheck.fix_inputs("real_estate", content, item) == [{"panel": "snips", "key": "land"}]
    q = ReviewItem(WORKBOOK_QUARTER, "Demo Q1 net income (B2)", "not_auto_verified")
    assert recheck.fix_inputs("digital_payments", {}, q) == [{"panel": "inputs-panel", "key": "dp_workbook"}]


def test_focus_never_has_a_fix_input():
    item = ReviewItem(UNAVAILABLE_PART, "Demo (not available yet)", "flagged")
    assert recheck.fix_inputs("focus", {"blocks": [_unavailable("demo", "Demo")]}, item) == []
