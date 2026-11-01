# Canonical corpus and development spans (G1a, corrected v2)

Implemented and tested offline: v2 schemas, canonical page construction, label
validation, ordered chunk mapping and single-span relevance/coverage primitives.
This is the first foundation for the later CLI/evaluator, not a completed G1
evaluation stack. Serving parser/API behavior is unchanged; its immutable chunk
parameters are now shared with evaluation. No real corpus,
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
characters**, then normalized as follows (`nfc-quotes-artifacts-whitespace-v2`):

1. Fold U+FB00–FB06 to `ff`, `fi`, `fl`, `ffi`, `ffl`, `st`, `st`; remove
   U+00AD, U+200B–200D and U+FEFF, then Unicode NFC (not NFKC).
2. Map U+2018/U+2019 to ASCII apostrophe, U+201C/U+201D to ASCII double quote.
3. Collapse every Unicode whitespace run recognized by Python `str.split()` into
   one ASCII space, strip leading/trailing whitespace. Thus paragraph separators
   also become spaces. Preserve case and all other punctuation/code points.
   No automatic line-break dehyphenation: `kube-\napiserver` becomes
   `kube- apiserver`, not a guessed identifier. En/em dashes remain unchanged.

Record the producer's Unicode database version. Every load recomputes normalization
and page hashes, including when Unicode versions differ: accept identical text/hash,
reject actual changes. Version mismatch alone is not failure.
Offsets are **0-based Unicode code-point indices**, half-open `[start,end)`,
into exactly the final canonical Python string. They are not UTF-8 byte or UTF-16
indices and cannot be applied to raw PDF bytes or pre-normalized parser text.
Page SHA-256 is over canonical text encoded as UTF-8 with no appended newline.
Blank physical pages remain empty with the empty-text hash; all-empty documents,
unknown/out-of-range page metadata and encrypted PDFs are rejected.

`extract_document` dispatches `.pdf` and `.md` only. HTML is explicitly unsupported.
`extract_markdown` requires local UTF-8 bytes and explicit offline flags. It calls
the same `.md` Unstructured partition helper as serving exactly once. Canonical
**logical page 1** is the nonempty element texts, in order, joined with two LF
characters and normalized exactly as PDF elements. The same elements go through
`chunk_by_title(**TITLE_CHUNKING)` and sequential offset mapping. Unknown physical
page numbers from this adapter are rejected, not presented as PDF citations.
There is no whole-file embedding shortcut. The previous
`markdown-source-utf8-v1` profile is rejected, invalidating its synthetic manifests
and labels instead of treating source markup offsets as rendered-text offsets.

Markdown profile `unstructured-markdown-v1` checks and records Unstructured
0.18.32, Markdown 3.11.2, lxml 6.1.3, beautifulsoup4 4.15.0, html5lib 1.1,
charset-normalizer 3.5.2, filetype 1.2.0, python-magic 0.4.27, langdetect 1.0.9,
and NLTK 3.10.4. These selective pins are in `parser-tests` and `MARKDOWN_PINS`;
the full parser identity/package list participates in the corpus SHA-256 fingerprint.
They are not a complete transitive/native lock (e.g. libmagic/libxml2).
The local parser can warn that native libmagic is unavailable; no privileged
installation is implied. Shared filename dispatch and exact canonical hashes
still require verification in each target environment.

Python-Markdown renders with tables/fenced-code extensions before Unstructured
extracts text. The fixture preserves inline/fenced identifiers `--max-pods=110`,
`kube-apiserver`, `AC-2(4)`, `a.b`, `kubectl` command lines and YAML key/value
punctuation. It strips heading/emphasis/backtick/fence markup, link destination
URLs and HTML comments. Canonical whitespace collapse removes YAML indentation
and command line breaks; canonical text is for labeling, **not executable config**.
Survival on synthetic fixtures is not a guarantee for all Kubernetes templates,
shortcodes, tables or embedded HTML. Review each acquired document for content
loss; record failures/identifier losses rather than silently repairing them.
No resource URL is passed to the parser, and tests block network access.
Document, gold and chunk references carry `page_kind: physical|logical`; logical
page 1 must never be cited as a physical PDF page.

PDF and Markdown chunk parameters live in frozen `rag.chunking.TITLE_CHUNKING`,
shared with serving without changing serving arguments. The evaluation policy ID encodes
version, max=1200, new=1000, combine=200 and multipage=false. Tests compare normalized
evaluation and serving PDF/Markdown chunk text in order. Markdown tests include
an authored >10k-character guide: all chunks are bounded by 1200 characters,
sequentially mapped, and retrieving an early chunk does not cover a late gold span.
Metadata, including parser profile/page kind, must travel with future scorecards.

`doc_version` is SHA-256 of the raw source bytes; it does not depend on chunk IDs.
`doc_id` groups a document's revisions. Source metadata records canonical URL,
revision/date, title, license, attribution and redistribution decision. These are
declarations, not proof of permission: later acquisition requires per-source rights
review, excluding unclear third-party content. Corpus identity is SHA-256 of
sorted-key compact JSON, UTF-8, no ASCII escaping; array order is significant.

