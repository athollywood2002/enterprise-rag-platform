# Document upload HTTP contract

## Scope

2026-11-01: endpoint tests exposed raw parser exception messages in HTTP 400
responses and unhandled failures when optional parser dependencies were missing.
The document upload route now returns fixed error messages instead of exception
strings. This contract applies to `POST /ingest/document`, not every endpoint or
every application/middleware failure.

Document-route request validation also uses a fixed 422 response: the framework's
default error reflected a rejected form field's raw input. Validation for other
endpoints retains its existing framework response shape.

Requests use multipart field `file` and header `x-api-key`. Valid authentication is
required. Filenames are reduced to a basename using the same sanitizer as the
parser, including Windows-style path separators. Control characters are rejected;
percent escapes are not decoded into filenames. Extensions are case-insensitive.
The extension allowlist is not proof of content safety or successful parsing of
every supported format.

Successful responses remain HTTP 200 with `source` and `chunks_indexed`.
`source` is the sanitized filename. The parser's `DocumentChunk` list is passed
unchanged to `ingest_chunks`, preserving text, source, chunk number and optional
page number. No document text is added to the response.

## Status and error messages

Errors are JSON objects with a `detail` field. These deliberate contract changes
replace raw parser messages and previously unhandled exceptions:

| Condition | Status | Detail |
| --- | --- | --- |
| Missing, empty or incorrect API key, including non-ASCII input | 401 | `Invalid API key` |
| Unsupported filename extension | 415 | `Unsupported document format` |
| Filename contains control characters | 400 | `Invalid filename` |
| Empty file contents | 400 | `Empty document` |
| Uploaded file exceeds 10 MiB | 413 | `Maximum upload size is 10 MiB` |
| Malformed, encrypted or textless PDF; parser `ValueError`; empty chunk list | 400 | `Invalid document or no extractable text` |
| Parser import/resource lookup failure (`ImportError` or `LookupError`) | 503 | `Document parser is unavailable` |
| Unexpected parser failure | 500 | `Document processing failed` |
| Upload read failure | 500 | `Unable to read document upload` |
| Engine raises `UnsafeCollectionError` | 403 | `Collection write policy forbids this operation` |
| Other ingestion/engine-construction failure | 500 | `Document ingestion failed` |
| Missing or wrongly typed multipart `file` field | 422 | `Invalid document upload` |

The 10 MiB file-content boundary is inclusive: exactly 10 MiB is accepted for
parsing; one byte over is rejected. Rejection during authentication, upload
validation or parsing does not construct an ingestion engine. An ingestion failure
does not establish transaction rollback or absence of earlier writes in a real
deployment; no real writes are performed by these tests.

Error payloads omit exception strings, paths, document contents and configuration
values. The API-key comparison uses bytes so non-ASCII header values cannot cause
the string-only `compare_digest` failure. Parser dependency classification remains
coarse: for example, a parser `KeyError` also belongs to `LookupError`. This is not
a complete operational error taxonomy or a global redaction/logging system.

## Automated verification

`tests/test_document_http.py` has 50 cases using FastAPI's in-process TestClient.
Its default `raise_server_exceptions=True` is retained, so an unhandled error
fails the test rather than being hidden by a simulated generic server response.
Ingestion is mocked in every HTTP test. The shared network/DNS and implicit
Qdrant-client guards remain enabled. No server is bound to a TCP port.

The cases cover authentication, the extension allowlist, unsupported extensions,
empty uploads, missing fields, 10 MiB minus/exact/plus-one boundaries, basename
handling, literal/encoded control characters, opaque error responses, empty
parser output, unchanged provenance handoff, collection-policy rejection and
upload/indexing failures. Allowlist tests use a mock parser: they do not verify
every document format.
Tests also check opaque validation on a mounted document route and preservation
of the existing validation shape on another endpoint.

Five opt-in `documents` cases use the real parser with synthetic PDFs: malformed,
truncated, blank, encrypted, and a generated two-page PDF with distinct facts.
The latter asserts each fact arrives at the mocked ingestion call on the correct
page. All PDF fixtures are generated in memory; no original or binary documents
are committed. The PDF builder is shared with the parser regression tests.

The dependency-unavailability test uses the real parser entry point. In a
base-only installation, Unstructured is genuinely absent. In the full parser
environment, a guarded import hook simulates the same failure. Both must return
HTTP 503 with the same fixed message, without indexing. CI's base-only job also
asserts that `find_spec('unstructured') is None` before running tests.

## Reproduction and observed results

Full local Python 3.12 environment, with the parser setup described in
[parser verification](parser-verification.md):

```bash
.venv/bin/python -m pytest -q --run-document-tests
.venv/bin/python -m pytest -v --run-document-tests tests/test_document_http.py
.venv/bin/python -m ruff check src/rag/api.py src/rag/documents.py tests/conftest.py tests/test_document_http.py tests/test_document_parsing.py
.venv/bin/python -m ruff format --check src/rag/api.py src/rag/documents.py tests/conftest.py tests/test_document_http.py tests/test_document_parsing.py
git diff --check
```

The parser-enabled suite passed with **186 tests**, no skips. Before the change,
the targeted error/dependency run failed all six selected cases. During fixture
development, the HTTP builder encoded a NUL filename, so its 415 response did not
exercise literal control-character validation. The corrected test sends literal
multipart bytes; a separate case verifies encoded names are not decoded.
Another regression test confirmed default 422 errors echoed a wrongly typed
file field's synthetic diagnostic input; document-route validation is now opaque.

A second temporary virtual environment was created with Python 3.12 and only
`pip install -e '.[dev]'`. A separate `find_spec` assertion confirmed Unstructured
and ReportLab were absent, then `python -m pytest -q` returned **160 passed,
26 skipped**. Skips are the 21 parser cases and five real-parser HTTP cases.
The mocked HTTP contracts, including the actual missing-dependency path, run in
that base-only suite. One Starlette deprecation warning was observed for its
fallback to the installed `httpx` version; it was not suppressed. Remote CI status
is reported separately in the PR and handoff, not assumed from local results.

## Limits not solved here

**A 10 MiB file-content check is not a total request-body or resource limit.**
The multipart framework may already have consumed/spooled input before the route
checks the file, including before endpoint authentication. Multipart overhead,
extra parts, concurrency, disk exhaustion and slow uploads require separate
request/server controls. The tests check one file's contents, not a hardened
reverse-proxy deployment.

Compressed document expansion, parser CPU/RAM/time limits, parser subprocess
isolation and synchronous work blocking the async route are still unresolved.
Do not expose the prototype publicly based on this change. OCR/scanned PDFs,
complex layouts, malware scanning, production error telemetry and end-to-end
Ollama/Qdrant indexing/retrieval remain outside this verification.

Rollback: revert this HTTP-contract/test commit through review while retaining
the collection and page-provenance safeguards. That restores the previous error
disclosure/unhandled-dependency behavior, so it is not a safe deployment fallback.
No live installation, service or database state was changed or needs restoring.
