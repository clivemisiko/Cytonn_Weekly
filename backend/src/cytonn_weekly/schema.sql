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
-- Seed: five sections.  ON CONFLICT DO NOTHING so re-running is safe.
-- ---------------------------------------------------------------------------
INSERT INTO sections (name, current_analyst, focus_topic_source, in_active_build)
VALUES
    ('Equities',          NULL, NULL,       0),
    ('Fixed Income',      NULL, NULL,       0),
    -- Digital Payments is the pilot section: first fetcher + checker to build.
    ('Digital Payments',  NULL, NULL,       1),
    ('Real Estate',       NULL, NULL,       0),
    -- Focus defaults to analyst-supplied sourcing; flip to 'tool' via
    -- update_section_config() once the tool-found path is trusted.
    ('Focus',             NULL, 'analyst',  0)
ON CONFLICT (name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- coordinator_reviews: one row per drafted-and-checked section awaiting (or
-- past) the analyst's accuracy review.  Content and items are JSON blobs;
-- only what is looked up by gets a column.  Rows are updated in place as the
-- analyst resolves items, so a refresh mid-review loses nothing; once a
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
    -- NULL until the analyst decides; set together with decided_at.
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
                  CHECK (report_type IN ('weekly', 'monthly', 'quarterly', 'half_year', 'annual', 'companion')),
    -- Normalized period label ("Q3'2026", "H1'2026", "FY'2025", "Weekly #38.2026"); '' only
    -- for a weekly review with no label.
    period        TEXT    NOT NULL DEFAULT '',
    CHECK ((decision IS NULL) = (decided_at IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_coordinator_reviews_lookup
    ON coordinator_reviews (section, run_date, decision);

-- The (report_type, period, section) index is created by sections._migrate(), after it has
-- added those columns to a database that predates them; creating it here would fail there.

-- ---------------------------------------------------------------------------
-- suggestion_decisions: what the analyst did with each "Notable this week"
-- suggestion (notable/store.py).  One row per week, section and suggestion; a
-- new decision on the same suggestion replaces the old one, and deleting the
-- row restores the suggestion.  Nothing here is read by a draft, a review, an
-- approval or the export.
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
-- draft_runs, run_events, draft_usage: every draft run started with POST /api/runs (api/runs.py writes through to them on each
-- status change and event, run_store.py), so a restart or an old run dropped from memory loses nothing.  run_id is the registry's
-- own id (a uuid in hex), not coordinator_reviews.run_id; review_id is that one.  period is the week or period the draft is for.
-- A run that was queued or running when the process stopped is marked 'interrupted' at the next start.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS draft_runs (
    run_id          TEXT    PRIMARY KEY,
    report_type     TEXT    NOT NULL,
    period          TEXT    NOT NULL DEFAULT '',
    section         TEXT    NOT NULL,
    section_title   TEXT    NOT NULL,
    report_title    TEXT    NOT NULL,
    status          TEXT    NOT NULL CHECK (status IN ('queued', 'running', 'finished', 'failed', 'interrupted')),
    started_at      TEXT    NOT NULL,   -- ISO-8601 UTC; for a queued run, when it joined the queue
    finished_at     TEXT,               -- ISO-8601 UTC; set exactly when the run has ended
    error           TEXT,               -- the failure or interruption sentence the run showed
    review_id       INTEGER,             -- the saved review, once finished
    is_dev_draft    INTEGER CHECK (is_dev_draft IN (0, 1) OR is_dev_draft IS NULL),
    dev_mode_label  TEXT,
    CHECK ((status IN ('queued', 'running')) = (finished_at IS NULL))
);

-- The events the run's screen and stream show, in order (common/run_events.py).  counts_json is the three review counts, or NULL.
CREATE TABLE IF NOT EXISTS run_events (
    run_id       TEXT    NOT NULL,
    seq          INTEGER NOT NULL,
    kind         TEXT    NOT NULL,
    label        TEXT    NOT NULL,
    detail       TEXT,
    counts_json  TEXT,
    event_at     TEXT    NOT NULL,   -- ISO-8601 UTC
    PRIMARY KEY (run_id, seq)
);

-- What a finished draft spent on Amazon Bedrock (the "usage" saved with its review): tokens and calls only.  A draft with no
-- Bedrock call has no row.
CREATE TABLE IF NOT EXISTS draft_usage (
    run_id                      TEXT    PRIMARY KEY,
    model                       TEXT    NOT NULL,
    calls                       INTEGER NOT NULL,
    input_tokens                INTEGER NOT NULL,
    output_tokens               INTEGER NOT NULL,
    calls_without_token_counts  INTEGER NOT NULL DEFAULT 0,
    saved_at                    TEXT    NOT NULL   -- ISO-8601 UTC
);

-- ---------------------------------------------------------------------------
-- report_jobs, job_messages (jobs.py): one job per report type, period and section, and its messages in order.  The three limits
-- are the values in force when the job was opened (CYTONN_JOB_*); agent/loop.py enforces them.  job_messages.job_id refers to
-- report_jobs.job_id (jobs.py checks it; no foreign key, as nowhere else in this schema).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS report_jobs (
    job_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type     TEXT    NOT NULL,
    period          TEXT    NOT NULL DEFAULT '',
    section         TEXT    NOT NULL,
    max_tool_calls  INTEGER NOT NULL,   -- per message
    call_budget     INTEGER NOT NULL,   -- model calls over the whole job
    token_budget    INTEGER NOT NULL,   -- input and output tokens over the whole job
    created_at      TEXT    NOT NULL,   -- ISO-8601 UTC
    status          TEXT    NOT NULL DEFAULT 'idle',   -- idle, working or paused (jobs.STATUSES)
    paused_reason   TEXT,               -- when paused: tool_calls, call_budget or token_budget
    calls_used      INTEGER NOT NULL DEFAULT 0,   -- model calls so far, against call_budget
    input_tokens    INTEGER NOT NULL DEFAULT 0,   -- tokens so far, input plus output against token_budget
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    budget_raises   INTEGER NOT NULL DEFAULT 0,   -- how many times the analyst pressed the raise button
    UNIQUE (report_type, period, section)
);

CREATE TABLE IF NOT EXISTS job_messages (
    job_id       INTEGER NOT NULL,
    seq          INTEGER NOT NULL,   -- 1, 2, 3, ... within one job
    role         TEXT    NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content      TEXT    NOT NULL,
    tool_name    TEXT,               -- a tool turn: which tool
    tool_result  TEXT,               -- a tool turn: what it returned
    created_at   TEXT    NOT NULL,   -- ISO-8601 UTC
    tool_use_id  TEXT,               -- a tool turn: the id the model gave the call, so the result pairs with it
    tool_input   TEXT,               -- a tool turn: the validated input, as JSON
    usage        TEXT,               -- an assistant turn the model wrote: {"model", "input_tokens", "output_tokens"} as JSON
    cards        TEXT,               -- an assistant turn: the cards shown with it, as JSON; never sent to the model
    PRIMARY KEY (job_id, seq)
);

-- ---------------------------------------------------------------------------
-- series, series_points (history/store.py): the weekly history the tool keeps itself, one current point per series and date.
-- A series is a key ('eq.pe', 'fi.mmf.rate') and a subject (a fund or company; '' when it has none) with one unit, fixed for good.
-- A point's value is decimal text.  A correction is a new row: the old one's superseded_by is set to it in the same transaction
-- and the old row is kept.  superseded_by NULL means current.  confirmed_at NULL means the point is not yet used by any reader.
-- source_ref is a source id, a form field or table key, or "<sheet>!<cell>"; for a worked-out point, the working.
-- Confidential series (the P/E series, the fund table, placements) live here and in the data folder only.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS series (
    series_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL,
    subject     TEXT NOT NULL DEFAULT '',
    unit        TEXT NOT NULL,
    section     TEXT NOT NULL,
    cadence     TEXT NOT NULL CHECK (cadence IN ('day', 'week', 'month')),
    label       TEXT NOT NULL,
    created_at  TEXT NOT NULL,   -- ISO-8601 UTC
    UNIQUE (key, subject)
);

CREATE TABLE IF NOT EXISTS series_points (
    point_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id      BIGINT NOT NULL,
    as_of          TEXT   NOT NULL,   -- the point's own date (YYYY-MM-DD)
    week_ending    TEXT   NOT NULL,   -- the report Friday it belongs to
    value          TEXT   NOT NULL,   -- decimal text
    origin         TEXT   NOT NULL CHECK (origin IN ('fetched', 'typed', 'worked_out', 'carried', 'workbook_import')),
    source_kind    TEXT   NOT NULL CHECK (source_kind IN ('source', 'form_field', 'workbook_cell', 'working')),
    source_ref     TEXT   NOT NULL,
    superseded_by  BIGINT,
    confirmed_by   TEXT,
    confirmed_at   TEXT,
    created_at     TEXT   NOT NULL,   -- ISO-8601 UTC
    CHECK ((confirmed_by IS NULL) = (confirmed_at IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_series_points_current ON series_points (series_id, as_of) WHERE superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS idx_series_points_week ON series_points (week_ending);
