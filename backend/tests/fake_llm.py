"""In-process fake OpenAI-compatible server for deterministic e2e tests.

Serves /v1/chat/completions on an ephemeral port. Detection requests (default
system prompt) return the configured entity list; re-check/audit requests
(system prompt contains "auditing") return the configured recheck findings
(empty by default). All request bodies are recorded for assertions."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class FakeLLM:
    def __init__(
        self,
        entities: list[dict],
        recheck_findings: list[dict] | None = None,
        vision_text: str = "",
    ):
        self.entities = entities
        self.recheck_findings = recheck_findings or []
        self.vision_text = vision_text
        self.requests: list[dict] = []
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_port}"

    def detection_requests(self) -> list[dict]:
        return [r for r in self.requests if not self._is_recheck(r)]

    def recheck_requests(self) -> list[dict]:
        return [r for r in self.requests if self._is_recheck(r)]

    @staticmethod
    def _is_recheck(request: dict) -> bool:
        system = next(
            (m["content"] for m in request.get("messages", []) if m.get("role") == "system"), ""
        )
        return "auditing" in system

    @staticmethod
    def _is_vision(request: dict) -> bool:
        return any(isinstance(m.get("content"), list) for m in request.get("messages", []))

    def vision_requests(self) -> list[dict]:
        return [r for r in self.requests if self._is_vision(r)]

    def __enter__(self) -> "FakeLLM":
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("content-length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                fake.requests.append(body)
                if FakeLLM._is_vision(body):
                    content = fake.vision_text
                else:
                    entities = fake.recheck_findings if FakeLLM._is_recheck(body) else fake.entities
                    content = json.dumps({"entities": entities})
                payload = json.dumps(
                    {
                        "id": "fake",
                        "object": "chat.completion",
                        "model": body.get("model", "fake"),
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": content},
                                "finish_reason": "stop",
                            }
                        ],
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
