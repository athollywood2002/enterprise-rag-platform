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

The custodian retains the protected bundle, its grading adapter and the raw evidence. Preserve earlier campaign evidence. Report the four previously dispatched questions separately from the eight previously untouched questions.

## Balanced comparison on the evaluation branch

Build both APIs from their separately pinned commits. Run only the client and host inspection tools from the independently reviewed evaluation commit. Make two independent copies of one verified application/Qdrant snapshot and one copy of the verified model volume. Check the selected job, document IDs, revisions, all selected point IDs and payloads, model digests, and source/image identities against the retained records. Use the custodian's exact 12-question export and receipt. Gold, grading criteria and the blind key stay with the custodian.

### Test host and ownership

1. On the guest, record `/proc/meminfo`, CPU allocation, `/proc/vmstat`, available disk, and the deployed stack's state, resource use, limits and storage roots. Account separately for production and the OS. The experiment's memory caps total **14.25 GiB** (12 GiB Ollama, four 512 MiB services and a 256 MiB runner). Model weights, context cache and runtime allocations share the Ollama cap. Compare available headroom to this budget before preparation and again before dispatch. Record the existing running/stopped state for final verification.
2. The evaluation-only [Compose file](../evaluation/compose.managed-compare.yaml) uses two private bridge networks and one experiment-owned model server connected to both. Supply the unique campaign ID, capacity-reviewed CPU quota, pinned local API images, original collection prefix, two experiment keys, new private evidence directory, reviewed runner checkout and independent snapshot directories named in the file. Prepare directories with the image UID's required access. Check **before starting services** that the five writable storage roots are distinct and disjoint from production, including their resolved paths and backing files. Preserve production mounts, ports and resources. Validate Compose with `docker compose -f evaluation/compose.managed-compare.yaml config --quiet` to keep keys out of logs.
3. Attach `org.enterprise-rag.eval.campaign` and `org.enterprise-rag.eval.role` labels as in the Compose file. Only the two API ports are published, on numeric loopback. The APIs route directly to their respective Qdrant containers and to the same Ollama container. The runner uses the host network and host cgroup namespace. Give it read-only access to cgroup v2. The host inspector uses read-only Docker metadata. Keep the Docker socket outside the client. Record effective Ollama context, residency and loading state from configuration and metadata before and after execution, with no warm-up.
4. Produce a private ownership receipt **on the guest host** with the reviewed code. Obtain the actual source roots of the deployed API, Qdrant and model mounts from inspection. Pass every protected root explicitly. This command needs access to the exact mount paths for directory identity checks.

```sh
python3 -m evaluation.campaign_resources --campaign "$RAG_EVAL_CAMPAIGN" \
  --protect "$production_api_storage" --protect "$production_qdrant_storage" \
  --protect "$production_model_storage" --output "$new_evidence/ownership.json"
```

The receipt records labeled container and image IDs, published bindings, the model/database targets resolved on the inspected bridges, all bridge members, mount identities, effective memory/CPU limits and the model-loading environment. The inspector checks the API routes and excludes foreign bridge members. The independently inspected, checksummed receipt binds the plan to those endpoints. Metadata-only API readiness establishes model names and availability. It cannot attest model digests, image contents or a new container behind a reassigned port. Preserve fresh before/after inspections and the host supervisor's identity/restart checks during the run.

### Private inputs

The plan is a JSON object with the following fields.

| Field | Value |
| --- | --- |
| `campaign_id` | Unique campaign label, also bound into the authorization and the consumption marker. |
| `runner` | Object with full reviewed `commit` and `source_sha256`. The latter maps the four filenames from `evaluation.managed_compare.runner_sources()` to SHA-256 over exact source bytes from that commit. |
| `order` | `baseline-first-on-odd-candidate-first-on-even` |
| `budget` | `{"http_seconds":300,"batch_seconds":7200,"no_new_after_seconds":6870}` |
| `questions`, `questions_sha256`, `freeze_sha256` | Path and exact byte hash of the question-only export, and hash of the original sealed bundle. |
| `custodian_receipt`, `custodian_receipt_sha256` | Path and hash. The custodian binds the sealed hash, export hash, count 12 and exact fields `["id","question"]` using `sealed_bundle_sha256_unchanged`, `question_export_sha256`, `question_export_count` and `question_export_fields`. |
| `ownership_receipt`, `ownership_sha256` | Path and exact byte hash of the host inspector output. |
| `arms` | `baseline` and `candidate`, each containing only `url`, `key_env`, `state_receipt`, and `state_sha256`. Use the inspected loopback bindings and dedicated `RAG_EVAL_*_KEY` variable names. |

