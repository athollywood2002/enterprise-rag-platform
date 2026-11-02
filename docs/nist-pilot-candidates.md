# NIST PDF pilot candidates — inspection, not admission

**Implemented/tested:** offline metadata-only audit and synthetic tests.
**Observed:** bounded official-source acquisition and fast/text-only inspection
of three candidates. **Not authorized/performed:** corpus admission, real labels,
timed pilot, embeddings, retrieval baseline or holdout setup.

**Screening follow-up (before admission):** the owner approved screening exactly SP 800-171r3
and SP 800-190 under a one-time 200-page cap. See [Option A inspection](nist-option-a-inspection.md):
183 actual pages inspected, with no admission at inspection time. The earlier 268-page three-document
preflight remains blocked for that original list; no general cap increase applies.

**Subsequent owner decision:** [limited admission record](pilot-admission.json)
approves only the vetted SP 800-171r3 for development-pilot use and defers SP 800-190.
Historical `admission=false` inspection fields above are retained, not rewritten.
The owner subsequently approved #69–#72: the [revised pilot protocol](development-pilot-protocol.md),
20 private real draft questions for review, and private canonical-manifest preparation.
See [manifest verification](pilot-manifest-verification.json) and
[draft review metadata](pilot-question-review.json). Independent review and a later
owner execution decision are still required; no gold labels or pilot run.

This report supports an owner decision; it does not make it. All three sources
remain `local_only` in inspection metadata. Raw PDFs, downloaded HTML and extracted
text stay outside Git. The [inventory](nist-pilot-inventory.json) contains source
URLs/checksums, rights decisions, selective parser pins, physical page hashes,
format-character counts and mapping diagnostics, not document bodies or gold.

## Frozen shortlist and acquisition

### Review #64: first shortlist does not meet pilot/M1 selection needs

The review accepted this audit/rights method, not the suitability of the first
candidate set. None is admitted. Cloud-definition documents do not supply the
planned requirement/control-ID stratum, and 800-145 alone is too small for a
representative timed 20-question pilot. The original inventory remains evidence
of that inspection, not a recommendation to proceed with it unchanged.

A second fixed request plan names SP 800-171 Rev. 3, SP 800-53B and SP 800-190,
with their official landing/download URLs and the **unchanged** caps. The
[second-shortlist preflight](nist-second-shortlist-preflight.json) records the
plan hash, exact request metadata, landing hashes and prefix hashes. It is
**blocked before full acquisition**, not a second canonical inventory:

| Candidate | HEAD-declared PDF bytes | Header-declared physical pages |
| --- | ---: | ---: |
| SP 800-171 Rev. 3 | 1,593,213 | 120 |
| SP 800-53B | 1,627,293 | 85 |
| SP 800-190 | 666,229 | 63 |
| Total | 3,886,735 | **268** |

Byte limits fit, but **268 exceeds the existing 180-page batch cap by 88**. The
two ID-rich documents alone declare 205 pages. No caps were raised, documents
trimmed, candidates substituted or batches silently split. Stop and request an
owner decision: revise the shortlist (e.g. 53B + 190 declares 148 pages), or
explicitly authorize a higher cap for screening all three. These are options,
not owner selection/admission or proof either pair meets rights/quality gates.

Preflight used nine unauthenticated requests: three bounded landing GETs, three
PDF HEADs and three `Range: bytes=0-16383` GETs. Required HTTP 206 and matching
Content-Range, refused redirects, and consumed exactly **49,152 PDF-prefix bytes**.
Page counts come from `/N` in each first linearization dictionary, **not** a full
parser run; full acquisition must verify them. Prefix SHA-256 values are explicitly
**not full-document SHA-256 pins**. No complete second-batch PDF acquired or
parsed; no Cf, canonical-page hashes, mapping, table or identifier-retention
claims for this set. Prefix binaries and HTML bodies remain outside Git.

The preflight also found a revision issue before full acquisition: the initial
plan provisionally named 53B as October 2020, but the official landing page says
September 2020 with December 10 updates and announces **Release 5.2.0 (August 27,
2025)**. Exact downloaded release and full byte hash require confirmation before
proceeding; do not silently treat the current URL as the original release.
171r3's final date is May 14, 2024; its June planning note describes HTML
availability, not a verified PDF erratum. 190's final date is September 25, 2017;
its outside coauthors are a rights-review flag, not a completed rights finding.

