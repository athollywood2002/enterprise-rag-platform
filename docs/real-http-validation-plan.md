# Isolated real HTTP validation

Status: **the scoped text HTTP smoke passed on 2026-11-04**; see
[current status](CURRENT_STATUS.md) for the observed results and limitations.
The completed run used a separately approved private packet. This guide does not
authorize a rerun or provide an executable launcher. The earlier
direct-model startup templates, old code pin, port map and PDF request script are
retired. Do not copy commands from their historical versions into a live packet.
Operational paths, artifact/model pins, credentials and receipts stay private.

## Current implementation and required code pin

The merged [generation cap](generation-budget.md),
[supervisor and optional budget proxy](evaluation-supervisor.md) provide opt-in
controls; they do not change normal API startup or supply an approved live launcher.
The private execution packet must name the **actual independently reviewed fixed
commit**, its code/archive identity and the launcher hash. A base commit that
predates the proxy corrections is not sufficient. This guide intentionally does
not invent a future commit or pin itself to a self-referential documentation commit.

Use a clean, separate checkout at that packet's approved pin. Verify loaded API
code and resolved non-secret configuration, not merely a health response. Keep
other opt-in ingestion strategies and private A/B evidence outside this check.

## Only the reviewed application route is counted

```text
authenticated HTTP caller -> fresh API child -> loopback budget proxy
                                               -> dedicated owned model service
                         -> dedicated owned native database
```

The API child must explicitly use the proxy model endpoint, matching both model
tags and the generation cap. The proxy has one pinned upstream independent of
incoming Host/URL fields. **No direct-model fallback**, alternate client, retries,
streaming or extra protocol options are allowed. Just launching a separate API
child does not inject the supervisor's in-process factory.

Proxy and in-process calls share one supervisor allowance: durable reservation
before forwarding, failed attempts charged, and admission ordered against stop.
Configuration rejects equivalent upstream/proxy endpoints by numeric identity,
including zero-padded port spellings. The proxy bounds upstream bodies and checks
JSON syntax before recording a successful response or publishing downstream 200.
Syntax/protocol acceptance is not an embedding-schema or answer-quality judgment.

The allowance counts only requests through the reviewed route. Port secrecy is
not network isolation; same-host code can connect directly if it knows/discovers
the upstream. The loopback proxy is unauthenticated. The packet must state whether
this trusted-application boundary is acceptable or require real OS/network
containment. Do not claim host-wide accounting from these application controls.

## Validated smoke contract: plain text, not PDF

The completed text smoke followed the smaller contract below. Any future run
requires its own reviewed private setup-and-smoke packet and explicit owner
approval of its execution scope.

1. Start only fresh foreground test services through the reviewed owner. Verify
   executable/model identities, dedicated storage, listener PID ownership,
   readiness and an empty database without making uncounted model calls.
2. Unauthorized plain-text ingestion and question requests must return 401 and
   spend no model allowance.
3. Ingest one tiny synthetic fact through `/ingest`; reingest the identical text;
   ask one authenticated question through `/ask`.
4. Expected attempts: **three embeddings and one chat**, all through the shared
   budget. Record each response before checking it. Set the same explicit cap in
   run configuration and API environment; select its value in the reviewed
   private packet, not by assuming a visible-answer token count. Thinking may
   consume the generation budget. A length stop or timeout is a retained failure,
   not permission to tune or retry.
5. While the database is still running, save exact counts, IDs and payloads after
   ingestion/reingestion. Require one stable point, only the approved new
   collection and no aliases. Inspect the answer, citation and generation metadata;
   HTTP 200 alone is not semantic success.

This tests plain-text HTTP integration and idempotent text ingestion only. It
does **not** validate `/ingest/document`, PDF parsing, page attribution, parser
resources, the earlier three-page/nine-embedding workflow or private pilot quality.
Those require a later separately reviewed document/parser packet. No broader
corpus, private development-set replay, A/B rerun or benchmark claim is included.

## Private packet gates and scope separation

Supply exact reviewed commands and hashes for read-only preflight, isolated
preparation, then service/smoke execution. The owner can approve preparation only;
that does not authorize service startup or inference. No later stage may run if
an earlier gate fails. Never silently patch an old pinned checkout.

- Use a compatible pinned application runtime/dependency set and a pinned native
  foreground database. Do not substitute a Docker client for process ownership.
- Exclusively create a new private root with separate runtime, database, evidence
  and test-model paths. Preserve partial output; no resume, overwrite or cleanup.
- Verify a separate test store containing only selected manifests and every
  referenced blob, with no writable aliases into the shared store. A startup
  no-prune flag or top-level permission observation is not read-only protection.
- Use one explicit private port map for API/proxy/model/database, bound to
  numeric loopback and verified against the fresh owned process identities.
- Verify usable user-manager/controller delegation and actual resource values
  before model-service startup. State which CPU, memory, task/thread, file and
  time limits are enforced. GPU observations are not an enforceable VRAM cap.
- Generate a fresh in-memory API key; never place it in command arguments, public
  Git, manifests, receipts or logs. Clear inherited proxy/RAG configuration.
- Stop on missing capability, pin/configuration drift, preexisting storage,
  unexpected alias/collection, HTTP/protocol error, timeout or exhausted budget.
  No repair, fallback, download of missing models or automatic retry is implied.

## Shutdown evidence is a separate gate

Collect database evidence **before** the supervisor's SIGKILL stop. Retained files
from a killed database are not a validated database view. Stop only fresh owned
process groups and any separately approved fresh control unit; never signal
discovered PIDs or shared daemons. Verify owned worker identities/listeners are
gone and the test control group is empty/absent. Record unrelated GPU changes
without treating ordinary shared activity as proof of a test failure or success.

The accepted private launcher observed only previously captured PID/start-time
identities after supervisor stop, using one 15-second monotonic deadline including
the first sample, queries and sleeps. Samples recorded elapsed time, state, thread
count and GPU visibility. Matching zombies remained present; ambiguous, failed or
late observations could not pass. Acceptance required every captured owned
identity and its GPU entry to disappear, plus the existing shared-service,
listener, finalization and outer-cgroup checks. A later successful observation
could not erase an earlier failure. This observation logic belongs to the private
launcher, not the public supervisor API.

Stop owned work before bounded evidence draining. Require preserved terminal
events and finalization status; an immutable incomplete marker is not a pass.
`complete` describes settled evidence, not successful integration or answers.
Generation caps, socket timeouts and the watchdog are not proof of deployed
inference cancellation. Python workers, escaped/offloaded work, controller
SIGKILL, filesystem stalls and uninterruptible OS operations retain the limits
described in the supervisor guide. Actual runtime shutdown/isolation must be
observed for the approved deployment; offline tests do not establish it.

Report checks, failures and semantic judgments separately. Keep evidence on any
failure, do not stop shared services or inspect protected collections, and obtain
explicit owner approval of the exact private live packet before execution.
