# Canonical corpus and development spans (G1a)

Implemented and tested offline: v1 schemas, canonical page construction, label
validation, unique chunk mapping and single-span relevance/coverage primitives.
This is the first foundation for the later CLI/evaluator, not a completed G1
evaluation stack. Serving parser/API behavior is unchanged. No real corpus,
human gold, holdout, new index or accuracy result is included here.

## Canonical reference and extraction

`evaluation.canonical.extract_pdf` accepts local embedded-text PDF bytes and
explicit source metadata. Install `.[dev,parser-tests]` for the selectively pinned
profile: Unstructured 0.18.32, inference 1.6.17, pdfminer.six 20260107, pypdf 6.21.4
and NLTK 3.10.4. The extractor checks installed versions before parsing. This is
not a full transitive lock: native libraries and other dependencies can still
affect extraction. Record runtime/package details with future acquisition runs;
changed canonical hashes require review regardless of whether package pins changed.

Set `AUTO_DOWNLOAD_NLTK=false`, `HF_HUB_OFFLINE=1`, and
`TRANSFORMERS_OFFLINE=1` before extraction. Missing flags fail before optional
parser imports; no implicit downloads are permitted by this adapter. Required
language assets must already be installed during explicit environment setup.
Fast/text-only extraction is shared with the existing parser backend; no OCR,
layout-model fallback, model inference, database or network client is introduced.
This imports private backend helpers from `rag.documents`; changes to those helpers
need the adapter regression suite, not an assumption of API stability.

One Unstructured partition pass supplies both canonical page elements and actual
title-aware page-local chunking. Physical PDF pages are 1-based. Nonempty elements
are grouped by verified page metadata in parser order, joined with **two LF
characters**, then normalized as follows (`nfc-quotes-whitespace-v1`):

1. Unicode NFC (not NFKC).
2. Map U+2018/U+2019 to ASCII apostrophe, U+201C/U+201D to ASCII double quote.
3. Collapse every Unicode whitespace run recognized by Python `str.split()` into
   one ASCII space, strip leading/trailing whitespace. Thus paragraph separators
   also become spaces. Preserve case and all other punctuation/code points.

Record Python's Unicode database version and reject a mismatched runtime in the
loader. Offsets are **0-based Unicode code-point indices**, half-open `[start,end)`,
into exactly the final canonical Python string. They are not UTF-8 byte or UTF-16
indices and cannot be applied to raw PDF bytes or pre-normalized parser text.
Page SHA-256 is over canonical text encoded as UTF-8 with no appended newline.
Blank physical pages remain empty with the empty-text hash; all-empty documents,
unknown/out-of-range page metadata and encrypted PDFs are rejected.

`doc_version` is SHA-256 of the raw source bytes; it does not depend on chunk IDs.
`doc_id` groups a document's revisions. Source metadata records canonical URL,
revision/date, title, license, attribution and redistribution decision. These are
declarations, not proof of permission: later acquisition requires per-source rights
review, excluding unclear third-party content. Corpus identity is SHA-256 of
sorted-key compact JSON, UTF-8, no ASCII escaping; array order is significant.

## Schemas and label loader

Strict frozen Pydantic models in `evaluation.corpus` define `canonical-corpus-v1`
and `span-labels-v1`. Generate machine-readable JSON Schema with
`CorpusManifest.model_json_schema()` or `DevelopmentLabels.model_json_schema()`.
Use `load_corpus` / `load_development_labels` for serialized inputs: explicit
version tags are required, duplicate JSON keys and unknown fields rejected.
Corpus documents/versions, ordered contiguous pages and query IDs must be unique.

Every gold span carries `doc_id`, `doc_version`, physical `page`, `page_sha256`,
`start`, `end`, and normalized verbatim `excerpt`. Loading checks the corpus
identity, source version/page, page hash, bounds and exact
`page.text[start:end] == excerpt`. A mismatch requires reannotation/revalidation;
the loader never searches for a replacement span or silently updates hashes.
Zero-length spans and overlapping/duplicate gold on one page are invalid.
Multiple disjoint spans (including on different pages/documents) are allowed.
Adjacent spans do not overlap under half-open boundaries.

`answerable` questions require spans. `near_miss` and `off_topic` questions forbid
spans; future retrieval metrics must exclude them and report unknown behavior
separately. `review_status` defaults to `draft`; code/schema conformance is not
human review. Real human verification and the timed ~20-question mixed pilot
remain owner work after the helper/acquisition reviews, not generated ground truth.

This loader only accepts the **development** split. `HoldoutCommitment` permits
only a plaintext SHA-256 and positive question count (plus schema version), not
questions, labels, sensitive paths or keys. No holdout file is created or opened.
The same macOS account is not a secrecy control. Real holdout requires owner-held
encryption/key custody or a separate account/machine and later explicit evaluation
approval. CLI path refusal, split freezing/stratification and protected final
evaluation are subsequent work; none is claimed implemented by this PR.

## Mapping and relevance

Normalize each chunk with the same policy and search only its attributed
document/version/page. Exactly **one** substring occurrence produces offsets.
Empty, missing-page, ambiguous (including overlapping occurrences), and
unlocatable chunks retain explicit statuses and match counts; none is dropped.
`CanonicalExtraction.mapping_counts` summarizes them. Invented title prefixes,
chunker transformations or page-crossing text may be unlocatable; report these as
mapping failures rather than inventing an alignment or scoring retrieval misses.
Scoring primitives raise `MappingFailure` for unmapped chunks. Consumers must
surface counts/reasons and withhold affected evaluation claims, not catch the
error and substitute zero. Even manually constructed mapped locations are checked
against canonical bounds/text/hash and uniqueness before scoring.

A chunk is relevant to a gold span only on the same document/version/page/hash
and when it covers **at least 50%** of gold code points OR contains the entire
normalized excerpt. `span_coverage` unions intersecting chunk intervals, avoids
double counting duplicates/overlap and divides by gold length. Merely touching a
boundary contributes zero. This primitive is not dataset Recall/MRR: aggregate
answerable-only denominators, multispan aggregation, scorecards and paired stats
belong to G1(c), not an invented result here.

## Verification and remaining boundaries

```bash
python -m pytest -q tests/test_canonical_corpus.py
python -m pytest -q --run-document-tests tests/test_canonical_corpus.py tests/test_canonical_pdf.py
python -m pytest -q --run-document-tests
python -m ruff check .
python -m ruff format --check .
```

Tests use tiny authored synthetic text/PDFs. The real-parser suite checks a single
partition call, independent physical-page extraction, normalized element splits,
titles and page boundaries, drift rejection, and same-runtime canonical/span
repeatability. It does not assert ranking/metric repeatability or cross-hardware
float equivalence. Compose, limits/health behavior, CPU tolerance and vector/
snapshot replay remain unimplemented or runtime-unverified until their own gates.
No model downloads/calls, services, containers, holdout access or corpus fetches.

Rollback: remove this offline evaluation-only module/test/doc addition via review;
no serving, storage or index migration. G1b corpus acquisition remains a separate
approved task with rights, size, provenance and extraction-consistency gates.
