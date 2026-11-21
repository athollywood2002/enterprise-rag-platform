"""Real SQLite and Qdrant local fixtures; mocked tags, selection observer only.

15 revisions/138 points here are synthetic, NOT the unavailable saved snapshot.
No embedding, chat, API server or model server is started or contacted.
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from copy import deepcopy
from unittest.mock import Mock

import httpx
import pytest
from qdrant_client import QdrantClient, models

from rag.config import Settings
from rag.core import RagEngine
from rag.folder_parser import PARSER_VERSION, DocumentError
from rag.index_compatibility import (
    checksum,
    encode,
    fingerprint,
    legacy_identity,
    register_legacy_context,
)
from rag.library import Library


def uid(value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "offline-compatibility-fixture:" + value))


class SelectionObserver(RagEngine):
    def ask(self, question, top_k=5, *, query_filter=None, collection_names=None):
        # Stop at the real Library.ask dispatch boundary. Exercise its exact
        # filter against real Qdrant local storage without embedding a question.
        points = []
        for name in collection_names:
            page, cursor = self.db.scroll(
                name, scroll_filter=query_filter, limit=1000, with_payload=True, with_vectors=False
            )
            assert cursor is None
            points.extend(page)
        return {"points": points, "filter": query_filter, "collections": collection_names}


@pytest.fixture
def saved(tmp_path, monkeypatch):
    forbidden = Mock(side_effect=AssertionError("Embedding or generation was invoked"))
    monkeypatch.setattr(RagEngine, "embed", forbidden)
    monkeypatch.setattr(RagEngine, "ask", forbidden)
    qdrant = QdrantClient(":memory:")
    state = {"digest": "synthetic-pinned-embedding-bytes", "db": qdrant, "endpoints": []}
    settings = Settings(
        _env_file=None,
        api_key="offline-fixture",
        ingest_data_dir=str(tmp_path / "copy"),
        qdrant_url="http://original:6333",
    )

    def transport(request):
        assert request.method == "GET" and request.url.path == "/api/tags", (
            "Unexpected model request"
        )
        return httpx.Response(
            200, json={"models": [{"name": "nomic-embed-text:latest", "digest": state["digest"]}]}
        )

    def factory(config):
        state["endpoints"].append(config.qdrant_url)
        return SelectionObserver(
            config,
            qdrant=state["db"],
            model_client=lambda t: httpx.Client(transport=httpx.MockTransport(transport)),
        )

    lib = Library(settings, factory, start_worker=False)
    signature = {
        "parser": PARSER_VERSION,
        "model": "nomic-embed-text:latest",
        "digest": state["digest"],
        "chunk_size": 900,
        "overlap": 150,
        "format": 1,
        "destination": settings.qdrant_collection,
    }
    legacy = {**signature, "database": settings.qdrant_url}
    old_fp, collection = legacy_identity(legacy)
    qdrant.create_collection(
        collection, vectors_config=models.VectorParams(size=3, distance=models.Distance.COSINE)
    )
    with lib.db() as db:
        db.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?)",
            ("selected", "browser", "fixture", "completed", 1.0, 0),
        )
        for i in range(15):
            doc_id, revision = uid(f"doc:{i}"), uid(f"rev:{i}")
            ids = [uid(f"point:{i}:{j}") for j in range(10 if i < 3 else 9)]
            points = [
                models.PointStruct(
                    id=pid,
                    vector=[1.0, 0.0, 0.0],
                    payload={
                        "document_id": doc_id,
                        "revision": revision,
                        "text": f"Synthetic fact {i}/{j}",
                        "chunk": j,
                        "source": f"browser:fixture/{i}.txt",
                    },
                )
                for j, pid in enumerate(ids)
            ]
            qdrant.upsert(collection, points, wait=True)
            db.execute(
                "INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    doc_id,
                    "browser:fixture",
                    f"{i}.txt",
                    checksum(f"content:{i}"),
                    old_fp,
                    revision,
                    collection,
                    json.dumps(ids),
                    float(i),
                ),
            )
            db.execute(
                "INSERT INTO revisions VALUES(?,?,?,?,?)",
                (revision, doc_id, collection, json.dumps(ids), "active"),
            )
            db.execute(
                "INSERT INTO files(id,job_id,path,size,status,doc_id,revision) VALUES(?,?,?,?,?,?,?)",
                (uid(f"file:{i}"), "selected", f"{i}.txt", 1, "completed", doc_id, revision),
            )
        documents = [dict(r) for r in db.execute("SELECT * FROM documents ORDER BY id")]
    points, _ = qdrant.scroll(collection, limit=1000, with_payload=True, with_vectors=True)
    proof = {
        "schema": 1,
        "legacy_signature": legacy,
        "documents": documents,
        "points": sorted(
            [
                {
                    "id": str(p.id),
                    "document_id": p.payload["document_id"],
                    "revision": p.payload["revision"],
                    "payload_sha256": checksum(p.payload),
                    "vector_sha256": checksum(p.vector),
                }
                for p in points
            ],
            key=lambda p: p["id"],
        ),
    }
    raw = encode(proof)
    yield {
        "lib": lib,
        "qdrant": qdrant,
        "state": state,
        "signature": signature,
        "proof": proof,
        "raw": raw,
        "hash": hashlib.sha256(raw).hexdigest(),
        "collection": collection,
        "fp": old_fp,
        "forbidden": forbidden,
    }
    forbidden.assert_not_called()
    lib.close()
    qdrant.close()


def register(saved, *, raw=None, signature=None):
    raw = saved["raw"] if raw is None else raw
    with saved["lib"].db() as db:
        db.execute("BEGIN IMMEDIATE")
        return register_legacy_context(
            db,
            saved["qdrant"],
            signature or saved["signature"],
            raw,
            hashlib.sha256(raw).hexdigest(),
        )


def dump(saved):
    with saved["lib"].db() as db:
        tables = {
            table: [tuple(r) for r in db.execute(f"SELECT * FROM {table} ORDER BY 1")]
            for table in ("jobs", "files", "documents", "revisions")
        }
    points, cursor = saved["qdrant"].scroll(
        saved["collection"], limit=1000, with_payload=True, with_vectors=True
    )
    assert cursor is None
    return checksum(
        {
            "tables": tables,
            "points": sorted(
                [p.model_dump(mode="json") for p in points], key=lambda p: str(p["id"])
            ),
        }
    )


def test_original_endpoint_preserves_unmigrated_legacy(saved):
    before = dump(saved)
    fp, engine = saved["lib"].model_context()
    assert (fp, engine.config.qdrant_collection) == (saved["fp"], saved["collection"])
    result = saved["lib"].ask("selection only", job_id="selected")
    assert len(result["points"]) == 138
    assert len({p.payload["revision"] for p in result["points"]}) == 15
    assert dump(saved) == before


def test_hostname_change_requires_proof_then_preserves_all_data(saved):
    before = dump(saved)
    lib = saved["lib"]
    lib.config.qdrant_url = "http://restored-name:6333/"
    with pytest.raises(DocumentError, match="verified legacy provenance"):
        lib.ask("selection only", job_id="selected")
    assert register(saved) is True
    assert register(saved) is False
    result = lib.ask("selection only", job_id="selected")
    assert result["collections"] == [saved["collection"]]
    assert len(result["points"]) == 138
    assert len({p.payload["revision"] for p in result["points"]}) == 15
    assert dump(saved) == before
    with lib.db() as db:
        assert db.execute("SELECT count(*) FROM index_contexts").fetchone()[0] == 1


def test_native_identity_does_not_depend_on_endpoint(saved):
    lib = saved["lib"]
    # Different identity, no legacy documents: deterministic v2 context.
    saved["state"]["digest"] = "new-independent-model"
    original_fp, engine = lib.model_context()
    lib.config.qdrant_url = "https://equivalent-endpoint.example:7443"
    changed_fp, changed_engine = lib.model_context()
    assert original_fp == changed_fp
    assert engine.config.qdrant_collection == changed_engine.config.qdrant_collection
    assert engine is not changed_engine
    assert changed_engine.config.qdrant_url == lib.config.qdrant_url


@pytest.mark.parametrize(
    "field,value",
    [
        ("digest", "wrong-model"),
        ("model", "other:latest"),
        ("parser", "incompatible-parser"),
        ("chunk_size", 1000),
        ("overlap", 120),
        ("format", 2),
        ("destination", "other_collection"),
    ],
)
def test_incompatible_identity_rejected_without_mutation(saved, field, value):
    before = dump(saved)
    signature = {**saved["signature"], field: value}
    assert fingerprint(signature) != fingerprint(saved["signature"])
    with pytest.raises(DocumentError, match="incompatible"):
        register(saved, signature=signature)
    assert dump(saved) == before
    with saved["lib"].db() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='index_contexts'").fetchone()


@pytest.mark.parametrize("defect", ["empty", "missing", "binding", "payload", "vector"])
def test_wrong_backend_and_corrupt_points_rejected(saved, defect):
    qdrant = saved["qdrant"]
    point = saved["proof"]["points"][0]
    if defect == "empty":
        qdrant.delete_collection(saved["collection"])
    elif defect == "missing":
        qdrant.delete(saved["collection"], models.PointIdsList(points=[point["id"]]))
    elif defect in {"binding", "payload"}:
        qdrant.set_payload(
            saved["collection"],
            {"document_id" if defect == "binding" else "text": "mismatched"},
            points=[point["id"]],
        )
    else:
        qdrant.update_vectors(
            saved["collection"], [models.PointVectors(id=point["id"], vector=[0.0, 1.0, 0.0])]
        )
    with pytest.raises(DocumentError):
        register(saved)
    with saved["lib"].db() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='index_contexts'").fetchone()


def test_endpoint_client_recreated_and_wrong_backend_rejected(saved):
    register(saved)
    saved["lib"].ask("initial selection")
    wrong = QdrantClient(":memory:")
    saved["state"]["db"] = wrong
    saved["lib"].config.qdrant_url = "http://wrong-backend:6333"
    try:
        with pytest.raises(DocumentError, match="absent"):
            saved["lib"].ask("selection only")
    finally:
        wrong.close()


def test_alias_to_an_unrelated_collection_is_rejected(saved):
    client = saved["qdrant"]
    points, _ = client.scroll(saved["collection"], limit=1000, with_payload=True, with_vectors=True)
    client.create_collection(
        "unrelated_copy",
        vectors_config=models.VectorParams(size=3, distance=models.Distance.COSINE),
    )
    client.upsert(
        "unrelated_copy",
        [models.PointStruct(id=p.id, vector=p.vector, payload=p.payload) for p in points],
    )
    client.delete_collection(saved["collection"])
    client.update_collection_aliases(
        change_aliases_operations=[
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    collection_name="unrelated_copy", alias_name=saved["collection"]
                )
            )
        ]
    )
    with pytest.raises(DocumentError, match="alias"):
        register(saved)


def test_ambiguous_native_context_does_not_replace_legacy(saved):
    with saved["lib"].db() as db:
        doc = dict(saved["proof"]["documents"][0])
        doc.update(
            id=uid("native-doc"),
            fingerprint=fingerprint(saved["signature"]),
            collection="native_collection",
        )
        db.execute(
            "INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?)",
            tuple(
                doc[k]
                for k in (
                    "id",
                    "source",
                    "path",
                    "content_hash",
                    "fingerprint",
                    "revision",
                    "collection",
                    "points",
                    "indexed",
                )
            ),
        )
    with pytest.raises(DocumentError, match="ambiguous"):
        register(saved)


def test_retired_revision_and_outside_job_excluded(saved):
    register(saved)
    lib = saved["lib"]
    first, second = saved["proof"]["documents"][:2]
    # A document exists in another job, while its active points share the same
    # compatible collection. A retired revision also remains physically present.
    with lib.db() as db:
        db.execute("UPDATE files SET job_id='outside' WHERE doc_id=?", (first["id"],))
        retired = uid("retired")
        retired_point = uid("retired-point")
        db.execute(
            "INSERT INTO revisions VALUES(?,?,?,?,?)",
            (retired, second["id"], saved["collection"], json.dumps([retired_point]), "retired"),
        )
    saved["qdrant"].upsert(
        saved["collection"],
        [
            models.PointStruct(
                id=retired_point,
                vector=[1.0, 0.0, 0.0],
                payload={"document_id": second["id"], "revision": retired, "text": "retired"},
            )
        ],
    )
    result = lib.ask("selection only", job_id="selected")
    assert len({p.payload["revision"] for p in result["points"]}) == 14
    assert all(
        p.payload["document_id"] != first["id"] and p.payload["revision"] != retired
        for p in result["points"]
    )
    with pytest.raises(DocumentError, match="No compatible"):
        lib.ask("selection only", job_id="unknown-job")


@pytest.mark.parametrize("corruption", ["pointer", "state", "collection"])
def test_corrupt_registry_rejected_before_dispatch(saved, corruption):
    register(saved)
    with saved["lib"].db() as db:
        if corruption == "pointer":
            db.execute(
                "UPDATE documents SET revision='absent' WHERE id=?",
                (saved["proof"]["documents"][0]["id"],),
            )
        elif corruption == "state":
            db.execute("UPDATE revisions SET state='retired'")
        else:
            db.execute("UPDATE documents SET collection='unrelated'")
    with pytest.raises(DocumentError):
        saved["lib"].ask("selection only")


def test_runtime_rechecks_registered_full_payload_and_vector(saved):
    register(saved)
    point = saved["proof"]["points"][0]
    saved["qdrant"].set_payload(
        saved["collection"], {"text": "different truth"}, points=[point["id"]]
    )
    with pytest.raises(DocumentError, match="saved provenance"):
        saved["lib"].ask("selection only")


def test_arbitrary_legacy_fingerprint_and_bad_proof_rejected(saved):
    proof = deepcopy(saved["proof"])
    proof["documents"][0]["fingerprint"] = "f" * 64
    with pytest.raises(DocumentError, match="does not reproduce"):
        register(saved, raw=encode(proof))
    with saved["lib"].db() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(DocumentError, match="checksum"):
            register_legacy_context(db, saved["qdrant"], saved["signature"], saved["raw"], "0" * 64)


def test_exception_after_insert_rolls_back_schema_and_metadata(saved):
    before = dump(saved)
    with pytest.raises(RuntimeError, match="injected"), saved["lib"].db() as db:
        db.execute("BEGIN IMMEDIATE")
        register_legacy_context(
            db, saved["qdrant"], saved["signature"], saved["raw"], saved["hash"]
        )
        raise RuntimeError("injected failure after insert, before commit")
    with saved["lib"].db() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='index_contexts'").fetchone()
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert dump(saved) == before
    assert register(saved)


def test_process_death_before_commit_is_recoverable(saved, tmp_path):
    # SQLite backup of the disposable fixture, not of any deployed registry.
    target = tmp_path / "crash.sqlite3"
    with saved["lib"].db() as db, sqlite3.connect(target) as backup:
        db.backup(backup)
    raw = tmp_path / "provenance.json"
    raw.write_bytes(saved["raw"])
    script = """
