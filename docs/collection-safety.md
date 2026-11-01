# Protected collection write policy

## Decision

2026-11-01: enforce collection safety in both settings validation and the RAG
engine's collection-creation and point-upsert paths. A safe default alone does
not protect an existing collection when an environment variable overrides it.

`rag.collection_safety.PROTECTED_COLLECTIONS` is a fixed, immutable set containing
`hdd_knowledge`. Add further protected names through a reviewed code change.
There is no environment variable or settings flag to clear this set or permit
protected writes.

Accepted names are 1-128 lowercase ASCII letters, digits, underscores or hyphens,
starting with a letter. Names are rejected, not silently trimmed, decoded or
rewritten. Case/whitespace variants of protected names, path-like names, encoded
names, control characters and Unicode lookalikes cannot bypass the check.
`rag_documents_v1`, `rag_unit_test` and `rag_portfolio_e2e_test_v1` are permitted
names; permission under this policy is not authorization to run a live test.

## Enforcement

- `Settings` validates explicit values, environment variables and dotenv values,
  including subsequent field assignments.
- `RagEngine` revalidates settings before constructing a client, covering
  Pydantic's unvalidated `model_construct` and `model_copy(update=...)` APIs.
- `ensure_collection` and `ingest_chunks` validate independently at entry. A
  protected name is rejected before embedding or any Qdrant request from these
  entry points. Text and document ingestion share this guarded indexing path.
- Each indexing operation captures its collection name once. Mutating shared
  settings during embedding or collection inspection cannot redirect that write.
- The engine validates the captured name and checks alias metadata immediately
  before collection creation and immediately before upsert. Upsert does not rely
  solely on `ensure_collection` having run.
- **Every alias is refused as a write target**, even an alias pointing to another
  test collection. This avoids permitting an alias that resolves to a protected
  collection. Alias lookup failures propagate without allowing a write; there is
  no permissive fallback. The client therefore needs permission to list aliases.

The guard raises `UnsafeCollectionError` (`ValueError`) in the engine; settings
validation surfaces a Pydantic `ValidationError`. Failures never enable writes.
This change does not add HTTP error translation, deletion, migration, cleanup or
administrative collection operations.

## Security boundary and limitations

This is an application guard against misconfiguration and unsafe use of its
indexing entry points. It is not a sandbox against arbitrary Python code that
replaces the guard or uses the raw Qdrant client directly. It does not inspect
stored documents, points or protected collection counts.

Alias checks and writes are separate requests. A concurrent administrator could
change aliases between them; the client cannot make them atomic. Use server-side
collection-scoped credentials where available, a separate test Qdrant instance,
and administrative controls that prevent concurrent alias changes. Do not treat
this guard as a substitute for those boundaries or point tests at live storage.

The existing public PR #1 still needs real parser/page-provenance testing and
synthetic end-to-end evidence. These guards do not establish retrieval quality or
make the document-ingestion prototype production-ready.

## Automated verification

The tests use synthetic text and mocked Qdrant/embedding clients. An autouse
fixture refuses socket connections, DNS resolution and implicit Qdrant client
construction. No database server, model server, document corpus or optional
Unstructured installation is required. Settings tests disable the real dotenv
file; the dotenv rejection test creates only a synthetic file in pytest's temp
directory.

Coverage includes:

- Protected names through explicit settings, environment and dotenv configuration.
- Case, whitespace, encoded/path-like names, control characters and lookalikes.
- Attempts to clear protection with environment variables.
- Assignment validation, unvalidated model creation/copies and tampered settings.
- Direct collection creation, text indexing, document indexing and empty input.
- Permitted targets, both new and existing, with all writes asserting the target.
- Mid-operation settings mutation, overridden collection setup, alias indirection,
  aliases introduced before writes and failed alias lookups.

Commands run in a separate local Python 3.12 virtual environment:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src/rag/collection_safety.py src/rag/config.py src/rag/core.py tests/conftest.py tests/test_collection_safety.py
.venv/bin/python -m ruff format --check src/rag/collection_safety.py src/rag/config.py src/rag/core.py tests/conftest.py tests/test_collection_safety.py
git diff --check
```

Results: the unit suite passed with 109 tests. The first run had two fixture
failures because operating-system environment variables cannot contain NUL
bytes; direct configuration still tests NUL rejection. Changed-file lint and
formatting checks pass. Full-tree lint also finds pre-existing import-order and
FastAPI default-argument findings outside this change; these are not fixed here.
No live integration test was performed or claimed.

Rollback: revert the safeguard commit through review. That would remove this
protection, so do not resume ingestion against existing collections after a
rollback. No runtime storage was changed by this work and none needs restoring.
