"""Real SQLite/Qdrant-local/parser tests; synthetic model transport, no services."""

from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from qdrant_client import QdrantClient

from demo.library_fixtures import text_pdf
from rag import api
from rag.config import Settings
from rag.core import RagEngine
from rag.folder_parser import DocumentError, chunks_from_pages, parse_pages
from rag.library import Library
from rag.source_roots import browse, inventory, open_beneath, relative_path


@pytest.fixture
def library(tmp_path):
    config = Settings(
        _env_file=None,
        api_key="synthetic-library-key",
        ingest_data_dir=str(tmp_path / "state"),
        ingest_source_roots={"shared": str(tmp_path / "sources")},
    )
    (tmp_path / "sources").mkdir()
    db = QdrantClient(":memory:")
    state = {"embed_failure": False, "digest": "frozen-test-model", "calls": 0}

    def transport(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={"models": [{"name": "nomic-embed-text:latest", "digest": state["digest"]}]},
            )
        if request.url.path == "/api/embed":
            state["calls"] += 1
            if state["embed_failure"]:
                return httpx.Response(503)
            return httpx.Response(200, json={"embeddings": [[1.0, 0.0, 0.0]]})
        return httpx.Response(
            200,
            json={
                "message": {"content": "The recovery code is ORION [1]."},
                "done": True,
                "done_reason": "stop",
                "eval_count": 12,
            },
        )

    def factory(c):
        return RagEngine(
            c,
            qdrant=db,
            model_client=lambda t: httpx.Client(transport=httpx.MockTransport(transport)),
        )

    lib = Library(config, factory, start_worker=False)
    lib.test_state = state
    yield lib
    lib.close()
    db.close()


def upload(lib, files, source="docs"):
    job = lib.create(
        "browser", source, [{"path": path, "size": len(data)} for path, data in files.items()]
    )
    for f in job["files"]:
        if f["status"] != "pending":
            continue
        lib.begin_upload(job["id"], f["id"])
        temp = lib.staging / (f["id"] + ".upload")
        temp.write_bytes(files[f["path"]])
        lib.finish_upload(f["id"], temp)
    lib.start_job(job["id"])
    return job["id"]


def finish(lib, job):
    for _ in range(20):
        lib.run_once()
        result = lib.get_job(job)
        if result["status"] in {"completed", "completed_with_errors", "cancelled"}:
            return result
    raise AssertionError("Job did not terminate")


def test_txt_csv_pdf_shared_parser():
    assert parse_pages(b"hello", "a.txt") == [("hello", None)]
    csv = parse_pages(b'asset,owner\nrouter,"Network, Ops"\n', "a.csv")[0][0]
    assert '"asset": "router"' in csv and '"owner": "Network, Ops"' in csv
    pages = parse_pages(text_pdf("First page fact", "Second page fact"), "a.pdf")
    chunks = chunks_from_pages(pages)
    assert [(c["page_number"], c["text"].strip()) for c in chunks] == [
        (1, "First page fact"),
        (2, "Second page fact"),
    ]


@pytest.mark.parametrize(
    "name,data,code",
    [
        ("a.exe", b"x", "unsupported"),
        ("a.txt", b"", "empty"),
        ("a.txt", b"\xff", "encoding"),
        ("a.txt", b"\x00abc", "binary_text"),
        ("a.csv", b"x,x\na,b", "csv_header"),
        ("a.csv", b"x,y\na", "csv_columns"),
        ("a.csv", b"x,y\n", "empty"),
        ("a.pdf", b"%PDF-not-valid", "malformed_pdf"),
    ],
)
def test_parser_errors(name, data, code):
    with pytest.raises(DocumentError) as e:
        parse_pages(data, name)
    assert e.value.code == code


def test_encrypted_scanned_and_limits():
    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    data = BytesIO()
    writer.write(data)
    with pytest.raises(DocumentError, match="scanned or empty"):
        parse_pages(data.getvalue(), "a.pdf")
    writer.encrypt("test-only")
    data = BytesIO()
    writer.write(data)
    with pytest.raises(DocumentError, match="Encrypted"):
        parse_pages(data.getvalue(), "a.pdf")
    with pytest.raises(DocumentError, match="page limit"):
        parse_pages(text_pdf("one", "two"), "a.pdf", max_pages=1)
    with pytest.raises(DocumentError, match="text exceeds"):
        parse_pages(b"abc", "a.txt", max_chars=2)


