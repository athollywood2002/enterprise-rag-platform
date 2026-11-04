"""Opt-in one-request loopback bridge; trusted application routing, not a sandbox."""

import hashlib
import json
import socket
import threading
import time
from pathlib import Path

import httpx

from evaluation.supervisor import SupervisorStopped, _BudgetTransport

MAX_HEADERS = 16 * 1024
MAX_BODY = 1024 * 1024
MAX_RESPONSE = 4 * 1024 * 1024
MAX_CONNECTIONS = 12


def _reject_constant(value):
    raise ValueError("Non-JSON numeric constant")


class _BoundedStream(httpx.SyncByteStream):
    def __init__(self, inner, deadline):
        self.inner, self.deadline = inner, deadline

    def __iter__(self):
        body = bytearray()
        for part in self.inner:
            if len(body) + len(part) > MAX_RESPONSE or time.monotonic() >= self.deadline:
                raise SupervisorStopped("Proxy upstream response bound exceeded")
            body.extend(part)
        try:
            # The shared budget transport consumes this stream before crediting
            # a response. Do not publish bytes/success until bounded JSON syntax
            # validation completes; this does not judge answer quality/schema.
            json.loads(body, parse_constant=_reject_constant)
        except (ValueError, RecursionError):
            raise SupervisorStopped("Proxy upstream JSON refused") from None
        if time.monotonic() >= self.deadline:
            raise SupervisorStopped("Proxy upstream response bound exceeded")
        yield bytes(body)

    def close(self):
        self.inner.close()


class _Upstream(httpx.HTTPTransport):
    def handle_request(self, request):
        response = super().handle_request(request)
        if response.status_code == 200 and (
            response.headers.get("content-encoding", "identity") != "identity"
            or response.headers.get("content-type", "").split(";")[0] != "application/json"
        ):
            response.close()
            raise SupervisorStopped("Proxy upstream representation refused")
        response.stream = _BoundedStream(response.stream, time.monotonic() + self.seconds)
        return response


