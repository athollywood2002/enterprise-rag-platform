"""Real sockets/API child, synthetic HTTP peers only; never Ollama or Qdrant."""

import hashlib
import json
import os
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from evaluation.supervisor import Child, RunConfig, Supervisor, SupervisorStopped

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX ownership")
_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex
_getaddrinfo = socket.getaddrinfo
_allowed = set()


@pytest.fixture(autouse=True)
def block_service_access(monkeypatch):
    """Override global deny only for exact fresh synthetic endpoint addresses."""
    _allowed.clear()

    def checked(address):
        assert address in _allowed, "Only fixture-owned synthetic ports permitted"

    def connect(sock, address):
        checked(address)
        return _connect(sock, address)

    def connect_ex(sock, address):
        checked(address)
        return _connect_ex(sock, address)

    def resolve(host, port, *args, **kwargs):
        checked((host, port))
        return _getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setenv("AUTO_DOWNLOAD_NLTK", "false")
    yield
    _allowed.clear()


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        number = sock.getsockname()[1]
        _allowed.add(("127.0.0.1", number))
        return number


@contextmanager
def peer(callback):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.reply({"result": {"exists": True}, "status": "ok", "time": 0})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            status, payload = callback(self.path, body)
            self.reply(payload, status)

        def reply(self, payload, status=200):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    _allowed.add(("127.0.0.1", server.server_port))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.fixture
def config(tmp_path):
    exe = Path(sys.executable).absolute()
    store = tmp_path / "synthetic-store"
    store.mkdir()
    proxy_port = port()
    return RunConfig(
        output=tmp_path / "run",
        model_store=store,
        children=(
            Child(
                exe,
                hashlib.sha256(exe.read_bytes()).hexdigest(),
                ("-I", "-c", "import time; time.sleep(60)"),
                {"OLLAMA_URL": f"http://127.0.0.1:{proxy_port}"},
            ),
        ),
        model_url=f"http://127.0.0.1:{port()}",
        proxy_port=proxy_port,
        embed_model="synthetic-embed",
        embed_digest="1" * 64,
        chat_model="synthetic-chat",
        chat_digest="2" * 64,
        num_predict=32,
        seconds=15,
        request_seconds=2,
        evidence_seconds=1,
        embeddings=9,
        chats=3,
    )


def embed(url):
    with httpx.Client(trust_env=False, timeout=3) as client:
        return client.post(
            url + "/api/embed", json={"model": "synthetic-embed", "input": "Synthetic fact"}
        )


