-- Schema for the PostgreSQL database (Supabase).  Run by db.open_db() on a connection whose search_path is the schema below.
-- The same tables, columns, CHECKs, UNIQUEs and defaults as schema.sql (SQLite), which stays the reference for what each column means.
-- Dates and JSON are TEXT, as in SQLite.  Every statement is safe to run again.

-- The token in braces is replaced by db.py with the quoted name from CYTONN_DATABASE_SCHEMA (default cytonn).  The
-- tables are in their own schema, never in public, which Supabase exposes through its web API.
CREATE SCHEMA IF NOT EXISTS {schema};

-- ---------------------------------------------------------------------------
-- sections: one row per report section; access and settings are section-based.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sections (
    name                TEXT    PRIMARY KEY,
    -- Nullable: who is responsible for this section in the current week.  NULL means unassigned.
    current_analyst     TEXT,
    -- Focus-only flag: "analyst" = the analyst supplies the topic; "tool" = the tool finds a candidate.  NULL elsewhere.
    focus_topic_source  TEXT    CHECK (focus_topic_source IN ('analyst', 'tool') OR focus_topic_source IS NULL),
    -- 1 = this section is actively being built in the current sprint.
    in_active_build     INTEGER NOT NULL DEFAULT 0 CHECK (in_active_build IN (0, 1))
);

INSERT INTO sections (name, current_analyst, focus_topic_source, in_active_build)
VALUES
    ('Equities',          NULL, NULL,       0),
    ('Fixed Income',      NULL, NULL,       0),
    ('Digital Payments',  NULL, NULL,       1),
    ('Real Estate',       NULL, NULL,       0),
    ('Focus',             NULL, 'analyst',  0)
ON CONFLICT (name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- coordinator_reviews: one row per drafted-and-checked section awaiting (or past) the coordinator's accuracy review.
-- Content and items are JSON text; only what is looked up by gets a column.  Once a decision is recorded the row is
-- frozen (review_store refuses to change it).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS coordinator_reviews (
    run_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Slug, e.g. 'digital_payments' (not sections.name, which is the display name).
    section       TEXT    NOT NULL,
    -- ISO date (YYYY-MM-DD) the draft was run, not the report week.
    run_date      TEXT    NOT NULL,
    created_at    TEXT    NOT NULL,   -- ISO-8601 UTC
    updated_at    TEXT    NOT NULL,   -- ISO-8601 UTC, last save
    -- NULL until the coordinator decides; set together with decided_at.
    decision      TEXT    CHECK (decision IN ('approved', 'rejected') OR decision IS NULL),
    decided_at    TEXT,
    -- compose_section() output, written once and never changed.
    content_json  TEXT    NOT NULL,
    -- Every ReviewItem as a JSON list, with its resolution and note; rewritten on each save.
    items_json    TEXT    NOT NULL,
    -- Which report this review belongs to (report_types.py): with period and section, the review's key.
    report_type   TEXT    NOT NULL DEFAULT 'weekly'
                  CHECK (report_type IN ('weekly', 'quarterly', 'half_year', 'annual', 'companion')),
    -- Normalized period label ("Q3'2026", "H1'2026", "FY'2025", "Weekly #38.2026"); '' only for a weekly review with no label.
    period        TEXT    NOT NULL DEFAULT '',
    CHECK ((decision IS NULL) = (decided_at IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_coordinator_reviews_lookup
    ON coordinator_reviews (section, run_date, decision);

-- SQLite creates this one in its migration, after adding the columns to an old database; here the table is new.
CREATE INDEX IF NOT EXISTS idx_coordinator_reviews_report
    ON coordinator_reviews (report_type, period, section, run_id);

-- ---------------------------------------------------------------------------
-- suggestion_decisions: what the analyst did with each "Notable this week" suggestion (notable/store.py).  One row per
-- week, section and suggestion; a new decision on the same suggestion replaces the old one.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS suggestion_decisions (
    -- The report week's Friday (YYYY-MM-DD) and the section slug.
    week_ending      TEXT NOT NULL,
    section          TEXT NOT NULL,
    -- notable/suggestion.py: a hash of the finding's kind, section, week, series and window.
    suggestion_id    TEXT NOT NULL,
    decision         TEXT NOT NULL CHECK (decision IN ('selected', 'dismissed')),
    -- The analyst's rewording of the headline; only on a selected suggestion, and the original is never changed.
    edited_headline  TEXT CHECK (edited_headline IS NULL OR decision = 'selected'),
    -- Why it was dismissed (optional); only on a dismissed suggestion.
    dismiss_reason   TEXT CHECK (dismiss_reason IS NULL OR decision = 'dismissed'),
    decided_at       TEXT NOT NULL,   -- ISO-8601 UTC
    UNIQUE (week_ending, section, suggestion_id)
);

-- ---------------------------------------------------------------------------
-- Row level security on, with no policies: Supabase's web API roles (anon, authenticated) see and change nothing here.
-- The app connects as the tables' owner, which row level security does not apply to (so no FORCE).
-- ---------------------------------------------------------------------------
ALTER TABLE sections             ENABLE ROW LEVEL SECURITY;
ALTER TABLE coordinator_reviews  ENABLE ROW LEVEL SECURITY;
ALTER TABLE suggestion_decisions ENABLE ROW LEVEL SECURITY;
