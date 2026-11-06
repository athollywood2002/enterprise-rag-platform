"""Bounded, authenticated-by-caller metadata checks; never inference or writes."""

import asyncio
import json
from datetime import UTC, datetime

import httpx

MAX_RESPONSE_BYTES = 1024 * 1024
CHECK_SECONDS = 4


async def metadata(client, url):
    try:
        async with asyncio.timeout(CHECK_SECONDS):
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        return "invalid response", None
                return "reachable", json.loads(body)
    except (httpx.HTTPError, TimeoutError):
        return "unavailable", None
    except (ValueError, UnicodeError):
        return "invalid response", None


def model_name(name):
    return name if ":" in name.rsplit("/", 1)[-1] else name + ":latest"


async def check_readiness(config, *, transport=None):
    async with httpx.AsyncClient(timeout=3, follow_redirects=False, transport=transport) as client:
        (ollama, tags), (qdrant, collections) = await asyncio.gather(
            metadata(client, config.ollama_url.rstrip("/") + "/api/tags"),
            metadata(client, config.qdrant_url.rstrip("/") + "/collections"),
        )
    names = None
    if ollama == "reachable":
        models = tags.get("models") if isinstance(tags, dict) else None
        if isinstance(models, list) and all(
            isinstance(m, dict) and isinstance(m.get("name"), str) for m in models
        ):
            names = {model_name(m["name"]) for m in models}
        else:
            ollama = "invalid response"
    if qdrant == "reachable":
        result = collections.get("result") if isinstance(collections, dict) else None
        items = result.get("collections") if isinstance(result, dict) else None
        if not isinstance(items, list) or not all(
            isinstance(item, dict) and isinstance(item.get("name"), str) for item in items
        ):
            qdrant = "invalid response"

    def model(name):
        return {
            "name": name,
            "status": "unknown"
            if names is None
            else "available"
            if model_name(name) in names
            else "missing",
        }

    chat, embedding = model(config.ollama_chat_model), model(config.ollama_embed_model)
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "mode": config.rag_model_mode,
        "chat_model": chat,
        "embedding_model": embedding,
        "ollama": ollama,
        "qdrant": qdrant,
        "metadata_ready": qdrant == "reachable"
        and chat["status"] == embedding["status"] == "available",
        "inference_tested": False,
    }
