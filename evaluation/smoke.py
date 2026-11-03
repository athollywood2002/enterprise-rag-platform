"""Authored synthetic HTTP flow; real routes/core, stub parser/services, no sockets."""

import hashlib
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from rag import api, core
from rag.config import Settings
from rag.documents import DocumentChunk

FACTS = (
    "The cobalt reserve contains seventeen lanterns.",
    "The amber laboratory opens on Tuesday.",
    "The lilac depot stores twenty-nine maps.",
)
QUESTIONS = (
    "How many lanterns does the cobalt reserve contain?",
    "When does the amber laboratory open?",
    "Who designed the lunar railway?",
)
SOURCE = "synthetic-smoke.pdf"
COLLECTION = "rag_eval_http_offline_stub"


class SmokeFailure(RuntimeError):
    """A synthetic contract check failed (never an answer-quality judgment)."""


def check(condition: bool) -> None:
    if not condition:
        raise SmokeFailure("Synthetic HTTP contract check failed")


@contextmanager
def offline_fence():
    def denied(*args, **kwargs):
        raise SmokeFailure("Offline smoke forbids sockets and real Qdrant clients")

    with (
        patch("socket.getaddrinfo", denied),
        patch("socket.create_connection", denied),
        patch("socket.socket.connect", denied),
        patch("socket.socket.connect_ex", denied),
        patch.object(core, "QdrantClient", side_effect=denied),
    ):
        yield


def fixture_pdf() -> bytes:
    """Deterministic three-page embedded-text PDF, without optional dependencies."""
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(FACTS)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Count 3 /Kids [{kids}] >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, fact in enumerate(FACTS):
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
            ).encode()
        )
        stream = f"BT /F1 12 Tf 72 720 Td ({fact}) Tj ET".encode()
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    data = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(data)
    data += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return (
        data
        + f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    )


def fixture_identity() -> dict:
    return {
        "id": "authored-synthetic-http-v1",
        "rights": "repository-authored synthetic data; MIT",
        "document_sha256": hashlib.sha256(fixture_pdf()).hexdigest(),
        "questions_sha256": hashlib.sha256(json.dumps(QUESTIONS).encode()).hexdigest(),
        "pages": 3,
        "questions": 3,
    }


class MemoryStub:
    """Minimal disposable Qdrant-shaped test double, NOT a database backend."""

    def __init__(self):
        self.points = {}
        self.size = None
        self.searches = 0

    def get_aliases(self):
        return SimpleNamespace(aliases=[])

    def collection_exists(self, name):
        check(name == COLLECTION)
        return self.size is not None

    def create_collection(self, collection_name, vectors_config):
        check(collection_name == COLLECTION and self.size is None)
        self.size = vectors_config.size

    def get_collection(self, name):
        check(name == COLLECTION)
        return SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=self.size)))
        )

    def upsert(self, collection_name, points, wait):
        check(collection_name == COLLECTION and wait)
        self.points.update({p.id: p for p in points})

    def query_points(self, collection_name, query, limit, with_payload):
        check(collection_name == COLLECTION and limit == 2 and with_payload)
        self.searches += 1
        ranked = sorted(
            self.points.values(),
            key=lambda p: (-sum(a * b for a, b in zip(query, p.vector)), p.payload["chunk"]),
        )
        points = (
            [
                SimpleNamespace(
                    id=p.id, score=sum(a * b for a, b in zip(query, p.vector)), payload=p.payload
                )
                for p in ranked[:limit]
            ]
            if any(query)
            else []
        )
        return SimpleNamespace(points=points)


@offline_fence()
def offline_http_smoke() -> dict:
    """No real parser/model/DB; fixed stubs deliberately do not measure accuracy."""
    config = Settings(
        _env_file=None,
        api_key="synthetic-smoke-only",
        qdrant_collection=COLLECTION,
        qdrant_url="http://qdrant.invalid:6333",
        ollama_url="http://ollama.invalid:11434",
        ollama_embed_model="synthetic-embed-stub",
        ollama_chat_model="synthetic-chat-stub",
    )
    database = MemoryStub()
    engine = core.RagEngine(config, qdrant=database)
    counts = {"stub_embeddings": 0, "stub_chats": 0, "stub_parser_passes": 0}

    def parser(data, filename):
        check(data == fixture_pdf() and filename == SOURCE)
        counts["stub_parser_passes"] += 1
        return [DocumentChunk(text, filename, i, i + 1) for i, text in enumerate(FACTS)]

    def service(request):
        body = json.loads(request.content)
        check(request.method == "POST" and request.url.host == "ollama.invalid")
        if request.url.path == "/api/embed":
            check(body["model"] == config.ollama_embed_model)
            counts["stub_embeddings"] += 1
            text = body["input"].lower()
            vector = [float(word in text) for word in ("cobalt", "amber", "lilac")]
            return httpx.Response(200, json={"embeddings": [vector]})
        check(request.url.path == "/api/chat" and body["model"] == config.ollama_chat_model)
        counts["stub_chats"] += 1
        prompt = body["messages"][0]["content"]
        answer = FACTS[0] if QUESTIONS[0] in prompt else FACTS[1]
        check(answer in prompt)
        return httpx.Response(200, json={"message": {"content": answer + " [1]"}})

    def client(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(service), trust_env=False)

    with (
        patch.object(api, "settings", lambda: config),
        patch.object(api, "engine", lambda: engine),
        patch.object(api, "parse_document", parser),
        patch.object(core, "httpx", SimpleNamespace(Client=client)),
        TestClient(api.app) as http,
    ):
        headers = {"x-api-key": config.api_key}
        upload = {"file": (SOURCE, fixture_pdf(), "application/pdf")}
        check(http.post("/ingest/document", files=upload).status_code == 401)
        check(counts["stub_parser_passes"] == 0 and not database.points)
        check(http.post("/ask", json={"question": QUESTIONS[0]}).status_code == 401)
        response = http.post("/ingest/document", headers=headers, files=upload)
        check(
            response.status_code == 200
            and response.json() == {"source": SOURCE, "chunks_indexed": 3}
        )
        answers = []
        for i, question in enumerate(QUESTIONS):
            response = http.post("/ask", headers=headers, json={"question": question, "top_k": 2})
            check(response.status_code == 200)
            result = response.json()
            if i < 2:
                check(result["answer"] == FACTS[i] + " [1]")
                check(result["sources"][0]["source"] == SOURCE)
                check(result["sources"][0]["page_number"] == i + 1)
                check(result["sources"][0]["text"] == FACTS[i])
            else:
                check(result["sources"] == [] and "don't know" in result["answer"])
            answers.append(result)
        before = sorted(database.points)
        response = http.post("/ingest/document", headers=headers, files=upload)
        check(
            response.status_code == 200 and sorted(database.points) == before and len(before) == 3
        )
    return {
        "checks": [
            "authentication",
            "multipart_ingest_to_ask",
            "source_and_page_propagation",
            "stub_rank_selection",
            "empty_retrieval_branch",
            "exact_reingestion_stable_ids",
        ],
        "counts": counts
        | {"stub_searches": database.searches, "stub_points": len(database.points)},
        "answers": answers,
        "scope": "in-process FastAPI + real RagEngine; parser/embedding/chat/storage are stubs",
    }
