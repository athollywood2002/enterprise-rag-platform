# Managed-answer grounding: offline correction, semantic validation pending

This PR starts from main `893d883`. It changes only managed answer instructions
and assignment of context citation IDs. `/ask`, authentication, selected-job and
committed-revision filters, retrieval, source ordering, parsers and index fingerprints
are unchanged. There is no retry, fallback generation, token increase or heuristic
answer rejection. Thinking stays `default`, the comparison cap is 1536 and the
application model timeout remains 180 seconds. No deployed instance was updated.

## Why this change

The primary default/1536 exposed 24-question run scored 18/24 combined passes
(same-rubric sensitivity 16–18). A later default/2048 pass also scored 18/24, not
an improvement; thinking-off's 14/24 is not the primary baseline.

Saved N24 evidence contains both the five-business-day training rule and an explicit
warning that company holidays are excluded and the calendar is absent. Both reached
the model. It nevertheless invented an exact date citing only the training rule.
This is a failure to use retrieved counterevidence, not a missing-passage diagnosis.

The revised general instructions put the calendar dependency first: retain the
governing rule, cite both it and the missing-calendar limitation, and state that the
exact date is unknown. They also explicitly allow date calculations when a complete
calendar and counting convention are supplied. There is no date-refusal classifier.

Other instructions clarify the same evidence discipline:

- Cite the exact passage supporting the claim, not just another passage from the
  same document. Cite applicability and value for each compared policy period.
- Cite every link in a cross-record identity/terms join.
- Cite supersession evidence and leave an unavailable replacement unknown.
- Keep operational targets distinct from mandatory deadlines; retain clock start events.
- Separate validation from final authorization, include every required approval,
  and do not equate unconfirmed completion with failure.

These are general rules, not embedded fixture identities, filenames or expected values.
JSON evidence records remain intact, including labels, zero values, units, coordinates,
source identities and effective dates. An input metadata key cannot override the
assigned citation number. JSON boundaries do not guarantee prompt-injection immunity.

## What the offline checks establish—and do not

`tests/test_managed_grounding.py` uses sanitized copies of nine **exposed** primary
cases. It reproduces the saved N24 failure and its valid-but-insufficient citation;
preserves N12's identity join, N14's policy scope, N16's target and backup clock,
N20's supersession warning, and N22's full cutover conditions. N10/N11 remain
spreadsheet/zero/unit controls. The original N11 already retrieved data [2] and
headers [4]; the diagnosis is not absent header retrieval.

An authored complete-calendar control supplies the counting convention and all
holidays for its interval. Tests verify that these inputs reach the model unchanged,
not that a mock model independently solves the date calculation. Authored reference
answers are not measured outputs. Mock replies deliberately retain wrong claims,
out-of-range citations and empty generation to show that the pipeline neither
silently repairs them nor grants semantic credit. N15 remains an empty-output
generation failure, not a supported abstention or a proven reasoning loop.

`evaluation.grounding` recognizes numeric, grouped, citation-prefixed and bold markers,
including paragraph qualifiers. It checks IDs against the returned excerpt array.
It never treats valid IDs, protocol completion or source-document identity as proof
of claim support. Unrecognized marker syntax needs manual review.

## Blinded held-out gate

A separate reviewer froze 12 fresh questions, expected answers, required passages and
grading criteria **before candidate edits** at `2026-11-15T18:25:57Z`.

- Frozen bundle SHA-256: `98be490af8dcd1eb9f78ed65e820ca382313d5b984b4fb5f3aa44817872b528a`
- Bundle content manifest SHA-256: `9e53b1b4912cff7a9fbe390b452f6483c56d3f0d0a2b549c8bc429b2e063044d`
- Nonrevealing receipt SHA-256: `08842e78188e16855439e9eb87fab13e21cb77f200c1858657b774ceda4936d0`

The implementer receives only count/hash/time/receipt, not held-out content. The
custodian's receipt records the older clean worktree it inspected; the candidate
worktree separately started clean at main `893d883`, also before any edits. The
corpus is synthetic and already exposed, and some reasoning patterns resemble the
development cases: this is question-level blinding, not an unseen-corpus benchmark.
Twelve cases do not establish general improvement. Record the exact candidate commit
before any reveal; changes after reveal make this set development evidence.

The protected bundle includes reviewer instructions and an evaluation adapter. It
and raw evidence stay private, outside Git. **No real-model comparison has run.**

## Runnable bounded comparison, for the custodian

`evaluation.managed_compare` defaults to an **offline plan**. Execution requires
separate owner authorization for two already-running, independently isolated APIs.
This implementation task grants no such inference/deployment authorization. Do not
point the command at the deployed API or shared model services through a tunnel.
The tool does not start services, import data, change settings or restore an installation.

After the candidate commit is fixed, the custodian exports a private JSON array with
only `id` and `question` per case; expected answers/passages/rubric remain grader-only.
The reviewer should adapt the sealed bundle's evaluation script to these response
artifacts without changing the frozen question or gold bytes. Use the same immutable
index snapshot, selected job, models/digests and CPU/memory for both arms. Baseline
and candidate must be distinct fixed commits; no prompt changes between arms.

Prepare a private plan with exactly:

```json
{
  "questions": "questions-only.json",
  "questions_sha256": "<SHA256 of exact question-export bytes>",
  "freeze_sha256": "<frozen bundle SHA256>",
  "custodian_receipt": "reviewer-adapter-receipt.json",
  "custodian_receipt_sha256": "<SHA256 of nonrevealing custodian receipt>",
  "arms": {
    "baseline": {
      "url": "http://127.0.0.1:19001",
      "key_env": "RAG_EVAL_BASELINE_KEY",
      "state_receipt": "baseline-state.json",
      "state_sha256": "<SHA256 of receipt bytes>"
    },
    "candidate": {
      "url": "http://127.0.0.1:19002",
      "key_env": "RAG_EVAL_CANDIDATE_KEY",
      "state_receipt": "candidate-state.json",
      "state_sha256": "<SHA256 of receipt bytes>"
    }
  }
}
```

Each fresh, metadata-only operator-inspected state receipt has these exact top-level
fields: `git_commit` (full SHA), `isolated: true`, `deployment: false`,
`shared_services: false`, `observed_at` (timezone-aware ISO timestamp), `inspection`
(inspection method/reference, no credentials) and `settings`. Settings have exactly:

- `think: "default"`, `num_predict: 1536`, `model_timeout_seconds: 180`, `top_k: 5`;
- `job_id` (same selected snapshot job), `resources` (identical positive integer
  `cpu_count` and `memory_bytes` limits);
- `chat_model`, `chat_digest`, `embed_model`, `embed_digest`;
- `corpus_sha256`, `index_sha256` (inspected corpus/index snapshot manifests);
- `documents_sha256`: SHA-256 of canonical `/library/documents` JSON, encoded by
  `evaluation.managed_compare.encode` (sorted keys, UTF-8, default JSON separators).

Both settings objects must be identical. Receipt timestamps must be less than 15
minutes old when execution starts. Digests/settings/isolation are operator
attestations, **not remotely proven by readiness**. Inspect them independently before
and after the comparison; preserve those receipts privately. Live readiness checks
model names/availability, and document snapshots are checked before and after. A
document receipt is not a proof of all underlying vector bytes.

The pinned custodian receipt must bind `question_export_sha256`,
`sealed_bundle_sha256_unchanged`, `question_export_count` and
`question_export_fields: ["id", "question"]` to this export and frozen bundle. The
runner checks these links and saves the exact export bytes, not re-encoded JSON.
The operator must authenticate the receipt's provenance independently; a file hash
does not prove who wrote it. Both arms must be byte-identical clones of one library
snapshot, including revision metadata and complete document records, not separate
reimports of identical source files. Relative input paths can refer outside the
plan folder; this is a trusted operator tool, not a filesystem sandbox.

Plan-only command (no network or generation):

```sh
PYTHONPATH=src python -m evaluation.managed_compare --plan /private/path/plan.json
```

Only after separate isolated-execution authorization, create a private authorization
JSON with exactly `owner_reference`, `plan_sha256` (exact plan-file bytes),
`isolated_execution_authorized: true` and `ledger_dir` (the fixed absolute private
campaign ledger directory). Set dedicated API keys in the named environment
variables without putting them in the plan, receipt, command line or Git. Then:

```sh
PYTHONPATH=src python -m evaluation.managed_compare \
  --plan /private/path/plan.json \
  --execute-authorization /private/path/authorization.json \
  --output /private/path/NEW-results
```

The runner permits numeric-loopback HTTP only, blocks the deployed API's port 18000,
disables proxies/redirects/transport retries, and consumes the canonical authorization
identity in its pinned campaign ledger via an exclusive durable file before any
network access. Loopback alone does not establish
isolation: do not use a forwarded shared/deployed endpoint. A consumed authorization
cannot be reused even with another output directory. Do not remove it to resume.
Copying or reformatting unchanged authorization content still hits the same ledger
identity. Changing the ledger or authorization content requires new owner approval;
the file-based gate does not authenticate or constrain a malicious operator.

Requests are sequential: baseline then candidate for each unchanged question, same
order in both arms, exactly one attempt per question per arm, `top_k=5` and explicit
job scope. Limits: application 180s (inspected), outer HTTP wall 300s, batch 3600s,
no new generation request after 3270s, 8MiB response ceiling. No SSH is used. A
durable reservation precedes dispatch; any uncertainty must be investigated from
the retained journal, never resent. New-output-only mode prevents local resumption.

Raw HTTP bytes, hashes, response/empty-body/empty-answer distinctions, timings,
generation evidence, returned excerpts, input hashes and metadata receipts are
retained with private permissions and checksums. A failed request or different
returned evidence between arms stops the comparison, retaining both failures and
successes. On cancellation, unresolved reservations remain explicitly uncertain.
The tool does not collect or display model reasoning.

Every response is marked **UNREVIEWED**, including successes. The custodian separately
grades passage retrieval, answer correctness, exact cited-claim support, omitted
conditions and correct abstention against the sealed gold. Report answer/citation/
combined scores, confounds and all failures; no automatic semantic improvement claim.
Model nondeterminism, API/model idle/loading/cache state and question exposure remain
limitations even when requests and retrieved passages match.
Baseline always runs first within each pair; this introduces a model-warmth/order
bias, so timing differences must not be treated as unbiased speed comparisons.

Submit for independent code/evidence review before any merge or deployment. Do not
change unrelated connector/retention work or existing PRs as part of this correction.
