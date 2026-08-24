-- Schéma glyphwell — version 1 (PRAGMA user_version).
--
-- Volontairement SANS FTS5 : le texte des sous-titres n'est ni copié ni indexé ici.
-- L'archive zip du corpus OPUS reste la seule source du texte, lue à la volée sans
-- jamais être décompressée ; cette base ne contient que le catalogue et l'état de
-- progression des recherches.

-- ---------------------------------------------------------------------------
-- Titres (source primaire : datasets IMDb officiels)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS titles (
    imdb_id          TEXT PRIMARY KEY,          -- forme canonique 'tt0133093'
    title_type       TEXT,                      -- movie | tvEpisode | tvSeries | short | ...
    primary_title    TEXT,
    original_title   TEXT,
    start_year       INTEGER,
    end_year         INTEGER,
    is_adult         INTEGER NOT NULL DEFAULT 0,
    runtime_minutes  INTEGER,
    -- Renseignés depuis title.episode.tsv, pour les épisodes uniquement.
    parent_imdb_id   TEXT,
    season_number    INTEGER,
    episode_number   INTEGER,
    source           TEXT NOT NULL DEFAULT 'imdb_datasets',
    imported_at      TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_titles_parent ON titles (parent_imdb_id)
    WHERE parent_imdb_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_titles_type_year ON titles (title_type, start_year);

-- ---------------------------------------------------------------------------
-- Fichiers de sous-titres du corpus
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subtitle_files (
    file_id                INTEGER PRIMARY KEY,
    opus_version           TEXT NOT NULL,       -- 'v2024'
    language               TEXT NOT NULL,       -- 'en'
    imdb_id                TEXT NOT NULL,
    -- Identifiant du sous-titre sur opensubtitles.org, porté par le nom de fichier : il
    -- permet de remonter à la fiche d'origine.
    opensubtitles_file_id  TEXT NOT NULL,
    -- Nom du membre dans l'archive zip, séparateur '/', préfixe inclus :
    -- 'OpenSubtitles/raw/en/1999/0133093/3660124.xml'. L'archive n'étant jamais
    -- décompressée, c'est la seule clé permettant d'ouvrir le fichier.
    rel_path               TEXT NOT NULL,
    year                   INTEGER,             -- année portée par l'arborescence OPUS
    sha256                 TEXT,                -- NULL tant que le fichier n'a pas été haché
    size_bytes             INTEGER,
    sentence_count         INTEGER,             -- NULL tant que le fichier n'a pas été lu
    discovered_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at             TEXT NOT NULL DEFAULT (datetime('now')),

    -- Un même sous-titre peut exister dans plusieurs releases OPUS : la version fait
    -- partie de l'identité du fichier.
    UNIQUE (opus_version, language, rel_path)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_subtitle_files_imdb ON subtitle_files (imdb_id);
CREATE INDEX IF NOT EXISTS idx_subtitle_files_scan
    ON subtitle_files (opus_version, language, rel_path);

-- ---------------------------------------------------------------------------
-- Recherches
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runs (
    run_id            INTEGER PRIMARY KEY,
    manifest_path     TEXT NOT NULL,
    -- SHA-256 du YAML. Identifie la recherche : modifier le manifeste crée un nouveau run
    -- au lieu de mélanger des résultats produits par deux prompts différents.
    manifest_hash     TEXT NOT NULL,
    -- Copie intégrale du YAML au lancement : un run reste interprétable même si le fichier
    -- source est modifié ou supprimé ensuite.
    manifest_snapshot TEXT NOT NULL,
    model             TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending|running|paused|done|failed
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at       TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_runs_hash ON runs (manifest_hash, status);

-- ---------------------------------------------------------------------------
-- File de travail et POINT DE REPRISE
-- ---------------------------------------------------------------------------
-- Une ligne par (recherche, fichier). C'est ici que vit la capacité de reprendre au
-- milieu d'un sous-titre.
CREATE TABLE IF NOT EXISTS run_files (
    run_id               INTEGER NOT NULL REFERENCES runs (run_id) ON DELETE CASCADE,
    file_id              INTEGER NOT NULL
                             REFERENCES subtitle_files (file_id) ON DELETE CASCADE,
    -- pending | in_progress | done | skipped | error
    status               TEXT NOT NULL DEFAULT 'pending',

    -- sha256 du fichier au moment de sa mise en file. Sert à détecter qu'une version plus
    -- récente du sous-titre est apparue depuis (cf. corpus refresh).
    file_sha256          TEXT,

    -- Curseur de reprise. `last_sentence_index` fait autorité : position, dans le flux de
    -- phrases du fichier, de la dernière phrase couverte par une fenêtre dont le résultat
    -- est committé. `last_sentence_id` est l'attribut <s id> correspondant, conservé pour
    -- la traçabilité (opaque, pas forcément numérique).
    last_sentence_index  INTEGER,
    last_sentence_id     TEXT,
    chunks_done          INTEGER NOT NULL DEFAULT 0,

    error                TEXT,
    started_at           TEXT,
    updated_at           TEXT NOT NULL DEFAULT (datetime('now')),

    PRIMARY KEY (run_id, file_id)
) STRICT;

-- La reprise sélectionne les fichiers non terminés dans un ordre déterministe : le tri se
-- fait sur subtitle_files.rel_path (cf. glyphwell.search.planner).
CREATE INDEX IF NOT EXISTS idx_run_files_pending ON run_files (run_id, status);
CREATE INDEX IF NOT EXISTS idx_run_files_file ON run_files (file_id);

-- ---------------------------------------------------------------------------
-- Résultats
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS results (
    result_id            INTEGER PRIMARY KEY,
    run_id               INTEGER NOT NULL REFERENCES runs (run_id) ON DELETE CASCADE,
    file_id              INTEGER NOT NULL
                             REFERENCES subtitle_files (file_id) ON DELETE CASCADE,

    chunk_index          INTEGER NOT NULL,      -- position de la fenêtre dans le fichier
    first_sentence_index INTEGER NOT NULL,
    last_sentence_index  INTEGER NOT NULL,
    first_sentence_id    TEXT,
    last_sentence_id     TEXT,

    matched              INTEGER NOT NULL DEFAULT 0,
    payload              TEXT,                  -- réponse JSON validée contre output.schema
    model                TEXT NOT NULL,
    latency_ms           INTEGER,
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),

    -- Idempotence de la reprise : rejouer une fenêtre déjà traitée ne peut pas produire de
    -- doublon (les écritures utilisent INSERT OR IGNORE). Suppose un découpage
    -- déterministe, garanti par l'ordre de parcours fixe du planner.
    UNIQUE (run_id, file_id, chunk_index)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_results_matches ON results (run_id, matched);
CREATE INDEX IF NOT EXISTS idx_results_file ON results (run_id, file_id);

-- ---------------------------------------------------------------------------
-- Traçabilité des acquisitions
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
    -- Date de la vérification de l'archive (ouverture du zip, comptage des membres).
    -- L'archive n'est jamais décompressée : il n'y a pas d'étape d'extraction.
    verified_at   TEXT,
    UNIQUE (opus_corpus, opus_version, language)
) STRICT;

CREATE TABLE IF NOT EXISTS imports (
    import_id   INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,                 -- imdb_basics | imdb_episode
    file_name   TEXT NOT NULL,
    released_at TEXT,                          -- date de publication du dataset, si connue
    row_count   INTEGER,
    imported_at TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_imports_source ON imports (source, imported_at);
