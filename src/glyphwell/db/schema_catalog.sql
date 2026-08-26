-- glyphwell catalog schema — version 1 (PRAGMA user_version).
--
-- Immutable data fetched from the internet: OPUS corpus catalog and IMDb titles. Nothing
-- here is written by a search — see schema_run.sql for the per-search, mutable schema.
--
-- Deliberately WITHOUT FTS5: subtitle text is neither copied nor indexed here.
-- The OPUS corpus zip archive remains the sole source of the text, read on the fly and
-- never decompressed; this database only holds the catalog.

-- ---------------------------------------------------------------------------
-- Titles (primary source: official IMDb datasets)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS titles (
    -- Numeric part of the canonical 'tt#######' identifier, `tt` stripped. Conversion is
    -- centralized in `glyphwell.corpus.layout` (`imdb_id_to_int`/`imdb_id_from_int`):
    -- every other layer of the code still deals exclusively in the canonical string form.
    imdb_id          INTEGER PRIMARY KEY,
    title_type       TEXT,                      -- movie | tvEpisode | tvSeries | short | ...
    primary_title    TEXT,
    original_title   TEXT,
    start_year       INTEGER,
    end_year         INTEGER,
    -- Filled in from title.episode.tsv, episodes only. Same numeric form as imdb_id.
    parent_imdb_id   INTEGER,
    season_number    INTEGER,
    episode_number   INTEGER
) STRICT;

-- Deliberately no secondary index here (e.g. on parent_imdb_id or (title_type,
-- start_year)): the only lookup direction this project needs is imdb_id -> title,
-- already served by the primary key. A secondary index's keys don't correlate with
-- title.basics.tsv's insertion order, so maintaining one during the bulk import of
-- millions of rows roughly halves throughput (measured) for a query pattern nothing
-- here performs. See ADR-0011.

-- ---------------------------------------------------------------------------
-- Corpus subtitle files
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subtitle_files (
    file_id                INTEGER PRIMARY KEY,
    opus_version           TEXT NOT NULL,       -- 'v2024'
    language               TEXT NOT NULL,       -- 'en'
    imdb_id                INTEGER NOT NULL,
    -- Identifier of the subtitle on opensubtitles.org, carried by the file name: it
    -- allows tracing back to the original listing.
    opensubtitles_file_id  INTEGER NOT NULL,
    -- Member name within the zip archive, '/' separator, prefix included:
    -- 'OpenSubtitles/raw/en/1999/0133093/3660124.xml'. Since the archive is never
    -- decompressed, this is the only key that allows opening the file.
    rel_path               TEXT NOT NULL,
    year                   INTEGER,             -- year carried by the OPUS directory tree
    size_bytes             INTEGER,
    sentence_count         INTEGER,             -- NULL until the file has been read

    -- The same subtitle can exist in several OPUS releases: the version is part of the
    -- file's identity.
    UNIQUE (opus_version, language, rel_path)
) STRICT;

-- Deliberately no per-file checksum here: a changed subtitle arrives under a new
-- opensubtitles_file_id (a new row), it never mutates an existing one, and
-- opus_version is already part of this table's identity. See ADR-0015, which
-- supersedes ADR-0006.
--
-- Deliberately no discovered_at/updated_at bookkeeping columns: nothing in the code
-- ever reads them back, and `corpus_downloads`/`corpus fetch` already give traceability
-- of when a release was acquired.

CREATE INDEX IF NOT EXISTS idx_subtitle_files_imdb ON subtitle_files (imdb_id);
CREATE INDEX IF NOT EXISTS idx_subtitle_files_scan
    ON subtitle_files (opus_version, language, rel_path);

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
    -- TEXT storage (STRICT tables reject a `DATETIME` column type): ISO-8601-ish
    -- 'YYYY-MM-DD HH:MM:SS' as produced by `datetime('now')`, read back as a real
    -- `datetime.datetime` by `glyphwell.db.repositories` (`datetime.fromisoformat`).
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
    -- Same TEXT-storage/typed-read pattern as corpus_downloads above.
    imported_at TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_imports_source ON imports (source, imported_at);
