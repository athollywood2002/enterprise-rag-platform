# Recorded live API evaluation — November 9, 2026

This archive preserves a maintainer-supplied evaluation of 30 sequential requests to `POST /library/ask`, using the existing 12-document, 52-chunk synthetic enterprise corpus. It is separate from the earlier three browser answers in the [screenshot gallery](../../images/arm64-manual-smoke-2026-11-09/).

Download `report.html` and open it locally to inspect questions, expected answers, actual answers, excerpts, and review notes. `report.json` and the JSONL files preserve machine-readable evidence. `README.txt` is the supplied archive description with identifiers sanitized.

| Recorded result | Value |
| --- | --- |
| Answer pass / partial / fail | 25 / 3 / 2 |
| Answer and citation both pass | 22 / 30 |
| HTTP 200 responses | 30 / 30 |
| Nonempty answers | 29 / 30 |
| Median request duration | 34.0 seconds |
| Nearest-rank p95 | 93.3 seconds |

The supplied review was performed by Codex, not an independent human judge. The saved case records reproduce these counts and timing aggregates; preserving them does not independently verify the remote execution or every judgment. Document-level source coverage is not answer-passage recall. This small, single-run synthetic evaluation does not establish production readiness, throughput, OCR quality, or access-control enforcement.

Two failures are recorded: T15 exhausted the 1,536-token generation cap with an empty visible answer despite relevant CSV evidence; T21 retrieved the relevant document but missed its answer-bearing passage. Partial results include unsupported additions and missing material qualifications. HTTP success is therefore not equivalent to answer success.

## Provenance and sanitization

The recorded deployment commit is `220d683dbcb99da2ff4916f1743f8f9d461f3c7a`; models are `qwen3:8b` and `nomic-embed-text:latest`. Model digests, synthetic source content hashes, timestamps, answers, excerpts, scores and timings are retained as supplied evidence. Existing ingestion was inspected, not rerun, according to the archive; it records unchanged indexed revisions at completion.

The VM hostname and installation-specific job, file/document, revision and collection identifiers were consistently replaced with public placeholders across all files. Consequently `raw_responses.jsonl` is a sanitized copy, not a byte-for-byte original or a reusable request file with a valid job ID. No credentials or private absolute filesystem paths were found. Synthetic `northstar.example` addresses are sample content. No answer text or review score was changed. `SHA256SUMS` covers the sanitized files only.

Saving this archive ran no inference, ingestion, deployment or demo. It does not change the earlier attempt 3 formal `FAILED_INCOMPLETE` status caused by partial log capture.
