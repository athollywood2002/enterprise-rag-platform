import pytest
from test_library import finish, upload
from test_library import library as library_fixture

from rag.folder_parser import COMPATIBLE_PARSERS, DocumentError

library = library_fixture


@pytest.mark.parametrize("historical", COMPATIBLE_PARSERS[:-1])
def test_correction_reindexes_same_bytes_without_losing_previous_revision(
    library, monkeypatch, historical
):
    lib = library
    context = lib.model_context
    monkeypatch.setattr(lib, "model_context", lambda *args: context(historical))
    files = {"retained.txt": b"Retained evidence"}
    assert finish(lib, upload(lib, files))["counts"]["successful"] == 1
    before = lib.documents()["documents"][0]
    monkeypatch.setattr(lib, "model_context", context)
    assert lib.ask("evidence")["sources"][0]["text"] == "Retained evidence"
    parse = lib.parse

    def fail_parse(*args):
        raise DocumentError("encoding", "Fixture: replacement parsing fails")

    monkeypatch.setattr(lib, "parse", fail_parse)
    assert finish(lib, upload(lib, files))["counts"]["failed"] == 1
    assert lib.documents()["documents"][0]["revision"] == before["revision"]
    assert lib.ask("evidence")["sources"][0]["text"] == "Retained evidence"
    monkeypatch.setattr(lib, "parse", parse)
    assert finish(lib, upload(lib, files))["counts"]["successful"] == 1
    after = lib.documents()["documents"][0]
    assert after["revision"] != before["revision"]
    assert after["collection"] != before["collection"]
    assert finish(lib, upload(lib, files))["counts"]["skipped"] == 1
