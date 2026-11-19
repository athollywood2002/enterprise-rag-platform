"""Synthetic independent snapshot authority; never contains campaign evidence or questions."""

import hashlib
import json
import sqlite3
from types import SimpleNamespace
from uuid import UUID

import httpx
from qdrant_client import QdrantClient, models

from rag.folder_parser import PARSER_VERSION

PREFIX = "rag_eval_reference"
MODEL = "nomic-embed-text:latest"
CHAT = "qwen3:8b"
TAGS = {"models": [{"name": MODEL, "digest": "b" * 64}, {"name": CHAT, "digest": "a" * 64}]}


def snapshot():
    signature = {
        "database": "http://qdrant:6333",
        "parser": PARSER_VERSION,
        "destination": PREFIX,
        "model": MODEL,
        "digest": "b" * 64,
        "format": 1,
        "chunk_size": 900,
        "overlap": 150,
    }
    fp = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    collection = PREFIX + "_ui_" + fp[:16]
    docs, files, records, bindings = [], [], [], []
    for n in range(16):
        doc = {
            "id": f"doc-{n}",
            "revision": f"rev-{n}",
            "fingerprint": fp,
            "collection": collection,
        }
        count = 10 if n < 3 else 9
        docs.append({**doc, "chunks": count})
        if n < 15:
            files.append({"doc_id": doc["id"], "job_id": "synthetic-job"})
        for i in range(count):
            pid = str(UUID(int=len(records) + 1))
            payload = {
                "document_id": doc["id"],
                "revision": doc["revision"],
                "text": f"Fixture row {n}/{i} €",
            }
            records.append({"id": pid, "payload": payload, "vector": [1.0, 0.0]})
            if n < 15:
                data = json.dumps(
                    payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                ).encode()
                bindings.append(
                    {
                        "id": pid,
                        "document_id": doc["id"],
                        "revision": doc["revision"],
                        "collection": collection,
                        "payload_sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
    for state in ("retired", "staging"):
        records.append(
            {
                "id": str(UUID(int=len(records) + 1)),
                "vector": [1.0, 0.0],
                "payload": {"document_id": "doc-0", "revision": state, "text": "Excluded"},
            }
        )
    manifest = {
        "job_id": "synthetic-job",
        "documents": [{k: v for k, v in doc.items() if k != "chunks"} for doc in docs[:15]],
        "points": bindings,
    }
    return SimpleNamespace(
        listing={"documents": docs},
        job={"id": "synthetic-job", "files": files},
        manifest=manifest,
        records=records,
        collection=collection,
    )


def backend(data=None, calls=None, mutate=None):
    data = data or snapshot()
    db = QdrantClient(":memory:")
    db.create_collection(
        data.collection, vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE)
    )
    db.upsert(data.collection, [models.PointStruct(**p) for p in data.records])

    def handle(req):
        if calls is not None:
            calls.append(req)
        assert "X-API-Key" not in req.headers
        if req.method == "GET" and req.url.path == "/api/tags":
            return httpx.Response(200, json=TAGS)
        base = f"/collections/{data.collection}/points"
        assert req.method == "POST" and req.url.path.startswith(base)
        body = json.loads(req.content)
        if req.url.path == base + "/scroll":
            points, cursor = db.scroll(
                data.collection,
                scroll_filter=models.Filter.model_validate(body["filter"]),
                limit=body["limit"],
                offset=body.get("offset"),
                with_payload=body["with_payload"],
                with_vectors=body["with_vector"],
            )
            result = {
                "points": [p.model_dump(mode="json") for p in points],
                "next_page_offset": cursor,
            }
        elif req.url.path == base:
            result = [
                p.model_dump(mode="json")
                for p in db.retrieve(
                    data.collection,
                    ids=body["ids"],
                    with_payload=body["with_payload"],
                    with_vectors=body["with_vector"],
                )
            ]
        else:
            assert req.url.path == base + "/query" and body["params"] == {"exact": True}
            result = db.query_points(
                data.collection,
                query=body["query"],
                query_filter=models.Filter.model_validate(body["filter"]),
                limit=body["limit"],
                search_params=models.SearchParams(exact=True),
                with_payload=True,
            ).model_dump(mode="json")
        if mutate:
            mutate(req, result)
        return httpx.Response(200, json={"result": result})

    return httpx.MockTransport(handle)


def seed(db, data):
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE documents (id PRIMARY KEY,revision,fingerprint,collection,points);
        CREATE TABLE revisions (id PRIMARY KEY,doc_id,collection,points,state);
        CREATE TABLE files (job_id,doc_id);
    """)
    for d in data.listing["documents"]:
        ids = [p["id"] for p in data.records if p["payload"]["revision"] == d["revision"]]
        row = {**d, "points": json.dumps(ids)}
        db.execute(
            "INSERT INTO documents VALUES (:id,:revision,:fingerprint,:collection,:points)", row
        )
        db.execute("INSERT INTO revisions VALUES (:revision,:id,:collection,:points,'active')", row)
        db.execute(
            "INSERT INTO files VALUES (?,?)",
            ("synthetic-job" if d["id"] != "doc-15" else "outside-job", d["id"]),
        )
    for p in data.records[-2:]:
        rev = p["payload"]["revision"]
        db.execute(
            "INSERT INTO revisions VALUES (?,?,?,?,?)",
            (rev, "doc-0", data.collection, json.dumps([p["id"]]), rev),
        )
    db.commit()