def test_nested_identity_skip_and_replacement(library):
    lib = library
    first = upload(
        lib, {"root/a/readme.txt": b"ORION recovery", "root/b/readme.txt": b"other fact"}
    )
    assert finish(lib, first)["counts"]["successful"] == 2
    docs = lib.documents()["documents"]
    assert len({d["id"] for d in docs}) == 2
    calls = lib.test_state["calls"]
    second = upload(lib, {"root/a/readme.txt": b"ORION recovery"})
    assert finish(lib, second)["counts"]["skipped"] == 1
    assert lib.test_state["calls"] == calls
    old = next(d for d in docs if d["path"].startswith("root/a"))
    third = upload(lib, {"root/a/readme.txt": b"Changed ORION recovery"})
    assert finish(lib, third)["counts"]["successful"] == 1
    current = lib.documents()["documents"]
    assert len(current) == 2  # absent from later selection is NOT deleted
    assert next(d for d in current if d["id"] == old["id"])["revision"] != old["revision"]
    engine = lib.get_engine(lib.config.model_copy(update={"qdrant_collection": old["collection"]}))
    assert engine.db.count(old["collection"]).count == 2
    assert lib.ask("Recovery?")["generation"]["status"] == "complete"


def test_root_namespace_and_model_change(library):
    lib = library
    finish(lib, upload(lib, {"same.txt": b"one"}, "source-a"))
    finish(lib, upload(lib, {"same.txt": b"two"}, "source-b"))
    assert len(lib.documents()["documents"]) == 2
    lib.test_state["digest"] = "new-model"
    with pytest.raises(DocumentError, match="No compatible"):
        lib.ask("question", 2)
    result = finish(lib, upload(lib, {"same.txt": b"one"}, "source-a"))
    assert result["counts"]["successful"] == 1
    assert len({d["collection"] for d in lib.documents()["documents"]}) == 2


@pytest.mark.parametrize("failure", ["parse", "embed", "index"])
def test_failed_replacement_preserves_searchable_revision(library, monkeypatch, failure):
    lib = library
    finish(lib, upload(lib, {"a.txt": b"original ORION"}))
    original = lib.documents()["documents"][0]
    job = upload(lib, {"a.txt": b"changed"})
    if failure == "parse":
        monkeypatch.setattr(lib, "parse", Mock(side_effect=DocumentError("bad", "Bad file")))
    elif failure == "embed":
        lib.test_state["embed_failure"] = True
    else:
        engine = lib.get_engine(
            lib.config.model_copy(update={"qdrant_collection": original["collection"]})
        )
        upsert = engine.db.upsert

        def partial(*args, **kwargs):
            upsert(*args, **kwargs)
            raise RuntimeError("simulated lost database acknowledgement")

        monkeypatch.setattr(engine.db, "upsert", partial)
    assert finish(lib, job)["counts"]["failed"] == 1
    assert lib.documents()["documents"][0]["revision"] == original["revision"]
    lib.test_state["embed_failure"] = False
    answer = lib.ask("question", 2)
    assert all(s["text"] == "original ORION" for s in answer["sources"])


def test_retry_failed_and_cancelled(library):
    lib = library
    lib.test_state["embed_failure"] = True
    job = upload(lib, {"a.txt": b"a", "b.txt": b"b"})
    assert finish(lib, job)["counts"]["failed"] == 2
    lib.test_state["embed_failure"] = False
    lib.retry(job)
    assert finish(lib, job)["counts"]["successful"] == 2
    cancelled = upload(lib, {"c.txt": b"c"})
    lib.cancel(cancelled)
    assert lib.get_job(cancelled)["status"] == "cancelled"
    lib.retry(cancelled)
    assert finish(lib, cancelled)["counts"]["successful"] == 1


def test_cancel_inflight_before_commit_keeps_previous(library, monkeypatch):
    lib = library
    finish(lib, upload(lib, {"a.txt": b"original"}))
    job = upload(lib, {"a.txt": b"replacement"})
    _, engine = lib.model_context()
    embed = engine.embed

    def cancel_during_embed(text):
        lib.cancel(job)
        return embed(text)

    monkeypatch.setattr(engine, "embed", cancel_during_embed)
    assert finish(lib, job)["counts"]["cancelled"] == 1
    assert (
        lib.documents()["documents"][0]["content_hash"]
        != __import__("hashlib").sha256(b"replacement").hexdigest()
    )


def test_restart_upload_and_processing_recovery(library):
    lib = library
    job = upload(lib, {"a.txt": b"ORION"})
    row = lib.get_job(job)["files"][0]
    lib.set_file(row["id"], "embedding")
    partial = lib.create("browser", "docs", [{"path": "b.txt", "size": 3}])
    lib.begin_upload(partial["id"], partial["files"][0]["id"])
    lib.close()
    resumed = Library(lib.config, lib.engine_factory, start_worker=False)
    try:
        assert resumed.get_job(job)["files"][0]["code"] == "interrupted"
        assert resumed.get_job(partial["id"])["files"][0]["code"] == "upload_interrupted"
        resumed.retry(job)
        assert finish(resumed, job)["counts"]["successful"] == 1
        resumed.retry(job)
        assert finish(resumed, job)["counts"]["successful"] == 1
        assert len(resumed.documents()["documents"]) == 1
    finally:
        resumed.close()


