from types import SimpleNamespace as NS

import httpx
import pytest

from rag.config import Settings
from rag.core import RagEngine


def candidate(i, text, score):
    return NS(id=i, score=score, payload={"source": f"{i}.txt", "chunk": 0, "text": text})


@pytest.mark.parametrize("reverse", [False, True])
def test_collection_partition_does_not_change_global_ranks(reverse):
    points = [
        candidate(1, "Generic operational chronology", 0.999),
        candidate(2, "The Orion recovery code is LANTERN.", 0.99),
        candidate(3, "The cafeteria menu is pasta.", 0.01),
        candidate(4, "The cafeteria menu is rice.", 0.01),
    ]
    filters = object()

    class DB:
        def __init__(self):
            self.groups = {"all": points}

        def collection_exists(self, name):
            return True

        def query_points(self, collection_name, **kwargs):
            assert kwargs["query_filter"] is filters
            return NS(points=self.groups[collection_name])

        def scroll(self, collection_name, **kwargs):
            assert kwargs["scroll_filter"] is filters
            assert kwargs["limit"] <= 256
            return self.groups[collection_name], None

    def service(request):
        if request.url.path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [[1.0, 0.0]]})
        return httpx.Response(200, json={"message": {"content": "synthetic"}, "done": True})

    db = DB()
    engine = RagEngine(
        Settings(_env_file=None, api_key="synthetic-test", ollama_url="http://model.invalid"),
        qdrant=db,
        model_client=lambda _: httpx.Client(transport=httpx.MockTransport(service)),
    )
    question = "What is the Orion recovery code?"
    together = engine.ask(question, 4, query_filter=filters, collection_names=["all"])
    db.groups = {"old": points[:2], "new": list(reversed(points[2:]))}
    names = ["new", "old"] if reverse else ["old", "new"]
    split = engine.ask(question, 4, query_filter=filters, collection_names=names)
    assert together["sources"][0]["source"] == "2.txt"
    assert split["sources"] == together["sources"]


def test_global_fusion_keeps_each_collection_scan_bounded(monkeypatch):
    from rag import retrieval

    monkeypatch.setattr(retrieval, "SCAN_LIMIT", 3)
    calls = []

    class DB:
        def scroll(self, **kwargs):
            assert kwargs["scroll_filter"] == "committed-only"
            assert kwargs["with_vectors"] is False
            name = kwargs["collection_name"]
            offset = kwargs["offset"] or 0
            limit = min(2, kwargs["limit"])
            calls.append((name, offset, limit))
            return [
                candidate(f"{name}-{i}", "Orion recovery", 0.1)
                for i in range(offset, offset + limit)
            ], offset + limit

    _, evidence = retrieval.managed_candidates(
        DB(), ["new", "old"], "Orion", [], "committed-only", 2
    )
    assert calls == [("new", 0, 2), ("new", 2, 1), ("old", 0, 2), ("old", 2, 1)]
    assert evidence["lexical_scanned"] == evidence["lexical_scan_limit"] == 6
    assert evidence["lexical_scan_truncated"]
    assert all(report["lexical_scan_truncated"] for report in evidence["collections"])
