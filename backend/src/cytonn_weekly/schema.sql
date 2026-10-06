-- Schema for data/app.db.
-- Apply with: sections.init_db() or sqlite3 data/app.db < src/cytonn_weekly/schema.sql (from backend/)

-- ---------------------------------------------------------------------------
-- sections: one row per report section; access and settings are section-based
-- (analysts rotate weekly, so ownership is stored here, not in a user table).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sections (
    name                TEXT    PRIMARY KEY,
    -- Nullable: who is responsible for this section in the current week.
    -- Rotates weekly; NULL means unassigned.
    current_analyst     TEXT,
    -- Focus-only flag: how the tool sources the topic this run.
    -- "analyst" = the analyst supplies the topic directly;
    -- "tool"     = the tool finds a candidate topic from historical reports.
    -- NULL for all non-Focus sections.
    focus_topic_source  TEXT    CHECK (focus_topic_source IN ('analyst', 'tool') OR focus_topic_source IS NULL),
    -- 1 = this section is actively being built in the current sprint.
    -- Digital Payments is the sole pilot section as of 2026-09-29;
    -- flip to 1 for each section as its fetcher/checker is implemented.
    in_active_build     INTEGER NOT NULL DEFAULT 0 CHECK (in_active_build IN (0, 1))
);

-- ---------------------------------------------------------------------------
-- Seed: five sections.  INSERT OR IGNORE so re-running is safe.
-- ---------------------------------------------------------------------------
INSERT OR IGNORE INTO sections (name, current_analyst, focus_topic_source, in_active_build)
VALUES
    ('Equities',          NULL, NULL,       0),
    ('Fixed Income',      NULL, NULL,       0),
    -- Digital Payments is the pilot section: first fetcher + checker to build.
    ('Digital Payments',  NULL, NULL,       1),
    ('Real Estate',       NULL, NULL,       0),
    -- Focus defaults to analyst-supplied sourcing; flip to 'tool' via
    -- update_section_config() once the tool-found path is trusted.
    ('Focus',             NULL, 'analyst',  0);

-- ---------------------------------------------------------------------------
-- coordinator_reviews: one row per drafted-and-checked section awaiting (or
-- past) the coordinator's accuracy review.  Content and items are JSON blobs;
-- only what is looked up by gets a column.  Rows are updated in place as the
-- coordinator resolves items, so a refresh mid-review loses nothing; once a
-- decision is recorded the row is frozen (review_store refuses to change it).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS coordinator_reviews (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
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
    -- Which report this review belongs to (report_types.py).  Together with period and
    -- section it is the review's key: a Q3'2026 Fixed Income review never collides with a
    -- weekly one.  Rows saved before report types existed are weekly with no period; a
    -- database from then gains both columns through sections._migrate(), not this statement,
    -- and ADD COLUMN appends, which is why they come last here too: a fresh table and a
    -- migrated one are identical.
    report_type   TEXT    NOT NULL DEFAULT 'weekly'
                  CHECK (report_type IN ('weekly', 'quarterly', 'half_year', 'annual', 'companion')),
    -- Normalized period label ("Q3'2026", "H1'2026", "FY'2025", "Weekly #38.2026"); '' only
    -- for a weekly review with no label.
    period        TEXT    NOT NULL DEFAULT '',
    CHECK ((decision IS NULL) = (decided_at IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_coordinator_reviews_lookup
    ON coordinator_reviews (section, run_date, decision);

-- The (report_type, period, section) index is created by sections._migrate(), after it has
-- added those columns to a database that predates them; creating it here would fail there.
