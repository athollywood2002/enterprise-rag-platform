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
