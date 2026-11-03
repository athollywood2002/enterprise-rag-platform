# Draft: isolated real HTTP validation

Status: **proposed, not executed or approved for execution**. Preparation was
approved on 2026-11-03. This document is a reviewable test design and command
template; the machine-specific service-start/stop packet is still outstanding.

## Purpose and fixed scope

Validate the merged default path through a real listening FastAPI process,
real PDF parsing, real Ollama embeddings/generation, and a real Qdrant server.
Use serving code at `6000ccd0202acfaa2cfba814e6c9e5a83abc03a1` in a separate,
clean checkout. PRs #12/#13 are excluded. This is an integration check, not a
repeat of the private A/B pilot or an answer-quality benchmark.

Only the repository-authored three-page fixture and its three questions in
`evaluation.smoke` are admitted. Two authorized uploads, three authorized
questions, plus one unauthorized upload and one unauthorized question.
Expected model calls: nine embeddings and at most three chats; zero for the
unauthorized requests. Exactly three points after each authorized upload;
point IDs and payloads must remain identical on reingestion.

## Required private execution packet

Every field below must be verified and filled in before a run is proposed.
Do not substitute remembered host addresses, floating model tags, placeholder
digests, existing database storage, or the synthetic local-plan example pins.

| Item | Proposed constraint / outstanding evidence |
| --- | --- |
| Machine | Owner-named lab host; identity and current capacity unverified |
| Checkout / Python | Separate clean checkout at the full commit above; absolute interpreter path, package lock/versions and offline parser resources verified |
| API | Proposed `http://127.0.0.1:18772`; unused port; one dedicated process, one worker, no reload |
| Qdrant | Separate disposable server/storage, proposed `http://127.0.0.1:16339`; exact version/image digest; no existing volumes or mounts |
| Ollama | Dedicated approved test instance, proposed `http://127.0.0.1:11435`; exact version, verified installed embedding/chat tags and artifact digests; no pulls |
| Collection | `rag_eval_http_synthetic_001`, only if absent and not an alias on the isolated server; otherwise STOP |
| Credentials | Fresh in-memory API key; never in Git, plan JSON, command arguments, logs or receipts |
| Resource limits | Proposed 15-minute total window; one request at a time; CPU/RAM/VRAM limits selected for the verified models and host |
| Ownership | Exact service-start commands, process/container IDs, storage paths and stop commands for only these test services |
| Review | Independent command review followed by owner approval of the completed packet |

Ports and names are proposals, not evidence of availability. Do not connect to,
inspect, modify, or delete existing collections, including `hdd_knowledge`.
Keep operational identities, actual model pins, credentials and receipts private.

**Blocking implementation detail:** the current `/ask` route accepts only
`question` and `top_k`. It sends no generation-token cap and has no global call
budget. Model HTTP timeouts are 120 seconds for embedding and 180 seconds for
chat; they are not a hard total-time or token budget. A caller timeout does not
cancel server work or unload a model. Before execution, provide and independently
review a supervisor and/or isolated model-service configuration that enforces
the approved resource/time/call limits and stops only owned test processes.
Do not invent unsupported request fields or treat limits in a manifest as enforced.

## Preparation commands (run only in the approved separate checkout)

These command templates are for the future execution packet, not commands run
while drafting this document. Use the verified interpreter as `python`.
Do not install packages, download parser resources, pull models, or modify a
shared environment as an implicit repair.

```bash
test "$(git rev-parse HEAD)" = "6000ccd0202acfaa2cfba814e6c9e5a83abc03a1"
test -z "$(git status --porcelain)"
test ! -e .env
python -m pip check
```

Create one new ignored run directory, fixture and offline parser receipt:

```python
import hashlib
import json
from pathlib import Path
from evaluation.run import new_output, provenance
from evaluation.smoke import FACTS, SOURCE, fixture_identity, fixture_pdf
from rag.documents import parse_document

out = new_output(Path("evaluation-runs/real-http-001"))
data = fixture_pdf()
chunks = parse_document(data, SOURCE)
if [(c.text, c.source, c.number, c.page_number) for c in chunks] != [
    (fact, SOURCE, i, i + 1) for i, fact in enumerate(FACTS)
]:
    raise RuntimeError("STOP: real parser fixture differs from the approved shape")
(out / SOURCE).write_bytes(data)
receipt = {
    "status": "parser-preflight-only",
    "fixture": fixture_identity(),
    "document_sha256": hashlib.sha256(data).hexdigest(),
    "provenance": provenance(),
    "chunks": 3,
    "pages": [1, 2, 3],
}
with (out / "parser-preflight.json").open("x") as f:
    json.dump(receipt, f, indent=2)
```

Use a private umask of 077 for the preparation and subsequent packet. Preserve a
partially created directory on failure; never overwrite, resume or auto-retry.
Freeze the parser receipt and full package inventory before live requests.

## Service startup and verification

