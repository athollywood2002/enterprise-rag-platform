# Folder ingestion workspace

Open `http://localhost:18000/` after starting Compose. The same API key used by
API clients unlocks the UI. It stays only in the tab's memory, never localStorage,
URLs or built JavaScript. Re-enter it after refresh; jobs and documents persist.
This is one trusted-user, single-instance workspace, not a multi-tenant service.
Use localhost or a trusted private network; use a TLS reverse proxy before sending
keys/documents over an untrusted network. No CORS access is enabled.

## Start, use, stop

```sh
cp .env.demo.example .env.demo
# Edit .env.demo: set a fresh RAG_API_KEY, your Ollama endpoint and installed models.
# Obtain the model names from your own Ollama installation; no model is downloaded by this app.
docker compose --env-file .env.demo -f compose.demo.yaml up -d --build --wait
# Open http://localhost:18000/
# Stop without deleting either persistent volume:
docker compose --env-file .env.demo -f compose.demo.yaml down
```

The API runs as UID 10001, with a read-only image and `/data` backed by the
`library-state` volume. That volume contains SQLite job/document records and staged
uploads. Qdrant has its own persistent `demo-qdrant` volume and no published ports.
Keep both volumes together when backing up or moving the workspace. Do not use
`down -v` unless intentionally discarding this isolated workspace's data.
One Uvicorn process and one ingestion worker are supported. A filesystem lock
refuses a second API process using the same data directory. Do not use `--workers`
or scale replicas. SQLite is local, not a network-share database.

1. Connect using the API key.
2. Choose **Folder on this computer**. Enter a stable source name and select the
   directory. The browser sends relative paths, including subfolders; it cannot
   grant the server access to a local path. Browsers exposing `webkitdirectory`
   are required (current Chromium/Firefox/Safari desktop). Mobile folder-picker
   availability varies. A source name plus relative path identifies a document.
3. Preview counts, total bytes, supported formats and excluded files. Nothing is
   uploaded until **Start ingestion**. Extension/size screening does not prove a
   document is parseable; parse errors appear in individual results.
4. Follow the backend's per-file states. **Queued** after upload means safely
   staged, not searchable. **Completed** means its revision is committed and
   searchable. **Skipped / unchanged** means compatible vector IDs were verified.
5. Ask a question using the selected job or all committed library documents.
   Inspect citations, relative paths, PDF pages, excerpts and generation status.
   A completed generation alone does not prove an answer is correct.

Refreshing restores jobs after reconnecting. After all uploads finish, the browser
submits Start and can close safely; the server owns processing. If closed during
upload, reselect the original folder and click **Retry failed / cancelled files**
on the saved job to supply missing bytes. Staged files do not need reuploading.
If closed between the last upload and Start, use that same retry button to release
staged work. Do not create a new job merely to recover a saved job.

## Server folders

Server mode only sees explicitly configured roots in the container. Example:

```sh
# Edit the host-side path in compose.sources.example.yaml first.
docker compose --env-file .env.demo -f compose.demo.yaml \
  -f compose.sources.example.yaml up -d --build --wait
```

The example mounts `./demo/fixtures` at `/sources/team:ro` and sets
`INGEST_SOURCE_ROOTS='{"team-documents":"/sources/team"}'`. Replace the host
path with the desired folder. Ensure UID 10001 can read it; the application does
not chmod it. Root labels are stable identity namespaces; changing the label
creates another source. The API exposes labels and relative paths, never configured
host paths. Server source files are never modified.

Browse subfolders and preview the selected subtree. Traversal, absolute input
paths, backslashes and control characters are rejected. Every component is opened
relative to an already-open directory descriptor with `O_NOFOLLOW`; **all symlinks
are excluded, even in-root ones**. FIFOs/devices/sockets are excluded. The mount
itself and its parent directories must be administrator-controlled. Keep the mount
read-only; this complements rather than replaces descriptor-based containment.
Sources changing during staging fail explicitly. A server job copies files into
staging before parsing; source contents can change between preview and staging.

## Actual format support

