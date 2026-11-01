# Review: enterprise-rag-platform

- **Repo:** https://github.com/athollywood2002/enterprise-rag-platform
- **Date:** 2026-11-01
- **Scope:** `main` (`1f36d3b`), all 4 feature branches, draft PRs #1–#4, CI history, repo settings
- **Method:** Read-only review in a throwaway clone. Ran tests and ruff locally. Nothing was changed or pushed on GitHub.

---

## Overall

This is a well-scoped prototype, and it's honest about its limits. The README and the architecture doc say clearly what isn't done, which is good for a portfolio project. The security instincts are sound: constant-time API key comparison, input size limits, error messages that don't leak data, and tests that can't reach real services.

The weak points are **performance and scaling on the ingestion path**, a **few real bugs in the upload branch**, and **process and presentation**: docs that contradict each other, a CI gap, and how heavy the safety work has become compared with the core code.

## What's there

- **`main`:** 13 files, about 190 lines of Python. A text-only RAG pipeline: FastAPI → Ollama embeddings → Qdrant → Ollama chat. 3 tests pass.
- **Branches:** four draft PRs stacked on each other (#1 → #2 → #3 → #4). Together they add about 1,660 lines, mostly tests and docs. They add document upload (PDF, Office files, email and others), page-number tracking, and protection for the Qdrant collections.
  - Top of stack (`feature/document-http-tests`): 160 passed, 26 skipped (base install). CI green on #3 and #4.
- **Secrets / private data:** I scanned every branch for IPs, home paths, tokens, keys and hostnames. **Nothing found.** `.env` is gitignored and `.env.example` only has placeholders.

| PR | Branch | Targets | Purpose |
|---|---|---|---|
| #1 | `feature/aiminirig-unstructured-ingestion` | `main` | Document upload + Unstructured parsing |
| #2 | `feature/protected-qdrant-collections` | #1 | Blocks writes to protected collections and aliases |
| #3 | `feature/parser-provenance-tests` | #2 | Keeps page numbers correct + parser tests |
| #4 | `feature/document-http-tests` | #3 | HTTP contract tests + errors that don't leak data |

---

## Findings

### 🔴 High

- [ ] **1. Uploads block the whole server** (PR #4, `src/rag/api.py:80`)
  `ingest_document` is `async def`, but it calls slow blocking code inside: the Unstructured parser and, for every chunk, an embedding request with a 120-second timeout. While one upload is processed, every other request waits, including `/health`.
  *Fix:* make it a plain `def` endpoint, or wrap the work in `run_in_threadpool`.

- [ ] **2. Ingestion is very slow and scales badly** (`src/rag/core.py`, every branch)
  Chunks are embedded one at a time. On the branches, each chunk also triggers 4–5 Qdrant calls (`get_aliases` twice, `collection_exists`, `get_collection`) before one final write. The largest allowed `/ingest` (250k characters) makes about 333 chunks, which means about 333 embedding requests and about 1,500 Qdrant calls in a single HTTP request.
  *Fix:* send texts to Ollama's `/api/embed` as a list (batched), and check the collection once per request.

- [ ] **3. Uploads have no real resource limit**
  The 10 MiB check happens only after the whole upload has already been saved to disk. A small `.docx` or `.xlsx` can also expand into huge content when parsed. Nothing caps parse time, memory or chunk count. The docs say this openly, but it's the biggest remaining denial-of-service risk once the server is reachable by anyone other than you.

### 🟠 Medium

- [ ] **4. `except (ImportError, LookupError)` → 503 is too broad** (`src/rag/api.py:98`)
  `LookupError` also covers `KeyError` and `IndexError`, so a real bug in the parser would be reported as "Document parser is unavailable" (503) and hidden. Catch the NLTK resource error specifically.

- [ ] **5. Wrong documents could be returned after re-ingesting**
  Point IDs are built from the source name, chunk number and chunk text. Re-uploading a changed `report.pdf` adds new chunks next to the old ones. Two different files with the same filename also mix together under one `source`. As a result, `/ask` can cite out-of-date content. (Already documented as a limitation.)

- [ ] **6. Qwen3 may include its reasoning in answers** (`core.py`, `ask`)
  `qwen3:8b` is a "thinking" model. Depending on your Ollama version, its reasoning can appear in `message.content` as `<think>…</think>` text unless you send `"think": false` or strip it. **Check this on the rig.**

- [ ] **7. Prompt structure is weak**
  The instructions, retrieved text and question all go into one user message. Putting the rules in a system message, and clearly marking where each excerpt starts and ends, would make prompt injection harder.

- [ ] **8. The README contradicts itself** (branches)
  The "Limitations" section still says ingestion is "text via JSON, not PDF upload". The new upload docs were added *after* the License section.

### 🟡 Low / polish

- [ ] **9. Lint fails on every branch, and CI doesn't run it.**
  `ruff check` reports import-order errors in `src/rag/api.py` and `tests/test_core.py` on `main`, and in `tests/test_core.py` and `tests/test_documents.py` on the top branch. `ruff` is listed as a dev dependency but never runs in CI. Add `ruff check` and `ruff format --check` as CI steps.
- [ ] **10. CI could be tighter.** There's no `permissions:` block, so the workflow gets the default token permissions. Actions are referenced by version tag rather than commit SHA. There's no pip cache. The base job tests Python 3.11 and the parser job tests 3.12, so neither version is tested end to end.
- [ ] **11. Dependency pins don't match.** The `documents` extra allows `unstructured[all-docs]>=0.16,<1`, but the tests pin `unstructured[pdf]==0.18.32`, so what users install isn't what CI tests. There's no lock file. `pypdf` is a core dependency on `main`, where nothing uses it. `pyproject.toml` has no `[build-system]` section.
- [ ] **12. Weak API keys are accepted.** The placeholder `replace-with-a-long-random-secret` would work as a real key. Enforce a minimum length or reject the placeholder.
- [ ] **13. Text ingested through `/ingest` shows "page None" to the model.** Those chunks have no page number, so the prompt literally contains `page None`. Leave the page out when it's missing.
- [ ] **14. Small code issues:**
  - `ingest_chunks` takes an `Iterable` but tests it with `if not chunks`, which is always true for a generator; the later `if not points` check rescues it.
  - `Chunk` and `DocumentChunk` are near-duplicate classes.
  - `/ask` runs the embedding before checking whether the collection exists.
  - `/ingest` doesn't turn `UnsafeCollectionError` into a 403 the way `/ingest/document` does.
- [ ] **15. Filename cleaning lets some characters through.** It rejects ASCII control characters but not DEL or Unicode direction-override characters (for example U+202E). The cleaned filename is shown to the model and returned to the user.

### 🔵 Process / presentation

- [ ] **16. The safety work is out of proportion.** The collection-safety module is 29 lines with 267 lines of tests. With PR descriptions full of "do not merge" and hundreds of lines of docs, the repo now reads more as defensive scaffolding than as a RAG system. Real gaps remain: no batching, no retrieval evaluation, and no end-to-end run against live Ollama and Qdrant.
- [ ] **17. A private system's name appears in a public repo.** `hdd_knowledge` and "AiMiniRig" (the name of the private `aiminirig-monitoring` repo) are in the code and docs. That's harmless, but decide whether that's what you want.
- [ ] **18. No branch protection on `main`, and repo metadata is empty.** There's no description or topics, and every commit on `main` is a one-file "Add RAG starter: X" commit.
- [ ] **19. The stack is 4 draft PRs deep with no live test.** None has run the full upload → Ollama → Qdrant → answer flow live. That one live run is the most important missing check before any merge.

---

## Strengths worth keeping

- The honest limits sections in the README and architecture doc.
- Constant-time API key comparison, now with a UTF-8 fix so non-ASCII keys get a 401 instead of a 500.
- Validation errors on the upload route don't echo back the rejected input.
- Tests block network and DNS access, so they never touch real services.
- The PR #3 fix that stops facts from different PDF pages from being labeled with the same page. It's a real bug, reproduced and fixed with a test.
- PR descriptions say which tests were actually run and don't overclaim.

## Suggested order of work

1. Fix the blocking upload endpoint (#1), batch the embeddings, and check the collection once per request (#2).
2. Narrow the 503 exception handling (#4), and check whether Qwen3's reasoning text leaks into answers (#6).
3. Run one live end-to-end test on the rig, then merge the stack.
4. Rewrite the README as one consistent document (#8) and add ruff to CI (#9).
5. Add document IDs with replace and delete (#5) and a simple retrieval evaluation, which shows more architecture skill than more guard code.
