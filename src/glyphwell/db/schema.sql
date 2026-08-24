-- glyphwell schema — version 1 (PRAGMA user_version).
--
-- Deliberately WITHOUT FTS5: subtitle text is neither copied nor indexed here.
-- The OPUS corpus zip archive remains the sole source of the text, read on the fly and
-- never decompressed; this database only holds the catalog and the search progress
-- state.

-- ---------------------------------------------------------------------------
-- Titles (primary source: official IMDb datasets)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS titles (
    imdb_id          TEXT PRIMARY KEY,          -- canonical form 'tt0133093'
    title_type       TEXT,                      -- movie | tvEpisode | tvSeries | short | ...
    primary_title    TEXT,
    original_title   TEXT,
    start_year       INTEGER,
    end_year         INTEGER,
    is_adult         INTEGER NOT NULL DEFAULT 0,
    runtime_minutes  INTEGER,
    -- Filled in from title.episode.tsv, episodes only.
    parent_imdb_id   TEXT,
    season_number    INTEGER,
    episode_number   INTEGER,
    source           TEXT NOT NULL DEFAULT 'imdb_datasets',
    imported_at      TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

-- Deliberately no secondary index here (e.g. on parent_imdb_id or (title_type,
-- start_year)): the only lookup direction this project needs is imdb_id -> title,
-- already served by the primary key. A secondary index's keys don't correlate with
-- title.basics.tsv's insertion order, so maintaining one during the bulk import of
-- millions of rows roughly halves throughput (measured) for a query pattern nothing
-- here performs. See db/migrations.py version 2.

-- ---------------------------------------------------------------------------
-- Corpus subtitle files
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subtitle_files (
    file_id                INTEGER PRIMARY KEY,
    opus_version           TEXT NOT NULL,       -- 'v2024'
    language               TEXT NOT NULL,       -- 'en'
    imdb_id                TEXT NOT NULL,
    -- Identifier of the subtitle on opensubtitles.org, carried by the file name: it
    -- allows tracing back to the original listing.
    opensubtitles_file_id  TEXT NOT NULL,
    -- Member name within the zip archive, '/' separator, prefix included:
    -- 'OpenSubtitles/raw/en/1999/0133093/3660124.xml'. Since the archive is never
    -- decompressed, this is the only key that allows opening the file.
    rel_path               TEXT NOT NULL,
    year                   INTEGER,             -- year carried by the OPUS directory tree
    sha256                 TEXT,                -- NULL until the file has been hashed
    size_bytes             INTEGER,
    sentence_count         INTEGER,             -- NULL until the file has been read
    discovered_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at             TEXT NOT NULL DEFAULT (datetime('now')),

    -- The same subtitle can exist in several OPUS releases: the version is part of the
    -- file's identity.
    UNIQUE (opus_version, language, rel_path)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_subtitle_files_imdb ON subtitle_files (imdb_id);
CREATE INDEX IF NOT EXISTS idx_subtitle_files_scan
    ON subtitle_files (opus_version, language, rel_path);

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
    -- file is later modified or deleted.
    manifest_snapshot TEXT NOT NULL,
    model             TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending|running|paused|done|failed
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
    file_id              INTEGER NOT NULL
                             REFERENCES subtitle_files (file_id) ON DELETE CASCADE,
    -- pending | in_progress | done | skipped | error
    status               TEXT NOT NULL DEFAULT 'pending',

    -- sha256 of the file at the time it was queued. Used to detect that a newer version
    -- of the subtitle has since appeared (see corpus refresh).
    file_sha256          TEXT,

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

-- Resuming selects unfinished files in a deterministic order: the sort is done on
-- subtitle_files.rel_path (see glyphwell.search.planner).
CREATE INDEX IF NOT EXISTS idx_run_files_pending ON run_files (run_id, status);
CREATE INDEX IF NOT EXISTS idx_run_files_file ON run_files (file_id);

-- ---------------------------------------------------------------------------
-- Results
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS results (
    result_id            INTEGER PRIMARY KEY,
    run_id               INTEGER NOT NULL REFERENCES runs (run_id) ON DELETE CASCADE,
    file_id              INTEGER NOT NULL
                             REFERENCES subtitle_files (file_id) ON DELETE CASCADE,

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

-- ---------------------------------------------------------------------------
-- Acquisition traceability
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS corpus_downloads (
    download_id   INTEGER PRIMARY KEY,
    opus_corpus   TEXT NOT NULL,
    opus_version  TEXT NOT NULL,
    language      TEXT NOT NULL,
    url           TEXT,
    archive_path  TEXT,
    sha256        TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending|downloaded|failed
    downloaded_at TEXT,
    -- Date the archive was verified (zip opened, members counted).
    -- The archive is never decompressed: there is no extraction step.
    verified_at   TEXT,
    UNIQUE (opus_corpus, opus_version, language)
) STRICT;

CREATE TABLE IF NOT EXISTS imports (
    import_id   INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,                 -- imdb_basics | imdb_episode
    file_name   TEXT NOT NULL,
    released_at TEXT,                          -- dataset release date, if known
    row_count   INTEGER,
    imported_at TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_imports_source ON imports (source, imported_at);