def test_real_api_child_uses_shared_proxy_for_embed_and_chat(config):
    seen = []

    def model(path, body):
        seen.append((path, body))
        if path == "/api/embed":
            return 200, {"embeddings": [[1.0, 0.0]]}
        return 200, {
            "message": {"content": "Synthetic answer [1]."},
            "done": True,
            "done_reason": "stop",
            "eval_count": 4,
        }

    def database(path, body):
        assert path == "/collections/synthetic_proxy_test/points/query"
        return 200, {
            "result": {
                "points": [
                    {
                        "id": "00000000-0000-0000-0000-000000000001",
                        "version": 1,
                        "score": 1.0,
                        "payload": {"source": "synthetic", "chunk": 0, "text": "Synthetic fact."},
                    }
                ]
            },
            "status": "ok",
            "time": 0,
        }

    with peer(model) as upstream, peer(database) as db:
        api_port = port()
        child = replace(
            config.children[0],
            args=("-m", "uvicorn", "rag.api:app", "--host", "127.0.0.1", "--port", str(api_port)),
            env=config.children[0].env
            | {
                "PYTHONPATH": str(Path("src").resolve()),
                "QDRANT_URL": db,
                "QDRANT_COLLECTION": "synthetic_proxy_test",
                "OLLAMA_EMBED_MODEL": config.embed_model,
                "OLLAMA_CHAT_MODEL": config.chat_model,
                "OLLAMA_NUM_PREDICT": "32",
                "API_KEY": "synthetic-only",
            },
        )
        config = replace(config, model_url=upstream, children=(child,))
        run = Supervisor(config)
        with (
            run,
            httpx.Client(
                base_url=f"http://127.0.0.1:{api_port}", trust_env=False, timeout=4
            ) as client,
        ):
            deadline = time.monotonic() + 5
            while True:
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline, "API readiness failed; retain child log"
                assert run._processes[0].poll() is None
                threading.Event().wait(0.02)
            response = client.post(
                "/ask", json={"question": "Synthetic?"}, headers={"x-api-key": "synthetic-only"}
            )
            assert response.status_code == 200, response.text
            assert response.json()["answer"] == "Synthetic answer [1]."
            assert run.counts == {"embed": 1, "chat": 1}
            assert [p for p, _ in seen] == ["/api/embed", "/api/chat"]
            assert child.env["OLLAMA_URL"] == run._proxy.url != upstream
            # Same shared accounting path, not a private proxy counter.
            with run.model_client() as direct:
                assert (
                    direct.post(
                        "/api/embed", json={"model": config.embed_model, "input": "Synthetic"}
                    ).status_code
                    == 200
                )
            assert run.counts == {"embed": 2, "chat": 1}
        assert run._processes[0].poll() == -9
        assert json.loads((config.output / "finalization.json").read_text())["status"] == "complete"


@pytest.mark.parametrize("status", [500, 302])
def test_failed_upstream_is_charged_without_retry_or_redirect(config, status):
    calls = []
    with peer(lambda p, b: (calls.append(p) or status, {})) as upstream:
        run = Supervisor(replace(config, model_url=upstream))
        with pytest.raises(SupervisorStopped), run, pytest.raises(httpx.TransportError):
            embed(run._proxy.url)
        assert calls == ["/api/embed"] and run.counts["embed"] == 1
        assert any(
            e.get("status") == status
            for e in map(json.loads, (config.output / "events.jsonl").read_text().splitlines())
        )


def test_concurrent_proxy_requests_cannot_overspend(config):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def model(path, body):
        calls.append(path)
        entered.set()
        assert release.wait(timeout=4)
        return 200, {}

    with peer(model) as upstream:
        run = Supervisor(replace(config, model_url=upstream, embeddings=1))
        try:
            with pytest.raises(SupervisorStopped), run, ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(embed, run._proxy.url)
                assert entered.wait(timeout=2)
                second = pool.submit(embed, run._proxy.url)
                assert run._stopped.wait(timeout=2)
                release.set()
                for future in (first, second):
                    with pytest.raises(httpx.TransportError):
                        future.result(timeout=3)
        finally:
            release.set()
        assert len(calls) == 1 and run.counts["embed"] == 1


@pytest.mark.parametrize(
    "raw",
    [
        b"GET /api/embed HTTP/1.1\r\n",
        b"POST http://example.invalid/api/embed HTTP/1.1\r\n",
        b"POST /api/embed?x=1 HTTP/1.1\r\n",
        b"POST /api/other HTTP/1.1\r\n",
        b"POST /api/embed HTTP/1.1\r\nHost: evil\r\n",  # Duplicate Host below.
        b"POST /api/embed HTTP/1.1\r\nTransfer-Encoding: chunked\r\n",
        b"POST /api/embed HTTP/1.1\r\nContent-Length: 9999999\r\n",
    ],
)
def test_proxy_rejects_framing_and_targets_before_forwarding(config, raw):
    calls = []
    with peer(lambda p, b: (calls.append(p) or 200, {})) as upstream:
        run = Supervisor(replace(config, model_url=upstream))
        with (
            pytest.raises(SupervisorStopped),
            run,
            socket.create_connection(("127.0.0.1", config.proxy_port), timeout=2) as conn,
        ):
            conn.sendall(
                raw
                + f"Host: 127.0.0.1:{config.proxy_port}\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{{}}".encode()
            )
            assert run._stopped.wait(timeout=2)
        assert calls == [] and run.counts["embed"] == 0


