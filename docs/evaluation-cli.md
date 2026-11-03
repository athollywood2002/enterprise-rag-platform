# Synthetic evaluation CLI

Run from the repository root with Python 3.11+ and the project's base/dev
dependencies already installed, with `rag` installed editable from this checkout
(as in the README). For an existing shared environment, prefix commands with
`PYTHONPATH=src` instead; the CLI refuses mismatched source imports so its code
hashes describe the code actually exercised. No optional parser package, model, service or
download is needed for the default smoke.

```bash
python -m evaluation.run --output evaluation-runs/offline-001
```

Each command requires a new output directory. It writes a private (0700) directory
and exclusive `manifest.json` (0600); existing output, symlink ancestors and `..`
paths are refused. Nothing is resumed, overwritten, deleted or retried. The
repository ignores `/evaluation-runs/`; keep other output locations out of Git.
These are local trusted-user path checks, not protection against a concurrent
hostile filesystem writer.

## What offline smoke covers

An authored, deterministic three-page PDF goes through the real authenticated
FastAPI `/ingest/document` and `/ask` routes in-process, using the real `RagEngine`.
The parser, embedding/chat transport and storage are explicit stubs. Socket and
real Qdrant-client construction guards are active before engine construction.
Patches restore on exit; no existing API dependency cache or collection is used.

Checks cover authentication, multipart ingestion, source/page propagation, fixed
stub rank selection, empty retrieval and stable IDs on exact reingestion. There
are two uploads and three questions; expected counts are nine **stub** embeddings,
two **stub** chats, two parser passes, three searches and three in-memory points.
The third question deliberately receives empty retrieval. This checks a code
branch, not semantic abstention. The answers are scripted, not quality evidence.

The fixture is a valid PDF, but parsing it is stubbed here. An optional isolated
real-parser preflight is available in the tests; it is not live-service testing:

```bash
python -m pytest -q tests/test_evaluation_run.py
# Only with the existing parser-tests environment/resources installed:
python -m pytest -q tests/test_evaluation_run.py --run-document-tests
```

## Manifest and replay

Schema `rag-synthetic-evaluation-v1` records mode/status, fixture and question
hashes, relevant code hashes, Git commit/dirty flag, Python/package versions,
explicit zero real network/model/database operations, scope limits and results.
Timestamps, durations, credentials and absolute filesystem paths are omitted.
In the same code/environment state, offline manifests are byte-identical. This
does not make real inference deterministic. Exit codes: 0 passed/planned, 1 smoke
failed, 2 invalid arguments/configuration/output. A smoke failure retains a
sanitized failed manifest without raw exception text; interrupts and output-write
failures can leave an incomplete directory, which must be preserved and inspected.

## Local approval plan only

There is deliberately no live dispatch implementation in this slice: a client
cannot yet prove that a running API is configured for a new isolated collection.
The plan mode validates intent and records unmet gates; it contacts nothing and
cannot certify a machine, model or collection.

Create `evaluation-runs/local-config.json` with exactly these fields (use actual
model tags/digests when proposing a real test):

```json
{
  "machine": "lab-proposal",
  "api_url": "http://127.0.0.1:8000",
  "collection": "rag_eval_http_proposal_001",
  "embed_model": "synthetic-embed:plan-only",
  "embed_digest": "1111111111111111111111111111111111111111111111111111111111111111",
  "chat_model": "synthetic-chat:plan-only",
  "chat_digest": "2222222222222222222222222222222222222222222222222222222222222222"
}
```

```bash
python -m evaluation.run --mode local-plan \
  --local-config evaluation-runs/local-config.json \
  --output evaluation-runs/local-plan-001
```

The example pins are placeholders, not verified artifacts. Only numeric loopback
HTTP URLs with an explicit port and no credentials/path/query are accepted. The
collection must use `rag_eval_http_` and pass the protected-name guard. Digests
must be nonzero lowercase 64-hex values; syntax validation is not verification.
Never put credentials in this file or its manifest.

The result is `planned-not-executed`, with `execution_allowed`,
`collection_absence_verified` and `model_presence_verified` all false. Before a
separately implemented live test, obtain owner approval and independent review of
machine/services, isolated storage/collection, model/resource pins, bounds and
literal commands. Confirm collection absence and alias safety server-side; verify
the API's actual configuration, preflight the real parser, and bound time/calls.
Do not use `hdd_knowledge`, existing collections, private pilot inputs or holdout.
Do not infer SSH/Docker/inference/write authorization from machine availability.
