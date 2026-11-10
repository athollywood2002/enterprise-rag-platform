# Table evidence and grounding correction

This correction starts from main `32437ab`. It leaves model identities, thinking mode, generation cap, legacy API/n8n behavior and the original evaluations unchanged. No live inference is part of its validation.

## Worksheet headers

Use **Excel Tables** (Insert → Table, with the header-row option) to explicitly select each table's header and range. Multiple nonoverlapping tables may have different headers on the same sheet. Header cells must be visible, nonempty, distinct text, with units included in the label; formula/merged/missing headers fail with `xlsx_header` guidance. Hidden labels are never recovered from table metadata. Totals are retained but excluded from named-data-row ranking. Visible cells outside explicit tables are preserved as coordinate-only context with a warning.

For a plain worksheet, the documented convention is one rectangular table: optional sparse title/metadata rows, then the first visible row covering **all populated visible columns**, containing unique text labels. That row supplies headers, including when the table starts to the right of column A. Leading empty columns are not invented. The parser reports this selection policy in a warning and provides `header_row` and `header_range`; inspect them. A full-width metadata row is indistinguishable from a header under this convention: select the actual region with an Excel Table instead. Multi-level/merged headers, separate units rows and multiple plain table regions are not inferred; flatten labels including units or use explicit tables. Missing/duplicate/non-text labels, near-full preambles, multiple full text rows before typed data, and detected blank-separated competing regions produce an actionable error, preserving any previous committed revision.

Data-row text repeats each actual column label and value. `column_labels`, `header_row`, `header_range`, `row_kind` and optional `table_name` survive chunking, Qdrant payloads and API responses. Cell continuations repeat their relevant label/unit, short row identifiers and exact cell/value offsets; all column labels remain metadata. No value is silently shortened. Titles/metadata remain searchable coordinate-only blocks. Hidden-content, formula-cache, external-link, resource and safe-replacement policies remain in force.

Example from the same genuine generated workbook before/after this correction (not an updated live library):

```text
Location in both: Sheet Systems — Europe · row 5 · A5:F5
Before: "A Catalog context 1; effective 2026-07-01": "SVC-002";
        "B (unnamed)": "Gatehouse SSO"; ... "E (unnamed)": "2"; "F (unnamed)": "0"
After:  "A Service ID": "SVC-002"; "B Service": "Gatehouse SSO";
        "C Owner": "Zoë"; "D Tier": "Tier 1";
        "E RTO hours": "2"; "F RPO minutes": "0"
Header location: A4:F4 (distinct from the data location A5:F5)
```

## Small retrieval change and offline evidence

Managed search retains global dense/BM25 reciprocal-rank fusion over compatible collections and adds one narrow ranking lane: a short multiword cell value or identifier must match the question at token boundaries **and** the question must mention a column label. For example, a named service plus RTO/RPO can promote its labeled data row over a generic recovery definition. It does not recognize any particular service, workbook, field name or expected answer in production code. Simple plural normalization allows `RTOs` to match `RTO`. Ordinary non-row passages are unaffected unless a qualifying row competes for the same context slots.

This lane uses the existing filtered bounded scan; there is no extra model call, database service, query expansion or retry. It is ranked globally, with stable ID tie-breaking, before RRF. Selected-job/committed-revision filters and the 5,000-chunks-per-collection ceiling are unchanged. Response metadata retains `method=dense-bm25-rrf`, discloses `ranking_lanes` and `structured_row_candidates`, and keeps `claim_support_verified=false`. Historical chunks without row metadata remain searchable through the original lanes. Cell continuations are not independently promoted by the named-row lane.

`test_n10_service_rows_reach_answer_context_with_distractor_dense_ranking` uses a genuine parsed XLSX and an intentionally adverse, **synthetic dense ranking** favoring five recovery-note distractors. It measures required **rows**, not workbook hits:

| Condition (same question, corrected XLSX rows, top_k=5) | Required service rows in final context |
| --- | --- |
| Dense + BM25 alone | 0/2 |
| Dense + BM25 + named-row/field lane | 2/2 |

