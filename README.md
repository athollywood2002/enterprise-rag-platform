# Enterprise RAG Platform

## Folder ingestion web interface

Open **http://localhost:18000/** with the Docker quickstart below. Select a browser
folder or a configured read-only server root, preview files, start ingestion,
recover saved jobs, and ask questions with citations. The managed library supports
UTF-8 TXT/CSV and text-based PDFs through a pinned parser in the image.

See [setup, limits, identity/update semantics and API usage](docs/folder-library.md)
and the [actual UI walkthrough](docs/ui-walkthrough.md). Jobs and staged uploads
persist in a dedicated SQLite volume. Legacy API/n8n routes remain compatible.


**Local-first RAG reference implementation** using Python, FastAPI, Ollama and Qdrant. A portfolio project demonstrating enterprise AI architecture fundamentals: ingestion, vector retrieval, grounded answers, source provenance and test automation.

> **Status: v0.1 prototype.** For local lab use only; not yet production hardened. No employer or customer data.

See [current status](docs/CURRENT_STATUS.md) for the distinction between `main`,
draft candidates, the accepted live text HTTP smoke and the private provisional pilot.

## Architecture

See [architecture notes and roadmap](docs/architecture.md).

```text
Text -> Normalize / overlapping chunks -> Ollama embeddings -> Qdrant
Document upload -> Unstructured -> page-local/title-aware chunks -> embeddings -> Qdrant
Question -> Ollama embedding -> top-k retrieval -> Ollama chat -> Answer + source excerpts
```

## Docker quickstart and existing text/CSV demo

The web UI supports TXT, CSV and text-based PDF through `/library/*`.
The existing n8n/CLI demo continues using `/ingest` for TXT and labeled CSV text;
it does not need the optional legacy Unstructured parser. Image tag: **`enterprise-rag-platform:folder-ui-v1`**
(local build, no registry publication). The image uses the frozen Linux amd64
Python 3.12 text-runtime wheel lock; Apple Silicon runs it under emulation.
Qdrant is pinned to **`qdrant/qdrant:v1.17.0`**, accessible only within the
Compose network, with a dedicated project-scoped `demo-qdrant` volume.
The API collection is fixed to `rag_text_csv_demo_v1`. No shared Qdrant URL or
storage path is accepted by this Compose setup.

Prerequisites: Docker Engine/Desktop with Compose v2 (`up --wait` support),
and an existing Ollama endpoint with an installed embedding and chat model.
Check the model names first; this setup does not start, upgrade or pull models
into Ollama. Host-loopback-only Ollama may not be reachable from a Linux container.
If it is unreachable, stop and review the route; do not change its listener
silently. Existing Ollama and Open WebUI remain independently managed.

**Completed historical validation:** PR #21's actual two-host manual n8n demo
passed on November 5, 2026 with a correct ORION/NetworkOps answer and both citations.
The separate bounded two-page PDF test also passed and was explicitly accepted by
the owner. Both are closed; neither is a general retrieval benchmark. The new
folder UI/parser implementation has its own unit, container and browser checks;
see [current status](docs/CURRENT_STATUS.md) and [walkthrough](docs/ui-walkthrough.md).
Synthetic CI replies are never evidence of real-model quality.

### Start

From the repository root, generate a private local configuration (fails if
`.env.demo` already exists, preserving your existing configuration):

```bash
umask 077
python3 - <<'PY'
from pathlib import Path
import secrets
text = Path(".env.demo.example").read_text()
text = text.replace("RAG_API_KEY=\n", "RAG_API_KEY=" + secrets.token_urlsafe(32) + "\n")
with open(".env.demo", "x") as output:
    output.write(text)
PY
# Edit .env.demo: choose the existing OLLAMA_URL and installed model tags.
# On Linux, host.docker.internal is mapped to the Docker host gateway.
docker compose --env-file .env.demo -f compose.demo.yaml config --quiet
docker compose --env-file .env.demo -f compose.demo.yaml build
docker compose --env-file .env.demo -f compose.demo.yaml up -d --wait --wait-timeout 90
curl --fail --silent --show-error http://127.0.0.1:18000/health
```

The default API listener is loopback-only. `/health` reports API process health,
not Ollama or database readiness. Do not print the expanded Compose configuration:
it contains the API key. `.env.demo` is ignored by Git and excluded from the image.

### Test

For a CLI smoke using the configured Ollama endpoint:

```bash
docker compose --env-file .env.demo -f compose.demo.yaml exec -T api python scripts/demo_smoke.py
```

This checks unauthorized 401s, ingests `runbook.txt` and the CSV converted to
labeled text under `inventory.csv`, then asks:
“What is the recovery code for demo-router-01 and which team owns it?”
Expected: **ORION**, **NetworkOps**, both filenames in the sources, and citations
resolving to both sources. Each file is one chunk; this sequence makes three
embedding requests and one chat request. It is not the private budget-supervised
PDF test. The script prints the raw answer before assertions, so failures remain
inspectable. Semantic contradictions still require human review; these small
fixture checks are not a grounding evaluator.

