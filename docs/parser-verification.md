# Parser and source-provenance verification

## Scope and decision

2026-11-01: tests reproduced a two-page PDF attribution failure in the original
document-ingestion branch. Distinct facts from pages 1 and 2 were combined into
one chunk attributed to page 1. A single `page_number` is not sufficient evidence
for a multipage chunk.

Keep the single-page payload schema for now, but chunk each consecutive group of
elements with the same valid page metadata separately. Title-aware chunking is
retained inside those groups with 1200/1000/200 character settings and
`multipage_sections=False`. This prevents short-section combination from merging
pages. Missing, nonpositive or boolean page values become `None`; unknown-page
elements are not merged with known-page elements or assigned their neighbors'
page. Chunk numbers remain sequential across the whole upload.

PDF partitioning explicitly uses Unstructured's local `fast` strategy and English
language settings. Pypdf validates PDF structure first and rejects encrypted PDFs;
bytes labeled PDF are not reinterpreted as another document type. There is no
automatic OCR or layout-model fallback. Scanned/image-only PDFs are not supported
by this path. Empty uploads, unsupported extensions and control characters in
filenames are rejected before optional imports or temporary-file creation.
Documents without extractable text raise `ValueError` rather than reporting a
successful zero-chunk upload. Parser source names remove Unix and Windows path
prefixes. Temporary upload files are removed after success or failure.

These are parser-layer changes only. No HTTP server, embeddings or database is
involved in this verification. API error mapping for arbitrary dependency/parser
failures and HTTP response filename normalization remain separate work.

## Reproduce locally

Use a separate virtual environment. Do not install into the existing backend:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,parser-tests]'
.venv/bin/python -m nltk.downloader -d .venv/nltk_data punkt_tab averaged_perceptron_tagger_eng
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q --run-document-tests
.venv/bin/python -m pytest -v --run-document-tests tests/test_document_parsing.py tests/test_document_inputs.py
.venv/bin/python -m ruff check src/rag/documents.py tests/conftest.py tests/test_document_inputs.py tests/test_document_parsing.py
.venv/bin/python -m ruff format --check src/rag/documents.py tests/conftest.py tests/test_document_inputs.py tests/test_document_parsing.py
git diff --check
```

`parser-tests` pins Unstructured 0.18.32, Unstructured inference 1.6.17,
pdfminer.six 20260107, pypdf 6.21.4, NLTK 3.10.4 and ReportLab 4.4.4. This is a
selected test dependency set, not a complete transitive dependency lock. NLTK's
tokenizer/tagger assets are explicit setup-time dependency downloads, not test-time
network activity. No LLM/OCR/layout weights are downloaded or used. Tests default
to the virtual environment's `nltk_data` directory; `NLTK_DATA` can specify a
dedicated setup location.

The optional parser tests are skipped unless `--run-document-tests` is supplied.
Opting in with missing dependencies fails rather than silently skipping them.
The separate `document-tests` CI job installs the pinned extra and language assets
and runs the complete suite with that flag on Python 3.12. It preinstalls CPU-only
Torch/Torchvision to avoid CUDA downloads. The existing lightweight Python 3.11
job does not need the parser dependency stack.

## Test inventory

`tests/test_document_inputs.py` runs without optional dependencies: six invalid
input cases assert rejection before imports or temporary writes.

`tests/test_document_parsing.py` exercises real Unstructured chunking. Deterministic
element fixtures replace only partitioning for semantic-boundary, cross-page,
chunk-size, invalid-page, filename and cleanup tests. They do not pretend to
verify PDF extraction.

The real-extraction tests do not mock the PDF or TXT partitioners:

- A generated two-page PDF contains a different synthetic fact on each page.
  Independent pypdf extraction checks the fixture, then actual Unstructured
  extraction/chunking must return each fact on its correct page, never together
  in a falsely single-page chunk.
- A guard test forbids the backend's OCR and layout-model paths while parsing
  that PDF. Socket/DNS access and implicit Qdrant construction are blocked for
  every test. Automatic NLTK downloads are disabled and model libraries are put
  in offline mode before optional imports.
- Malformed/truncated PDFs, a blank PDF, an encrypted synthetic PDF, whitespace
  text, and ordinary text with no page metadata have explicit assertions.

No binary PDF, existing document, chunk output or runtime storage is committed.
ReportLab generates the fixture deterministically in memory with generic metadata.

## Evidence and remaining limitations

Before the parser change, the targeted regression run failed all seven selected
cases: six early-validation tests and the real two-page attribution test. The PDF
test observed only page 1 in returned chunk metadata. During test development one
OCR-guard test also failed because it referenced the wrong private backend hook;
it was corrected to the hooks present in the pinned version.

The first remote workflow run failed before jobs started because `runner.temp`
is not available in job-level `env`. The follow-up uses the supported
`github.workspace` context and keeps language resources under the ignored
`.venv/nltk_data` path. Remote CI results must be checked separately from local
parser results; the initial workflow rejection is not a passing test run.

After the change, the full local Python 3.12 suite passed with 136 tests, including
21 opt-in parser cases. The lightweight run reports parser cases separately as
skipped. The detailed command results are recorded in the pull request/relay
handoff; no live end-to-end success is claimed.

Coverage is limited to English text PDFs/TXT and deterministic elements. OCR,
scanned PDFs, tables, complex layouts, other allowlisted formats and malicious-file
resource isolation are not verified. Page accuracy still depends on the upstream
partitioner's element metadata; unknown pages are intentionally not guessed.
Retrieval/citations after indexing, HTTP upload behavior and service integration
remain untested here. Native library imports can emit platform warnings; no
system-library installation or repair is part of this change.

Rollback: revert this parser/test commit through review while retaining the
protected-collection guard. Reverting reintroduces the known cross-page attribution
risk; do not claim precise page citations after such a rollback. No live storage
was accessed or changed and none needs restoring.
