"""Opt-in POSIX test-process owner and bounded model transport; not a host sandbox."""

import hashlib
import json
import math
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from evaluation.run import new_output
from rag.config import Settings


class SupervisorStopped(RuntimeError):
    """No further dispatch is permitted in this run."""


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate protocol key")
        value[key] = item
    return value


@dataclass(frozen=True)
class Child:
    executable: Path
    sha256: str
    args: tuple[str, ...]
    env: dict[str, str]


@dataclass(frozen=True)
class RunConfig:
    output: Path
    model_store: Path
    children: tuple[Child, ...]
    model_url: str
    embed_model: str
    embed_digest: str
    chat_model: str
    chat_digest: str
    num_predict: int
    seconds: float
    request_seconds: float
    embeddings: int
    chats: int

    def validate(self) -> None:
        if os.name != "posix":
            raise ValueError("Test process-group ownership requires POSIX")
        if not self.output.is_absolute() or self.output.exists():
            raise ValueError("A fresh absolute output/storage path is required")
        if not self.model_store.is_absolute() or not self.model_store.is_dir():
            raise ValueError("An explicit existing model-store directory is required")
        output, store = self.output.resolve(), self.model_store.resolve()
        if output == store or output in store.parents or store in output.parents:
            raise ValueError("Model store and fresh run storage must not overlap")
        if not isinstance(self.children, tuple) or not self.children:
            raise ValueError("Fresh owned children are required; no attach mode")
        for child in self.children:
            if (
                not child.executable.is_absolute()
                or not child.executable.is_file()
                or not os.access(child.executable, os.X_OK)
            ):
                raise ValueError("Explicit executable file required")
            if hashlib.sha256(child.executable.read_bytes()).hexdigest() != child.sha256:
                raise ValueError("Executable pin mismatch")
            if not isinstance(child.args, tuple) or any(
                not isinstance(a, str) or "\x00" in a for a in child.args
            ):
                raise ValueError("Explicit argument tuple required; no shell")
            if not isinstance(child.env, dict) or any(
                not isinstance(k, str)
                or not k
                or "=" in k
                or "\x00" in k
                or not isinstance(v, str)
                or "\x00" in v
                for k, v in child.env.items()
            ):
                raise ValueError("Explicit child environment required")
        if not isinstance(self.model_url, str) or not re.fullmatch(
            r"http://127\.0\.0\.1:[0-9]{1,5}", self.model_url
        ):
            raise ValueError("Explicit numeric-loopback model URL required")
        if not 1 <= int(self.model_url.rsplit(":", 1)[1]) <= 65535:
            raise ValueError("Invalid model port")
        for tag, digest in (
            (self.embed_model, self.embed_digest),
            (self.chat_model, self.chat_digest),
        ):
            if not isinstance(tag, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", tag
            ):
                raise ValueError("Explicit model tags required")
            if (
                not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or int(digest, 16) == 0
            ):
                raise ValueError("Explicit nonzero model artifact digests required")
        if (
            type(self.num_predict) is not int
            or Settings.validate_generation_cap(self.num_predict) is None
        ):
            raise ValueError("Explicit generation cap required")
        for value in (self.seconds, self.request_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("Explicit positive finite time limits required")
        if self.request_seconds > self.seconds:
            raise ValueError("Request limit exceeds run deadline")
        for value, ceiling in ((self.embeddings, 9), (self.chats, 3)):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError(
                    "Dispatch allowances must be positive and at most 9 embed / 3 chat"
                )


class Supervisor:
    """Only processes spawned here are stop targets. Use as a context manager.

    Children must stay foreground in their fresh process groups. Daemonization,
    escaping descendants, hostile code and external direct callers are outside
    this boundary. A deployment packet must establish service/port/store isolation.
    """

    def __init__(self, config: RunConfig):
        config.validate()  # Before output, processes or transport construction.
        self.config = config
        self._lock = threading.RLock()
        self._ownership_lock = threading.RLock()
        self._stopped = threading.Event()
        self._stop_reason = None
        self._stop_revision = 0
        self._logged_revision = 0
        self._processes: list[subprocess.Popen] = []
        self._pending_stop: list[subprocess.Popen] = []
        self._stop_errors: list[str] = []
        self._counts = {"embed": 0, "chat": 0}
        self._state = "new"
        self._timer = None
        self._journal = None
        self._deadline = 0.0
        self._started = 0.0
        self._stop_elapsed = None
        self._handlers = {}
        self._launching = False
        self.output = None

    def _event(self, event: str, **fields) -> None:
        self._journal.write(
            json.dumps({"event": event, "elapsed": time.monotonic() - self._started, **fields})
            + "\n"
        )
        self._journal.flush()
        os.fsync(self._journal.fileno())

    @property
    def counts(self) -> dict:
        with self._lock:
            return self._counts.copy()

    def __enter__(self):
        if threading.current_thread() is not threading.main_thread():
            raise ValueError("Process lifecycle must run on the main thread")
        with self._lock:
            if self._state != "new":
                raise SupervisorStopped("Runs cannot be resumed or reused")
        try:
            with self._lock:
                self.output = new_output(self.config.output)
                fd = os.open(
                    self.output / "events.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
                self._journal = os.fdopen(fd, "w")
                self._state = "starting"
                self._started = time.monotonic()
                self._deadline = self._started + self.config.seconds
                for signum in (signal.SIGINT, signal.SIGTERM):
                    self._handlers[signum] = signal.getsignal(signum)
                    signal.signal(signum, self._interrupt)
                self._timer = threading.Timer(self.config.seconds, self._stop, args=("deadline",))
                self._timer.daemon = True
                self._timer.start()
                self._check(starting=True)
                self._event(
                    "start",
                    schema="rag-owned-supervisor-v1",
                    supervisor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    seconds=self.config.seconds,
                    request_seconds=self.config.request_seconds,
                    embeddings=self.config.embeddings,
                    chats=self.config.chats,
                    num_predict=self.config.num_predict,
                    model_store=str(self.config.model_store),
                    model_url=self.config.model_url,
                    embed_model=self.config.embed_model,
                    chat_model=self.config.chat_model,
                    embed_digest=self.config.embed_digest,
                    chat_digest=self.config.chat_digest,
                    executable_pins=[c.sha256 for c in self.config.children],
                    argv_sha256=[
                        hashlib.sha256(
                            json.dumps([str(c.executable), *c.args]).encode()
                        ).hexdigest()
                        for c in self.config.children
                    ],
                )
            for i, child in enumerate(self.config.children):
                with self._lock:
                    self._check(starting=True)
                fd = os.open(
                    self.output / f"child-{i}.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
                self._launching = True
                try:
                    with os.fdopen(fd, "wb") as log:
                        proc = subprocess.Popen(
                            [str(child.executable), *child.args],
                            cwd=self.output,
                            env=child.env.copy(),
                            stdin=subprocess.DEVNULL,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            start_new_session=True,
                        )
                    with self._lock:
                        self._processes.append(proc)
                        with self._ownership_lock:
                            self._pending_stop.append(proc)
                        # Timeout/signal during Popen still owns this new child.
                        self._event("spawn", child=i, pid=proc.pid)
                        self._check(starting=True)
                finally:
                    self._launching = False
            with self._lock:
                self._check(starting=True)
                self._state = "running"
            return self
        except BaseException:  # Cleanup even on KeyboardInterrupt; never swallow it.
            try:
                self._stop("startup_failed")
            finally:
                if self._journal:
                    self._journal.close()
                self._restore_signals()
            raise

    def _interrupt(self, signum, frame):
        already_stopping = self._stopped.is_set()
        self._stop("interrupted")
        if not already_stopping and not self._launching:
            raise KeyboardInterrupt("Owned test run interrupted")
        # Let Popen return/register before raising: never abandon an unregistered child.

    def _restore_signals(self):
        for signum, handler in self._handlers.items():
            signal.signal(signum, handler)
        self._handlers.clear()

    def _check(self, *, starting: bool = False) -> None:
        if self._stopped.is_set() or (
            self._state != "running" and not (starting and self._state == "starting")
        ):
            raise SupervisorStopped("Run stopped or deadline expired")
        if time.monotonic() >= self._deadline:
            self._stop("deadline")
            raise SupervisorStopped("Run deadline expired")
        if any(proc.poll() is not None for proc in self._processes):
            self._stop("child_exited")
            raise SupervisorStopped("Owned child exited before run completion")

    def abort(self) -> None:
        self._stop("aborted")

    def _stop(self, reason: str) -> None:
        # Stop signalling must not wait for a dispatch/event fsync holding _lock.
        with self._ownership_lock:
            changed = not self._stopped.is_set()
            if changed:
                self._stopped.set()
                self._stop_reason = reason
                self._stop_elapsed = time.monotonic() - self._started if self._started else None
            if self._timer:
                self._timer.cancel()
            pending, self._pending_stop = self._pending_stop, []
            # Signal all groups before waiting; a slow child cannot defer the
            # stop signal to another owned model process. Never re-signal reaped IDs.
            for proc in pending:
                try:
                    # Only group IDs created by our own start_new_session Popen.
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError as error:
                    self._stop_errors.append(type(error).__name__)
            for proc in pending:
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self._stop_errors.append("ChildWaitTimeout")
            if self._stop_errors:
                self._stop_reason = "stop_failed"
            if changed or pending:
                self._stop_revision += 1
            revision = self._stop_revision
        with self._lock:
            if revision >= self._logged_revision:
                self._state = self._stop_reason
            if revision > self._logged_revision and self._journal and not self._journal.closed:
                self._event(
                    "stop",
                    reason=self._state,
                    counts=self._counts,
                    stop_errors=self._stop_errors,
                    stop_requested_elapsed=self._stop_elapsed,
                    children=[{"pid": p.pid, "returncode": p.returncode} for p in self._processes],
                )
                self._logged_revision = revision

    def __exit__(self, kind, value, traceback):
        try:
            if kind is None:
                with self._lock:
                    self._check()
                self._stop("completed")
            else:
                self._stop("interrupted" if issubclass(kind, KeyboardInterrupt) else "failed")
        finally:
            # May have failed the success check after the timer/child exit.
            try:
                self._stop("failed")
            finally:
                self._journal.close()
                self._restore_signals()
        if self._state != "completed" and kind is None:
            raise SupervisorStopped("Run did not complete")

    def model_client(
        self, timeout: float | None = None, *, transport: httpx.BaseTransport | None = None
    ) -> httpx.Client:
        with self._lock:
            self._check()
        if timeout is not None and (
            type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0
        ):
            raise ValueError("Invalid client timeout")
        seconds = (
            self.config.request_seconds
            if timeout is None
            else min(timeout, self.config.request_seconds)
        )
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("Invalid client timeout")
        upstream = (
            transport if transport is not None else httpx.HTTPTransport(retries=0, trust_env=False)
        )
        return httpx.Client(
            transport=_BudgetTransport(self, upstream),
            base_url=self.config.model_url,
            timeout=seconds,
            follow_redirects=False,
            trust_env=False,
        )


class _BudgetTransport(httpx.BaseTransport):
    def __init__(self, run: Supervisor, upstream: httpx.BaseTransport):
        self.run, self.upstream = run, upstream

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        run = self.run
        try:
            path = request.url.path
            if (
                request.method != "POST"
                or str(request.url) != str(httpx.URL(run.config.model_url + path))
                or path not in ("/api/embed", "/api/chat")
            ):
                raise SupervisorStopped("Only pinned model POST routes are permitted")
            try:
                body = json.loads(request.content, object_pairs_hook=_unique_object)
            except ValueError as error:
                raise SupervisorStopped("Malformed model request") from error
            if not isinstance(body, dict):
                raise SupervisorStopped("Model request must be an object")
            route = "embed" if path == "/api/embed" else "chat"
            if route == "embed":
                valid = (
                    set(body) == {"model", "input"}
                    and body["model"] == run.config.embed_model
                    and isinstance(body["input"], str)
                    and bool(body["input"].strip())
                )
            else:
                valid = (
                    set(body) == {"model", "messages", "stream", "options"}
                    and body["model"] == run.config.chat_model
                    and body["stream"] is False
                    and isinstance(body["options"], dict)
                    and type(body["options"].get("num_predict")) is int
                    and body["options"] == {"num_predict": run.config.num_predict}
                    and isinstance(body["messages"], list)
                    and len(body["messages"]) == 1
                    and isinstance(body["messages"][0], dict)
                    and set(body["messages"][0]) == {"role", "content"}
                    and body["messages"][0]["role"] == "user"
                    and isinstance(body["messages"][0]["content"], str)
                    and bool(body["messages"][0]["content"].strip())
                )
            if not valid:
                raise SupervisorStopped("Model request differs from the pinned protocol")
            with run._lock:
                run._check()
                ceiling = run.config.embeddings if route == "embed" else run.config.chats
                if run._counts[route] >= ceiling:
                    raise SupervisorStopped("Model dispatch allowance exhausted")
                run._counts[route] += 1  # Failed attempts still consume the reservation.
                run._event("reserve", route=route, number=run._counts[route])
                remaining = min(run.config.request_seconds, run._deadline - time.monotonic())
                if remaining <= 0:
                    run._stop("deadline")
                    raise SupervisorStopped("Run deadline expired")
                prior = request.extensions.get("timeout", {})
                request.extensions["timeout"] = {
                    key: min(prior[key], remaining) if prior.get(key) is not None else remaining
                    for key in ("connect", "read", "write", "pool")
                }
            response = self.upstream.handle_request(request)  # Exactly one attempt, no retry.
            try:
                response.read()
                if response.status_code != 200:
                    with run._lock:
                        if not run._stopped.is_set():
                            run._event("response_error", route=route, status=response.status_code)
                    raise SupervisorStopped("Model request failed")
                with run._lock:
                    run._check()  # Never credit a result arriving after stop/deadline.
                    run._event("response", route=route, status=response.status_code)
                    run._check()
                return response
            except BaseException:
                response.close()
                raise
        except BaseException:
            run._stop("dispatch_failed")
            raise

    def close(self) -> None:
        self.upstream.close()
