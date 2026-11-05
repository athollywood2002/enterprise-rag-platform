"""Exercise real API/Qdrant; inference uses the configured Ollama endpoint."""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from demo.contract import QUESTION, documents, validate_answer  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--fixtures", type=Path, default=Path(__file__).resolve().parents[1] / "demo/fixtures"
    )
    args = parser.parse_args()
    key = os.environ["API_KEY"]

    def request(path, payload=None, authenticated=True):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["x-api-key"] = key
        req = urllib.request.Request(
            args.url.rstrip("/") + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=240) as response:
            return json.load(response)

    # Retry read-only readiness, never ingestion or model requests.
    deadline = time.monotonic() + 60
    while True:
        try:
            request("/health")
            with urllib.request.urlopen(os.environ["QDRANT_URL"] + "/readyz", timeout=2):
                pass
            break
        except (OSError, urllib.error.URLError):
            if time.monotonic() >= deadline:
                raise RuntimeError("API/Qdrant readiness timed out") from None
            time.sleep(1)
    docs = documents(args.fixtures)
    for route, payload in [("/ingest", docs[0]), ("/ask", {"question": QUESTION})]:
        try:
            request(route, payload, authenticated=False)
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise
        else:
            raise RuntimeError(f"{route}: unauthorized request was accepted")
    for doc in docs:
        result = request("/ingest", doc)
        if result != {"source": doc["source"], "chunks_indexed": 1}:
            raise RuntimeError(f"Unexpected ingest result: {result}")
    result = request("/ask", {"question": QUESTION, "top_k": 2})
    print(json.dumps({"question": QUESTION, "response": result}, indent=2), flush=True)
    validate_answer(result, docs)
    print("PASS: unauthorized401; two ingestions; expected answer and both cited sources")


if __name__ == "__main__":
    main()
