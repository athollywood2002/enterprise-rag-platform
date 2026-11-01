# Enterprise RAG Platform

**Local-first RAG reference implementation** using Python, FastAPI, Ollama and Qdrant. A portfolio project demonstrating enterprise AI architecture fundamentals: ingestion, vector retrieval, grounded answers, source provenance and test automation.

> **Status: v0.1 prototype.** For local lab use only; not yet production hardened. No employer or customer data.

## Architecture

See [architecture notes and roadmap](docs/architecture.md).

```text
Text -> Normalize / overlapping chunks -> Ollama embeddings -> Qdrant
Document upload -> Unstructured -> page-local/title-aware chunks -> embeddings -> Qdrant
Question -> Ollama embedding -> top-k retrieval -> Ollama chat -> Answer + source excerpts
```

## Prerequisites

- Python 3.11+
- Ollama and a dedicated Qdrant test instance, accessed through localhost or private transport
- Ollama models: `ollama pull nomic-embed-text` and `ollama pull qwen3:8b` (or set your actual installed model tag)

The synthetic live tests used **Qdrant server 1.17.0 with qdrant-client 1.17.0**.
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

- The 10 MiB file check does **not** bound total request bodies, multipart spooling,
  disk use, document expansion, parser CPU/RAM/time or concurrency. Parsing and
  synchronous indexing run in a worker thread, not the event loop; this is not
  process isolation, a durable job queue or a guarantee of cancellation/rollback.
- Missing parser imports and exact built-in resource `LookupError` return opaque
  503s; `KeyError`/`IndexError` are opaque processing 500s. Error text is sanitized,
  not a global log-redaction policy. See [pre-merge corrections](docs/premerge-corrections.md).
- Changed documents can leave stale chunks. Replacement/deletion semantics,
  batching, hybrid retrieval, reranking, retrieval evaluation, observability and
  enterprise identity/authorization remain future work.
- Application protected-name and alias guards are not server-side authorization.
  Never use existing data-bearing collections for tests. See the
  [collection safety policy](docs/collection-safety.md) before ingestion.
- Local inference is not guaranteed deterministic: model temperature/seed are not
  pinned, and reasoning behavior has not been exhaustively tested.

## License

MIT. Contributions welcome.