import json, os, sqlite3, sys
from rag.index_compatibility import register_legacy_context
db = sqlite3.connect(sys.argv[1]); db.row_factory = sqlite3.Row
proof = open(sys.argv[2], "rb").read()
class VerifiedFixtureClient:
    def get_aliases(self):
        from types import SimpleNamespace
        return SimpleNamespace(aliases=[])
    def collection_exists(self, name): return True
    def retrieve(self, *args, **kwargs): raise AssertionError("verification is mocked below")
# The parent tests exercise real point verification. This child isolates the
# real SQLite crash boundary after successful verification, without IPC/server.
import rag.index_compatibility as m
m.verify_backend = lambda *args: None
db.execute("BEGIN IMMEDIATE")
register_legacy_context(db, VerifiedFixtureClient(), json.loads(sys.argv[3]), proof, sys.argv[4])
os._exit(23)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(target),
            str(raw),
            json.dumps(saved["signature"]),
            saved["hash"],
        ],
        env={**os.environ, "PYTHONPATH": "src"},
        check=False,
    )
    assert result.returncode == 23
    with sqlite3.connect(target) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='index_contexts'").fetchone()
        assert db.execute("SELECT count(*) FROM documents").fetchone()[0] == 15


def test_registered_context_survives_restart_and_model_change_stays_incompatible(saved):
    register(saved)
    lib = saved["lib"]
    config, factory = lib.config, lib.engine_factory
    lib.close()
    restarted = Library(
        config.model_copy(update={"qdrant_url": "http://after-restart:6333"}),
        factory,
        start_worker=False,
    )
    saved["lib"] = restarted
    assert len(restarted.ask("selection only")["points"]) == 138
    saved["state"]["digest"] = "a-different-embedding-model"
    with pytest.raises(DocumentError, match="No compatible"):
        restarted.ask("selection only")


