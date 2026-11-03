# Opt-in requirement/page chunking (P2-B development variant)

This experimental strategy depends on the canonical parser/mapping work in draft
PR #12. It is a separate, stacked change, not a change to that PR or an enabled
deployment. No retrieval or generation improvement is established by unit tests
or offline text inspection.

## Opt in explicitly

```python
from rag.documents import parse_document

chunks = parse_document(
    pdf_bytes,
    "sample.pdf",
    chunking_strategy="nist-requirement-page-v1",
)
```

The default remains `chunking_strategy="title"`, including for non-NIST documents.
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
- Keep the complete requirement **page fragment** together, including DISCUSSION,
  REFERENCES, Source Controls and Supporting Publications until the next genuine
  requirement heading. A sentence fragment misclassified as a title is not a split.
- Headers/footers and family headings are separate, unattributed fragments. The
  main `References` or an `Appendix A.`-style title ends requirement attribution;
  uppercase `REFERENCES` within a requirement does not. No text is dropped.
- Carry the owning `requirement_id` across pages, never the text. A continuation
  and its references remain attributed to their owner without mixing in the next
  requirement. Every chunk has exactly one physical page. Duplicate body headings
  fail closed. Tables, inline IDs and standalone IDs do not introduce headings.
- `DocumentChunk.requirement_id` is optional (`None` for the default). It is
  descriptive provenance in the Python result, not a new retrieval filter. The
  existing engine payload and prompt are unchanged; this PR does **not** add
  control-ID extraction, hybrid search, larger k or MMR.

This grammar targets the admitted English SP 800-171r3 fast-parser layout. It is
not a universal NIST parser, table reconstruction or corpus-admission mechanism.
Parser misclassification or an unexpected heading convention requires inspection,
not a silent fallback. Default title parsing remains available for other formats.

## Size and page trade-offs

There is deliberately **no character-based cut within a page fragment**. Otherwise
an unfortunate size boundary could recreate the sentence/reference problem this
variant tests. Chunks may exceed the default 1,200-character bound, including in
unattributed front matter and appendices. Character counts are not token budgets.
This strategy adds no parser resource sandbox or model-context guarantee.

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
