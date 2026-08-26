"""Resume cursor: checkpoint reading, position arithmetic, and committing chunks."""

import sqlite3

import pytest

from glyphwell.corpus.chunker import Chunk, iter_chunks
from glyphwell.corpus.reader import Sentence
from glyphwell.db.repositories import ResultsRepository, RunFilesRepository, RunsRepository
from glyphwell.search.checkpoint import Checkpoint, commit_chunk, load_checkpoint, resume_position


def _sentences(n: int) -> list[Sentence]:
    return [Sentence(index=i, id=str(i), text=f"s{i}") for i in range(n)]


def test_resume_position_of_a_fresh_file_starts_at_zero() -> None:
    assert resume_position(None, size=5, overlap=2) == (0, 0)


def test_resume_position_of_a_not_yet_started_checkpoint_starts_at_zero() -> None:
    checkpoint = Checkpoint(
        run_id=1, file_id=1, last_sentence_index=None, last_sentence_id=None, chunks_done=0
    )
    assert resume_position(checkpoint, size=5, overlap=2) == (0, 0)


@pytest.mark.parametrize(
    ("n", "size", "overlap"),
    [(20, 5, 2), (20, 5, 0), (17, 4, 1), (18, 9, 0), (30, 8, 3)],
)
def test_resume_position_reproduces_the_next_chunk_of_a_fresh_pass(
    n: int, size: int, overlap: int
) -> None:
    """The direct cross-check between `iter_chunks`'s windowing and this arithmetic."""
    fresh = list(iter_chunks(_sentences(n), size=size, overlap=overlap))
    assert len(fresh) >= 2, "need at least two chunks for there to be a 'next' one"

    for committed_index in range(len(fresh) - 1):
        committed = fresh[committed_index]
        checkpoint = Checkpoint(
            run_id=1,
            file_id=1,
            last_sentence_index=committed.last.index,
            last_sentence_id=committed.last.id,
            chunks_done=committed_index + 1,
        )
        start_index, start_chunk_index = resume_position(checkpoint, size=size, overlap=overlap)

        resumed = next(
            iter_chunks(
                _sentences(n)[start_index:],
                size=size,
                overlap=overlap,
                start_chunk_index=start_chunk_index,
            )
        )
        expected = fresh[committed_index + 1]
        assert resumed.index == expected.index
        assert [s.index for s in resumed.sentences] == [s.index for s in expected.sentences]


_REL_PATH = "OpenSubtitles/raw/en/1999/0133093/3660124.xml"


def _seed(conn: sqlite3.Connection) -> tuple[int, int]:
    run_id = RunsRepository(conn).create(
        manifest_path="m.yaml", manifest_hash="h", manifest_snapshot="name: a\n", model="m"
    )
    file_id = 1
    RunFilesRepository(conn).enqueue_many(run_id, [(file_id, _REL_PATH)])
    return run_id, file_id


def test_load_checkpoint_returns_none_when_file_not_in_queue(run_db: sqlite3.Connection) -> None:
    assert load_checkpoint(run_db, run_id=1, file_id=1) is None


def test_load_checkpoint_reflects_a_fresh_queue_entry(run_db: sqlite3.Connection) -> None:
    run_id, file_id = _seed(run_db)
    checkpoint = load_checkpoint(run_db, run_id=run_id, file_id=file_id)
    assert checkpoint is not None
    assert checkpoint.started is False


def _chunk(index: int, first: int, last: int) -> Chunk:
    return Chunk(
        index=index,
        sentences=tuple(Sentence(index=i, id=str(i), text=f"s{i}") for i in range(first, last + 1)),
    )


def test_commit_chunk_writes_result_and_advances_cursor(run_db: sqlite3.Connection) -> None:
    run_id, file_id = _seed(run_db)
    chunk = _chunk(0, 0, 1)

    inserted = commit_chunk(
        run_db,
        run_id=run_id,
        file_id=file_id,
        chunk=chunk,
        matched=True,
        payload={"matched": True},
        model="m",
        latency_ms=42,
    )

    assert inserted is True
    row = RunFilesRepository(run_db).get(run_id, file_id)
    assert row is not None
    assert row.last_sentence_index == 1
    assert row.last_sentence_id == "1"
    assert row.chunks_done == 1
    assert ResultsRepository(run_db).count(run_id) == 1


def test_commit_chunk_replay_is_idempotent(run_db: sqlite3.Connection) -> None:
    run_id, file_id = _seed(run_db)
    chunk = _chunk(0, 0, 1)

    first = commit_chunk(
        run_db,
        run_id=run_id,
        file_id=file_id,
        chunk=chunk,
        matched=True,
        payload=None,
        model="m",
        latency_ms=1,
    )
    second = commit_chunk(
        run_db,
        run_id=run_id,
        file_id=file_id,
        chunk=chunk,
        matched=True,
        payload=None,
        model="m",
        latency_ms=1,
    )

    assert first is True
    assert second is False
    assert ResultsRepository(run_db).count(run_id) == 1
    row = RunFilesRepository(run_db).get(run_id, file_id)
    assert row is not None
    assert row.chunks_done == 1