The new `/library/*` interface uses shared `rag.folder_parser` code from both the
UI and API clients. The Docker lock already includes **pypdf 6.21.4** with a wheel
hash; no optional Unstructured closure, NLTK downloads, OCR or model downloads are
required for this path. TXT/CSV use Python's standard library. Parsing runs in a
separate child with a 512 MiB address-space bound, 32 MiB output-file bound and a
wall timeout. PDF extraction is explicitly text-only and physical-page-local.

| Format | Behavior |
| --- | --- |
| TXT | UTF-8 (optional BOM), whitespace-normalized, bounded overlapping chunks. |
| CSV | UTF-8, comma-delimited, unique nonempty header row. Rows become quoted, labeled field/value text before chunking. Quoted commas/newlines are retained as escaped values. Wrong column counts or malformed quoting fail. |
| PDF | Embedded text extracted per physical page with pypdf; chunks never cross pages. Encrypted, malformed, textless/scanned or mixed text/textless PDFs fail explicitly. No OCR/layout/table reconstruction guarantee. |

Empty, binary-text, unsupported and oversized files receive actionable results.
A blank PDF page is conservatively treated like a scanned page and rejected; export
a text-only copy with blank pages removed. Complex column/table order is not
validated by this first implementation. CSV rows longer than the chunk size may
span overlapping chunks, so this is not a structured SQL/table query engine.

Legacy `/ingest`, `/ask`, and optional Unstructured `/ingest/document` retain their
existing semantics and collection. The merged n8n text/CSV workflow remains valid.
The UI uses a **separate managed library**; legacy ingestions do not automatically
appear in it. The legacy optional document endpoint does not gain a silent parser
switch. For consistent folder parsing, new n8n workflows use the library API below.

## Durable identity and replacement

The stable ID hashes source mode, stable source label and full relative path.
Same basenames in different folders/roots remain distinct; renaming/moving a file
creates another identity. Absence in a later selection never deletes a document.

Compatibility hashes include parser version, chunk parameters, embedding model
name and its current Ollama `/api/tags` digest, plus configured database/destination.
The parser/chunk algorithm version is explicitly maintained in code. A model-name
match alone is insufficient. Changed model bytes get a separate collection and
require reingestion before the new index is searched. The managed collection name
is the configured collection prefix plus `_ui_` and the compatibility hash prefix.
Model switching leaves old collections retained; no automatic collection deletion.

Each attempt writes vectors under a unique immutable revision. All vectors must
be acknowledged and retrieved successfully before one SQLite transaction switches
the document's active revision and marks the file completed. Search includes only
SQLite-committed active revisions, so partial upserts, lost acknowledgements and
failed replacements do not expose partial new documents or delete usable old ones.
A lock holds the active revision stable through retrieval/generation and replacement.
Old chunks are removed **after** the switch. Failed cleanup remains visible as
`cleanup_pending` and is retried by the worker; retired vectors are excluded from
search even while physical deletion is unavailable. Collection write protections
and alias rejection apply to all managed upserts/deletes too.

After a restart, in-flight files with no committed revision become failed/interrupted
and require explicit retry. A committed revision is recognized from SQLite.
Pending queued work resumes. Interrupted uploads require reupload unless fully
staged. Runtime success is never inferred from an upload, process exit, or filename.
Retention is conservative: staged bytes, jobs and document versions remain on disk
up to quotas; there is no automatic source-document deletion or retention purge.

## Limits and cancellation

Concurrency is deliberately fixed at **one file**. API requests and source uploads
are authenticated; all users sharing the key share the same jobs and documents.
The UI reports real counts and current chunk completion from SQLite, not timed
percentages. The finished-file bar includes failed/skipped/cancelled files, with
separate counts so it is not mistaken for successful indexing.

