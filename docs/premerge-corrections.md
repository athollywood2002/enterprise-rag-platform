# Scoped pre-merge corrections

The async document route still validates and awaits the upload read, then awaits
one Starlette worker-thread call for parsing and synchronous engine ingestion.
Existing success/error shapes remain, except for the intended exception narrowing:
parser `KeyError`, `IndexError` and other `LookupError` subclasses now produce an
opaque processing 500 instead of parser-unavailable 503. Exact built-in
`LookupError` remains 503 for compatibility with NLTK's missing-resource exception;
this is still coarse and a parser raising that exact class for a bug cannot be
distinguished without a future typed parser-resource boundary. Imports remain 503.

Tests check parsing and ingestion share a worker thread, upload reading remains
on the event loop, and a health request on the same ASGI loop completes while a
parser waits on an explicit release event. Existing HTTP error/provenance tests
still apply to the worker path. A thread pool does not provide parser process
isolation, quotas, durable jobs, or rollback after partial ingestion. Thread-pool
saturation and CPU-heavy Python work can still affect responsiveness.

CI now checks full-tree Ruff lint/format in the base job. Two existing test import
ordering errors were corrected. Jobs use `ubuntu-24.04` rather than a migrating
`ubuntu-latest`, with Node 24 actions `checkout@v7.0.1` and `setup-python@v7.1.0`.
Versions/runtime were verified against the official action release metadata and
`action.yml`; hosted-runner compatibility is checked by the actual workflow run.
No self-hosted runner or live service configuration is changed.

README now describes implemented upload behavior, tested versus allowlisted
formats, and the limits of synthetic evidence. Retrieval selectivity work and
larger architectural changes remain separate from this code patch.

Rollback: revert this isolated correction commit or commits; no data migration is
involved. Reverting the worker dispatch would restore the known event-loop
blocking behavior. Keep the PR draft and unmerged until reviewed.
