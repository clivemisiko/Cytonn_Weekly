-- Schema for data/app.db.
-- Apply with: sections.init_db() or sqlite3 data/app.db < data/schema.sql

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
