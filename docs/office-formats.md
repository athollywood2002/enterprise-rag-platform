# Managed document formats and reindexing

These formats apply to browser uploads, configured read-only server folders and `/library/*` API clients. The legacy `/ingest`, `/ingest-document`, `/ask` and n8n collection contracts are unchanged. Legacy n8n documents are not automatically imported into the managed library.

| Format | Extracted content | Citation location | Important limitations |
| --- | --- | --- | --- |
| TXT | UTF-8 paragraphs and Markdown sections | section / paragraph | No inferred layout or pages |
| CSV | UTF-8 labeled values | chunk | Structured row improvements follow separately |
| PDF | Text on every physical page | PDF page | No OCR; encrypted or textless pages fail |
| DOCX | Body headings, paragraphs and table rows in order | section, paragraph, table / row | Tracked changes fail: accept/reject them first. Nested tables, text boxes, content controls and fields fail with export guidance. Headers, footers, comments, foot/endnotes, images and embedded objects are excluded with warnings. No page numbers or OCR. Merged table cells are emitted once per row; layout is not reconstructed. |
| RTF | Readable text, Unicode, paragraph boundaries | paragraph | Objects, images, fields, revisions, tables, comments and header/footer content fail with export guidance. Export to DOCX or plain text; no inferred pages. |

| PPTX | Slide titles, text shapes, grouped text and tables in shape-tree order | slide / shape / table row | Speaker notes excluded with warnings. Hidden slides included with warnings. Images, charts and embedded objects excluded with warnings; no OCR or layout reading-order inference. Image-only decks fail. |

Legacy `.doc`, `.xls`, `.ppt`, macros, OCR and LibreOffice conversion are outside this milestone. Never rename a legacy extension to bypass preview: content signatures are checked.

## Operation

Use the existing [installer quickstart](../README.md#install-and-open). Dependencies are in the application and hash-locked Docker image; no Office installation is needed. Select a small folder, preview eligibility, ingest, and inspect the completed file's warnings and returned excerpt locations. Preview validates names/sizes, not complete document structure; corrupt/encrypted/unsupported content fails during the bounded parser step. Export a simpler file and reselect it when instructed.

Parsing and chunking run in a Linux child with a wall deadline, 512 MiB address-space and 32 MiB output-file ceilings. Office packages additionally allow at most 4096 parts, 64 MiB total expanded bytes, 32 MiB per part and a 200:1 per-part expansion ratio. DTD/entity declarations and macro parts are rejected. Extraction is bounded by configured characters/chunks and 10,000 text blocks. Oversized prose is split into labeled character continuations with bounded repeated section context; no text value is silently truncated. External relationships are never fetched or executed.

## Existing data

Keep volumes and the existing installation directory. Rebuild the API only when you choose to deploy the new version; stop/start alone keeps its saved image. Do not delete the library or run `down -v`.

The parser compatibility fingerprint changes. Old committed revisions remain searchable while their original parser fingerprint and current embedding model digest match a supported historical parser. New and old compatible collections can be searched together. Changing the embedding model/digest still requires explicit reingestion; incompatible vectors are not mixed.

To adopt new chunking/location metadata, select the same source name and relative folder paths and ingest again. The first import after a parser change intentionally reindexes even unchanged bytes into the new parser collection. The old revision stays searchable until successful verification and atomic publication of its replacement. Failed/cancelled replacements keep the previous searchable revision. After successful replacement, normal cleanup may remove that document's retired points; untouched documents and volumes remain. A second unchanged import skips after verifying compatible indexed points. Back up data before deployment if rollback to an older application image is required; old code cannot search newer parser fingerprints.

Real-model accuracy for the new formats remains unmeasured. Genuine-format extraction, transactions and synthetic-model API tests do not establish semantic correctness.