Both Gatehouse SSO and Beacon security rows, with RTO hours and RPO minutes, reach the actual captured `/api/chat` request. This is deterministic pipeline evidence, not a replay of the original embeddings or a measured live recall improvement. The exact original workbook/dense vectors are not reconstructed from the Q&A results. The existing native amd64/ARM64 synthetic container checks also ingest a preamble-bearing XLSX and require both named service rows and their zero/nonzero RPO values in HTTP sources. No real-model answer is graded by those checks.

## Grounding: implementation versus measurement

Managed requests now separate generic system instructions from JSON evidence records with stable citation IDs, source identity, location and full text. Source text is not clipped or converted into inferred policy conclusions. JSON escaping preserves source boundaries; it does not establish immunity to prompt injection. Legacy `/ask` retains its original message contract.

The compact instruction set emphasizes evidence-supported supersession, unknown replacements, absent calendar inputs, material qualifications, complete approval gates, exact claim-to-excerpt support and actual requested calculations. It explicitly distinguishes missing completion evidence from a failed/unperformed action. No case-specific answer or private reasoning is added to the context. Valid citation numbers and completed generation still do not establish factual support.

Sanitized retained excerpts/questions/answers under `tests/fixtures/quality` preserve N03, N04, N11, N15, N17, N20, N22 and N24 for offline context-integrity checks. **N11 data [2] and actual headers [4] were both retrieved**: the model failed to combine available evidence. Header association reduces that burden; it does not revise the diagnosis to missing header retrieval. Tests preserve the supersession warning, holiday-calendar gap, “if requested,” separate approval source, Security signoff and unknown rehearsal status. They do not claim those semantic failures are fixed by mocked responses.

The original 30-question baseline remains unchanged. The separate November 10 addendum retains **16/24 fully passing**, with 17 answer passes, four partials and three failures; N15 retains its clarity flag. Its metadata correction renames the checksum-file hash to `sha256sums_sha256`. Neither original archive nor its 82 checksummed files is rewritten or published by this correction.

## Later update/reindex and same-24-question check

This is one deferred live check, requiring separate execution authorization:

1. After review/merge approval, record the selected commit, saved image, model digests/settings and index state; retain a restorable backup. Update the existing installation and rebuild its API with `bash setup.sh --device cpu --rebuild`. Keep volumes, key, model names/digests, thinking setting and 1536-token cap unchanged.
2. Parser fingerprint becomes `folder-v4.2-xlsx-header-association`; v4.1 and earlier supported revisions remain readable. Reimport the **same folder, source name and relative paths**. The fingerprint change deliberately reindexes unchanged bytes for all managed formats. Existing committed revisions stay searchable until each replacement is verified and published; failed/cancelled replacements retain their prior revision. Successful replacement follows the existing retired-point lifecycle; no manual data cleanup is needed. An unchanged subsequent import skips normally.
3. Confirm actual service headers/units and coordinates in the new chunks, document identities and successful revision changes. Resolve any `xlsx_header` error through explicit Table selection before continuing; do not silently count an old retained revision as corrected extraction.
4. Send the **same frozen 24 questions once**, in the same order, selected-job scope and `top_k=5`. No automatic retries or question/expected-answer edits. Save original HTTP bodies, generation evidence, retrieved rows, timings and before/after index/model/config snapshots in a new evidence directory. Preserve the original run/addendum.
5. Compare required-passage recall (N10 both rows, N11 usable header/value associations), answer correctness, exact cited-claim support and material conditions. Review N20/N24 abstention, N03/N04/N17/N22 qualifications/citations and N15's leading result explicitly. Report answer/citation/combined scores separately and re-review successes too. The same exposed questions are a development comparison, not a blind benchmark. RTF/PPTX remain untested by this corpus.

Offline checks do not authorize VM changes, reingestion, live inference, image publication or merges. Connectors/retention, new formats and installer behavior are outside this correction.
