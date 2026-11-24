# Qdrant endpoint changes and legacy index compatibility

The connection URL is a routing address. Version 2 identities contain the exact
embedding model name and digest, parser version, chunk size, overlap, format
version and destination prefix, plus an identity schema version. They do not
contain a hostname, port or protocol. Changing any compatibility field produces
a different identity. Qdrant clients are cached by endpoint and collection.

## Existing indexes

Existing document fingerprints, collections, document/revision IDs, memberships,
payloads and vectors are retained. At the original endpoint the exact old hash
algorithm still selects the original collection. There is no blanket acceptance
of legacy fingerprints, collection scanning or hostname guessing. At a changed
endpoint an unregistered legacy context fails closed, with a provenance hint.

Explicit registration adds one `index_contexts` row mapping a version 2 identity
to the original fingerprint and collection. It never rewrites documents,
revisions, job membership or Qdrant data. One context cannot silently replace
another. A conflicting native version 2 context requires separate investigation.
Registration is deliberately not an automatic startup migration.

Imports stop with `legacy_registration_required` if this destination prefix
contains an identity that cannot be resolved at the current endpoint and has
neither verified legacy registration nor a successful native publication record.
This check runs before parsing, embedding or index writes, including unchanged
files. A failed registration does not authorize a new v2 collection. Successful
native v2 publications record their fingerprint/collection in
`native_index_contexts` in the document visibility transaction, so fresh installs
and subsequent native model/parser changes remain usable after a restart.
Unattributed identities require explicit verification; the application does not
guess whether they represent an endpoint change or a model change.

Each selected document must still have exactly one matching active revision,
matching collection and point memberships. Before model dispatch, read-only
verification checks all selected point IDs and their document/revision bindings;
registered legacy points additionally retain full payload and stored-vector hash
anchors. Missing collections, aliases, absent/mismatched points and corrupt
active pointers fail explicitly. The query filter includes selected revisions,
documents and exact point IDs; retired/outside-job data remains excluded.

This establishes equality of the registered data, not the physical identity of a
server. An exact verified restore is an acceptable backend. Endpoint ownership,
TLS and prevention of concurrent external database mutation remain operator
responsibilities. The application owns its registry and index under its existing
single-process contract. It does not add authentication identities or ACLs.

## Saved bindings and verified replacements

Runtime verification compares each preserved document with its immutable saved
reference, including its revision, collection, fingerprint and complete unique
point membership. Matching current SQLite tables to each other is insufficient.
Missing, extra, duplicate or substituted IDs fail. Read-only Qdrant scrolling
checks the exact membership of the document/revision, including unexpected points
not listed in SQLite. Every expected point must match its full payload and stored
vector hashes. An anchor binding mismatch always rejects verification. Missing
saved documents in the selected scope also fail; retired and outside-job data
remain excluded.

A legitimate application replacement creates a new revision and new point IDs.
Before publication the predecessor's metadata must match the trusted reference,
and the new stored points are read and verified. The visibility transaction
updates the document and its latest `index_publications` receipt atomically. The
receipt contains the complete document, point bindings, stored content hashes and
predecessor revision. A failed transaction retains the old visibility and receipt.
The original saved proof is never rewritten.

Subsequent reads require the latest publication receipt when one exists; they
cannot choose an older saved revision instead. This allows verified replacements
after restart while rejecting consistent SQLite/Qdrant relabeling without a
publication record. Existing native data without a saved reference or receipt
retains basic binding verification; successful publications from this version
always create receipts. Unrecorded changes to registered legacy revisions are
rejected rather than inferred to be legitimate.

The trusted inputs are the saved proof and application-owned publication metadata
under the existing single-process writer contract. A checksum detects changes to
a record; it does not authenticate a party capable of rewriting both records and
their checksums. Operators must preserve this trust boundary. Receipt schema 1
uses the current checksum serialization without changing old proof bytes or the
legacy fingerprint format. Canonical-format changes and verification caching are
separate follow-ups; the full verification reads remain in place here.

## Required legacy provenance

Use a cold, independently verified saved registry and saved Qdrant data. Work on
disposable copies. Keep the original archives and their checksum records intact.
Do not manufacture provenance by reading an unknown target and declaring it the
reference. A checksum binds bytes; it does not establish their origin. Retain
the trusted original configuration, saved model tags/digest, source archive
hashes and the independent verification record alongside the private manifest.
If those are unavailable, leave the registry unchanged and obtain them first.