def test_cli_verify_apply_backup_and_repeat(saved, tmp_path):
    from scripts.register_legacy_index import main

    lib = saved["lib"]
    lib.close()
    identity = tmp_path / "identity.json"
    identity.write_bytes(encode(saved["signature"]))
    proof = tmp_path / "proof.json"
    proof.write_bytes(saved["raw"])
    backup = tmp_path / "before.sqlite3"
    args = [
        "--working-copy",
        str(lib.root),
        "--qdrant-url",
        "http://disposable-only:6333",
        "--identity",
        str(identity),
        "--identity-sha256",
        hashlib.sha256(identity.read_bytes()).hexdigest(),
        "--provenance",
        str(proof),
        "--provenance-sha256",
        saved["hash"],
    ]

    class ReadOnlyClient:
        def __getattr__(self, name):
            assert name in {"get_aliases", "collection_exists", "get_collection", "retrieve"}
            return getattr(saved["qdrant"], name)

        def close(self):
            pass

    def factory(**kwargs):
        return ReadOnlyClient()

    before = dump(saved)
    assert main(args, client_factory=factory) == {
        "verified": True,
        "applied": False,
        "changed": False,
    }
    assert not backup.exists()
    with lib.db() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='index_contexts'").fetchone()
    apply_args = [*args, "--apply", "--backup", str(backup)]
    result = main(apply_args, client_factory=factory)
    assert result["applied"] and result["changed"]
    assert result["backup_sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT count(*) FROM documents").fetchone()[0] == 15
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='index_contexts'").fetchone()
    assert main(apply_args, client_factory=factory) == {
        "verified": True,
        "applied": False,
        "changed": False,
    }
    assert dump(saved) == before


def test_cli_existing_backup_never_overwritten(saved, tmp_path):
    from scripts.register_legacy_index import backup_registry

    target = tmp_path / "existing.sqlite3"
    target.write_bytes(b"preserve previous backup")
    with saved["lib"].db() as db, pytest.raises(FileExistsError):
        backup_registry(db, target)
    assert target.read_bytes() == b"preserve previous backup"