class BudgetProxy:
    """Supervisor-owned listener and bounded daemon workers; no standalone attach mode."""

    def __init__(self, run):
        self.run = run
        self.url = f"http://127.0.0.1:{run.config.proxy_port}"
        self._lock = threading.RLock()
        self._sockets = set()
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._listener = None

    def start(self):
        listener = socket.socket()
        try:
            listener.bind(("127.0.0.1", self.run.config.proxy_port))
            listener.listen(MAX_CONNECTIONS)
            listener.settimeout(0.1)
            with self._lock:
                if self.run._stopped.is_set():
                    raise SupervisorStopped("Stopped before proxy start")
                self._listener = listener
            threading.Thread(target=self._accept, daemon=True).start()
            self.run._event(
                "proxy",
                endpoint=self.url,
                upstream=self.run.config.model_url,
                proxy_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                max_headers=MAX_HEADERS,
                max_body=MAX_BODY,
                max_response=MAX_RESPONSE,
                max_connections=MAX_CONNECTIONS,
            )
        except BaseException:
            listener.close()
            raise

    def stop(self):
        # Called only after owned process signals/reaping. No join, evidence I/O,
        # or blocking server.shutdown() on the ownership stop path.
        with self._lock:
            listener = self._listener
            self._listener = None
            sockets = list(self._sockets)
        if listener is not None:
            # Linux can keep a listening socket alive while another thread is
            # blocked in accept/select, even after close(). Wake it explicitly.
            try:
                listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            listener.close()
        for conn in sockets:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _accept(self):
        while not self.run._stopped.is_set():
            with self._lock:
                listener = self._listener
            if listener is None:
                return
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                if not self.run._stopped.is_set():
                    self.run._request_stop("proxy_listener_failed")
                return
            if not self._slots.acquire(blocking=False):
                conn.close()
                self.run._request_stop("proxy_overload")
                return
            registered = False
            try:
                self.run._begin_attempt()
                registered = True
                with self._lock:
                    if self.run._stopped.is_set():
                        raise SupervisorStopped("Stopped during proxy accept")
                    self._sockets.add(conn)
                threading.Thread(target=self._serve, args=(conn,), daemon=True).start()
            except BaseException:  # noqa: BLE001 - release registered ownership on thread-start failure.
                conn.close()
                with self._lock:
                    self._sockets.discard(conn)
                self._slots.release()
                if registered:
                    self.run._finish_attempt()
                self.run._request_stop("proxy_accept_failed")
                return

    def _read_request(self, conn):
        deadline = min(self.run._deadline, time.monotonic() + self.run.config.request_seconds)
        data = bytearray()

        def receive(maximum):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or self.run._stopped.is_set():
                raise SupervisorStopped("Proxy request deadline/stop")
            conn.settimeout(remaining)
            part = conn.recv(maximum)
            if not part:
                raise ValueError("Truncated proxy request")
            return part

        while b"\r\n\r\n" not in data:
            if len(data) >= MAX_HEADERS:
                raise ValueError("Proxy headers too large")
            data.extend(receive(min(4096, MAX_HEADERS - len(data))))
        raw, body = bytes(data).split(b"\r\n\r\n", 1)
        lines = raw.decode("ascii").split("\r\n")
        method, target, version = lines[0].split(" ")
        if method != "POST" or version != "HTTP/1.1" or target not in ("/api/embed", "/api/chat"):
            raise ValueError("Proxy route/method refused")
        headers = {}
        for line in lines[1:]:
            key, value = line.split(":", 1)
            if not key or any(
                c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-" for c in key
            ):
                raise ValueError("Invalid header")
            key, value = key.lower(), value.strip()
            if any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("Invalid header value")
            if key in headers:
                raise ValueError("Duplicate header")
            headers[key] = value
        if (
            headers.get("host") != self.url.removeprefix("http://")
            or headers.get("content-type") != "application/json"
            or any(
                k in headers for k in ("transfer-encoding", "expect", "content-encoding", "upgrade")
            )
        ):
            raise ValueError("Proxy framing/host refused")
        length = headers.get("content-length", "")
        if not length.isascii() or not length.isdecimal() or len(length) > 8:
            raise ValueError("Explicit bounded content length required")
        length = int(length)
        if not 0 < length <= MAX_BODY or len(body) > length:
            raise ValueError("Proxy body size refused")
        while len(body) < length:
            body += receive(min(65536, length - len(body)))
        return target, body

    def _serve(self, conn):
        phase = "framing"
        try:
            target, body = self._read_request(conn)
            phase = "dispatch"
            upstream = _Upstream(
                retries=0, trust_env=False, limits=httpx.Limits(max_keepalive_connections=0)
            )
            upstream.seconds = self.run.config.request_seconds
            with httpx.Client(
                transport=_BudgetTransport(self.run, upstream, track_attempt=False),
                timeout=self.run.config.request_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                # The inbound target never selects the upstream host or headers.
                response = client.post(
                    self.run.config.model_url + target,
                    content=body,
                    headers={"content-type": "application/json", "accept-encoding": "identity"},
                )
                payload = response.content
            if self.run._stopped.is_set():
                raise SupervisorStopped("Stopped before proxy response")
            phase = "publication"
            conn.settimeout(
                min(
                    self.run.config.request_seconds,
                    max(0.001, self.run._deadline - time.monotonic()),
                )
            )
            conn.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: "
                + str(len(payload)).encode()
                + b"\r\n\r\n"
                + payload
            )
        except Exception as error:  # noqa: BLE001 - fail closed at the HTTP worker boundary.
            # No response/body/exception text in the evidence or error response.
            self.run._request_stop("proxy_failed")
            try:
                self.run._event("proxy_error", phase=phase, error=type(error).__name__)
            except OSError:
                pass  # _event records I/O failures for incomplete finalization.
        finally:
            conn.close()
            with self._lock:
                self._sockets.discard(conn)
            self._slots.release()
            self.run._finish_attempt()
