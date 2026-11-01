# Enterprise RAG Platform

**Local-first RAG reference implementation** using Python, FastAPI, Ollama and Qdrant. A portfolio project demonstrating enterprise AI architecture fundamentals: ingestion, vector retrieval, grounded answers, source provenance and test automation.

> **Status: v0.1 prototype.** For local lab use only; not yet production hardened. No employer or customer data.

## Architecture

See [architecture notes and roadmap](docs/architecture.md).

```text
Text -> Normalize / overlapping chunks -> Ollama embeddings -> Qdrant
Question -> Ollama embedding -> top-k retrieval -> Ollama chat -> Answer + source excerpts
```

## Prerequisites

- Python 3.11+
- Existing Ollama endpoint (11434) and Qdrant endpoint (6333), locally or on your private lab network
- Ollama models: `ollama pull nomic-embed-text` and `ollama pull qwen3:8b` (or set your actual installed model tag)

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
# Edit API_KEY and model names in .env; URLs should point at your local lab.
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

## Key design choices

- **Local-first:** no required external inference API.
- **Source evidence:** return scored retrieved chunks with every answer, rather than only model-written citations.
- **Reproducible:** documented environment variables and basic CI tests.
- **Safety:** API key for demo endpoints, no sensitive fixtures, and explicit limits in architecture documentation.

## Limitations and next steps

Current ingestion is **text via JSON**, not PDF upload; PDF parsing, hybrid retrieval, reranking, authorization, observability, and robust retrieval evaluation are planned improvements. This intentionally avoids claiming unfinished capabilities. Large documents should be split by the client or processed through a future ingestion worker. For long-term operation, document IDs, replacement semantics and deletion must be added (reingesting changed content currently leaves older chunks present).

## License

MIT. Contributions welcome.

## Document-aware ingestion (AiMiniRig migration branch)

This branch integrates the Unstructured title-aware parsing strategy from AiMiniRig.

Install the optional parsing dependencies with `pip install -e '.[dev,documents]'`.
Then upload a **non-sensitive sample document** (10 MiB maximum):

```bash
curl -X POST http://127.0.0.1:8000/ingest/document \
  -H "x-api-key: $RAG_API_KEY" -F "file=@sample.pdf"
```

The response includes the number of indexed chunks. Query with `/ask` and inspect
`sources[].page_number` and `sources[].chunk`.

See [AiMiniRig migration notes](docs/aiminirig-migration.md).
Parsing supports the file extensions listed there; some formats require additional
OS dependencies. This code has not yet passed a live document-to-answer test.