@pytest.mark.parametrize(
    "body",
    [
        b"{",
        b'{"model":"wrong","input":"x"}',
        b'{"model":"synthetic-embed","input":["x"]}',
        b'{"model":"synthetic-embed","input":"x","stream":true}',
        b'{"model":"synthetic-embed","model":"synthetic-embed","input":"x"}',
    ],
)
def test_proxy_reuses_protocol_validation(config, body):
    calls = []
    with peer(lambda p, b: (calls.append(p) or 200, {})) as upstream:
        run = Supervisor(replace(config, model_url=upstream))
        with (
            pytest.raises(SupervisorStopped),
            run,
            httpx.Client(trust_env=False) as client,
            pytest.raises(httpx.TransportError),
        ):
            client.post(
                run._proxy.url + "/api/embed",
                content=body,
                headers={"content-type": "application/json"},
            )
        assert calls == [] and run.counts["embed"] == 0


def test_stalled_proxy_upstream_records_cutoff_and_immutable_finalization(config):
    entered, release = threading.Event(), threading.Event()
    outcomes = []

    def model(path, body):
        entered.set()
        assert release.wait(timeout=4)
        return 200, {}

    def request(url):
        try:
            embed(url)
        except httpx.TransportError:
            outcomes.append("stopped")

    with peer(model) as upstream:
        run = Supervisor(replace(config, model_url=upstream, evidence_seconds=0.1))
        thread = None
        try:
            with pytest.raises(SupervisorStopped), run:
                thread = threading.Thread(target=request, args=(run._proxy.url,))
                thread.start()
                assert entered.wait(timeout=2)
            marker = (config.output / "finalization.json").read_bytes()
            summary = json.loads(marker)
            assert (
                summary["status"] == "incomplete" and summary["inflight_evidence_unrecorded"] == 1
            )
            assert run._processes[0].poll() == -9
            release.set()
            thread.join(timeout=3)
            assert not thread.is_alive()
            with run._evidence:
                assert run._evidence.wait_for(lambda: run._active_attempts == 0, timeout=3)
            assert (config.output / "finalization.json").read_bytes() == marker
            assert run._journal.closed and outcomes == ["stopped"]
        finally:
            release.set()
            if thread:
                thread.join(timeout=3)


def test_one_request_per_connection_and_no_admission_after_stop(config):
    with peer(lambda p, b: (200, {})) as upstream:
        run = Supervisor(replace(config, model_url=upstream))
        with pytest.raises(SupervisorStopped), run:
            with socket.create_connection(("127.0.0.1", config.proxy_port), timeout=2) as conn:
                body = b'{"model":"synthetic-embed","input":"x"}'
                request = (
                    f"POST /api/embed HTTP/1.1\r\nHost: 127.0.0.1:{config.proxy_port}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: keep-alive\r\n\r\n".encode()
                    + body
                )
                conn.sendall(request)
                data = b""
                while part := conn.recv(4096):
                    data += part
                assert b"Connection: close" in data
                with run._proxy._lock:
                    listener = Mock(wraps=run._proxy._listener)
                    run._proxy._listener = listener
                run.abort()
                listener.shutdown.assert_called_once_with(socket.SHUT_RDWR)
                listener.close.assert_called_once()
                controls = [
                    call[0] for call in listener.method_calls if call[0] in ("shutdown", "close")
                ]
                assert controls == ["shutdown", "close"]
                try:
                    conn.sendall(request)
                    assert conn.recv(4096) == b""
                except (BrokenPipeError, ConnectionResetError):
                    pass
            with pytest.raises(OSError):
                socket.create_connection(("127.0.0.1", config.proxy_port), timeout=1)
        assert run.counts["embed"] == 1