**#65 follow-up:** SP 800-53 Rev. 5 is not this SP 800-53B candidate and was not
requested. It needs its own owner-approved resource preflight if wanted later;
do not silently excerpt it or infer permission to expand current caps. G1(c)
synthetic metrics remains a separate pending unit; this blocked preflight does
not change normalization or authorize labels, holdout operations or runtime work.

### Original first-batch evidence

Selected these three cloud-infrastructure publications **before** downloading;
did not substitute other publications after seeing results. Acquired 2026-11-02
UTC from official CSRC/NVL URLs. Release dates are not byte pins: future use must
verify the recorded SHA-256 and reject changes rather than silently updating it.

| Candidate/revision | Bytes | Physical pages | Mapped chunks | Canonical characters |
| --- | ---: | ---: | ---: | ---: |
| SP 800-145, September 2011; erratum 2012-04-27 | 85,781 | 7 | 21 | 10,761 |
| SP 800-144, December 2011 | 1,105,061 | 80 | 379 | 228,024 |
| SP 800-210, July 2020 (final July 31) | 1,289,805 | 34 | 144 | 79,462 |

PDF SHA-256 values:

```text
800-145  7b0c1a9fdfc67218b8ba2098f448c100c27070db91736b3c87fed63bfa21d418
800-144  47f0fdf31f4f2b37fb2a8fa0bf77235aad0b3daa74a6397603a619a839500a42
800-210  147271600180dfd048c21da0892a1228f574bdf7b69f5982710a3aa6ebf79a95
```

Ten unauthenticated requests: three landing pages, three PDFs and four policy
requests. Eight bodies accepted; two HTTP 301 responses rejected (no automatic
redirect). The CSRC copyright link also redirected; its explicit same-origin
destination was inspected as a separate request. The general policy links to the
more specific technical-publications policy, fetched once. No crawl, linked paper
fetches, credentials or private sources. Limits: 5 MiB/PDF, 12 MiB total PDFs,
256 KiB/HTML response, 180 physical pages total. Accepted PDFs total **2,480,647
bytes / 121 pages**. Exact URLs, response types and SHA-256 were checked. Every
accepted PDF was unencrypted. Acquired HTML bodies and policy hashes are pinned in
the inventory; dynamic HTML is evidence of this inspection, not immutable content.

## Rights screening and proposed owner decision

