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


def test_named_row_lane_is_global_and_does_not_change_plain_text_ranking():
    from rag.retrieval import managed_candidates, row_rank

    points = [candidate(i, f"noise {i}", 0.9 - i / 100) for i in range(5)]
    for i, entity in [(8, "Example gateway"), (9, "Other security")]:
        points.append(
            NS(
                id=i,
                score=0.01,
                payload={
                    "text": f"{entity} RTO hours 2 RPO minutes 0",
                    "row_kind": "data",
                    "column_labels": ["Service", "RTO hours", "RPO minutes"],
                    "row_entities": [entity],
                },
            )
        )

    class DB:
        def __init__(self, groups):
            self.groups = groups

        def scroll(self, collection_name, **kw):
            assert kw["scroll_filter"] == "selected-job-committed-revisions"
            return self.groups[collection_name], None

    def ranked(groups):
        return managed_candidates(
            DB(groups),
            list(groups),
            "Compare Example gateway and Other security RTOs and RPOs",
            points[:5],
            "selected-job-committed-revisions",
            5,
        )[0]

    together = ranked({"all": points})
    split = ranked({"new": points[::2], "old": points[1::2]})
    assert [(p.payload, p.score) for p in together] == [(p.payload, p.score) for p in split]
    assert {p.payload["row_entities"][0] for p in together if "row_entities" in p.payload} == {
        "Example gateway",
        "Other security",
    }
    assert row_rank("generic RTO definition", points) == []
    assert row_rank("Example gateway owner", points) == []
    assert (
        row_rank(
            "Example gateway RTO", [NS(id=1, payload={**points[-2].payload, "row_kind": "header"})]
        )
        == []
    )