@pytest.mark.parametrize(
    "change", [{"proxy_port": 0}, {"proxy_port": True}, {"proxy_port": 70000}, {"children": ()}]
)
def test_invalid_proxy_configuration_has_no_output(config, change):
    with pytest.raises(ValueError):
        Supervisor(replace(config, **change))
    assert not config.output.exists()


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"OLLAMA_URL": "http://127.0.0.1:1"},
        {"ollama_url": "http://127.0.0.1:1"},
        {"http_proxy": "http://example.invalid"},
    ],
)
def test_missing_or_conflicting_child_proxy_environment_refused(config, env):
    child = replace(
        config.children[0],
        env=env if not env or "OLLAMA_URL" in env else config.children[0].env | env,
    )
    with pytest.raises(ValueError):
        Supervisor(replace(config, children=(child,)))
    assert not config.output.exists()


def test_upstream_equals_proxy_is_refused(config):
    with pytest.raises(ValueError):
        Supervisor(replace(config, model_url=f"http://127.0.0.1:{config.proxy_port}"))


def test_partial_header_times_out_and_stops_owned_child(config):
    run = Supervisor(replace(config, request_seconds=0.15))
    with (
        pytest.raises(SupervisorStopped),
        run,
        socket.create_connection(("127.0.0.1", config.proxy_port), timeout=2) as conn,
    ):
        conn.sendall(b"POST /api/embed HTTP/1.1\r\nHost: ")
        assert run._stopped.wait(timeout=2)
    assert run._processes[0].poll() == -9 and run.counts["embed"] == 0


@pytest.mark.parametrize("kind", ["headers", "body", "response"])
def test_proxy_size_bounds(config, monkeypatch, kind):
    from evaluation import budget_proxy

    calls = []
    monkeypatch.setattr(budget_proxy, "MAX_RESPONSE", 16)
    with peer(lambda p, b: (calls.append(p) or 200, {"padding": "x" * 32})) as upstream:
        run = Supervisor(replace(config, model_url=upstream))
        with pytest.raises(SupervisorStopped), run:
            if kind == "response":
                with pytest.raises(httpx.TransportError):
                    embed(run._proxy.url)
            else:
                with socket.create_connection(("127.0.0.1", config.proxy_port), timeout=2) as conn:
                    if kind == "headers":
                        raw = (
                            b"POST /api/embed HTTP/1.1\r\nX-Padding: "
                            + b"x" * budget_proxy.MAX_HEADERS
                        )
                    else:
                        raw = (
                            f"POST /api/embed HTTP/1.1\r\nHost: 127.0.0.1:{config.proxy_port}\r\nContent-Type: application/json\r\nContent-Length: {budget_proxy.MAX_BODY + 1}\r\n\r\n"
                        ).encode()
                    conn.sendall(raw)
                    assert run._stopped.wait(timeout=2)
        assert len(calls) == (1 if kind == "response" else 0)
        assert run.counts["embed"] == (1 if kind == "response" else 0)


def test_only_fixture_owned_ports_are_allowed():
    with pytest.raises(AssertionError, match="fixture-owned"):
        socket.create_connection(("127.0.0.1", 11434))
    with pytest.raises(AssertionError, match="fixture-owned"):
        socket.create_connection(("example.invalid", 80))


@pytest.mark.parametrize(
    "override",
    [
        {"stream": True},
        {"options": {}},
        {"options": {"num_predict": 31}},
        {"options": {"num_predict": 32, "temperature": 0}},
        {"model": "wrong"},
        {"messages": [{"role": "system", "content": "x"}]},
    ],
)
def test_proxy_chat_protocol_refused_before_reservation(config, override):
    calls = []
    payload = {
        "model": config.chat_model,
        "stream": False,
        "messages": [{"role": "user", "content": "Synthetic"}],
        "options": {"num_predict": 32},
    } | override
    with peer(lambda p, b: (calls.append(p) or 200, {})) as upstream:
        run = Supervisor(replace(config, model_url=upstream))
        with (
            pytest.raises(SupervisorStopped),
            run,
            httpx.Client(trust_env=False) as client,
            pytest.raises(httpx.TransportError),
        ):
            client.post(run._proxy.url + "/api/chat", json=payload)
        assert calls == [] and run.counts == {"embed": 0, "chat": 0}


