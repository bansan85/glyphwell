"""Acquisition, parcours et découpage du corpus de sous-titres."""

from glyphwell.corpus.chunker import Chunk, chunk_count, iter_chunks
from glyphwell.corpus.hashing import sha256_file
from glyphwell.corpus.layout import CorpusEntry, iter_corpus, normalize_imdb_id, parse_entry
from glyphwell.corpus.reader import Sentence, count_sentences, iter_sentences

__all__ = [
    "Chunk",
    "CorpusEntry",
    "Sentence",
    "chunk_count",
    "count_sentences",
    "iter_chunks",
    "iter_corpus",
    "iter_sentences",
    "normalize_imdb_id",
    "parse_entry",
    "sha256_file",
]
