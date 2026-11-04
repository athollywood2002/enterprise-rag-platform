"""Only mock transports and fresh disposable Python children; no real services."""

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from evaluation.supervisor import Child, RunConfig, Supervisor, SupervisorStopped
from rag.config import Settings
from rag.core import RagEngine

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")


@pytest.fixture
def config(tmp_path):
    exe = Path(sys.executable).resolve()
    store = tmp_path / "synthetic-model-store"
    store.mkdir()
    return RunConfig(
        output=tmp_path / "run",
        model_store=store,
        children=(
            Child(
                exe,
                hashlib.sha256(exe.read_bytes()).hexdigest(),
                ("-I", "-c", "import time; time.sleep(60)"),
                {},
            ),
        ),
        model_url="http://127.0.0.1:18772",
        embed_model="synthetic-embed",
        embed_digest="1" * 64,
        chat_model="synthetic-chat",
        chat_digest="2" * 64,
        num_predict=32,
        seconds=5,
        request_seconds=1,
        evidence_seconds=1,
        embeddings=9,
        chats=3,
    )


@pytest.fixture
def sentinel():
    proc = subprocess.Popen(
        [sys.executable, "-I", "-c", "import time; time.sleep(60)"], start_new_session=True
    )
    try:
        yield proc
    finally:
        proc.terminate()
        proc.wait(timeout=2)


def embed(client):
    return client.post("/api/embed", json={"model": "synthetic-embed", "input": "Synthetic fact."})


def chat(client, **overrides):
    return client.post(
        "/api/chat",
        json={
            "model": "synthetic-chat",
            "stream": False,
            "messages": [{"role": "user", "content": "Synthetic question?"}],
            "options": {"num_predict": 32},
        }
        | overrides,
    )


def events(config):
    return [json.loads(line) for line in (config.output / "events.jsonl").read_text().splitlines()]


def test_edges_and_durable_reservation_before_each_dispatch(config):
    run = Supervisor(config)
    calls = []

    def service(request):
        assert events(config)[-1]["event"] == "reserve"
        calls.append(request.url.path)
        assert all(0 < value <= 1 for value in request.extensions["timeout"].values())
        return httpx.Response(200, json={})

    with (
        pytest.raises(SupervisorStopped, match="allowance"),
        run,
        run.model_client(transport=httpx.MockTransport(service)) as client,
    ):
        owned = list(run._processes)
        for _ in range(9):
            assert embed(client).status_code == 200
        for _ in range(3):
            assert chat(client).status_code == 200
        embed(client)
    assert run.counts == {"embed": 9, "chat": 3}
    assert len(calls) == 12 and all(p.poll() is not None for p in owned)
    assert events(config)[-1]["counts"] == run.counts


def test_chat_allowance_rejected_before_fourth_dispatch(config):
    service = Mock(return_value=httpx.Response(200))
    run = Supervisor(config)
    with (
        pytest.raises(SupervisorStopped),
        run,
        run.model_client(transport=httpx.MockTransport(service)) as client,
    ):
        for _ in range(3):
            chat(client)
        chat(client)
    assert service.call_count == 3 and run.counts == {"embed": 0, "chat": 3}


def test_concurrent_reservations_never_overspend(config):
    barrier = threading.Barrier(9)
    seen = []

    def service(request):
        seen.append(request.url.path)
        barrier.wait(timeout=3)
        return httpx.Response(200)

    run = Supervisor(config)
    with (
        pytest.raises(SupervisorStopped),
        run,
        run.model_client(transport=httpx.MockTransport(service)) as client,
    ):
        with ThreadPoolExecutor(max_workers=9) as pool:
            assert all(r.status_code == 200 for r in pool.map(lambda _: embed(client), range(9)))
        embed(client)
    assert len(seen) == 9 and run.counts["embed"] == 9


@pytest.mark.parametrize(
    "failure", [httpx.ConnectError("synthetic"), httpx.ReadTimeout("synthetic"), 500, 302]
)
def test_failed_attempt_consumes_budget_and_never_retries(config, failure):
    def service(request):
        if isinstance(failure, Exception):
            raise failure
        return httpx.Response(failure, headers={"location": "http://example.invalid"})

    service = Mock(side_effect=service)
    run = Supervisor(config)
    with (
        pytest.raises((httpx.HTTPError, SupervisorStopped)),
        run,
        run.model_client(transport=httpx.MockTransport(service)) as client,
    ):
        embed(client)
    assert service.call_count == 1 and run.counts["embed"] == 1
    assert events(config)[-1]["reason"] == "dispatch_failed"


