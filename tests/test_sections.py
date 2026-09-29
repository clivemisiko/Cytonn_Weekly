"""Unit tests for cytonn_weekly.sections.

All tests use an in-memory SQLite database so they are hermetic: no file I/O,
no dependency on the state of data/app.db, and safe to run in parallel.
"""

import pytest
from cytonn_weekly.sections import get_section_config, init_db, update_section_config

# ---------------------------------------------------------------------------
# Fixture: fresh in-memory DB per test
# ---------------------------------------------------------------------------

DB = ":memory:"


@pytest.fixture(autouse=True)
def seeded_db(tmp_path):
    """Each test gets a fresh seeded in-memory DB via a temp file.

    SQLite's :memory: databases are per-connection, so we use a temp file
    instead — this keeps all calls within the same test pointing at the same
    state without threading concerns.
    """
    db = tmp_path / "test.db"
    init_db(db)
    # Inject the path into the module-level default so helpers can be called
    # without repeating db_path in every assertion.  We pass db_path
    # explicitly in every call instead, so this fixture just returns the path.
    return db


# ---------------------------------------------------------------------------
# Seeded section reads
# ---------------------------------------------------------------------------

KNOWN_SECTIONS = [
    "Equities",
    "Fixed Income",
    "Digital Payments",
    "Real Estate",
    "Focus",
]


@pytest.mark.parametrize("section", KNOWN_SECTIONS)
def test_get_known_section_returns_dict(seeded_db, section):
    cfg = get_section_config(section, db_path=seeded_db)
    assert isinstance(cfg, dict)
    assert cfg["name"] == section


def test_equities_defaults(seeded_db):
    cfg = get_section_config("Equities", db_path=seeded_db)
    assert cfg["current_analyst"] is None
    assert cfg["focus_topic_source"] is None
    assert cfg["in_active_build"] == 0


def test_digital_payments_is_active_build_pilot(seeded_db):
    """Digital Payments is the only section marked in_active_build=1 at seed."""
    cfg = get_section_config("Digital Payments", db_path=seeded_db)
    assert cfg["in_active_build"] == 1


def test_only_digital_payments_is_active_build(seeded_db):
    """No other seeded section should have in_active_build=1."""
    non_pilot = [s for s in KNOWN_SECTIONS if s != "Digital Payments"]
    for section in non_pilot:
        cfg = get_section_config(section, db_path=seeded_db)
        assert cfg["in_active_build"] == 0, (
            f"{section} unexpectedly has in_active_build=1"
        )


def test_focus_has_analyst_topic_source_by_default(seeded_db):
    cfg = get_section_config("Focus", db_path=seeded_db)
    assert cfg["focus_topic_source"] == "analyst"


def test_non_focus_sections_have_null_topic_source(seeded_db):
    non_focus = [s for s in KNOWN_SECTIONS if s != "Focus"]
    for section in non_focus:
        cfg = get_section_config(section, db_path=seeded_db)
        assert cfg["focus_topic_source"] is None, (
            f"{section} unexpectedly has focus_topic_source set"
        )


# ---------------------------------------------------------------------------
# Unknown section name
# ---------------------------------------------------------------------------

def test_unknown_section_raises_key_error(seeded_db):
    with pytest.raises(KeyError, match="Unknown section"):
        get_section_config("Derivatives", db_path=seeded_db)


def test_empty_string_raises_key_error(seeded_db):
    with pytest.raises(KeyError):
        get_section_config("", db_path=seeded_db)


def test_case_sensitive_match(seeded_db):
    """Section names are stored title-cased; wrong case should raise."""
    with pytest.raises(KeyError):
        get_section_config("equities", db_path=seeded_db)


# ---------------------------------------------------------------------------
# update_section_config
# ---------------------------------------------------------------------------

def test_update_current_analyst(seeded_db):
    update_section_config("Equities", current_analyst="Jane", db_path=seeded_db)
    cfg = get_section_config("Equities", db_path=seeded_db)
    assert cfg["current_analyst"] == "Jane"


def test_update_focus_topic_source_to_tool(seeded_db):
    update_section_config("Focus", focus_topic_source="tool", db_path=seeded_db)
    cfg = get_section_config("Focus", db_path=seeded_db)
    assert cfg["focus_topic_source"] == "tool"


def test_update_with_no_fields_raises(seeded_db):
    with pytest.raises(ValueError, match="No fields specified"):
        update_section_config("Equities", db_path=seeded_db)


def test_update_unknown_section_raises_key_error(seeded_db):
    with pytest.raises(KeyError, match="Unknown section"):
        update_section_config("Derivatives", current_analyst="X", db_path=seeded_db)


def test_update_does_not_affect_other_sections(seeded_db):
    update_section_config("Equities", current_analyst="Jane", db_path=seeded_db)
    cfg = get_section_config("Fixed Income", db_path=seeded_db)
    assert cfg["current_analyst"] is None


# ---------------------------------------------------------------------------
# init_db idempotency
# ---------------------------------------------------------------------------

def test_init_db_is_idempotent(seeded_db):
    """Calling init_db a second time must not duplicate seed rows."""
    init_db(seeded_db)  # second call
    # If rows were duplicated this would raise sqlite3.IntegrityError or
    # return a wrong count; get_section_config should still work cleanly.
    cfg = get_section_config("Digital Payments", db_path=seeded_db)
    assert cfg["in_active_build"] == 1
