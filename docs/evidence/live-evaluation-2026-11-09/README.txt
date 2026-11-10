Live RAG evaluation — November 9, 2026

Open report.html for the scored questions, expected answers, actual answers, retrieved excerpts, and review notes.

Scope: 30 sequential requests against the existing completed my-documents job on evaluation-vm. The 12 supported indexed documents contain 52 chunks. All 12 source hashes matched the original synthetic corpus. Existing ingestion was inspected, not rerun.

Results: 25 answer passes, 3 partial answers, 2 failed answers. 22 of 30 passed both answer and citation review. All requests returned HTTP 200, but one returned an empty answer after reaching the configured 1,536-token generation limit. Median response time was 34.0 seconds; nearest-rank p95 was 93.3 seconds. Total API request time was 18.9 minutes.

Files:
- report.html: readable report, with expandable evidence for every question
- report.json: full machine-readable review and environment
- reviewed_results.jsonl: one scored case per line
- test_cases.jsonl: questions, expected answers, and designated source evidence
- raw_responses.jsonl: exact API responses, start markers, environment snapshot, and final index check
- environment.json: job, indexed hashes/revisions, supported formats, model digests, generation cap

Request endpoint: POST /library/ask
Body fields: question, top_k=5, job_id=public-job-001
Models: qwen3:8b and nomic-embed-text:latest
Reviewed deployed repository commit: 220d683dbcb99da2ff4916f1743f8f9d461f3c7a

No automatic retries, ingestion rerun, configuration edits, or code changes were made. Indexed revisions and hashes were unchanged at the end. This is one small synthetic evaluation, not a scale, throughput, OCR, or ACL-enforcement test. Document-level coverage metrics do not guarantee that the answer-bearing passage was retrieved.