def test_stalled_work_deadline_stops_owned_child_not_only_request(config):
    config = replace(config, seconds=0.3, request_seconds=0.2)
    run = Supervisor(config)
    started = time.monotonic()

    def stalled(request):
        run._processes[0].wait(timeout=2)  # Released by the independent watchdog.
        return httpx.Response(200)

    with (
        pytest.raises(SupervisorStopped),
        run,
        run.model_client(transport=httpx.MockTransport(stalled)) as client,
    ):
        embed(client)
    assert time.monotonic() - started < 2
    assert run._processes[0].returncode == -9
    assert events(config)[-1]["reason"] == "deadline"
    assert run.counts["embed"] == 1


def test_expired_deadline_rejects_client_and_dispatch(config, sentinel):
    config = replace(config, seconds=0.2, request_seconds=0.1)
    run = Supervisor(config)
    with pytest.raises(SupervisorStopped), run:
        run._processes[0].wait(timeout=2)
        run.model_client(transport=httpx.MockTransport(lambda _: pytest.fail("No dispatch")))
    assert run.counts == {"embed": 0, "chat": 0}
    assert events(config)[-1]["reason"] == "deadline"
    assert sentinel.poll() is None


def test_partial_startup_failure_stops_already_owned_child(config, monkeypatch):
    config = replace(config, children=config.children * 2)
    real_popen = subprocess.Popen
    owned = []

    def launch(*args, **kwargs):
        if owned:
            raise OSError("synthetic startup failure")
        proc = real_popen(*args, **kwargs)
        owned.append(proc)
        return proc

    monkeypatch.setattr("evaluation.supervisor.subprocess.Popen", launch)
    with pytest.raises(OSError), Supervisor(config):
        pytest.fail("Startup should fail")
    assert owned[0].poll() == -9
    assert (config.output / "child-0.log").is_file()
    assert events(config)[-1]["reason"] == "startup_failed"


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, RuntimeError])
def test_interruption_and_failure_preserve_evidence_and_unrelated_sentinel(config, interrupt):
    sentinel = subprocess.Popen(
        [sys.executable, "-I", "-c", "import time; time.sleep(60)"], start_new_session=True
    )
    try:
        run = Supervisor(config)
        with pytest.raises(interrupt), run:
            raise interrupt("synthetic interruption")
        assert run._processes[0].poll() == -9
        assert sentinel.poll() is None
        assert (config.output / "child-0.log").exists()
        assert events(config)[-1]["reason"] == (
            "interrupted" if interrupt is KeyboardInterrupt else "failed"
        )
    finally:
        sentinel.terminate()  # Only this test's own unrelated fixture.
        sentinel.wait(timeout=2)


def test_success_stops_descendants_and_never_reuses_kill_targets(config):
    descendant = (
        "import time\nfrom pathlib import Path\nwhile True:\n"
        " Path('heartbeat').write_text(str(time.monotonic()))\n time.sleep(.01)\n"
    )
    code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-I','-c',{descendant!r}]); time.sleep(60)"
    )
    child = replace(config.children[0], args=("-I", "-c", code))
    run = Supervisor(replace(config, children=(child,)))
    heartbeat = config.output / "heartbeat"
    with run:
        until = time.monotonic() + 2
        while not heartbeat.exists() and time.monotonic() < until:
            time.sleep(0.01)
        assert heartbeat.exists()
    time.sleep(0.1)
    final = heartbeat.stat().st_mtime_ns
    time.sleep(0.1)
    assert heartbeat.stat().st_mtime_ns == final
    assert events(config)[-1]["reason"] == "completed"
    assert config.output.stat().st_mode & 0o777 == 0o700
    assert (config.output / "events.jsonl").stat().st_mode & 0o777 == 0o600
    assert (config.output / "child-0.log").stat().st_mode & 0o777 == 0o600
    assert run._pending_stop == []
    run.abort()  # No re-signalling reaped/reusable process IDs.
    assert len([e for e in events(config) if e["event"] == "stop"]) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"seconds": 0},
        {"seconds": float("inf")},
        {"seconds": True},
        {"request_seconds": 6},
        {"evidence_seconds": 0},
        {"evidence_seconds": float("inf")},
        {"evidence_seconds": threading.TIMEOUT_MAX * 2},
        {"embeddings": 10},
        {"chats": 4},
        {"chats": False},
        {"num_predict": None},
        {"num_predict": -1},
        {"num_predict": True},
        {"children": ()},
        {"embed_digest": "0" * 64},
        {"chat_digest": "bad"},
        {"embed_model": ""},
        {"model_url": "http://localhost:18772"},
        {"model_url": "http://127.0.0.1:99999"},
        {"model_url": "http://127.0.0.1:18772/api"},
        {"output": Path("relative")},
        {"model_store": Path("/nonexistent-synthetic-store")},
    ],
)
def test_invalid_configuration_precedes_output_or_launch(config, changes, monkeypatch):
    launch = Mock()
    monkeypatch.setattr("evaluation.supervisor.subprocess.Popen", launch)
    with pytest.raises(ValueError):
        Supervisor(replace(config, **changes))
    launch.assert_not_called()
    assert not config.output.exists()