The exact bootstrap/stop commands depend on the verified host, service versions,
model artifacts and supervisor; **they are not supplied or authorized here**.
Start new isolated services only through that separately reviewed packet.
No live `evaluation.run` mode exists; `local-plan` cannot launch this test.

The dedicated API process must receive these settings explicitly:
`API_KEY`, `QDRANT_URL=http://127.0.0.1:16339`,
`QDRANT_COLLECTION=rag_eval_http_synthetic_001`,
`OLLAMA_URL=http://127.0.0.1:11435`,
and the verified `OLLAMA_EMBED_MODEL` / `OLLAMA_CHAT_MODEL`.
Do not inherit proxy or unrelated RAG environment settings. Launch the pinned
checkout's `rag.api:app` on loopback port 18772, one worker, without reload.

Before requests, save evidence from the actual API process showing its loaded
code path/hash and resolved non-secret settings; a health response alone cannot
prove collection isolation. Record owned process/container identities.
Verify service versions and installed model digests with read-only requests,
and verify collection absence and alias safety only on the dedicated Qdrant.
Require an otherwise empty test server. Freeze model/service configuration;
no other clients or alias administration during the run.

## Exact HTTP request sequence after all gates pass

The following client template uses a fresh in-memory key shared with the owned
API process by the approved launcher. `RAG_EVAL_API_KEY` is not an API setting;
the launcher must pass the same value to the server as `API_KEY`.
Run under the approved supervisor. Each response is preserved before checking
its status. Any exception/nonexpected result ends the sequence without retry.

```python
import json
import os
from pathlib import Path
import httpx
from evaluation.smoke import QUESTIONS, SOURCE

out = Path("evaluation-runs/real-http-001")
document = (out / SOURCE).read_bytes()
key = os.environ["RAG_EVAL_API_KEY"]
if not key:
    raise RuntimeError("STOP: missing test key")
headers = {"x-api-key": key}

with httpx.Client(
    base_url="http://127.0.0.1:18772",
    trust_env=False,
    follow_redirects=False,
    timeout=httpx.Timeout(600.0, connect=5.0),
) as client:
    def request(name, path, expected, **kwargs):
        response = client.post(path, **kwargs)
        with (out / (name + ".json")).open("x") as f:
            json.dump({
                "status_code": response.status_code,
                "body": response.text,
            }, f, indent=2)
        if response.status_code != expected:
            raise RuntimeError("STOP: unexpected HTTP status")
        return response.json()

    def upload(name, authenticated=True):
        return request(
            name, "/ingest/document", 200 if authenticated else 401,
            headers=headers if authenticated else {},
            files={"file": (SOURCE, document, "application/pdf")},
        )

    upload("01-unauthorized-upload", authenticated=False)
    request("02-unauthorized-ask", "/ask", 401,
            json={"question": QUESTIONS[0], "top_k": 2})
    first = upload("03-upload")
    if first != {"source": SOURCE, "chunks_indexed": 3}:
        raise RuntimeError("STOP: unexpected ingestion result")
    for i, question in enumerate(QUESTIONS, 1):
        request(f"04-question-{i}", "/ask", 200, headers=headers,
                json={"question": question, "top_k": 2})
    second = upload("05-reingestion")
    if second != first:
        raise RuntimeError("STOP: reingestion result differs")
```

The 600-second read timeout accommodates sequential per-chunk embedding calls;
it is an inactivity timeout, not the approved supervisor's hard wall-clock bound.
No reconnect/retry loop, embeddings probe or extra question is permitted.
Read-only database inspection checkpoints and model-call accounting belong in
the reviewed supervisor packet: after unauthorized requests, after first upload,
and after reingestion. Save exact point counts, IDs and source/page/text payloads;
do not infer idempotency solely from `chunks_indexed`.

## Pass, fail and stop criteria

- Unauthorized calls return 401 and cause zero parser/model/database work.
- Real parser preflight yields exactly the authored facts on pages 1, 2 and 3.
- First upload creates only the approved collection and exactly three points.
- Inspect both answerable responses: facts must be correct, their supporting
  excerpts retrieved, and citations must resolve to the correct source/page.
  A missing fact or citation is a failure to report, not permission to rerun.
- The lunar-railway negative must acknowledge insufficient evidence without
  inventing an answer. Real Qdrant may return sources for this negative.
  Do not require an empty source list or count a 200 response as semantic success.
- Reingestion preserves all three point IDs and payloads and adds no points.
- Observed call counts remain within nine embeddings and three chats, with no
  unapproved requests, retries, models, files, collections or service changes.
- Stop on configuration/hash drift, preexisting collection/alias, missing model,
  parser mismatch, HTTP error, timeout or resource/call-limit breach. Preserve
  partial responses and sanitized failure evidence. No automatic recovery.

On completion or abort, the supervisor stops only owned test processes, including
in-flight generation as supported and verified for the chosen runtime. Preserve
storage and receipts; no collection/volume deletion, model removal, restart of
shared services or cleanup is included. Report integration checks and semantic
judgments separately. Do not report a benchmark score or general accuracy gain.