| Environment variable | Default |
| --- | ---: |
| `INGEST_DATA_DIR` | `/data` in Docker; disabled unless set for a direct Python launch |
| `INGEST_MAX_FILES` | 500 selection entries (server directories count toward traversal bound) |
| `INGEST_MAX_FILE_BYTES` | 10 MiB |
| `INGEST_MAX_BATCH_BYTES` | 100 MiB |
| `INGEST_MAX_STAGED_BYTES` | 1 GiB reserved staged bytes across retained jobs |
| `INGEST_MAX_JOBS` / `INGEST_MAX_DOCUMENTS` | 100 / 5000 |
| `INGEST_MAX_PAGES` / `INGEST_MAX_CHARS` / `INGEST_MAX_CHUNKS` | 200 / 2,000,000 / 3000 per file |
| `INGEST_UPLOAD_SECONDS` / `INGEST_PARSE_SECONDS` | 120 / 30 |
| `INGEST_FILE_SECONDS` | 300 cooperative processing deadline |

Selection JSON has an additional 2 MiB request boundary; server traversal depth is
limited to 32. Embedding requests have the existing 120-second HTTP timeout, model
identity lookups 15 seconds and Qdrant calls 30 seconds. Cancellation and file
deadlines are checked **between operations and before commit**. They cannot undo
an in-flight request; observation can therefore exceed the file deadline by one
operation. A late result cannot commit. Parser timeout kills only its own child.
No promise is made to interrupt a model server already generating tokens. API
shutdown waits briefly; unfinished work is marked interrupted when reopened.
No automatic inference retries occur; the user explicitly retries failed/cancelled
files. Cleanup retries perform database operations only.

## API / n8n integration

All calls require `x-api-key`; use n8n's Header Auth credentials, never export the
value. Use the existing API's private URL from the n8n host. Server roots refer to
the API container, not the machine running n8n.

- `GET /library/config`: supported formats, configured root labels, destination and limits.
- `GET /library/browse?root=label&path=subfolder`: bounded folder listing.
- `POST /library/preview`: `{ "mode":"browser", "source":"team", "files":[{"path":"docs/a.txt","size":123}] }`, or `{ "mode":"server", "source":"team-documents", "folder":"manuals" }`.
- `POST /library/jobs`: same selection, creates persisted job/file IDs. Server jobs queue immediately after staging each selected file. Browser jobs wait for uploads and Start.
- `PUT /library/jobs/{job}/files/{file}`: raw file bytes, exact preview size. Returns `staged`, **not** indexed.
- `POST /library/jobs/{job}/start`: release fully staged browser job.
- `GET /library/jobs` / `GET /library/jobs/{job}`: status and per-file results.
- `POST /library/jobs/{job}/retry` / `cancel`: explicit retry or cooperative cancellation.
- `GET /library/documents`: committed document metadata and cleanup backlog.
- `POST /library/ask`: `{ "question":"…", "top_k":5, "job_id":"optional job ID" }`; returns the existing answer/sources/generation shape with relative source paths and PDF pages.

A minimal n8n flow is Manual Trigger → create server job → bounded polling of job
status → check successful/failed counts → library ask → inspect citations. For
files on the n8n host, use browser-mode manifest + raw PUTs + Start instead. The
old exported workflow continues using its original `/ingest` and `/ask` route.

## Validation and limits of evidence

`tests/test_library.py` uses real SQLite, local-mode Qdrant and real parser children,
with a synthetic model transport. It covers replacement failure, lost upsert
acknowledgement, retry, cancellation, restarted work, identity changes, limits,
containment and HTTP authentication. Existing API tests remain in the suite.

The Docker CI runs `scripts/library_smoke.py` **inside the built image**, using a
real dedicated Qdrant server and synthetic Ollama fixture. It exercises TXT, CSV,
two-page PDF, duplicate basenames, reingestion/replacement, errors, cancellation,
server source mount, cited answers, API restart and explicit recovery. The earlier
n8n contract and API smoke still run. Its inference is synthetic, not a real-model
quality result. No shared n8n or AiMiniRig service is used.

Actual UI screenshots and browser checks are described in `ui-walkthrough.md`.
This small fixture does not establish broad PDF quality, retrieval selectivity,
multi-user isolation, production readiness or a metered model budget for normal UI
use. Registry publication and deployment to shared services are separate steps.