The UTF-8 JSON provenance schema has exactly four top-level fields:

| Field | Required content |
| --- | --- |
| `schema` | Integer `1` |
| `legacy_signature` | `parser`, normalized `model` (including `:latest` if applicable), embedding `digest`, `chunk_size`, `overlap`, `format`, original `destination`, original literal `database` URL |
| `documents` | Every original `documents` row with that fingerprint, with all nine SQLite columns retained verbatim; `points` remains its original JSON string |
| `points` | One entry for every registered point: string `id`, `document_id`, `revision`, `payload_sha256`, `vector_sha256` |

Point hashes use SHA-256 of `json.dumps(value, sort_keys=True,
separators=(",", ":"), allow_nan=False).encode()`. Hash the complete saved payload
and the complete **stored/retrieved** vector, including its representation;
pre-insertion vectors may differ after storage normalization. Use the same
Qdrant client representation/version for reference and target verification.
Do not infer units, model digests or parser identities from vector dimensions.

The separate pinned identity JSON contains exactly the seven signature fields
without `database`. Derive it from independently reviewed configuration and
saved embedding-model metadata. It must exactly equal the legacy signature
after removal of `database`. The migration makes no model-server request.
Pin both input file SHA-256 values from their trusted verification record.

## Upgrade and verification on a disposable copy

This command is a verification-only example; `RESTORED_COPY_URL` must address
the disposable restore, never the deployed database. Use the reviewed checkout's
environment with `PYTHONPATH=src`; no application server or worker is needed.

```bash
PYTHONPATH=src python scripts/register_legacy_index.py \
  --working-copy /absolute/path/to/disposable/data \
  --qdrant-url "$RESTORED_COPY_URL" \
  --identity /absolute/path/to/private/identity.json \
  --identity-sha256 "$REVIEWED_IDENTITY_SHA256" \
  --provenance /absolute/path/to/private/provenance.json \
  --provenance-sha256 "$REVIEWED_PROVENANCE_SHA256"
```

The command holds the application's process lock, uses real SQLite transactions
and only Qdrant metadata/point reads, and rolls back by default. It does not
construct `Library`, so startup recovery does not alter unrelated jobs/files.
For an explicitly authorized working-copy migration, append `--apply --backup
/absolute/path/to/new/registry-before.sqlite3`. Verification runs before backup;
then a consistent SQLite backup is saved exclusively (never overwritten), and
verification repeats inside `BEGIN IMMEDIATE` before the single metadata row
commits. Schema creation and insert share the transaction. FULL synchronization
and SQLite recovery protect the commit boundary. An exception/process death
before commit leaves the old state; after commit the complete mapping is visible.
Repeating the same successful registration returns `changed: false`, verifies
the same data, and creates no extra backup or metadata. Conflicting/changed
reference bytes fail; they are never silently substituted.

After registration, run the actual `Library.ask` selection on the copy with
model methods replaced by fail-fast stubs/selection observation. Check the exact
eligible IDs and physical point bindings at both URLs. No embedding or answer
generation is required. A collection's mere existence is insufficient.

## Rollback

Keep the application stopped. Revert the code and endpoint configuration, then
restore the pre-registration SQLite backup using SQLite's backup API into an
offline working copy. Do not copy a database over live WAL/SHM files. Restore
the matching registry/index pair before resuming the original version. Qdrant
requires no reversal because registration performs no writes there. Original
legacy fingerprints remain usable by the old code at the original endpoint.

Newly ingested version 2 identities are not understood by the old application.
Rollback after subsequent ingestion therefore requires the complete matching
pre-upgrade registry/index snapshot, not only removal of the metadata table.

## Evidence boundary

The focused tests use real SQLite and Qdrant local storage with fabricated data,
mocked `/api/tags`, and a dispatch observer exercising the actual `Library.ask`
selection/filter. Embedding and real generation methods fail immediately.
The process-death test uses real SQLite crash recovery but mocks backend
verification in its child; other tests exercise actual local point reads.

The fabricated 15 revisions/138 points are a shape regression, **not proof of
preservation of the user's saved 15-revision/138-point snapshot**. That separate
verification requires the unavailable private snapshot/provenance. No claim of
saved-snapshot validation or production migration is made by these tests.
