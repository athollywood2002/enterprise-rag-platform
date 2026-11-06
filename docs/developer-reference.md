# Development and earlier validation

For a first run, follow the [Docker browser quickstart](../README.md#docker-browser-quickstart). The commands below are alternatives for contributors. Run them from the repository root.

## Offline and synthetic container checks

```bash
python3 -m unittest discover -s demo -p 'test_*.py' -v
node --test demo/n8n/workflow.test.cjs
# Create .env.demo as in the quickstart. Choose a free loopback port.
# A separate project and volumes; synthetic model, real API and Qdrant:
RAG_PORT=18001 docker compose --env-file .env.demo -p rag-demo-ci -f compose.demo.yaml -f compose.smoke.yaml build
RAG_PORT=18001 docker compose --env-file .env.demo -p rag-demo-ci -f compose.demo.yaml -f compose.smoke.yaml up -d --wait --wait-timeout 90
RAG_PORT=18001 docker compose --env-file .env.demo -p rag-demo-ci -f compose.demo.yaml -f compose.smoke.yaml exec -T api python scripts/demo_smoke.py
RAG_PORT=18001 docker compose --env-file .env.demo -p rag-demo-ci -f compose.demo.yaml -f compose.smoke.yaml exec -T api python scripts/library_smoke.py
RAG_PORT=18001 docker compose --env-file .env.demo -p rag-demo-ci -f compose.demo.yaml -f compose.smoke.yaml down
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
read -rs -p 'API key: ' RAG_API_KEY
printf '\n'
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
coverage focuses on text PDFs and TXT. See [parser verification](parser-verification.md),
[HTTP contract](document-http-contract.md) and [migration notes](aiminirig-migration.md).

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
jobs; neither is a live RAG test. [Offline abstention regression](abstention-regression.md)
recognizes limited wordings and sends unsupported phrasing to manual review; it
does not establish semantic grounding.

### Accepted live text HTTP smoke

On 2026-11-04, one separately approved lab run at `4051ca5` passed the real
API → budget proxy → dedicated Ollama/Qdrant text path: unauthorized requests
returned 401, identical reingestion retained one point, and a cited answer
completed within exactly three embedding calls and one chat call. Resource,
finalization and owned-process/GPU shutdown checks passed. See
[current status](CURRENT_STATUS.md) for evidence scope and remaining work.
This run covered the text HTTP path only.

### Synthetic evaluation smoke

From the repository root, run
`python -m evaluation.run --output evaluation-runs/offline-001`.
See the [evaluation CLI guide](evaluation-cli.md) for scope, manifests and
plan-only local gates. This uses real HTTP routes/core with stub services, not
live inference or a quality benchmark.

### Offline development labeling

The [PDF-only excerpt-labeling CLI](labeling-cli.md) displays canonical page
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

[Generation budgets](generation-budget.md) · [Evaluation supervisor](evaluation-supervisor.md) · [Evaluation corpus](evaluation-corpus.md)
