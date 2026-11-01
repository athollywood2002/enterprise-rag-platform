# Kubernetes Hugo preparation: `k8s-hugo-preprocess-v1`

Status: proposed G1b contract for independent review. Do not use it to create
real Kubernetes canonical text or labels before that review. The merged PDF and
Markdown canonical parser contracts are unchanged. This helper does not download,
follow includes, call a model, create a corpus, or label anything.

## Why prepare the source?

Kubernetes website Markdown contains Hugo frontmatter and template shortcodes.
Serving-equivalent Markdown parsing alone preserves that noise and can omit
included examples. Data preparation is part of the architecture: the prepared
`.md` must be the exact bytes later supplied to both serving and evaluation.
Rendering loss and template handling are separate checks; serving parity does
not establish source completeness.

`evaluation.kubernetes_hugo.prepare_kubernetes_markdown(raw)` is a pure, bounded
function. It returns a `PreparedMarkdown` containing a strict `PreparationRecord`
and either complete UTF-8 bytes or **None**. Excluded inputs never expose a partial
prepared body. It does not infer rights from an accepted transformation.

## Exact supported subset

1. Maximum input: **131,072 bytes**. Decode strict UTF-8, reject BOM-prefixed
   frontmatter, NUL/other ASCII controls except TAB/LF, DEL, and bare CR. Convert
   CRLF to LF. No Unicode normalization, whitespace collapse, paragraph reflow,
   identifier rewriting, dehyphenation or appended newline happens here.
2. Require `---` on the first line and a later standalone `---` closing line.
   Strip the entire frontmatter. Preserve only top-level, unindented `title:` and
   `content_type:` values in the preparation source record. Require both; reject
   duplicate or unsupported values. Other frontmatter is discarded, never executed.
3. Metadata supports nonempty single-line plain strings without YAML indicator
   prefixes or inline ` #` comments; YAML single-quoted strings with doubled
   apostrophes; and JSON-compatible double-quoted strings. `content_type` must
   match `[a-z][a-z0-9_-]*`. Unquoted booleans/null/numbers, quoted field names,
   block scalars, aliases, tags, collection values,
   multiline strings and other YAML syntax for these fields are excluded. This
   is a **restricted scalar reader**, not a general YAML parser. It never loads
   objects, resolves anchors or interprets the discarded metadata.
4. Remove **standalone** comment lines `<!-- overview -->` and `<!-- body -->`
   only. Leading/trailing spaces/TABs and spaces/TABs inside the marker are
   allowed. Other comments and inline markers are retained unchanged. The later
   Markdown parser may remove HTML comments; inspect that separately.
5. The only supported shortcode is angle-delimited
   `{{< glossary_tooltip text="containers" term_id="container" >}}`.
   Exactly `text` and `term_id` are required, once each, in either order. Attribute
   separators can include line breaks. Attribute values use double quotes with
   no escapes or line breaks. The visible text must be nonempty, have no edge
   whitespace, and contain only Unicode alphanumerics or ` -.,:()/+`.
   `term_id` must match `[A-Za-z0-9][A-Za-z0-9_-]*`. Replace the whole shortcode
   with its **explicit text value**, not a guessed display name from `term_id`.
   Markdown/HTML metacharacters in the visible value are outside this subset.
6. Count complete shortcodes by name, including closing forms such as `/note`.
   Reject all other names, `%` forms, missing/duplicate/unknown attributes,
   mismatched delimiters, escaped-shortcode examples and leftover `{{`/`}}`.
   This includes `code_sample`, `include`, tabs, notes, figures, feature-state,
   parameter/version substitution, headings and API-reference templates.
   **No referenced path or URL is opened**, even when it appears harmless.
7. Avoid rewriting literal code examples: exclude template delimiters/known
   markers inside fenced code or delimiters inside paired same-line backtick
   spans. Backtick and tilde fences of >=3 characters, indented by <=3 spaces,
   are tracked until a same-character closing fence of sufficient length.
   Exclude unclosed fences and unpaired/multiline inline backtick contexts.
   Ordinary paired inline code elsewhere on a glossary line is allowed. This
   intentionally conservative subset can reject otherwise valid Markdown.
8. Reject an empty resulting body. On **any** exclusion, return no prepared
   bytes, no document version and no changes notice. Counts/reasons and any
   recovered metadata remain available; `recognized_markers` is a diagnostic
   count, not a claim that an excluded document was published or transformed.
   No document is partly admitted after removing an unsupported template.

Counts cover the body after frontmatter removal; incomplete delimiters have a
separate reason rather than an invented shortcode name. Reasons and count names
are sorted/unique for deterministic records. Reapplying this preprocessor to its
own output is not the workflow: it requires raw frontmatter and rejects missing
frontmatter rather than silently applying a second transformation.

