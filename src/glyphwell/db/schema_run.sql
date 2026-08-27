-- glyphwell run schema — version 1 (PRAGMA user_version).
--
-- Mutable state of one search: its life cycle, its work queue and resume cursors, and
-- its results. One database per search (see schema_catalog.sql for the immutable
-- corpus/IMDb catalog it reads from, in a separate database file).

-- ---------------------------------------------------------------------------
-- Searches
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runs (
    run_id            INTEGER PRIMARY KEY,
    manifest_path     TEXT NOT NULL,
    -- SHA-256 of the YAML. Identifies the search: modifying the manifest creates a new
    -- run instead of mixing results produced by two different prompts.
    manifest_hash     TEXT NOT NULL,
    -- Full copy of the YAML at launch time: a run stays interpretable even if the source
    -- file is later modified or deleted, and is the durable handle `search resume` /
    -- `search status` / `search export` use — no `run_id` is exposed on the CLI.
    manifest_snapshot TEXT NOT NULL,
    model             TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending|running|paused|done|failed
    -- Locked response-to-input token ratio (ADR-0022), NULL until enough of the run's own
    -- completions have been observed to calibrate one (see glyphwell.search.calibration).
    -- Written once, never updated afterward: chunk sizing must stay deterministic across
    -- a resume (CLAUDE.md §7).
    calibrated_response_ratio REAL,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at       TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_runs_hash ON runs (manifest_hash, status);

-- ---------------------------------------------------------------------------
-- Work queue and RESUME POINT
-- ---------------------------------------------------------------------------
-- One row per (search, file). This is where the ability to resume in the middle of a
-- subtitle lives.
CREATE TABLE IF NOT EXISTS run_files (
    run_id               INTEGER NOT NULL REFERENCES runs (run_id) ON DELETE CASCADE,
    -- Surrogate key of a `subtitle_files` row in the *catalog* database. Not FK-enforced:
    -- SQLite cannot enforce a foreign key across two separate database files. See
    -- ADR-0018.
    file_id              INTEGER NOT NULL,
    -- Copy of the catalog's `subtitle_files.rel_path` at enqueue time, so the work
    -- queue's deterministic order (`ORDER BY rel_path`) is computable from this database
    -- alone, without a cross-database join. Safe to duplicate: immutable for a fixed
    -- `file_id` (a changed subtitle arrives under a new file_id, never mutates an
    -- existing row — see ADR-0015).
    rel_path             TEXT NOT NULL,
    -- pending | in_progress | done | skipped | error
    status               TEXT NOT NULL DEFAULT 'pending',

    -- Resume cursor. `last_sentence_index` is authoritative: position, in the file's
    -- sentence stream, of the last sentence covered by a chunk whose result has been
    -- committed. `last_sentence_id` is the corresponding <s id> attribute, kept for
    -- traceability (opaque, not necessarily numeric).
    last_sentence_index  INTEGER,
    last_sentence_id     TEXT,
    chunks_done          INTEGER NOT NULL DEFAULT 0,

    error                TEXT,
    started_at           TEXT,
    updated_at           TEXT NOT NULL DEFAULT (datetime('now')),

    PRIMARY KEY (run_id, file_id)
) STRICT;

-- Resuming selects unfinished files in a deterministic order: ORDER BY rel_path (see
-- glyphwell.search.planner).
CREATE INDEX IF NOT EXISTS idx_run_files_pending ON run_files (run_id, status, rel_path);

-- ---------------------------------------------------------------------------
-- Results
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS results (
    result_id            INTEGER PRIMARY KEY,
    run_id               INTEGER NOT NULL REFERENCES runs (run_id) ON DELETE CASCADE,
    -- Surrogate key of a `subtitle_files` row in the catalog database. Same soft
    -- reference as `run_files.file_id` above — see ADR-0018.
    file_id              INTEGER NOT NULL,

    chunk_index          INTEGER NOT NULL,      -- position of the chunk within the file
    first_sentence_index INTEGER NOT NULL,
    last_sentence_index  INTEGER NOT NULL,
    first_sentence_id    TEXT,
    last_sentence_id     TEXT,

    matched              INTEGER NOT NULL DEFAULT 0,
    payload              TEXT,                  -- JSON response validated against output.schema
    model                TEXT NOT NULL,
    latency_ms           INTEGER,
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),

    -- Idempotence of resuming: replaying an already-processed chunk cannot produce a
    -- duplicate (writes use INSERT OR IGNORE). This assumes deterministic chunking,
    -- guaranteed by the planner's fixed traversal order.
    UNIQUE (run_id, file_id, chunk_index)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_results_matches ON results (run_id, matched);
CREATE INDEX IF NOT EXISTS idx_results_file ON results (run_id, file_id);
