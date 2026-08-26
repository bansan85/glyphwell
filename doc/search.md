# Step 3 — searching the corpus

The corpus is on disk (step 1) and titles resolve through the IMDb datasets (step 2).
This step catalogues the corpus, then scans it with a model run locally by Ollama,
driven by a YAML manifest.

## In one command

```bash
uv run glyphwell corpus index                                          # once
uv run glyphwell search run searches/example.yaml --dry-run            # check the manifest
uv run glyphwell search run searches/example.yaml --limit 20           # a small trial
uv run glyphwell search run searches/example.yaml                      # the real thing
```

`--dry-run` never touches the database and never calls Ollama: it picks one real file
matching the manifest's `select` filters from the already-downloaded archive, renders its
first chunk's prompt exactly as it would be sent, and prints it. Here is the actual output
against `searches/example.yaml`:

```
$ uv run glyphwell search run searches/example.yaml --dry-run
 Manifest        ski_pistes (ac210bd3e68c)
 File            OpenSubtitles/raw/en/1892/2/1960660614.xml
 Title           Le clown et ses chiens (1892)
 Model           huihui_ai/qwen3-abliterated:14b
 Options         {"temperature": 0, "num_ctx": 12288, "num_predict": 300}
 Output format   json
 Output schema   yes
 Ollama host     http://localhost:11434
 Ollama timeout  300.0s
+------------------------------- system prompt -------------------------------+
| You analyze excerpts of movie and TV show subtitles.                        |
| You answer only with a JSON object matching the requested schema.           |
| ...                                                                         |
+-------------------------------- user prompt --------------------------------+
| Title: Le clown et ses chiens (1892) (1892) — tt0000002                     |
| Excerpt: lines 1 to 55                                                      |
|                                                                              |
| [1] Born of Osiris                                                          |
| [2] - Follow The Signs (Official video)                                     |
| ...                                                                         |
+------------------------------- output.schema -------------------------------+
| { "type": "object", "properties": { "matched": {...}, ... }, ... }          |
+-------------------------------------------------------------------------- --+
```

The manifest's `select` filters matched the corpus's very first file, a music-video
subtitle — a reminder that `select`/the pre-filter are what keep an unrelated file from
costing a model call, not the manifest's prompt.

## Catalog vs. run database

Every command in this step reads two SQLite databases (see
[ADR-0018](../docs/adr/0018-split-catalog-and-run-databases.md)):

- The **catalog database** (`glyphwell.db` by default, `--catalog-database` /
  `GLYPHWELL_CATALOG_DATABASE`) — corpus and IMDb data, immutable once fetched, shared by
  every search.
- A **run database**, one per search — `runs`, `run_files`, `results`. `search run`
  creates it automatically (default: `<data-dir>/<manifest filename>.db`, e.g.
  `data/ski_pistes.db` for `searches/ski_pistes.yaml`), overridable with `--run-database`
  / `GLYPHWELL_RUN_DATABASE`. There is no separate init step for it.

`search resume`, `search status`, and `search export` take the **run database's file
path** as their argument, not a numeric id: that file, together with the manifest
snapshot it already carries (`runs.manifest_snapshot`), is the complete, durable handle
for a search — it works even if the original YAML has since changed or been deleted.

## Cataloguing the corpus (`corpus index`)

`corpus index` walks the archive's members via `corpus/layout.py::iter_corpus` and
populates `subtitle_files` (one row per member: language, IMDb id, OPUS version) — a pure
catalog from member names, reading only the central directory, never a member's content.
Members that don't match the expected layout are skipped and counted, not fatal to the
whole scan.

| Option | Effect |
|---|---|
| `--language`, `-l` | Restricts the scan to a single language. |

Rerun it after a new `corpus fetch` to catalogue an additional release or language;
already catalogued members are left alone, and a newly appeared subtitle file (a new
`opensubtitles_file_id`) is added as its own row (see ADR-0015).

## The manifest

A search is entirely described by one YAML file — see the fully commented
[`searches/example.yaml`](../searches/example.yaml) for the authoritative reference. Its
top-level sections:

| Section | Purpose |
|---|---|
| `model`, `options` | Ollama model tag and generation options (`temperature`, `num_ctx`, `num_predict`, ...), passed through as-is. |
| `select` | Which subtitles to analyze: language, IMDb title type, year range, an explicit id list (a series id expands to all of its episodes), and whether to keep every translation of a title or only its most complete one (`one_subtitle_per_title`, on by default — see *Deduplicating translations* below). Requires the IMDb datasets to be imported for anything beyond language. |
| `chunk` | `size`/`overlap`, in sentences — the unit of both a model call and the resume cursor. |
| `prefilter` | A local substring/regex check (`any`/`all`/`none`/`off`) that skips a chunk without calling the model at all. |
| `prompt` | `system`/`user` templates, with `{{ title }}`, `{{ year }}`, `{{ imdb_id }}`, `{{ first_id }}`, `{{ last_id }}`, `{{ chunk }}` placeholders. |
| `output` | `format` (`json`/`text`) and, for JSON, the `schema` requested from Ollama and re-checked against the response. |
| `match_when` | Which boolean field of the response counts as a match, or `null` for "every response counts". |