Alternatively, run the same demo manually through the
[importable n8n workflow](demo/n8n/text-csv-demo.json), following the
[import and two-host setup instructions](demo/n8n/README.md). For the requested
one-workflow live demo, use n8n as the inference test; do not also run the CLI
smoke against the live model beforehand. n8n reads the files where n8n runs,
not from the Mac or the API container. Set its API URL to the reviewed private
listener, and use an HTTP Header Auth credential (`x-api-key`) on all three
HTTP nodes. No secret or credential ID is included in the export.

Before a two-host run, review actual private addresses/ports, the n8n-readable
folder, and Ollama model tags. Make only the RAG API reachable from n8n; Qdrant
has no published ports. Do not change running n8n, Ollama, Open WebUI or network
rules as an implicit setup step. The completed private PDF smoke is a separate historical test, not permission for another live run.

### Stop

```bash
docker compose --env-file .env.demo -f compose.demo.yaml down
```

This stops/removes only the demo Compose containers/network and retains the demo
Qdrant and library-state volumes. It does not stop Ollama, Open WebUI or n8n. There is deliberately no
volume-delete command in the live quickstart. Verify that this project name is
unused before first deployment; never attach existing Qdrant storage.

### Offline and synthetic container checks

```bash
python3 -m unittest discover -s demo -p 'test_*.py' -v
node --test demo/n8n/workflow.test.cjs
# A separate CI-only project and volume; stub inference, real API/Qdrant:
RAG_API_KEY=ci-only-disposable-demo-key docker compose -p rag-demo-ci -f compose.demo.yaml -f compose.smoke.yaml build
RAG_API_KEY=ci-only-disposable-demo-key docker compose -p rag-demo-ci -f compose.demo.yaml -f compose.smoke.yaml up -d --wait --wait-timeout 90
RAG_API_KEY=ci-only-disposable-demo-key docker compose -p rag-demo-ci -f compose.demo.yaml -f compose.smoke.yaml exec -T api python scripts/demo_smoke.py
RAG_API_KEY=ci-only-disposable-demo-key docker compose -p rag-demo-ci -f compose.demo.yaml -f compose.smoke.yaml exec -T api python scripts/library_smoke.py
RAG_API_KEY=ci-only-disposable-demo-key docker compose -p rag-demo-ci -f compose.demo.yaml -f compose.smoke.yaml down
```

Do not run the CI override on a live-demo project: it intentionally substitutes
synthetic Ollama responses. The GitHub `docker-demo` job builds and tests this
isolated stack without pushing an image. The Code-node tests execute exported
JavaScript in a harness; they do not claim an n8n engine/import test.

## Prerequisites

- Python 3.11+
- Ollama and a dedicated Qdrant test instance, accessed through localhost or private transport
- Ollama models: `ollama pull nomic-embed-text` and `ollama pull qwen3:8b` (or set your actual installed model tag)

Earlier synthetic live tests used **Qdrant server 1.17.0 with qdrant-client 1.17.0**.
The accepted 2026-11-04 text HTTP smoke used **server 1.17.0 with client 1.17.1**.
The client dependency is restricted to `>=1.17,<1.18` to stay within that minor
version while allowing patch updates. Other client/server pairings have not been
live-tested here; check compatibility before using a different server version.
Development dependencies pin **Ruff 0.17.3**, the CI-validated lint/format version.
These selective pins are not a complete dependency lock or a security-update policy.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
# Edit API_KEY and model names in .env; URLs should point at your local lab.
# Set QDRANT_COLLECTION to a new disposable test collection; never use existing data.
uvicorn rag.api:app --app-dir src --host 127.0.0.1 --port 8000
```

In another shell:

```bash
export RAG_API_KEY='the-secret-you-configured-in-.env'
curl -s -X POST http://127.0.0.1:8000/ingest \
  -H "x-api-key: $RAG_API_KEY" -H 'content-type: application/json' \
  -d '{"source":"example.txt","text":"A RAG platform uses retrieved documents to support answers."}'
curl -s -X POST http://127.0.0.1:8000/ask \
  -H "x-api-key: $RAG_API_KEY" -H 'content-type: application/json' \
  -d '{"question":"What supports the answers?","top_k":5}'
python -m pytest -q
```

## Document upload

Install optional parsing dependencies in the isolated environment:

```bash
pip install -e '.[dev,documents]'
curl -X POST http://127.0.0.1:8000/ingest/document \
  -H "x-api-key: $RAG_API_KEY" -F "file=@synthetic-sample.pdf"
