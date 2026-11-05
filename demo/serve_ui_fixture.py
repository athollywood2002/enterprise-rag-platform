"""Local UI review only: actual API/jobs/parser, local Qdrant, synthetic inference."""

import os
from pathlib import Path

import httpx
import uvicorn
from qdrant_client import QdrantClient

from rag import api
from rag.config import Settings
from rag.core import RagEngine
from rag.library import Library


def main():
    root = Path(os.environ["UI_FIXTURE_DIR"])
    config = Settings(
        _env_file=None,
        api_key="synthetic-ui-fixture-key",
        ingest_data_dir=str(root / "state"),
        ingest_source_roots={"demo-server": str(root / "sources")},
        ollama_num_predict=1536,
    )
    db = QdrantClient(path=str(root / "qdrant"))

    def model(request):
        import json
        import re

        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [{"name": "nomic-embed-text:latest", "digest": "ui-synthetic-model"}]
                },
            )
        if request.url.path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [[1.0, 0.0, 0.0]]})
        data = json.loads(request.content)
        excerpts = re.findall(
            r"\[(\d+)\] ([^\n]+) \(page ([^,]+), chunk [^:]+: ([^\n]+)",
            data["messages"][0]["content"],
        )
        code = next(n for n, source, page, text in excerpts if "ORION" in text)
        owner = next(n for n, source, page, text in excerpts if "NetworkOps" in text)
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": f"The recovery code is ORION [{code}]. The owner is NetworkOps [{owner}]."
                },
                "done": True,
                "done_reason": "stop",
                "eval_count": 24,
            },
        )

    api.settings = lambda: config
    api.app.state.library = Library(
        config,
        lambda c: RagEngine(
            c, qdrant=db, model_client=lambda t: httpx.Client(transport=httpx.MockTransport(model))
        ),
    )
    uvicorn.run(api.app, host="127.0.0.1", port=18890, log_level="warning")


if __name__ == "__main__":
    main()
