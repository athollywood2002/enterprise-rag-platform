# NIST Option A — screening complete, admission pending

Owner authorized **only SP 800-171 Revision 3 (May 2024) and SP 800-190
(September 2017)** for a one-time **200-page aggregate screening cap**. Existing
5 MiB/PDF and 12 MiB aggregate PDF byte caps remain unchanged. The named list,
versions, exact official URLs, expected preflight lengths/prefix hashes and limits
were frozen before the two complete requests. This is not authorization to admit
data, label questions, run a timed pilot or access holdout content.

## Full-file verification

Acquired 2026-11-02 UTC using two unauthenticated official NVL HTTPS GETs, redirects
disabled. Both returned HTTP 200/application-pdf at the exact URL, matched prior
Content-Length and 16-KiB prefix hashes, and stayed within byte caps. Full SHA-256
pins established here are **not** the earlier prefix hashes. No replacement,
partial-document truncation, SP 800-53B download or additional source fetch.

| Document | Bytes | Actual physical pages | Raw full-file SHA-256 |
| --- | ---: | ---: | --- |
| SP 800-171r3 | 1,593,213 | 120 | `3e4631df8b5d61f40a6e542b52779ef30ddbbfff31e09214fa94ad6e6f5e6d08` |
| SP 800-190 | 666,229 | 63 | `0ebad52c4a3aba971b3a707b056e57238d1c4ad8f212dffd461ff9f5fed1bdb6` |
| Total | **2,259,442** | **183 ≤ 200** | |

Strict pypdf structural checks confirmed both page counts against the prior header
declarations and no encryption **before canonical extraction**. Both documents'
title, DOI/publication number, authors and title-page dates matched the frozen
identity. 171r3's visual change log on physical page 120 contains no populated
entries. HTTP Last-Modified agrees with May 2024 / September 2017, but is evidence,
not an immutable version pin; the full SHA-256 is the byte identity for replay.

The [metadata inventory](nist-option-a-inventory.json) records the plan/hash,
acquisition, per-page canonical hashes/counts, lexical probes, parser identity,
warnings, visual-review page/render hashes and rights recommendations. It has no
document bodies, diagrams or gold and is not a labeling corpus manifest. Source
PDFs, extracted text and rendered pages remain private, outside Git. All candidates
have `corpus_admitted: false` and `redistribution: local_only`.

## Rights and document-specific recommendations

Screened extracted text across both documents for copyright/reproduction/credit
markers and quotations, checked quotation contexts, and inspected the rendered
authority/authorship and selected visual pages listed below. This is not a
line-by-line visual inspection of all 183 pages or legal advice. No linked reference
was fetched; a citation is not independent permission for its source.

### SP 800-171r3: preferred identifier/prose candidate for admission review

- Ron Ross and Victoria Pillitteri are credited to NIST. Physical page 3 states
  voluntary nongovernmental use, not subject to copyright in the United States,
  and appreciation for attribution. Checked visually as well as in extracted text.
- No separate restrictive credit or reproduced third-party figure identified by
  the screening; table of contents lists tables, not figures. Referenced sources
  remain referenced sources, not independently cleared material.
- Recommendation: **prioritize for independent review and a later owner admission
  decision**, with full citation, byte/version pin and transformation notice. Do
  not describe it as CC0, globally public domain, admitted, or automatically cleared
  for all downstream redistribution. Current decision remains local-only inspection.

### SP 800-190: useful semantic candidate, qualified rights and quality review

- Physical page 2 visually confirms Murugiah Souppaya (NIST), John Morello
  (Twistlock) and Karen Scarfone (Scarfone Cybersecurity). Physical page 3 explicitly
  says the publication is not subject to copyright in the United States and asks
  for attribution. Mixed authorship does not invalidate that statement by itself.
- Inspected **all three listed figures**, on physical pages **6, 17 and 20**:
  container architecture, VM/container comparison and lifecycle architecture.
  No separate external reproduction/copyright/image-credit notice was visible on
  those figure pages. That is a finding about visible credits, not proof of the
  artwork's complete rights chain. Government seal/trademarks are not a grant to
  reuse branding or imply endorsement.
- The definition quoted on physical page 15 cites NIST SP 800-125; that source was
  not separately fetched or rights-cleared. Trademark ownership notice on page 5
  is recorded as such, not treated as a license or infringement finding.
- Recommendation: **retain local-only; request independent assessment of the
  specific publication statement, mixed authorship and incorporated material before
  owner admission**. Prose may be useful for a later pilot, but diagram answers and
  table relationships cannot be assumed from canonical text. No whole-PDF/artwork
  redistribution clearance is claimed. No partial-admission/redaction policy added.

Reuse the pinned official policy snapshots from the first inventory: NIST's
technical-series policy distinguishes NIST employee works, foreign rights and
third-party content. Attribute authors, publication/revision, DOI and access date,
and use the requested “Republished courtesy of the National Institute of Standards
and Technology” wording if an approved workflow later republishes permitted work.
Any unresolved incorporated material remains excluded from admitted data; screening
does not make the owner decision or override rights uncertainty.

## Canonical/mapping and #62 results

Existing pinned fast/text-only extractor and unchanged normalization/chunker.
Existing isolated Python 3.12.16/macOS arm64 environment; no installations, OCR,
layout-model fallback or model inference. Set all three offline flags and existing
NLTK path before imports; denied socket connect/connect_ex/create_connection and
DNS resolution during extraction. No network during parsing, services or GPU.