Each arm's operator-signed-off state receipt contains exactly `git_commit`, `isolated: true`, `deployment: false`, `campaign_id`, `api_container_id`, a timezone-qualified `observed_at`, a non-secret `inspection` reference, and `settings`. Inspection must bind the image ID to its pinned API source. Set `settings` with exactly these fields:

- `think: "default"`, `num_predict: 1536`, `model_timeout_seconds: 180`, `embedding_timeout_seconds: 120`, `top_k: 5`;
- `job_id`, `resources` containing positive integer `cpu_count` and `memory_bytes` (the API memory limit);
- `chat_model`, `chat_digest`, `embed_model`, `embed_digest`;
- `corpus_sha256`, `index_sha256` and `documents_sha256`. Bind the snapshot manifests and hash the complete `/library/documents` JSON with `evaluation.managed_compare.encode`.

Both settings objects must match. Both state receipts and the host receipt must be at most 15 minutes old at launch. Paths in the plan are relative to its directory or absolute in the client namespace. Keep private files in dedicated directories and use mode 0600 for files. The authorization object contains `owner_reference`, `campaign_id`, the exact `plan_sha256`, `isolated_execution_authorized: true` and a fixed absolute nonsymlink `ledger_dir`. Keep the old ledger and original evidence intact.

### Preflight, dispatch and closeout

Inside the prepared, resource-limited runner, validate the plan and then exercise the actual cgroup/disk reader before consuming the live ledger. Point `--disk-path` at a mount on the guest filesystem backing the experiment; verify this correspondence during host inspection. These two preflight commands make zero network requests.

```sh
python -m evaluation.managed_compare --plan /campaign/plan.json
python -m evaluation.managed_compare --plan /campaign/plan.json --check-resources --disk-path /campaign
```

After exact-head review and owner authorization, use one invocation with a fresh results directory.

```sh
python -m evaluation.managed_compare --plan /campaign/plan.json \
  --execute-authorization /campaign/authorization.json --disk-path /campaign \
  --output /campaign/new-results
```

Consumption is exclusive per campaign in its fixed ledger, including when the same authorization is copied or reserialized. The runner reserves each unique arm/case before dispatch, then checks the cutoff again. A durable, explicitly undispatched reservation consumes no attempt. A reservation without a known outcome counts once. Never resend an uncertain request. Readiness and document preflight use metadata only. Each ordinal gets two serial requests in the frozen order. Source lists and retrieval metadata must match within each pair, whichever arm went first. Empty answers, cap exhaustion and wrong answers stay in the grading set. A transport, resource, ownership, parity or time failure stops the campaign.

Each ask keeps its exact HTTP entity bytes, hashes, generation evidence, ranked passages, timings and reservation. Interrupted prefixes have separate partial evidence. The privacy-preserving client requests identity encoding. Unexpected content encodings retain their wire bytes and stop the run. Telemetry records absolute guest paging counters and deltas from the first sample, available memory, disk free, and each experiment cgroup's usage, limits, swap and memory events before dispatch and at least every five seconds during requests. Existing idle guest swap is recorded separately. An experiment OOM, swapping, disappearance/limit change or free disk below 4 GiB stops dispatch. On a kernel without swap-peak accounting, use a zero swap limit for every monitored cgroup. Keep actual host snapshots/telemetry even on a partial run.

The custodian randomizes and conceals the arm identities before grading each attempted answer using the frozen rubric. Keep the random mapping private and lock per-answer worksheets before unblinding. Report primary untouched questions, previously exposed questions, full and attempted denominators, per-case gains/regressions, condition and citation support, appropriate abstentions, false refusals, and infrastructure/empty/cap failures. Timings include order and model residency effects. Verify the Mac evidence copy before exact-identity cleanup. Recheck protected production state and authenticated readiness if it was running. A merge or production update requires a separate decision.