## Identity, source record and attribution

The sidecar `PreparationManifest` has explicit schema
`k8s-hugo-preparation-v1`, the existing citation/rights `SourceRecord`, and a
`PreparationRecord` containing:

- `raw_sha256`: SHA-256 of exact upstream bytes, before CRLF conversion;
- `doc_version`: SHA-256 of complete prepared UTF-8 bytes, or null on exclusion;
- `preprocessor_id`, preserved `title` and `content_type`, counts, reasons and
  acceptance status;
- `changes_notice`: the fixed, versioned changes statement on acceptance only.

`manifest.source.title` must equal the preserved title. `content_type` remains
in the structured preparation portion of this composite source record. An
accepted manifest requires the changes statement in `source.attribution`.
Retain the **entire sidecar** with source URL, pinned revision, rights decision
and canonical manifest; do not discard it after extracting Markdown. This PR
does not change `canonical-corpus-v2` or silently attach unknown fields to it.
The full acquisition/corpus assembly step must retain and bind this sidecar;
that step is pending, not claimed implemented here.

`PreparedMarkdown.verify(raw)` recomputes the entire preparation and compares
both bytes and record. Before later canonicalization, verify the raw/prepared
pair; give exactly `prepared.data` to `extract_markdown` and to serving upload.
The resulting canonical document's `doc_version` must equal the sidecar's
prepared-byte hash, **not** the original upstream hash. A preprocessor policy
change needs a new ID and reviewed corpus rebuild. Manifest identity must include
the policy ID, even if two policies happen to produce identical bytes.

An attribution entry for an accepted CC BY 4.0 source must retain upstream
credits and include the actual title, pinned source link/revision, license link
`https://creativecommons.org/licenses/by/4.0/`, and `CHANGES_NOTICE`, with a link
to this specification. Do not imply Kubernetes endorsement. Example structure:

> Kubernetes documentation contributors, [actual title and pinned source].
> Licensed CC BY 4.0. Changes: prepared by `k8s-hugo-preprocess-v1`; frontmatter
> and supported markers removed, glossary text substituted, line endings
> normalized. See this preprocessing specification.

This is a template, not the attribution for a distributed corpus. The strict
record checks strings/identity, not legal permission. Inspect each actual source
and any third-party content; exclude unresolved dependencies or rights. Keep
raw files private unless redistribution is verified. No accepted real source or
real transformed content is published with this PR.

## Bounded inspection evidence

`docs/kubernetes-source-inspection.json` records one inspected upstream Pods
source, pinned revision/URLs, raw/license checksums, counts and exclusion.
No upstream source body is committed. Four unauthenticated public HTTP requests
were made: an initial commit-metadata response exceeded its 32-KiB cap and was
rejected, then a small Git-ref lookup, repository LICENSE and the one Markdown
file. Successful content types were checked; redirects and oversized/unexpected
content were rejected. Source/license caps were 128 KiB, no crawling/includes.

The 26,031-byte Pods source has 46 complete shortcode occurrences across 10
names. It is **excluded**, including a code-sample dependency and glossary calls
with missing visible text. No prepared bytes, canonical text, corpus or labels
were created for it. The repository LICENSE is CC BY 4.0; no additional
copyright/license notice was found in a bounded text scan of that source, but
included content was not fetched or rights-cleared. The inspection decision is
local-only/excluded, not a blanket redistribution approval. Do not broaden the
pattern set or fetch its includes just to make the sample pass.

## Verification and deferred work

```bash
python -m pytest -q tests/test_kubernetes_hugo.py
python -m pytest -q --run-document-tests tests/test_kubernetes_hugo.py
python -m pytest -q --run-document-tests
python -m ruff check .
python -m ruff format --check .
```

Tests author their own synthetic text. One opt-in real-parser test checks the
prepared-byte version, preserved identifiers and serving/evaluation parity; it
does not process the inspected real source or create human gold.

Independent review is required before real Kubernetes preprocessing is used for
canonicalization/labeling. Finding #55 (assert the Markdown partitioner selection)
and #52 (chunk-map provenance/efficiency) remain separate follow-ups; no serving
or parser behavior is changed here. G1(b)/(c)/(d), NIST acquisition, a useful
licensed pilot corpus and the owner annotation pilot remain pending. The demo/lab
Compose proposal adds no image build/publish/model-download/runtime permission.

Decision: keep the v1 allowlist deliberately small, accepting exclusions rather
than implementing Hugo or inventing missing content. Expand only through a new
reviewed policy version and source tests. Rollback: reviewed revert of these
preparation-only additions; no serving, storage or index migration. Do not undo
the merged canonical contract or revive whole-file Markdown chunking.