## Schemas and label loader

Strict frozen Pydantic models in `evaluation.corpus` define `canonical-corpus-v2`
and `span-labels-v2`. Earlier v1 serialized manifests/labels and normalization IDs
are explicitly rejected: rebuild/revalidate synthetic fixtures, never silently
migrate offsets. No real labels existed at this policy change.
Generate machine-readable JSON Schema with
`CorpusManifest.model_json_schema()` or `DevelopmentLabels.model_json_schema()`.
Use `load_corpus` / `load_development_labels` for serialized inputs: explicit
version tags are required, duplicate JSON keys and unknown fields rejected.
Corpus documents/versions, ordered contiguous pages and query IDs must be unique.

Every gold span carries `doc_id`, `doc_version`, `page`, `page_sha256`,
`page_kind`, `start`, `end`, and normalized verbatim `excerpt`. Loading checks the corpus
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
`query_type` is `identifier|semantic|mixed`; `difficulty` is `easy|medium|hard`;
both fields are **required**, with no silent defaults. The future CLI must prompt
for them. Existing v2 serialized labels missing either field fail validation;
synthetic fixtures supply explicit values. `tags` are unique validated identifiers
and may be empty. Later split tooling can stratify by
category/type/difficulty and tags; no real split or annotation is generated here.

This loader only accepts the **development** split. `HoldoutCommitment` permits
only a plaintext SHA-256 and positive question count (plus schema version), not
questions, labels, sensitive paths or keys. No holdout file is created or opened.
The same macOS account is not a secrecy control. Real holdout requires owner-held
encryption/key custody or a separate account/machine and later explicit evaluation
approval. CLI path refusal, split freezing/stratification and protected final
evaluation are subsequent work; none is claimed implemented by this PR.

## Mapping and relevance

Normalize each chunk with the same policy and search only its attributed
document/version/page. Standalone `map_chunk` still requires one occurrence.
Extractor `map_chunks` validates the actual output sequence against the canonical
page from offset zero. The next chunk must begin at the previous end or after
one canonical separator space. No content may be skipped; hard element splits
can be adjacent with no separator. Repeats resolve by this verified prefix, not
by choosing the next arbitrary occurrence. Cursor resets at each page. The final
chunk must reach page end. Noncontiguous order, injected titles, overlap or omitted
text fail closed instead of inventing alignment.
Normalized-empty emitted chunks (including `TableChunk` objects whose only
remaining content is HTML metadata) are **not retrievable text candidates**.
The shared mapper records `empty_skipped` diagnostics for every one, without
advancing the cursor/prefix or changing failure state. It never promotes HTML
metadata into canonical text. `CanonicalExtraction.from_mappings` separates
these diagnostics from `.chunks` and records their count as `.empty_skipped`;
`.mapping_counts` reports that count alongside candidate statuses. Both PDF and
Markdown extractors use the same path. Actual empty-table output now matches
serving's `if not text: continue` behavior. Artifact-only strings that normalize
to empty are likewise diagnosed; serving raw text is not changed by this adapter.

Nonempty missing-page, ambiguous (including overlapping occurrences), overlap,
blocked and unlocatable candidates retain explicit statuses and match counts.
After a genuine failure, later nonempty chunks stay blocked, even if empty
outputs intervene. Trailing empty outputs cannot hide omitted canonical text:
the last mapped candidate becomes unlocatable on incomplete coverage. An
all-empty output stream for a nonempty page keeps a missing-content failure
sentinel, not a successful empty mapping. A completely missing output stream
still fails. Standalone `map_chunk` retains its `empty` failure behavior.

Raw `map_chunks` output includes the explicit skipped diagnostics. Use the
extraction factory and score `.chunks`, not those diagnostics. Passing a raw
diagnostic to scoring still raises rather than silently creating a retrieval
miss. The factory rejects purported empty diagnostics with nonempty text,
offsets or nonzero/invalid match counts. Invented title prefixes,
chunker transformations or page-crossing text may be unlocatable; report these as
mapping failures rather than inventing an alignment or scoring retrieval misses.
Scoring primitives raise `MappingFailure` for unmapped chunks. Consumers must
surface counts/reasons and withhold affected evaluation claims, not catch the
error and substitute zero. Even manually constructed mapped locations are checked
against canonical bounds/text/hash/page kind and occurrence count before scoring.
Sequential locations additionally store the ordered normalized prefix, replayed
against canonical text before accepting their offset; standalone locations retain
uniqueness checks. This proves canonical text alignment, **not actual parser-run
provenance**: a caller can construct a prefix by slicing canonical text. Prefix
storage is quadratic and match counting can be costly on long pages. Review #52
is deferred to a narrow G1(c) change: consider an ordered per-document
page/start/end/policy chunk-map commitment rather than claiming prefixes are
tamper-evident parser proof. No such commitment is implemented here.

