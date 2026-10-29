# AiMiniRig ingestion integration

## Origin

Adapted from `unstructured-lab/src/parse_files.py`, `chunk_files.py`, `embed_chunks.py`,
`load_qdrant.py` and `ask_rag.py` in the owner's March 2026 AiMiniRig prototype.

We retained Unstructured's `partition()` and `chunk_by_title()` parameters:
`max_characters=1200`, `new_after_n_chars=1000`,
`combine_text_under_n_chars=200`, `multipage_sections=True`.

## Differences

- File parsing uses temporary files, not hardcoded home-directory mounts.
- Uploads are capped at 10 MiB and restricted to supported extensions.
- Source metadata preserves the user-visible filename and page number without leaking
  temporary or local absolute paths.
- Multiple chunks from the same page remain distinct; no filename/page deduplication.
- No unrestricted-search fallback when a document filter has no matches.
- A new Qdrant collection is used by default. **Never point this at `hdd_knowledge`.**
- Ollama embeddings use `/api/embed`, not the deprecated `/api/embeddings`.

## Test locally

Install `pip install -e '.[dev,documents]'` into an isolated virtual environment.
Then set `API_KEY` in `.env`, confirm Ollama and Qdrant endpoints, and start FastAPI.
Upload a non-sensitive sample PDF via:

```bash
curl -X POST http://127.0.0.1:8000/ingest/document \
  -H "x-api-key: $RAG_API_KEY" \
  -F "file=@sample.pdf"
```

Verify that `/ask` returns provenance for the correct filename/page.

## Remaining work

PDF parsing may require system packages such as Poppler or Tesseract depending on file
content and parsing strategy. This prototype has no OCR confidence measurement, full
document lifecycle, tenant authorization, or persistent audit logs. Do not expose it
to the public Internet.