def test_proxy_port_conflict_fails_closed_without_children(config):
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", config.proxy_port))
        occupied.listen()
        run = Supervisor(config)
        with pytest.raises(OSError), run:
            pytest.fail("Conflicting proxy must not start")
        assert run._processes == [] and run._journal.closed


def test_proxy_stop_releases_partial_request_with_complete_evidence(config):
    run = Supervisor(config)
    with (
        pytest.raises(SupervisorStopped),
        run,
        socket.create_connection(("127.0.0.1", config.proxy_port), timeout=2) as conn,
    ):
        conn.sendall(b"POST /api/embed HTTP/1.1\r\n")
        with run._evidence:
            assert run._evidence.wait_for(lambda: run._active_attempts == 1, timeout=2)
        run.abort()
    summary = json.loads((config.output / "finalization.json").read_text())
    assert summary["status"] == "complete" and summary["inflight_evidence_unrecorded"] == 0
    assert run.counts == {"embed": 0, "chat": 0}


def test_connection_ceiling_stops_without_forwarding(config, monkeypatch):
    from evaluation import budget_proxy

    monkeypatch.setattr(budget_proxy, "MAX_CONNECTIONS", 2)
    run = Supervisor(config)
    connections = []
    try:
        with pytest.raises(SupervisorStopped), run:
            for number in (1, 2):
                connections.append(
                    socket.create_connection(("127.0.0.1", config.proxy_port), timeout=2)
                )
                with run._evidence:
                    assert run._evidence.wait_for(
                        lambda n=number: run._active_attempts == n, timeout=2
                    )
            connections.append(
                socket.create_connection(("127.0.0.1", config.proxy_port), timeout=2)
            )
            assert run._stopped.wait(timeout=2)
        assert run._stop_reason == "proxy_overload" and run.counts["embed"] == 0
    finally:
        for conn in connections:
            conn.close()


def test_proxy_known_500_is_retained_when_worker_drains_during_grace(config, monkeypatch):
    stopped, release = threading.Event(), threading.Event()
    outcomes = []
    with peer(lambda p, b: (500, {})) as upstream:
        run = Supervisor(replace(config, model_url=upstream))
        original_stop, original_drain = run._request_stop, run._drain_evidence

        def stop(reason):
            original_stop(reason)
            if reason == "dispatch_failed" and not stopped.is_set():
                stopped.set()
                assert release.wait(timeout=3)

        def drain(deadline):
            release.set()
            return original_drain(deadline)

        def request():
            try:
                embed(run._proxy.url)
            except httpx.TransportError:
                outcomes.append("failed")

        monkeypatch.setattr(run, "_request_stop", stop)
        monkeypatch.setattr(run, "_drain_evidence", drain)
        thread = threading.Thread(target=request)
        try:
            with pytest.raises(SupervisorStopped), run:
                thread.start()
                assert stopped.wait(timeout=2)
            ledger = list(
                map(json.loads, (config.output / "events.jsonl").read_text().splitlines())
            )
            assert any(e["event"] == "response_error" and e["status"] == 500 for e in ledger)
            summary = json.loads((config.output / "finalization.json").read_text())
            assert summary["status"] == "complete" and summary["inflight_evidence_unrecorded"] == 0
        finally:
            release.set()
            if thread.ident is not None:
                thread.join(timeout=3)
                assert not thread.is_alive()
        assert outcomes == ["failed"] and run.counts["embed"] == 1