The official [technical-publications policy](https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications)
distinguishes NIST-employee works, foreign rights and third-party works. It asks
for a recommended citation and “Republished courtesy of the National Institute
of Standards and Technology.” NIST hosting alone is not a blanket grant. The
[general policy](https://www.nist.gov/copyrights-disclaimers) likewise excepts
copyright-marked material. No candidate is labeled CC0 or generically licensed MIT.

- **800-145: preferred small pilot candidate, pending owner/reviewer admission.**
  NIST authors Peter Mell and Timothy Grance; physical page 5 expressly permits
  voluntary non-government use and says it is not subject to copyright, with
  attribution desired. All seven extracted pages were read. No external reproduced
  quotation/figure credit or restrictive notice identified in that text. This is
  text-based screening, not exhaustive visual/legal clearance. Preserve attribution,
  original version/hash and any transformation notice in a later admitted corpus.
- **800-144: exclude from proposed admission until external passages are cleared.**
  Physical page 11 has a no-copyright statement, but an outside coauthor is credited
  on page 4 and pages 47–48 contain direct external quotations (including a provider
  statement). Citation alone is not permission. No copyrighted quotation is included
  in this report; no redaction/partial-document policy was invented to bypass the
  gate. Offline local inspection is not permission to redistribute or label it.
- **800-210: defer admission for independent mixed-authorship/figure review.**
  Physical page 3 explicitly says not subject to copyright in the United States;
  page 2 credits both NIST and outside university authors. Six diagrams need
  provenance and visual review. No contrary copyright notice was identified in
  extracted text. Outside authorship alone does not prove a restriction or invalidate
  the publication statement; the conservative decision is to seek review, not infer
  worldwide redistribution permission from hosting or a missing notice.

These are conservative screening decisions, not legal advice. Do not add unclear
material to an admitted corpus, even when extraction and CI succeed. The owner may
choose 800-145 first, resolve the others, or authorize a different bounded shortlist.
One seven-page definitions document is **not** evidence that the eventual >=150
question dataset, document-grouped split or identifier-stratum floors are feasible.
The three candidates emphasize cloud concepts/access policy, not rich control IDs
or command flags. Do not invent `AC-2(4)`/CVE coverage or treat cited identifiers as
human-verified answer spans. This batch produces no proposed multi-document admitted
corpus; owner and independent rights review remain the blocker.

## Extraction and #62 findings

Used existing isolated Python 3.12.16 on macOS arm64 and pinned
`unstructured-pdf-fast-v1` packages from the inventory. Normalization remains
`nfc-quotes-artifacts-whitespace-v2`; baseline chunking is unchanged. Offline flags
set before parser imports; socket connect/connect_ex/create_connection/getaddrinfo
were denied during inspection. No OCR, layout-model fallback, network/model calls,
GPU, Qdrant, services or downloads during parsing. A non-zero-indexed PDF xref warning
was emitted during the run; parsing continued without changing source bytes.

`evaluation.pdf_audit.audit_pdf` performs three real passes:

1. Existing `extract_pdf`: canonical physical pages and scoreable chunk mappings.
2. Existing PDF partition helper again: raw element `Cf` inventory and a normalized
   page-text comparison against the first pass. It neither patches nor repairs text.
3. Existing serving `parse_document`: compare normalized chunk text **and physical
   page order** with extraction. Normalization-empty serving chunks are counted
   separately, not silently called parity.

All **544** scoreable chunks mapped; no mapping failures, blank physical pages or
non-space canonical characters outside mapped chunks. All 121 repeated partition
pages matched their canonical text, and serving parity held for all three PDFs.
**Raw Unstructured partition Cf: zero on every page. Canonical Cf/Cc: zero on every
page.** #62 is checked for this exact sample/runtime; no normalization-v3 or visible
placeholder change is needed based on these results. Future PDFs must be checked
again. This does not inventory every PDF glyph/object or prove visual completeness:
fast extraction omits diagram semantics, and all three comparisons share parser
dependencies. Table/reading-order fidelity still needs human inspection of selected
pages before labels.

The JSON is deliberately not `canonical-corpus-v2`: it contains no page text and
cannot be fed directly to the labeling helper. No real corpus manifest, labels,
questions, split, holdout or protected file was created. Rights-unresolved candidates
were inspected locally only and remain excluded from admission.

## Reproduction and review

Offline audit API (no downloader or path discovery):

```python
import hashlib
import json
from pathlib import Path

from evaluation.corpus import SourceRecord
from evaluation.pdf_audit import audit_pdf

inventory = json.loads(Path("docs/nist-pilot-inventory.json").read_text())
candidate = inventory["documents"][0]
data = Path("/owner/explicit-candidate.pdf").read_bytes()  # placeholder; no holdout
assert hashlib.sha256(data).hexdigest() == candidate["source_sha256"]
source = SourceRecord.model_validate(candidate["source"])
result = audit_pdf(data, doc_id=candidate["doc_id"], source=source)
assert result["pages"] == candidate["pages"]
```

Only run against separately approved local candidate bytes in the pinned environment
with `AUTO_DOWNLOAD_NLTK=false`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, existing
NLTK assets and network denial. Missing package/resources must fail, not trigger
installation. The API does not enforce OS isolation; caller/test network guards
remain required. Do not point it or agents at holdout/encrypted/private documents.
The acquisition/rights decisions are not inferred by this API. An initial private
driver filename shadowed Python's `inspect` module and failed before extraction;
renamed it and reran successfully. No source/parser policy correction was needed.

```bash
python -m pytest -q --run-document-tests tests/test_pdf_audit.py
python -m pytest -q --run-document-tests
python -m ruff check .
python -m ruff format --check .
```

Synthetic tests exercise Cf counting, real fast-PDF metadata/page/serving parity,
repeatability, no body emission, explicit mapping failures and simulated second-pass
format drift. The drift test mutates only a synthetic parser result; it is not
evidence of a format character in the NIST sources. Real source inspection is
recorded separately above, not run by CI. No test implies label quality or rights.

Code Review: assess per-source rights/provenance, #62 inventory and shared-parser
quality limitations before owner selection. G1(c) synthetic metrics/scorecard stays
a separate delivery; G1(d) remains unstarted. Rollback: reviewed revert of this
audit/test/metadata/guide addition; no service, corpus, storage or index migration.
