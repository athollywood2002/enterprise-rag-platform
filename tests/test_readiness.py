import asyncio

import httpx
import pytest

from rag import readiness
from rag.config import Settings


def config(**kwargs):
    return Settings(_env_file=None, api_key="private-test-key", **kwargs)


def check(handler, **kwargs):
    return asyncio.run(
        readiness.check_readiness(config(**kwargs), transport=httpx.MockTransport(handler))
    )


def valid(request):
    assert request.method == "GET"
    assert "x-api-key" not in request.headers
    if request.url.path == "/api/tags":
        return httpx.Response(
            200, json={"models": [{"name": "qwen3:8b"}, {"name": "nomic-embed-text:latest"}]}
        )
    assert request.url.path == "/collections"
    return httpx.Response(200, json={"result": {"collections": []}})


def test_metadata_only_with_explicit_mode_and_model_names():
    result = check(valid, rag_model_mode="synthetic")
    assert result["metadata_ready"] and not result["inference_tested"]
    assert result["mode"] == "synthetic"
    assert result["embedding_model"] == {"name": "nomic-embed-text", "status": "available"}
    assert check(valid)["mode"] == "unknown"


@pytest.mark.parametrize("body", [{}, [], {"models": [None]}, {"models": [{"name": 3}]}])
def test_invalid_model_metadata_cannot_pass(body):
    result = check(
        lambda r: httpx.Response(200, json=body) if r.url.path == "/api/tags" else valid(r)
    )
    assert result["ollama"] == "invalid response"
    assert result["chat_model"]["status"] == "unknown"
    assert not result["metadata_ready"]


def test_missing_model_is_distinct_from_unreachable():
    result = check(valid, ollama_chat_model="not-installed")
    assert result["chat_model"]["status"] == "missing"
    assert result["ollama"] == "reachable"
    assert not result["metadata_ready"]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not json"),
        httpx.Response(500),
        httpx.Response(302, headers={"location": "http://other/"}),
        httpx.Response(200, json={"result": {}}),
    ],
)
def test_database_errors_never_pass_or_expose_urls(response):
    result = check(lambda r: response if r.url.path == "/collections" else valid(r))
    assert not result["metadata_ready"]
    assert "localhost" not in str(result) and "private-test-key" not in str(result)


def test_response_size_limit(monkeypatch):
    monkeypatch.setattr(readiness, "MAX_RESPONSE_BYTES", 4)
    assert not check(valid)["metadata_ready"]


def test_overall_deadline_includes_delayed_metadata(monkeypatch):
    monkeypatch.setattr(readiness, "CHECK_SECONDS", 0.01)

    async def slow(request):
        await asyncio.sleep(0.05)
        return valid(request)

    result = check(slow)
    assert result["ollama"] == result["qdrant"] == "unavailable"


def test_route_requires_existing_api_authentication():
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from rag.library_api import routes

    def deny():
        raise HTTPException(401, "Unauthorized")

    app = FastAPI()
    app.include_router(routes(deny, lambda: pytest.fail("must not access manager")))
    assert TestClient(app).get("/library/readiness").status_code == 401


@pytest.mark.parametrize("mode", ["real", "synthetic", "unknown"])
def test_managed_ask_binds_mode_and_preserves_response(mode):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from rag.library_api import routes

    payload = {"answer": "fixture [1]", "sources": [], "generation": {"status": "complete"}}
    library = SimpleNamespace(config=config(rag_model_mode=mode), ask=Mock(return_value=payload))
    manager = Mock(return_value=library)
    app = FastAPI()
    app.include_router(routes(lambda: None, manager))
    response = TestClient(app).post("/library/ask", json={"question": "Fixture?", "job_id": "job"})
    assert response.status_code == 200
    assert response.json() == payload | {"model_mode": mode}
    manager.assert_called_once_with()
    library.ask.assert_called_once_with("Fixture?", 5, "job")
    assert "model_mode" not in payload  # No mutation of shared/legacy engine results.


def test_managed_ask_keeps_serving_mode_when_configuration_changes_inflight():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from rag.library_api import routes

    serving = SimpleNamespace(config=config(rag_model_mode="real"))
    current = [serving]

    def answer(*args):
        # A newer configuration/readiness check cannot relabel this older request.
        serving.config.rag_model_mode = "synthetic"
        current[0] = SimpleNamespace(config=config(rag_model_mode="unknown"))
        return {"answer": "older request", "sources": [], "model_mode": "untrusted payload"}

    serving.ask = Mock(side_effect=answer)
    manager = Mock(side_effect=lambda: current[0])
    app = FastAPI()
    app.include_router(routes(lambda: None, manager))
    response = TestClient(app).post("/library/ask", json={"question": "Fixture?"})
    assert response.status_code == 200
    assert response.json()["model_mode"] == "real"
    manager.assert_called_once_with()


def test_managed_ask_mode_metadata_requires_existing_auth(monkeypatch):
    from unittest.mock import Mock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from rag import api
    from rag.library_api import routes

    monkeypatch.setattr(api, "settings", lambda: config())
    manager = Mock(side_effect=AssertionError("Unauthenticated ask must not reach library"))
    app = FastAPI()
    app.include_router(routes(api.authorize, manager))
    response = TestClient(app).post("/library/ask", json={"question": "Fixture?"})
    assert response.status_code == 401
    manager.assert_not_called()