Editing any of this changes the manifest's SHA-256, which is its identity: a search
already in progress keeps its results, and an edited manifest starts a fresh run instead
of mixing answers produced by two different prompts (ADR-0004).

### Citing lines instead of quoting them

Wherever `output.schema` nests a field named `excerpt_ids` (an array of the cited
sentence ids — see `findings` in `searches/example.yaml`), glyphwell reconstructs a
sibling `excerpt` field itself from the chunk's own text (the cited lines, joined with
`\n`) instead of asking the model to reproduce them verbatim. Drop `excerpt` from that
object's `properties`/`required` entirely: citing ids it already has in context is a much
smaller generation than an exact quote, and reconstructing it locally guarantees the
quote is exact. An id that doesn't refer to a line of the chunk is rejected the same way
as any other schema violation (`ModelOutputError`).

### Choosing a model

Nothing about the manifest format requires an "aligned" instruct model — `options` and
`prompt` are free text passed straight through. If your prompts are the kind a
general-purpose model refuses, an uncensored or abliterated model (for example
`huihui_ai/qwen3-abliterated:14b`, the shipped example's default) is a legitimate choice,
but it comes with a trade-off worth knowing about: these models are not benchmarked for
strict JSON-schema compliance the way an official instruct release is. `output.schema` is
always re-validated after the call regardless of which model produced it (ADR-0013), so a
non-compliant response fails loudly (`ModelOutputError`, one file marked in error) instead
of silently corrupting a result — but a model with a high violation rate means a search
with a high per-file error rate. Prefer the smallest model that reliably follows your
schema; test with `--dry-run` and a `--limit` trial before committing to a full-corpus run.

## Deduplicating translations

OpenSubtitles frequently carries several independent translations for the same
`(imdb_id, language)` — a dozen or more is not unusual. `select.one_subtitle_per_title`
(on by default) keeps only the one most likely to carry the fullest legitimate dialogue
transcript, cutting redundant Ollama calls; set it to `false` to analyze every
translation. See [ADR-0020](../docs/adr/0020-deduplicate-subtitle-translations-by-size.md)
for the algorithm and the empirical thresholds behind it.

For a real run, the ranking is based on `subtitle_files.size_bytes`, populated by
`corpus index` — rerun it after upgrading to this version if your catalog predates it, or
every group ties and the pick degrades to an arbitrary (but still deterministic) one.

`--dry-run` applies the same algorithm, but computes sizes directly from the archive's own
central directory rather than the catalog — so it is never affected by a stale catalog,
but it does read the archive's whole metadata once before printing anything (still no
member content, no decompression), rather than stopping at the first match. Expect a
`--dry-run` invocation to take a few extra seconds on the full corpus when
`one_subtitle_per_title` is on (the default); set it to `false` for the previous,
near-instant first-match preview.

## Prefiltering

`prefilter.mode: "off"` (the shipped default) sends every chunk to the model — correct for
prototyping a prompt, but on a corpus of hundreds of thousands of files it is, by a wide
margin, the most expensive way to run a search. Once a prompt is settled, turning on
`any` with a handful of on-topic keywords is usually the single biggest lever on total
run time: a chunk is only skipped if the model would almost certainly have answered
`matched: false` anyway. Calibrate broadly — a prefilter that discards a chunk the model
would have kept is a silent false negative, not a faster search.

## Chunking and resume

Sentences stream past a fixed-stride sliding window (`chunk.size`, `chunk.overlap`); one
model call per window, one SQLite transaction per call, writing the result and the resume
cursor together (ADR-0005). Interrupting a run — `Ctrl-C`, a crash, a restart — never
costs more than the one chunk in flight when it happened; rerunning the same manifest
picks the queue back up exactly where it left off. A subtitle file that newly appears in
the corpus (a new `opensubtitles_file_id`) reaches an already-running search the same
way: rerun `corpus index`, then the manifest (ADR-0015).

## Concurrency

`Settings.concurrency` (`--concurrency`, or `GLYPHWELL_CONCURRENCY`) bounds how many
chunks are analyzed in parallel — across different files, never within one file's own
chunk sequence (ADR-0012). Raising it only helps up to what the Ollama server can actually
run in parallel: a GPU too small to fit the model already serializes the underlying
compute, so a bigger `concurrency` just adds queuing, not throughput. When the model
barely fits in VRAM, `--concurrency 1` is usually the right call; there is more headroom
to raise it once the model comfortably fits.

## Troubleshooting

**"model ... not available on ..."** — the manifest's `model` is not pulled locally.
`ollama pull <model>` before rerunning; `search run` checks this before scanning the
corpus, not partway through it.

**"no file in the corpus matches this manifest's select filters"** — either `corpus index`
has not run yet, or `select` (language, title type, year, ids) matches nothing. Loosen the
filters or run `corpus index` first.

**A model response is rejected (`ModelOutputError`)** — the response did not conform to
`output.schema` even though it was requested from Ollama (ADR-0013), or, for a schema
using the `excerpt_ids` convention (*Citing lines instead of quoting them* above), an id
did not refer to a line of the chunk. That file is marked in error and the rest of the
run continues; see *Choosing a model* above if this happens often.

## What's next

`search resume` and `search status` are operational (see *Catalog vs. run database*
above for how they locate a search). `search export` is wired into the CLI and
typechecks, but its body is not written yet — see the changelog's *Known limitations*.
