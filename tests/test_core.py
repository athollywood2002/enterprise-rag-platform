import pytest
from rag.core import chunk_text


def test_empty_document():
    assert chunk_text(" \n ", "empty") == []


def test_chunks_overlap():
    parts = chunk_text("abcdefghij", "sample", size=6, overlap=2)
    assert [p.text for p in parts] == ["abcdef", "efghij"]
    assert [p.number for p in parts] == [0, 1]


def test_bad_chunk_config():
    with pytest.raises(ValueError):
        chunk_text("hello", "test", size=5, overlap=5)