def test_restart_after_commit_recognizes_visibility_transaction(library):
    lib = library
    job = upload(lib, {"a.txt": b"ORION"})
    finish(lib, job)
    row = lib.get_job(job)["files"][0]
    lib.set_file(row["id"], "indexing")  # crash marker around completed visibility transaction
    lib.close()
    resumed = Library(lib.config, lib.engine_factory, start_worker=False)
    try:
        assert resumed.get_job(job)["files"][0]["status"] == "completed"
    finally:
        resumed.close()


def test_missing_vectors_are_not_skipped(library):
    lib = library
    finish(lib, upload(lib, {"a.txt": b"x"}))
    doc = lib.documents()["documents"][0]
    _, engine = lib.model_context()
    engine.db.delete_collection(doc["collection"])
    assert finish(lib, upload(lib, {"a.txt": b"x"}))["counts"]["successful"] == 1


@pytest.mark.parametrize(
    "path", ["../secret", "/etc/passwd", "a/../../b", "a//b", "a/./b", "a\\b", "a\x00b"]
)
def test_paths_rejected(path):
    with pytest.raises(DocumentError):
        relative_path(path)


def test_server_symlinks_special_files_and_nested(library, tmp_path):
    root = Path(library.source_root("shared"))
    (root / "nested").mkdir()
    (root / "nested/a.txt").write_text("hello")
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    (root / "escape.txt").symlink_to(outside)
    (root / "alias").symlink_to(root / "nested", target_is_directory=True)
    import os

    os.mkfifo(root / "pipe")
    files = inventory(str(root), "", 20)
    assert sum(f["excluded"] for f in files) == 3
    for path in ["escape.txt", "alias/a.txt", "pipe"]:
        with pytest.raises(DocumentError), open_beneath(str(root), path):
            pass
    with pytest.raises(DocumentError):
        browse(str(root), "../", 20)
    job = library.create("server", "shared", folder="nested")
    assert finish(library, job["id"])["counts"]["successful"] == 1
    assert library.documents()["documents"][0]["path"] == "nested/a.txt"


def test_limits_and_exclusions(library):
    library.config.ingest_max_file_bytes = 4
    p = library.preview(
        "browser", "demo", [{"path": "x.exe", "size": 1}, {"path": "x.txt", "size": 5}]
    )
    assert p["eligible"] == 0
    library.config.ingest_max_batch_bytes = 3
    with pytest.raises(DocumentError, match="batch"):
        library.preview("browser", "demo", [{"path": "x.txt", "size": 4}])
    library.config.ingest_max_files = 1
    with pytest.raises(DocumentError, match="file-count"):
        library.preview(
            "browser", "demo", [{"path": "a.txt", "size": 1}, {"path": "b.txt", "size": 1}]
        )


def test_http_auth_streaming_recovery_and_static_ui(library, monkeypatch):
    monkeypatch.setattr(api, "settings", lambda: library.config)
    monkeypatch.setattr(api, "library", lambda: library)
    # install() captured the library function; set state so the original function returns this test instance.
    api.app.state.library = library
    with TestClient(api.app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/ui/app.js").status_code == 200
        assert client.get("/library/jobs").status_code == 401
        headers = {"x-api-key": library.config.api_key}
        job = client.post(
            "/library/jobs",
            headers=headers,
            json={
                "mode": "browser",
                "source": "demo",
                "files": [{"path": "folder/test.txt", "size": 3}],
            },
        ).json()
        file = job["files"][0]
        endpoint = f"/library/jobs/{job['id']}/files/{file['id']}"
        assert client.put(endpoint, headers=headers, content=b"long").status_code == 400
        assert (
            client.get("/library/jobs/" + job["id"], headers=headers).json()["files"][0]["status"]
            == "failed"
        )
        client.post(f"/library/jobs/{job['id']}/retry", headers=headers)
        assert (
            client.put(endpoint, headers=headers, content=b"abc").json()["ready_to_search"] is False
        )
        assert client.post(f"/library/jobs/{job['id']}/start", headers=headers).status_code == 200
        assert finish(library, job["id"])["counts"]["successful"] == 1
        # New request is a refresh: persisted status, no duplicate ingestion.
        assert (
            client.get("/library/jobs/" + job["id"], headers=headers).json()["counts"]["successful"]
            == 1
        )
    api.app.state.library = None