def test_bad_executable_pin_and_existing_output_refused(config, monkeypatch):
    launch = Mock()
    monkeypatch.setattr("evaluation.supervisor.subprocess.Popen", launch)
    with pytest.raises(ValueError):
        Supervisor(replace(config, children=(replace(config.children[0], sha256="0" * 64),)))
    config.output.mkdir()
    (config.output / "preserved").write_text("synthetic existing evidence")
    with pytest.raises(ValueError):
        Supervisor(config)
    assert (config.output / "preserved").read_text() == "synthetic existing evidence"
    launch.assert_not_called()


@pytest.mark.parametrize(
    "case",
    ["wrong-host", "wrong-path", "wrong-method", "batch", "model", "no-cap", "bool-cap", "stream"],
)
def test_bypass_and_malformed_requests_never_reach_transport(config, case):
    # cap=1 specifically catches Python's True == 1 equality trap.
    config = replace(config, num_predict=1)
    service = Mock(return_value=httpx.Response(200))
    run = Supervisor(config)
    with (
        pytest.raises(SupervisorStopped),
        run,
        run.model_client(transport=httpx.MockTransport(service)) as client,
    ):
        if case == "wrong-host":
            client.post("http://127.0.0.1:18773/api/embed", json={})
        elif case == "wrong-path":
            client.post("/api/generate", json={})
        elif case == "wrong-method":
            client.get("/api/tags")
        elif case == "batch":
            client.post("/api/embed", json={"model": "synthetic-embed", "input": ["one", "two"]})
        elif case == "model":
            chat(client, model="other-model", options={"num_predict": 1})
        elif case == "no-cap":
            chat(client, options={})
        elif case == "bool-cap":
            chat(client, options={"num_predict": True})
        else:
            chat(client, stream=True, options={"num_predict": 1})
    service.assert_not_called()
    assert run.counts == {"embed": 0, "chat": 0}


def test_real_engine_embed_and_chat_use_the_same_supervised_path(config):
    def service(request):
        if request.url.path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [[1.0, 0.0]]})
        return httpx.Response(
            200,
            json={
                "message": {"content": "Synthetic fact. [1]"},
                "done": True,
                "done_reason": "stop",
            },
        )

    run = Supervisor(config)

    class Factory:
        def __bool__(self):
            return False  # An explicitly supplied callable must never fall back to a raw client.

        def __call__(self, timeout):
            return run.model_client(timeout, transport=httpx.MockTransport(service))

    with run:
        db = Mock()
        db.collection_exists.return_value = True
        db.query_points.return_value = SimpleNamespace(
            points=[
                SimpleNamespace(
                    score=1.0,
                    payload={
                        "source": "synthetic.txt",
                        "chunk": 0,
                        "text": "Synthetic fact.",
                        "page_number": 1,
                    },
                )
            ]
        )
        engine = RagEngine(
            Settings(
                _env_file=None,
                api_key="synthetic-only",
                ollama_url=config.model_url,
                ollama_embed_model=config.embed_model,
                ollama_chat_model=config.chat_model,
                ollama_num_predict=config.num_predict,
            ),
            qdrant=db,
            model_client=Factory(),
        )
        assert engine.ask("Synthetic question?")["generation"]["status"] == "complete"
    assert run.counts == {"embed": 1, "chat": 1}


