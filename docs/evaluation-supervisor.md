# Opt-in evaluation supervisor

`evaluation.supervisor` is a POSIX library for a separately approved test launcher,
not a live command or a new `evaluation.run` mode. It is not enabled by normal API
startup. Tests use synthetic Python children, a real API child, mock transports
and fake loopback HTTP peers, never actual model/database services.

A separately approved private launcher completed one real text HTTP smoke on
2026-11-04 using the optional proxy; see [current status](CURRENT_STATUS.md).
That run verified its own resource controls and shutdown observations. It does
not establish a general deployment-isolation or in-flight cancellation guarantee.

## Required configuration

Supply every required deployment field explicitly (only `proxy_port` is optional):

- `output`: new absolute private run/storage directory; exclusive creation,
  no resume/overwrite. The supervisor never deletes it.
- `model_store`: existing absolute directory, disjoint from output. Its presence
  is checked, not its contents, read-only mount policy or actual service usage.
- `children`: foreground `Child` specs with absolute executable, SHA-256 pin,
  argument tuple and complete environment map. No implicit shell or inherited environment.
  Child working directories are the fresh output directory. Review arguments and
  environment to bind actual service model/storage paths; these cannot be inferred
  from arbitrary executable arguments by this library.
- `model_url`: explicit `http://127.0.0.1:<port>`, with no path, credentials or
  proxy. There is no default endpoint or attach-to-existing mode.
- `embed_model`, `chat_model`, and their nonzero 64-hex artifact digests. Tags are
  enforced on requests; artifact identity must be verified externally before a
  deployment. The library does not inspect a daemon or load models to verify it.
- `num_predict`: explicit positive integer in the validated signed-32-bit range.
- `seconds`, `request_seconds`: positive finite run and request limits; request
  limit cannot exceed the run deadline.
- `evidence_seconds`: explicit positive finite finalization grace, shared by
  outcome draining and writer-lock acquisition **after owned work is stopped**.
  It grants no extra model time. All time limits must fit `threading.TIMEOUT_MAX`.
- `embeddings`, `chats`: positive per-run allowances, at most **9 and 3**.

Missing/invalid configuration fails before dispatch. Executable files are hashed
before launch preparation; use trusted, frozen filesystems, not concurrent hostile
writers. These checks do not attest the deployed binary or runtime isolation.

## Dispatch boundary

Within `with Supervisor(config) as run`, `run.model_client` creates a synchronous
client with a single budgeted transport path. It accepts only POST `/api/embed`
with one text input, or non-streaming POST `/api/chat` with one user message and
exactly the configured `num_predict` option. Other routes, hosts, models, batch
inputs, duplicate JSON keys, missing/boolean caps and extra options are rejected before forwarding.
Redirects, environment proxies and automatic transport retries are disabled.

An atomic lock checks state/deadline and reserves one call **before** forwarding.
The reservation is flushed/fsynced to `events.jsonl` before the one transport
attempt. Failed attempts still spend it. Concurrent calls cannot overspend; a
limit/protocol/transport failure stops the run and owned work, with no retry.
After durable reservation, lifecycle is checked again. A final ownership-locked
admission check is the logical transport handoff, ordered against stop signalling:
if stop wins, forwarding is forbidden; if admission wins, the charged attempt is
in flight. The ownership lock is released before network I/O. Admission is not an
atomic remote socket send: an admitted attempt can race a subsequent stop at
transport entry, but its owned runtime is stopped and late results are rejected.
Terminal `handoffs` counters distinguish admitted attempts from reservations
cancelled by stop; cancelled reservations remain spent.
Response bytes are read within the guarded attempt; a result arriving after
deadline/abort cannot be credited. Narrower caller timeouts are not expanded.

For in-process integration, `RagEngine` accepts an optional `model_client` factory
taking a timeout. Set it to `run.model_client` in an explicitly reviewed launcher;
both embedding and chat then use the same allowances. Omit it and existing client
construction/timeouts remain unchanged. Normal FastAPI startup does **not** inject
this factory. A separate API process needs the explicit proxy wiring described
below; merely starting it as a child does not instrument its calls.

This is a trusted-caller boundary, **not a host/network sandbox**. Direct external
HTTP clients, a different engine factory, unreviewed retrying custom transports
or independently running services can bypass it. Injected transports are an
offline test seam; deployment must use the reviewed no-retry transport. Do not
claim global machine-wide accounting from this application counter.
It counts outbound HTTP attempts, not a server's internal retries or remote
offload; those require separate runtime verification.

