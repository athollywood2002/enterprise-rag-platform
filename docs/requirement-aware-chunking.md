# Opt-in bounded requirement/page chunking (P2-B v2 draft)

This experimental strategy is a separate draft, not an enabled deployment. PR #13
remains stacked on draft PR #12 for now; the parser/mapping code it needs is already
on main. PR #12 also has unrelated audit code/tests and pilot documentation: no
technical dependency on those files was found. Retargeting/rebasing needs separate
approval; neither PR is merged or altered by the dependency recommendation.
No retrieval or generation improvement is established by offline inspection.

## Opt in explicitly

```python
from rag.documents import parse_document

chunks = parse_document(
    pdf_bytes,
    "sample.pdf",
    chunking_strategy="nist-requirement-page-v2",
)
```

The default remains `chunking_strategy="title"`, including for non-NIST documents.
The earlier unbounded v1 draft is superseded, not retained as an indexing option;
its commit and private receipts remain historical evidence, not v2 results.
Existing HTTP ingestion still uses the default; no endpoint, environment setting
or automatic filename/content detection enables this variant. The opt-in rejects
non-PDF input, unknown/backtracking pages and documents without supported headings.

For offline canonical inspection, pass the same keyword to
`evaluation.canonical.extract_pdf`. Canonical page text, parser identity,
normalization, source version and character offsets do not change with strategy.
The returned extraction has a distinct `chunking_policy` identity. Always validate
all mappings and serving/canonical parity for an admitted source before indexing.

## Boundaries and attribution

- Requirement scope starts at a `Title` element matching a `3.x.` family heading.
  Within that scope, a `Title` beginning `03.xx.xx` followed by an English name
  starts a requirement. An introductory ID-shaped example is not a requirement.
- Within each requirement/page, greedily pack conservative sentence units toward
  1,200 raw characters, with a hard 2,400-character cap. Never cut inside a unit.
  DISCUSSION and arbitrary parser titles do not force cuts. Protect dotted IDs,
  decimals, initials, list labels and common abbreviations. Paragraph breaks and
  semicolons do not by themselves identify sentence boundaries. This deliberately
  narrow grammar is not a general English sentence-segmentation guarantee.
- Keep each REFERENCES/Source Controls/Supporting Publications tail indivisible
  with its owning requirement ID; it can be its own same-owner subchunk, never
  attached to the next requirement. No invented heading prefixes or overlap.
- Headers/footers and family/end-section titles are **diagnostic-only**. The
  main `References` or an `Appendix A.`-style title ends requirement attribution;
  uppercase `REFERENCES` within a requirement does not. No source text is discarded
  from canonical accounting. Other unassigned front/back matter remains indexable;
  lack of an ID alone is not grounds for excluding substantive text.
- Carry the owning `requirement_id` across pages, never the text. A continuation
  and its references remain attributed to their owner without mixing in the next
  requirement. Every chunk has exactly one physical page. Duplicate body headings
  fail closed. Tables, inline IDs and standalone IDs do not introduce headings.
- `DocumentChunk.requirement_id` is optional (`None` for the default). It is
  descriptive provenance in the Python result, not a new retrieval filter. The
  existing engine payload and prompt are unchanged; this PR does **not** add
  control-ID extraction, hybrid search, larger k or MMR.

Canonical extraction maps **all** fragments in source order before excluding
layout. `CanonicalExtraction.chunks` contains only indexable mappings;
`layout_skipped` retains the excluded mapped records (text, physical page, offsets,
page hash and match count). `mapping_counts` reports both. Serving parsing returns
only indexable chunks with contiguous numbers. Use canonical diagnostics, not a
second attempt to map the filtered serving texts, to inspect source accounting.

For the pinned admitted SP 800-171r3 source SHA-256, both paths require the exact
set of 130 IDs (including withdrawn headings) **and** the SHA-256 of all ordered,
whitespace-collapsed heading texts joined by newlines. A missing/demoted heading,
extra ID, title change or reordering fails closed. This source-specific guard is
not a claim of universal coverage or independently verified gold labels.

This grammar targets the admitted English SP 800-171r3 fast-parser layout. It is
not a universal NIST parser, table reconstruction or corpus-admission mechanism.
Parser misclassification or an unexpected heading convention requires inspection,
not a silent fallback. Default title parsing remains available for other formats.

## Size and page trade-offs

1,200 is a target, not an absolute bound. An indivisible sentence, table or reference
tail may exceed it up to 2,400 raw characters. Above 2,400, reject the document with
an explicit error: never split the unit, truncate it, omit it or fall back silently.
Diagnostic-only layout is not embedded and is excluded from the indexing cap.
Character counts are not token budgets. This strategy adds no parser sandbox or
model-context guarantee. Physical page boundaries can still interrupt sentences.

Before any separately authorized model run, inspect maximum sizes and resolve
embedding/context budgets using the exact installed models. Never silently
truncate, drop long fragments, change chunking mid-run or assume all five retrieved
fragments fit a generation context. No model calls are needed for the structural
tests. A sentence that crosses a **physical page** can still be split: preserving
page provenance takes precedence over promising cross-page sentence continuity.

## Tests, evaluation and migration

Deterministic authored synthetic tests cover false titles inside the phrase
"records retention policy", reference ownership around IR-04 and consecutive
requirement IDs, introductory examples, page continuation, layout, tables, empty
text, long indivisible units, duplicate headings and strict canonical offsets.
An optional generated PDF test exercises the real pinned parser and both serving
and canonical strategies. Existing generic-format tests remain unchanged.

Offline candidate coverage against the **entire transformed index** measures
whether a span could be represented, not whether retrieval will rank it at k, a
model will use it, or an answer is correct. Targeted development failures motivated
this design, so later results must not be presented as blind generalization.

Use a **new isolated collection** and a new run receipt for a reviewed A/B plan.
Chunk numbers/text and therefore point identities change; never upsert these into
the baseline collection or reinterpret old ranks under the new policy. Keep source,
canonical pages, frozen questions/order and candidate provenance fixed. Compare
retrieval first; any generation uses the same reviewed prompt and model artifact,
with nondeterminism/context caveats. Do not bundle retrieval diversity or hybrid
changes into this chunker comparison. Model execution still needs owner approval.

Rollback is opt-out: call the default title strategy. Preserve all experimental
and baseline evidence; this code performs no collection migration, deletion,
service start or cleanup. PR #12 remains draft/unmerged while this dependency is
reviewed independently.
