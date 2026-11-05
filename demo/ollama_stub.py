"""CI-only deterministic protocol fixture. This is NOT model inference."""

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/embed":
            result = {"embeddings": [[1.0, 0.0, 0.0]]}
        elif self.path == "/api/chat":
            prompt = data["messages"][0]["content"]
            refs = {
                name: re.search(r"\[(\d+)\] " + re.escape(name) + r" \(page", prompt).group(1)
                for name in ("runbook.txt", "inventory.csv")
            }
            result = {
                "message": {
                    "role": "assistant",
                    "content": (
                        f"The recovery code is ORION [{refs['runbook.txt']}]. "
                        f"The owner is NetworkOps [{refs['inventory.csv']}]."
                    ),
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
