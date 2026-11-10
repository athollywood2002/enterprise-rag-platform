# Managed document formats and reindexing

These formats apply to browser uploads, configured read-only server folders and `/library/*` API clients. The legacy `/ingest`, `/ingest-document`, `/ask` and n8n collection contracts are unchanged. Legacy n8n documents are not automatically imported into the managed library.

| Format | Extracted content | Citation location | Important limitations |
| --- | --- | --- | --- |
| TXT | UTF-8 paragraphs and Markdown sections | section / paragraph | No inferred layout or pages |
| CSV | UTF-8 comma-delimited records with unique nonempty headers; quoted field/value associations | record, column and continuation offsets | Ordinary records stay together; oversized records repeat identifying/header context. No SQL or type inference. |
| PDF | Text on every physical page | PDF page | No OCR; encrypted or textless pages fail |
| DOCX | Body headings, paragraphs and table rows in order | section, paragraph, table / row | Tracked changes fail: accept/reject them first. Nested tables, text boxes, content controls and fields fail with export guidance. Headers, footers, comments, foot/endnotes, images and embedded objects are excluded with warnings. No page numbers or OCR. Table grid positions include omitted leading/trailing cells. Merged cells are emitted once per row with their column span and matching header labels; visual layout is not reconstructed. |
| RTF | Readable text, Unicode, paragraph boundaries; single Windows-1252 or Windows-1251 code page | paragraph | Objects, images, fields, revisions, tables, comments and header/footer content fail with export guidance. Literal high bytes and hex escapes use the declared code page (default Windows-1252); Unicode controls override fallback bytes. Matching/default font charsets are supported. Mixed code pages, conflicting font charsets, other code pages and Mac/DOS encodings fail explicitly: export Unicode TXT or DOCX. No inferred pages. |
| PPTX | Slide titles, text shapes, grouped text and tables in shape-tree order | slide / shape / table row | Speaker notes excluded with warnings. Hidden slides included with warnings. Images, charts and embedded objects excluded with warnings; no OCR or layout reading-order inference. Image-only decks fail. |
| XLSX | Visible worksheets, labeled rows, stored cell values, ISO dates and number formats | sheet / row / cell range; cell and offsets for continuations | Explicit Excel Table headers or the documented single-table header convention after sparse preambles; ambiguous layouts need an Excel Table. Hidden sheets, rows and columns excluded with warnings. Worksheet hidden-by-default rows are excluded unless explicitly marked visible. Merged cells use anchor values only. Cached formula results may be stale; missing results are unavailable. Images, charts, comments and embedded objects are excluded. |

Legacy `.doc`, `.xls`, `.ppt`, macros, OCR and LibreOffice conversion are outside this milestone. Never rename a legacy extension to bypass preview: content signatures are checked.

## Operation

Use the existing [installer quickstart](../README.md#install-and-open). Dependencies are in the application and hash-locked Docker image; no Office installation is needed. Select a small folder, preview eligibility, ingest, and inspect the completed file's warnings and returned excerpt locations. Preview validates names/sizes, not complete document structure; corrupt/encrypted/unsupported content fails during the bounded parser step. Export a simpler file and reselect it when instructed.

Parsing and chunking run in a Linux child with a wall deadline, 512 MiB address-space and 32 MiB output-file ceilings. Office packages additionally allow at most 4096 parts, 64 MiB total expanded bytes, 32 MiB per part and a 200:1 per-part expansion ratio. DTD/entity declarations and macro parts are rejected. Extraction is bounded by configured characters/chunks and 10,000 text blocks. Oversized prose is split into labeled character continuations with bounded repeated section context; no text value is silently truncated. External relationships are never fetched or executed.

## Spreadsheet policy and limits

CSV and XLSX use the same row-preserving chunk contract. Normal rows stay in one chunk. Oversized rows split into cell continuations with full column labels, row coordinates and short identifying values repeated; `value_start`/`value_end` identify the complete value's character spans. No indexed value is silently shortened. A context too large to fit produces an explicit error. Names, amounts and units stay paired with their column labels; this is retrieval over text, not a calculation engine.

XLSX respects worksheet `sheetFormatPr.zeroHeight` and explicit row `hidden` overrides. Under a hidden-by-default sheet, only rows explicitly marked `hidden="0"` or `hidden="false"` are visible; under the normal visible default, explicitly hidden rows remain excluded. Each affected sheet reports `hidden rows excluded`. Header selection and its limits are documented in the [table quality correction](table-evidence-quality.md#worksheet-headers).

XLSX opens two read-only-in-purpose workbook representations: formulas and supplied cached values. It never evaluates formulas. An existing cached result is labeled **not recalculated**; an absent cache is **unavailable**, never zero. External-reference formulas are unavailable and external links are never fetched. Formula expressions are not indexed. Number-format strings are retained as context, not interpreted as new calculations. Save/recalculate in your spreadsheet application before export when fresh formula results are needed.

Limits are 32 worksheets, 10,000 row indices per sheet/CSV, 256 columns, 100,000 cells per workbook/CSV, 100,000 characters per cell and 200 characters per header label, plus package, text, child-memory and chunk limits. Hidden content counts toward safety limits. Multiple header regions require explicit nonoverlapping Excel Tables, or separate sheets/CSV files. Empty or image/chart-only workbooks fail explicitly. Password-protected/encrypted files and macro-bearing packages fail; `.xlsm`, `.xls`, `.doc` and `.ppt` remain ineligible.

## Existing data

Keep volumes and the existing installation directory. Rebuild the API only when you choose to deploy the new version; stop/start alone keeps its saved image. Do not delete the library or run `down -v`.

The current parser fingerprint is `folder-v4.2-xlsx-header-association`. It adds corrected XLSX headers to the earlier DOCX table-grid, RTF code-page and XLSX row-visibility corrections; v4.1 remains a supported historical fingerprint. Previously indexed text is not rewritten automatically. Old committed revisions remain searchable while their original parser fingerprint and current embedding model digest match a supported historical parser. New and old compatible collections can be searched together. Changing the embedding model/digest still requires explicit reingestion; incompatible vectors are not mixed.

To adopt new chunking/location metadata, select the same source name and relative folder paths and ingest again. The first import after a parser change intentionally reindexes even unchanged bytes into the new parser collection. The old revision stays searchable until successful verification and atomic publication of its replacement. Failed/cancelled replacements keep the previous searchable revision. After successful replacement, normal cleanup may remove that document's retired points; untouched documents and volumes remain. A second unchanged import skips after verifying compatible indexed points. Back up data before deployment if rollback to an older application image is required; old code cannot search newer parser fingerprints.

The retained November 10 development evaluation exercised DOCX/XLSX and exposed remaining retrieval/grounding failures; it did not exercise RTF/PPTX. Real-model benefit from this header/retrieval correction remains unmeasured. Genuine-format extraction, transactions and synthetic-model API tests do not establish semantic correctness.