## Deadline, ownership and evidence

Lifecycle runs on the main thread; concurrent model clients are allowed. Each
child is freshly spawned with `start_new_session=True`; only those recorded group
IDs are stop targets. There is no PID-input or process-name kill interface. The
elapsed-time deadline starts on entry after output reservation. An independent
monotonic timer stops registered groups even while a request stalls. Dispatch also
checks the deadline. Stop sends SIGKILL to all owned groups before waiting/reaping;
there is no graceful shutdown or deletion. Stop errors are recorded as failures,
not successful completion. Previously reaped group IDs are not signalled again.

Normal finish, dispatch failure, child exit, timeout and context exceptions stop
owned children. Temporary SIGINT/SIGTERM handlers stop owned work and are restored
on exit. A signal/timeout during `Popen` prevents use. On constructor return,
registration and stop-on-handoff are atomic under the ownership mechanism, before
any bookkeeping lock or journal I/O. Signal handlers request the ownership stop
without synchronous journaling. Spawn evidence and updated terminal child/stop
records are retained afterward; no model dispatch is allowed during startup.
Uninterruptible OS spawn/kill operations and scheduler delays are not made
real-time by a Python watchdog. SIGKILL of the controller itself cannot run Python
cleanup. An external containment mechanism is needed if those failures must be
covered by the deployment's hard-stop guarantee.
Python documents both [uninterruptible initial process creation](https://docs.python.org/3/library/subprocess.html#subprocess.run)
and [timer scheduling variation](https://docs.python.org/3/library/threading.html#timer-objects).

Children must remain foreground and keep descendants in their owned groups.
Daemonization, `setsid` escape, remote/offloaded inference and malicious processes
are not contained. A blocked Python/mock worker thread is not forcibly cancelled;
the guarantee tested here is stopping registered external work and refusing late
results. The real runtime's in-flight shutdown still needs approved verification.

Private output contains durable start/spawn/reserve/response/stop events, elapsed times, limits,
pins, source/argv hashes, owned PIDs, return codes and stop errors; per-child logs are exclusive 0600
under a 0700 directory. Raw prompts, response bodies and credentials are not copied
into events, but arbitrary child logs may contain sensitive data. Preserve output
on failure and review it privately. Disk/log growth and parser CPU/RAM are not
bounded by this component. It never deletes storage or stops a shared daemon.
For a later approved real test, take point-count/ID/payload evidence while services
are still running, before normal context exit. SIGKILL can leave database storage
inconsistent; retained files alone are not a validated post-stop database view.
`completed` means the context body ended in time, not that required questions were
asked or answers passed semantic review.
These process-control events are run-specific telemetry, not the deterministic
offline smoke manifest. Stop-request time is not proof of when a real model stopped.

### Optional separate-API budget bridge

`RunConfig.proxy_port` defaults to `None` (no listener). When explicitly enabled,
the supervisor binds only `127.0.0.1` at that port before launching children. The
port must differ from the pinned `model_url` upstream.
Equivalent numeric ports are rejected even if the upstream spelling has leading
zeros; upstream URL validation and identity checks precede output or startup.
At least one child's explicit `OLLAMA_URL` must be the exact proxy URL; conflicting
case variants and child forwarding-proxy environment variables are refused. Configure that child's
model tags and `OLLAMA_NUM_PREDICT` to match the run. Normal `rag.api` startup and
defaults are unchanged. This bridge has no live-run CLI or automatic launcher.

Inbound Host is checked against the proxy, never used to choose the upstream.
Only origin-form `POST /api/embed` and `POST /api/chat`, HTTP/1.1 with unique
headers, JSON content type and a positive bounded Content-Length are supported.
Transfer-Encoding, Expect, content encoding, upgrades, duplicate headers and
alternate paths/targets are refused. Each connection handles exactly one request
and closes; no keep-alive/pipeline reuse or redirect following is supported.
Malformed requests stop the run, rather than offering a fallback route.

Limits are 16 KiB headers, 1 MiB request body, 4 MiB upstream response, and 12
concurrent connections. Inbound framing/body reads share an absolute
`request_seconds` deadline, capped at the run deadline; response sends have a
bounded timeout. Upstream uses no environment proxy, retries or connection reuse;
compressed/non-JSON representations are refused. Response streams are buffered
with size/elapsed checks between reads and bounded per-operation socket timeouts,
then parsed as JSON before the shared transport
records `response` success or the proxy publishes HTTP 200. Empty, malformed,
invalid-encoding and non-JSON numeric-constant bodies fail the charged attempt,
close the upstream response and stop the run without copying body text to events.
This is JSON syntax validation, not a response-schema or answer-quality gate.
These checks are not OS real-time cancellation: a read already in progress can last
until its timeout and Python workers can outlive the evidence grace.

Every accepted connection is an active evidence producer through framing,
dispatch and response publication. `_BudgetTransport` performs the **same**
protocol validation, durable reservation, charged failure and stop-ordered
admission as in-process clients; there is no proxy counter or second reservation.
Connections still reading headers can appear in the conservative cutoff count
without having spent a model reservation. On stop, owned process groups are
signalled/reaped first, then the listener closes and accepted downstream sockets
are shut down without joining workers. Upstream operations settle within their
timeouts or remain explicitly outstanding at evidence cutoff. An idle accept
thread may take its short polling interval to return; it cannot admit after stop.

This is routing for a **trusted application**, not network containment. Validating
the supplied environment does not prove an arbitrary child honors it. The
loopback listener has no authentication; other local callers can consume its
allowance or stop the run. Withholding
the upstream port from API configuration does not make that port unreachable.
Same-host code can discover or directly connect to it. Offline tests establish
the reviewed API's configured route using a real child and fake HTTP peers, not
direct-connect impossibility. A live packet needing that guarantee must supply
separately reviewed OS/network isolation. Never attach to shared daemons or use
this bridge as a general HTTP proxy.

### Bounded evidence finalization

Context exit stops owned work first, without waiting for journal/network work.
It then waits up to `evidence_seconds` for active dispatch/evidence producers,
including unadmitted attempts, to finish their outcome writes. This tracks active
attempts through their evidence cleanup, not cumulative handoff totals. No
ownership lock is held during draining or filesystem I/O. Journal writes and
closure share the writer lock, so a closed check cannot race a write or close.

Each run writes an exclusive private `finalization.json` (0600), separate from the
journal. Its `status` describes **evidence finalization**, not integration success.
`complete` means producers settled with writer access and no recorded journal I/O
failure; a known HTTP failure can have complete evidence. Callers must still await
their workers/results, close their clients and evaluate failures explicitly.

If the grace expires, `inflight_evidence_unrecorded` counts attempts whose outcome
evidence was not fully settled at cutoff. This is a conservative count, not an
assertion that every such attempt reached a model or lost every response field.
`journal_writer_unavailable` separately flags failure to obtain the writer lock;
`journal_error` / `journal_errors` flag observed I/O failures. These conditions make
finalization `incomplete`, and otherwise-normal context exit raises
`SupervisorStopped`. Signal handlers are restored even at cutoff.

When writer access is available, the terminal stop event also carries the cutoff
count before sealing and closing. If a writer remains blocked, the independent
sidecar records incomplete evidence without an unbounded join or unsafe close;
`journal_closed: false` reports deferred closure at that snapshot. Closure is
attempted under the writer lock when a producer/publisher returns. Late outcome
writes are declined after sealing, never written into a closed journal. The
sidecar is not rewritten to turn a timeout into a pass if a worker later returns.

The grace bounds waiting for producers and writer access, not uninterruptible
filesystem syscalls. An OS write/close failure may leave partial artifacts or
propagate an error. Python worker threads are not forcibly cancelled; stalled
producers can outlive context exit, while registered external work is already
stopped. Preserve incomplete artifacts and do not treat them as a successful run.

## Offline evidence and remaining deployment gates

Run `python -m pytest -q tests/test_supervisor.py`. Fixtures use mock transports
and disposable, test-owned Python sleepers/heartbeat descendants. Checks cover
allowance edges/concurrency, failed dispatch accounting, route bypass refusal,
stalled/expired work, partial startup, interruption, process-group stop, unrelated
sentinel survival, event-gated drain/cutoff/deferred-close races, no closed-journal
writes, and actual `RagEngine` factory integration. Earlier failed test
artifacts are not rewritten into passes.

Before any real run, independently review actual executable/model/runtime pins,
paths, service arguments, unused ports, fresh isolated storage, read-only model
access, service readiness/port ownership, foreground process topology, call-path
wiring, resource limits and observed shutdown behavior. The configured loopback
URL is **not proof** it belongs to a spawned child. The library neither inspects nor
launches a deployment automatically and selects no live cap or machine limits.
The completed text smoke is historical evidence for its reviewed configuration;
future live execution still requires a complete private packet and owner approval.