```

The multipart file-content limit is 10 MiB. Successful responses contain `source`
and `chunks_indexed`; `/ask` returns excerpts with filename, chunk index, score
and `page_number` when known. Unknown pages remain unknown. PDF extraction uses
local fast/text-only parsing, with page-local title-aware chunks; scanned/OCR,
encrypted and textless PDFs are not supported.

The extension allowlist also includes TXT, DOCX, PPTX, XLSX, HTML/HTM, MD, CSV,
EML and MSG. These routes depend on installed parser/OS capabilities; being
allowlisted is not evidence of full format validation. Real automated parsing
coverage focuses on text PDFs and TXT. See [parser verification](docs/parser-verification.md),
[HTTP contract](docs/document-http-contract.md) and [migration notes](docs/aiminirig-migration.md).

## Tests and observed scope

Base tests run with `python -m pytest -q` (or `pytest -q`). For optional real
parser tests, install the recorded test extra and setup-time language resources:

```bash
pip install -e '.[dev,parser-tests]'
python -m nltk.downloader -d .venv/nltk_data punkt_tab averaged_perceptron_tagger_eng
python -m pytest -q --run-document-tests
python -m ruff check .
python -m ruff format --check .
```

Tests block live database/inference access. CI runs base-only and parser-enabled
jobs; neither is a live RAG test. [Offline abstention regression](docs/abstention-regression.md)
recognizes limited wordings and sends unsupported phrasing to manual review; it
does not establish semantic grounding.

### Accepted live text HTTP smoke

On 2026-11-04, one separately approved lab run at `4051ca5` passed the real
API → budget proxy → dedicated Ollama/Qdrant text path: unauthorized requests
returned 401, identical reingestion retained one point, and a cited answer
completed within exactly three embedding calls and one chat call. Resource,
finalization and owned-process/GPU shutdown checks passed. See
[current status](docs/CURRENT_STATUS.md) for evidence scope and remaining work.
The launcher and raw receipts remain private; this is not a new public CLI mode,
a document/PDF test or a retrieval-quality benchmark.

### Synthetic evaluation smoke

From the repository root, run
`python -m evaluation.run --output evaluation-runs/offline-001`.
See the [evaluation CLI guide](docs/evaluation-cli.md) for scope, manifests and
plan-only local gates. This uses real HTTP routes/core with stub services, not
live inference or a quality benchmark.

### Offline development labeling

The [PDF-only excerpt-labeling CLI](docs/labeling-cli.md) displays canonical page
text and records uniquely matched supporting spans as development drafts. It needs
an explicitly supplied, rights-admitted canonical JSON manifest, not running
services or parser packages. Run `python -m evaluation.label --help` from this
repository root. Type/difficulty are explicit; no holdout mode or secrecy claim.
Real annotation remains owner/review gated; the tests use synthetic data only.

A separately run two-page synthetic fixture at `fa6c9e5` established ingestion,
page provenance, answer/citation selection, manually reviewed abstention and stable
exact-byte reingestion (2 points before and after). Its first automated harness
stopped on an abstention-detector false negative; later offline replay does not
make it an uninterrupted automated pass. A separate single raw-answer sample had
no reasoning tags. Two points queried with top_k=2 did **not** establish retrieval
selectivity or retrieval-quality metrics. These are scoped lab observations, not
production-readiness claims.

## Key design choices

- **Local-first:** no required external inference API.
- **Source evidence:** return scored retrieved chunks with every answer, rather than only model-written citations.
- **Reproducible:** documented environment variables and basic CI tests.
- **Safety:** API key for demo endpoints, no sensitive fixtures, and explicit limits in architecture documentation.

## Limitations and next steps

- **Legacy `/ingest/document`:** the 10 MiB file check does **not** bound total request bodies, multipart spooling,
  disk use, document expansion, parser CPU/RAM/time or concurrency. Parsing and
  synchronous indexing run in a worker thread, not the event loop; this is not
  process isolation, a durable job queue or a guarantee of cancellation/rollback.
- **Legacy `/ingest/document`:** missing parser imports and exact built-in resource `LookupError` return opaque
  503s; `KeyError`/`IndexError` are opaque processing 500s. Error text is sanitized,
  not a global log-redaction policy. See [pre-merge corrections](docs/premerge-corrections.md).
- **Legacy `/ingest` and `/ingest/document`:** changed documents can leave stale
  chunks; these synchronous endpoints do not provide managed replacement or durable jobs.
  The [folder library](docs/folder-library.md) does provide persisted jobs, bounded
  parsing and committed document replacement in separate managed collections.
  It does not automatically delete documents absent from a later selection.
- Hybrid retrieval, reranking, broad retrieval evaluation, enterprise observability
  and identity/authorization remain future work.
- Application protected-name and alias guards are not server-side authorization.
  Never use existing data-bearing collections for tests. See the
  [collection safety policy](docs/collection-safety.md) before ingestion.
- Local inference is not guaranteed deterministic: model temperature/seed are not
  pinned, and reasoning behavior has not been exhaustively tested.
- [Optional generation token budget](docs/generation-budget.md): unset by default;
  termination evidence distinguishes limited, empty and unknown chat results.
  This is not a wall-time limit or cancellation mechanism.
- [Opt-in evaluation supervisor](docs/evaluation-supervisor.md): bounded model
  dispatch and fresh child-process ownership, with offline tests and one scoped
  live text HTTP smoke; not enabled by normal API startup or a substitute for
  reviewed deployment isolation.

## License

MIT. Contributions welcome.

The next real-model UI milestone is a [bounded mixed-folder test](docs/live-folder-ui-test-plan.md), planned separately from synthetic CI.
