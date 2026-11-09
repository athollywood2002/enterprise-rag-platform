"""CI-only deterministic protocol fixture. This is NOT model inference."""

import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/api/tags":
            self.send_error(404)
            return
        body = json.dumps(
            {
                "models": [
                    {"name": "nomic-embed-text:latest", "digest": "synthetic-ci-embedding-v1"},
                    {"name": "qwen3:8b", "digest": "synthetic-ci-chat-v1"},
                ]
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/embed":
            if "SIMULATE_EMBED_FAILURE" in data["input"]:
                self.send_error(503)
                return
            if "WAIT_FOR_RESTART" in data["input"]:
                time.sleep(20)
            result = {"embeddings": [[1.0, 0.0, 0.0]]}
        elif self.path == "/api/chat":
            prompt = data["messages"][0]["content"]
            excerpts = re.findall(
                r"\[(\d+)\] (.*?) \((.*?), chunk \d+\): (.*?)(?=\n\n\[\d+\] |\n\nQuestion:|\Z)",
                prompt,
                re.S,
            )
            if "How many brass telescopes" in prompt:
                ref = next(
                    n for n, source, page, text in excerpts if "seventeen brass telescopes" in text
                )
                answer = f"The cobalt observatory stores seventeen brass telescopes [{ref}]."
            else:
                runbook = next(n for n, source, page, text in excerpts if "ORION" in text)
                inventory = next(n for n, source, page, text in excerpts if "NetworkOps" in text)
                answer = f"The recovery code is ORION [{runbook}]. The owner is NetworkOps [{inventory}]."
            result = {
                "message": {
                    "role": "assistant",
                    "content": answer,
                },
                "done": True,
                "done_reason": "stop",
                "eval_count": 24,
            }
        else:
            self.send_error(404)
            return
        body = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 11434), Handler).serve_forever()