| Document | Canonical characters | Mapped/serving chunks | Cf raw/canonical | Captured parser warnings |
| --- | ---: | ---: | --- | --- |
| 171r3 | 256,384 | 498 / 498 | 0 on all 120 pages | 0 |
| 190 | 163,709 | 300 / 300 | 0 on all 63 pages | 0 |

All **798** scoreable chunks mapped. No blank pages, mapping failures,
normalization-empty serving chunks or non-space canonical characters outside mapped
chunks. Real repeated partition pages matched canonical text; serving normalized
text **and physical-page order** matched. An additional extraction for lexical
inspection reproduced all 183 page hashes. Captured Python warnings and WARNING+
logging records during audit/additional extraction: none. This is not a guarantee
that all native-library stderr or every possible parser issue is observable.

Raw Unstructured-partition `Cf`, canonical `Cf` and canonical `Cc` counts are zero
on every page. **#62 needs no normalization change for these exact files/runtime.**
This is not a complete PDF glyph inventory and does not imply clean text, visual
completeness or retrieval accuracy. Shared-parser parity alone cannot detect a
loss shared by both evaluation and serving.

## Identifier retention and observed content limitations

- **171r3 dotted IDs:** pattern `\b03\.\d{2}\.\d{2}\b` finds **130 distinct IDs**
  in both normalized pypdf text and canonical text, **522 canonical occurrences**;
  no missing or extra distinct matches. Includes cross-references, tables and
  withdrawn entries, **not 130 active requirements, unique answers or labels**.
  Comparison extractor is a lexical check, not independent semantic verification.
  Fixed probes `03.01.01`, `03.01.02`, `03.14.01` retain counts **20, 8, 4**.
- **171r3 visual prose/table check:** physical page 16 shows a prose requirement;
  the ID/title and final account-monitoring clause land in different baseline
  chunks (zero-based global indices **53** and **55**). No query or gold was
  created. Do not infer a whole requirement is retrievable in one chunk.
- **171r3 physical page 103, Table 3:** visual rows are flattened into an ID column,
  then descriptions, then tailoring and requirement columns. Lexical survival is
  **not row-association preservation**. The source uses `AC-02(04)` (one canonical
  occurrence on that page), not `AC-2(4)`; a failed unpadded probe does not mean
  the control is absent. No automatic identifier rewriting was performed.
- **190 semantic probes:** `Docker` **15**, `Kubernetes` **3** and `PR.AC-4` **1**
  retain normalized-pypdf/canonical occurrence counts. These simple substring
  counts, including bibliography/acknowledgements, are not relevance judgments.
  Other `AC-2`/`IA-2` substring probes in the inventory likewise are not token-aware
  control counts. No dotted 171r3-style IDs occur in 190.
- **190 rotated margin noise:** all **61 physical pages 3–63** retain a spaced,
  misordered vertical availability/DOI notice at the start of canonical text.
  It contains no `Cf`/`Cc`; zero format-character counts therefore miss this
  quality defect. No silent deletion, de-spacing, OCR or normalization-v3 repair.
- **190 figure text loss:** rendered labels `Internal Registry` (page 6),
  `Virtual Machine Manager` (17), `Image Creation` (20) are visually present but
  each has **zero occurrences on that canonical page**. Captions/prose survive;
  diagram semantics and labels do not. Images remain private, not committed.
- **190 tables (visual pages 51, 55):** some rows serialize usefully, but wrapping
  splits identifiers such as `AC- 22`, whitespace erases columns and chunk boundaries
  do not certify row relationships. The current baseline remains unchanged; #58
  row-aware experiments remain future measured work.

Visual spot checks: 171r3 physical **3, 16, 103, 120**; 190 **2, 3, 6, 17, 20,
51, 55**. Rendered with existing pypdfium2 at scale 1.4; hashes/version in inventory.
This records exactly what was checked, not exhaustive visual or legal clearance.

## Next decision and verification

Option A now supplies the requested identifier-rich prose plus container semantics
for review, but **no corpus is admitted**. 183 screened pages are within the
one-time authorization, above the earlier approximate 50–150-page pilot suggestion;
do not silently trim documents to fit that suggestion. Owner selection/rights and
pilot-design approval remain required. If the owner needs a different source set,
seek new scoped approval rather than activating any suggested fallback automatically.

Code Review: assess the specific rights statements and visual findings, #62,
identifier/probe interpretation, table flattening and margin/figure defects before
the owner selects data. Recommend 171r3 as the stronger admission-review candidate;
190 remains conditional on independent rights/quality review. Keep raw bodies and
renders private until affirmatively cleared. No annotation or measured baseline
claim follows from green tests or this inspection.

Observed verification and exact CI results are recorded with this update's PR/relay.
Source inspection is separate from CI (CI uses only synthetic fixtures). Reproduction
uses the existing `audit_pdf` API and pinned full bytes/source metadata with offline
flags and network denial; verify source hashes and both page counts before extraction.
The frozen plan, original warning-free run and retained private renders/canonical text
permit comparison without publishing bodies. No canonical corpus manifest or gold
labels were created. G1(c) synthetic metrics stays a separate pending unit; G1(d)
remains unstarted. Rollback: reviewed revert of this metadata/docs evidence update,
without changing audit code, serving, schemas, dependencies, indexes or storage.