A chunk is relevant to a gold span only on the same document/version/page/hash
and when it covers **at least 50%** of gold code points **at the gold location**.
Identical text elsewhere is not relevant. The former excerpt-content fallback was
removed because strict offsets make it redundant at the true location and wrong
at another occurrence. `span_coverage` unions intersecting chunk intervals, avoids
double counting duplicates/overlap and divides by gold length. Merely touching a
boundary contributes zero. This primitive is not dataset Recall/MRR: aggregate
answerable-only denominators, multispan aggregation, scorecards and paired stats
belong to G1(c), not an invented result here.

## Verification and remaining boundaries

```bash
python -m pytest -q tests/test_canonical_corpus.py
python -m pytest -q --run-document-tests tests/test_canonical_corpus.py tests/test_canonical_pdf.py tests/test_canonical_markdown.py tests/test_canonical_tables.py
python -m pytest -q --run-document-tests
python -m ruff check .
python -m ruff format --check .
```

Tests use authored synthetic text/PDFs/Markdown, including a >10k-character guide.
The real-parser suite checks a single
partition call, independent physical-page extraction, normalized element splits,
titles and page boundaries, drift rejection, and same-runtime canonical/span
repeatability. It does not assert ranking/metric repeatability or cross-hardware
float equivalence. Compose, limits/health behavior, CPU tolerance and vector/
snapshot replay remain unimplemented or runtime-unverified until their own gates.
No model downloads/calls, services, containers, holdout access or corpus fetches.

### Empty-table regression (#57)

An authored Markdown pipe table with oversized description cells and empty
separator rows makes the actual pinned Markdown parser/title chunker emit four
empty `TableChunk`s carrying nonempty `text_as_html`. The regression requires
those actual outputs (not fabricated empty chunks), checks `empty_skipped=4`,
and compares all retained chunk texts/counts and independently located offsets
with serving. It verifies mapping/scoring after the final skipped chunk.

The PDF adapter is checked with the same real parsed Table/chunker and controlled
physical-page metadata; **PDF partition is stubbed in that case** because fast
PDF extraction does not promise table structure. A separate drawn-grid PDF runs
the real text-only PDF parser and checks serving parity and physical offsets.
No OCR, layout/model inference or table reconstruction is added.

Decision: skip/count empty emitted text exactly at the evaluation mapping boundary,
not modify serving or recover HTML-only content. Canonical text/hashes, source
versions, normalization, schemas and chunking parameters stay unchanged. Previously
blocked extraction must be rerun; no automatic label migration is implied.
Rollback is a reviewed revert of this correction; no serving/storage/index change.

### Backlog: row-aware tables (#58; ADR-002/P2-B input)

The baseline title chunker can split oversized rows/cells into separate chunks,
separating a flag from its description. The synthetic table above demonstrates
this with `--synthetic-000` in a different chunk from `row-00-word-000`. Whole
rows may be retained when they fit; this is not a claim that every table is split
without row awareness.

Record this as an ADR candidate and a **future measured variant**, not a baseline
repair: compare row/identifier-aware table chunks only after measuring the current
serving baseline. A variant needs a distinct policy ID and tests for provenance,
mapping/coverage, oversized rows, latency and token cost. Do not invent/repeat flag
text without explicit mapping semantics. No row-aware variant, corpus choice,
quality improvement or P2-B execution is authorized or implemented by this fix.

### Correction decisions (#44–#53)

Keep strict contiguous ordered alignment rather than guessing across omitted
content; prefer explicit failure over inflated retrieval scores. Review #51
supersedes the literal-source Markdown decision: use serving-equivalent rendered
elements and bounded chunks, and disclose rendering losses instead of measuring
a whole-file retrieval system that serving does not use. No PDF contract change
is needed for this repair. Review #53 requires explicit type/difficulty; #52 is
deferred as described above.
Version normalization/schema before human labeling; permit cross-Unicode runtime
loads only after actual text/hash verification. Use location-only relevance and
explicit stratification fields. Independent review is required before dependent
labeling or final canonical real-corpus builds. The labeling CLI must display the
canonical page for owner copy/paste (future G1(b) CLI work, not implemented here).

Rollback: reviewed revert of the corrections, restoring the serving literal
arguments if the shared policy module is removed. No storage or index migration.
G1b corpus acquisition remains a separate
approved task with rights, size, provenance and extraction-consistency gates.

For Kubernetes Hugo sources, see the proposed
[versioned preparation contract](kubernetes-hugo-preprocessing.md) and bounded
inspection record. The raw upstream SHA-256 and the hash of bytes actually passed
to the canonical parser are distinct: after reviewed preprocessing, `doc_version`
is the prepared-byte hash. Preserve the preparation sidecar/policy and source
attribution with the corpus. Real Kubernetes canonicalization/labeling remains
gated on review of that preparation contract; this does not change the merged
PDF/Markdown parser or authorize includes, real labels or runtime work.