def test_sigterm_handler_stops_owned_work_and_restores_handlers(config):
    previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    run = Supervisor(config)
    with pytest.raises(KeyboardInterrupt), run:
        handler = signal.getsignal(signal.SIGTERM)
        assert handler != previous[signal.SIGTERM]
        handler(signal.SIGTERM, None)  # Invoke the installed handler, not a signal at pytest.
    assert run._processes[0].poll() == -9
    assert events(config)[-1]["reason"] == "interrupted"
    assert all(signal.getsignal(s) == h for s, h in previous.items())


def test_interruption_during_spawn_does_not_abandon_new_child(config, monkeypatch):
    real_popen = subprocess.Popen
    spawned = []

    def launch(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        spawned.append(child)
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        return child

    monkeypatch.setattr("evaluation.supervisor.subprocess.Popen", launch)
    with pytest.raises(SupervisorStopped), Supervisor(config):
        pytest.fail("Interrupted startup must not become usable")
    assert spawned[0].poll() == -9
    assert events(config)[-1]["reason"] == "interrupted"


def test_deadline_during_spawn_prevents_use_and_stops_child_on_handoff(config, monkeypatch):
    real_popen = subprocess.Popen
    spawned = []
    config = replace(config, seconds=0.1, request_seconds=0.05)

    def launch(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        spawned.append(child)
        time.sleep(0.2)  # Simulate a delayed constructor handoff, no model dispatch.
        return child

    monkeypatch.setattr("evaluation.supervisor.subprocess.Popen", launch)
    with pytest.raises(SupervisorStopped), Supervisor(config):
        pytest.fail("Expired startup must not become usable")
    assert spawned[0].poll() == -9
    assert events(config)[-1]["reason"] == "deadline"


def test_client_after_context_and_run_reuse_refused(config):
    run = Supervisor(config)
    with run:
        pass
    with pytest.raises(SupervisorStopped):
        run.model_client()
    with pytest.raises(SupervisorStopped), run:
        pytest.fail("No reuse")


def test_narrower_client_timeout_is_not_expanded(config):
    seen = []

    def service(request):
        seen.append(request.extensions["timeout"])
        return httpx.Response(200)

    with (
        Supervisor(config) as run,
        run.model_client(0.01, transport=httpx.MockTransport(service)) as client,
    ):
        embed(client)
    assert all(value <= 0.01 for value in seen[0].values())


def test_child_exit_is_failure_not_success_or_permission_to_dispatch(config):
    config = replace(
        config,
        children=(replace(config.children[0], args=("-I", "-c", "import time; time.sleep(.1)")),),
    )
    run = Supervisor(config)
    with pytest.raises(SupervisorStopped), run:
        run._processes[0].wait(timeout=2)
        run.model_client()
    assert events(config)[-1]["reason"] == "child_exited"
    assert run.counts == {"embed": 0, "chat": 0}


def test_failed_stop_is_reported_not_completed(config, monkeypatch):
    run = Supervisor(config)
    real_killpg = os.killpg
    try:
        with pytest.raises(SupervisorStopped), run:
            monkeypatch.setattr(
                "evaluation.supervisor.os.killpg", Mock(side_effect=PermissionError("synthetic"))
            )
        assert events(config)[-1]["reason"] == "stop_failed"
        assert events(config)[-1]["stop_errors"]
    finally:
        for proc in run._processes:
            real_killpg(
                proc.pid, signal.SIGKILL
            )  # Clean up only our deliberately un-stopped fixture.
            proc.wait(timeout=2)


def test_watchdog_stop_does_not_wait_for_event_lock(config, monkeypatch):
    config = replace(config, seconds=0.2, request_seconds=0.1)
    run = Supervisor(config)
    original = run._event

    def event(name, **fields):
        if name == "response":
            run._processes[0].wait(timeout=2)  # Simulate stalled evidence I/O under _lock.
        return original(name, **fields)

    monkeypatch.setattr(run, "_event", event)
    with (
        pytest.raises(SupervisorStopped),
        run,
        run.model_client(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client,
    ):
        embed(client)
    assert run._processes[0].poll() == -9
    assert events(config)[-1]["reason"] == "deadline"


@pytest.mark.parametrize(
    "data",
    [
        b"bad-json",
        b"[]",
        b"null",
        b'{"model":"synthetic-embed","input":["one","two"],"input":"one"}',
    ],
)
def test_invalid_json_never_dispatches(config, data):
    service = Mock(return_value=httpx.Response(200))
    run = Supervisor(config)
    with (
        pytest.raises(SupervisorStopped),
        run,
        run.model_client(transport=httpx.MockTransport(service)) as client,
    ):
        client.post("/api/embed", content=data)
    service.assert_not_called()
    assert run.counts["embed"] == 0


def test_multiple_clients_share_one_run_allowance(config):
    service = Mock(return_value=httpx.Response(200))
    run = Supervisor(replace(config, embeddings=1))
    with (
        pytest.raises(SupervisorStopped),
        run,
        run.model_client(transport=httpx.MockTransport(service)) as first,
        run.model_client(transport=httpx.MockTransport(service)) as second,
    ):
        embed(first)
        embed(second)
    assert service.call_count == 1 and run.counts["embed"] == 1


def test_watchdog_start_failure_restores_handlers_without_launch(config, monkeypatch):
    previous = signal.getsignal(signal.SIGTERM)
    launch = Mock()
    monkeypatch.setattr("evaluation.supervisor.subprocess.Popen", launch)
    monkeypatch.setattr(
        "evaluation.supervisor.threading.Timer.start", Mock(side_effect=RuntimeError("synthetic"))
    )
    with pytest.raises(RuntimeError), Supervisor(config):
        pytest.fail("No watchdog means no usable run")
    launch.assert_not_called()
    assert signal.getsignal(signal.SIGTERM) == previous
    assert events(config)[-1]["reason"] == "startup_failed"


def test_explicit_abort_prevents_late_result_and_spares_sentinel(config, sentinel):
    run = Supervisor(config)

    def service(request):
        run.abort()
        return httpx.Response(200)

    with (
        pytest.raises(SupervisorStopped),
        run,
        run.model_client(transport=httpx.MockTransport(service)) as client,
    ):
        embed(client)
    assert events(config)[-1]["reason"] == "aborted"
    assert events(config)[-1]["handoffs"]["embed"] == 1
    assert run.counts["embed"] == 1
    assert run._processes[0].poll() == -9 and sentinel.poll() is None


@pytest.mark.parametrize("reason", ["deadline", "interrupted"])
@pytest.mark.parametrize("blocked_event", ["spawn", "stop"])
def test_late_spawn_is_stopped_before_blocked_bookkeeping(
    config, monkeypatch, reason, blocked_event
):
    config = replace(config, seconds=0.15 if reason == "deadline" else 5, request_seconds=0.05)
    run = Supervisor(config)
    real_popen, original_event = subprocess.Popen, run._event
    spawned = []
    ready, journal_entered, release = threading.Event(), threading.Event(), threading.Event()
    observed = []

    def launch(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        spawned.append(child)
        ready.set()
        if reason == "interrupted":
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        else:
            gate = journal_entered if blocked_event == "stop" else run._stopped
            assert gate.wait(timeout=2)
        return child

    def event(name, **fields):
        if name == blocked_event:
            journal_entered.set()
            if name == "stop":
                assert release.wait(timeout=2)
            else:
                try:
                    spawned[0].wait(timeout=0.5)
                    observed.append(True)
                except subprocess.TimeoutExpired:
                    observed.append(False)
        return original_event(name, **fields)

    def monitor():
        try:
            if ready.wait(timeout=2) and journal_entered.wait(timeout=2):
                try:
                    spawned[0].wait(timeout=0.5)
                    observed.append(True)
                except subprocess.TimeoutExpired:
                    observed.append(False)
        finally:
            release.set()

    monkeypatch.setattr("evaluation.supervisor.subprocess.Popen", launch)
    monkeypatch.setattr(run, "_event", event)
    watcher = threading.Thread(target=monitor) if blocked_event == "stop" else None
    for thread in (watcher,):
        if thread:
            thread.start()
    try:
        with pytest.raises(SupervisorStopped), run:
            pytest.fail("Stopped startup cannot become usable")
    finally:
        release.set()
        for thread in (watcher,):
            if thread:
                thread.join(timeout=3)
                assert not thread.is_alive()
    assert observed == [True], "Child survived until blocked bookkeeping was released"
    assert spawned[0].poll() == -9
    ledger = events(config)
    assert any(e["event"] == "spawn" and e["pid"] == spawned[0].pid for e in ledger)
    assert ledger[-1]["reason"] == reason
    assert ledger[-1]["children"][-1]["returncode"] == -9


@pytest.mark.parametrize("trigger", ["abort", "failed_request", "failed_http"])
def test_stop_during_durable_reservation_prevents_transport_handoff(config, monkeypatch, trigger):
    run = Supervisor(config)
    original_event = run._event
    reserved, signalled, release = threading.Event(), threading.Event(), threading.Event()
    inflight = threading.Event()
    failures = []
    charged = 1 if trigger == "abort" else 2

    def upstream(request):
        if trigger != "abort":
            inflight.set()
            assert reserved.wait(timeout=2)
            if trigger == "failed_http":
                return httpx.Response(500)
            raise httpx.ConnectError("synthetic failed in-flight attempt")
        return httpx.Response(200)

    service = Mock(side_effect=upstream)

    def event(name, **fields):
        if name == "reserve" and fields["number"] == charged:
            reserved.set()
            assert release.wait(timeout=2)
            assert signalled.is_set()
        return original_event(name, **fields)

    def stop():
        if trigger == "abort":
            assert reserved.wait(timeout=2)
            run.abort()
        else:
            try:
                embed(client)
            except (httpx.ConnectError, SupervisorStopped) as error:
                failures.append(type(error).__name__)

    def observe_stop():
        try:
            assert reserved.wait(timeout=2)
            run._processes[0].wait(timeout=2)  # Stop signal has completed, not just been requested.
            signalled.set()
        finally:
            release.set()

    monkeypatch.setattr(run, "_event", event)
    stopper, observer = threading.Thread(target=stop), threading.Thread(target=observe_stop)
    try:
        with (
            pytest.raises(SupervisorStopped),
            run,
            run.model_client(transport=httpx.MockTransport(service)) as client,
        ):
            stopper.start()
            observer.start()
            if trigger != "abort":
                assert inflight.wait(timeout=2)
            embed(client)
    finally:
        release.set()
        for thread in (stopper, observer):
            if thread.ident is not None:
                thread.join(timeout=3)
                assert not thread.is_alive()
    expected_handoffs = 0 if trigger == "abort" else 1
    assert service.call_count == expected_handoffs  # The paused request never forwards.
    assert (
        failures
        == {"abort": [], "failed_request": ["ConnectError"], "failed_http": ["SupervisorStopped"]}[
            trigger
        ]
    )
    assert signalled.is_set() and run.counts["embed"] == charged
    assert events(config)[-1]["handoffs"]["embed"] == expected_handoffs
    assert events(config)[-1]["reason"] == ("aborted" if trigger == "abort" else "dispatch_failed")
    if trigger == "failed_http":
        assert any(e["event"] == "response_error" and e["status"] == 500 for e in events(config))


def test_stop_winning_final_admission_forbids_upstream_call(config, monkeypatch):
    run = Supervisor(config)
    original_admit = run._admit_dispatch
    at_handoff, stopped = threading.Event(), threading.Event()
    service = Mock(return_value=httpx.Response(200))

    def admit(route):
        at_handoff.set()  # Reservation is durable; pause before the final ownership gate.
        assert stopped.wait(timeout=2)
        original_admit(route)

    def stop():
        assert at_handoff.wait(timeout=2)
        run.abort()
        stopped.set()

    monkeypatch.setattr(run, "_admit_dispatch", admit)
    stopper = threading.Thread(target=stop)
    try:
        with (
            pytest.raises(SupervisorStopped),
            run,
            run.model_client(transport=httpx.MockTransport(service)) as client,
        ):
            stopper.start()
            embed(client)
    finally:
        if stopper.ident is not None:
            stopper.join(timeout=3)
            assert not stopper.is_alive()
    service.assert_not_called()
    assert run.counts["embed"] == 1
    assert events(config)[-1]["handoffs"]["embed"] == 0


@pytest.mark.parametrize("mode", ["drain", "cutoff", "writer", "transport"])
def test_finalization_retains_or_explicitly_accounts_for_worker_evidence(config, monkeypatch, mode):
    config = replace(config, evidence_seconds=1 if mode == "drain" else 0.2)
    run = Supervisor(config)
    ready, release, draining = threading.Event(), threading.Event(), threading.Event()
    original_stop, original_event, original_drain = (
        run._request_stop,
        run._event,
        run._drain_evidence,
    )
    previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    outcomes, violations = [], []
    paused = False

    class CheckedJournal:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def write(self, data):
            if self.inner.closed:
                violations.append("write_after_close")
                raise AssertionError("Journal write after close")
            return self.inner.write(data)

        def close(self):
            assert run._lock._is_owned()  # CPython test witness: closure holds the writer lock.
            return self.inner.close()

    def stop(reason):
        nonlocal paused
        original_stop(reason)
        if mode in ("drain", "cutoff") and reason == "dispatch_failed" and not paused:
            paused = True
            ready.set()  # Real ownership stop completed, before response-error publication.
            assert release.wait(timeout=3)

    def event(name, **fields):
        if mode == "writer" and name == "response_error":
            ready.set()  # Caller holds the journal lock; finalization must not wait forever.
            assert release.wait(timeout=3)
        return original_event(name, **fields)

    def drain(deadline):
        draining.set()
        return original_drain(deadline)

    def service(request):
        if mode == "transport":
            ready.set()
            assert release.wait(timeout=3)  # Outstanding attempt cannot finish before cutoff.
        return httpx.Response(500)

    def worker():
        try:
            embed(client)
        except BaseException as error:  # noqa: BLE001 - return all thread failures to assertions.
            outcomes.append(error)

    def release_during_grace():
        assert draining.wait(timeout=2)
        release.set()

    monkeypatch.setattr(run, "_request_stop", stop)
    monkeypatch.setattr(run, "_event", event)
    monkeypatch.setattr(run, "_drain_evidence", drain)
    thread = threading.Thread(target=worker)
    releaser = threading.Thread(target=release_during_grace) if mode == "drain" else None
    client = None
    try:
        with pytest.raises(SupervisorStopped), run:
            run._journal = CheckedJournal(run._journal)
            client = run.model_client(transport=httpx.MockTransport(service))
            thread.start()
            assert ready.wait(timeout=2)
            if releaser:
                releaser.start()
            exit_started = time.monotonic()
        elapsed = time.monotonic() - exit_started
        assert elapsed < 1.5
        assert run._processes[0].poll() == -9
        assert all(signal.getsignal(s) == h for s, h in previous.items())
        assert draining.is_set()
        summary_bytes = (config.output / "finalization.json").read_bytes()
        summary = json.loads(summary_bytes)
        expected = 0 if mode == "drain" else 1
        assert summary["inflight_evidence_unrecorded"] == expected
        assert summary["status"] == ("complete" if mode == "drain" else "incomplete")
        assert summary["journal_writer_unavailable"] is (mode == "writer")
        assert summary["journal_closed"] is (mode != "writer")
        if mode == "drain":
            assert any(
                e["event"] == "response_error" and e["status"] == 500 for e in events(config)
            )
        else:
            assert not any(e["event"] == "response_error" for e in events(config))
            if mode != "writer":
                assert events(config)[-1]["inflight_evidence_unrecorded"] == 1
    finally:
        release.set()
        for item in (thread, releaser):
            if item and item.ident is not None:
                item.join(timeout=3)
                assert not item.is_alive()
        if client:
            client.close()
    assert len(outcomes) == 1 and isinstance(outcomes[0], SupervisorStopped)
    assert violations == [] and run._journal.closed
    assert run._active_attempts == 0
    assert (config.output / "finalization.json").read_bytes() == summary_bytes
    assert (config.output / "finalization.json").stat().st_mode & 0o777 == 0o600


def test_journal_write_failure_is_not_labelled_complete_evidence(config, monkeypatch):
    run = Supervisor(config)
    with pytest.raises(SupervisorStopped), run:
        original_write = run._journal.write

        def write(data):
            if '"event": "response_error"' in data:
                raise OSError("synthetic evidence failure")
            return original_write(data)

        monkeypatch.setattr(run._journal, "write", write)
        with (
            run.model_client(
                transport=httpx.MockTransport(lambda _: httpx.Response(500))
            ) as client,
            pytest.raises(OSError),
        ):
            embed(client)
    summary = json.loads((config.output / "finalization.json").read_text())
    assert summary["status"] == "incomplete"
    assert summary["inflight_evidence_unrecorded"] == 0
    assert summary["journal_errors"] == ["OSError"]
    assert run._journal.closed and run._processes[0].poll() == -9
