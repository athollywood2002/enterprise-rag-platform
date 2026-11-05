# Proposed real-model folder UI test — not executed

Purpose: one bounded, owner-observed mixed-folder UI demonstration after review of
the job-status/readiness follow-up. This is separate from the already completed
n8n and bounded PDF HTTP tests. Synthetic CI cannot substitute for this test.
Do not publish an image, merge, or change shared services as part of this plan.

## Freeze the packet before execution approval

Record the reviewed commit, locally built image ID, Docker base/Qdrant digests,
installed Ollama chat and embedding names/digests, and fixture SHA-256 hashes.
**Build before packet review/approval**, then freeze the resulting immutable image
identity and locally available Qdrant image. Approval must name those built bytes,
not a tag that will be rebuilt later. Launch with no build or pull; verify the
effective API container image ID against the approved image before any ingestion.
If platform/manifest-store identifiers differ, resolve that identity before approval;
do not waive a mismatch or silently substitute an image.
Do not pull models or upgrade dependencies. Read-only preflight must verify the
current AiMiniRig ports, available resources and Ollama endpoint reachable from
an isolated API container. Do not assume old host inventories remain current.

Prepare a unique Compose project, API image tag, key file (mode 0600), loopback
port and new SQLite/Qdrant volumes. Qdrant has no host port. The API binds only
AiMiniRig loopback; use a Mac SSH tunnel for the browser. No n8n changes are needed.
Use the base Compose interpolation: `RAG_BIND_IP=127.0.0.1` and `RAG_PORT` set to
the approved rig port. Do **not** append an override `ports` list: Compose can
retain the base publication (including 18000) alongside the override. Parse the
resolved config in memory and assert exactly one API publication at the approved
loopback port/target8000, no Qdrant publication, exactly the intended services,
unique project/volume names (not external storage), and the approved image tags.
Assert effective `OLLAMA_NUM_PREDICT` equals the approved cap (base currently1536),
the exact approved Ollama endpoint/model names, and `RAG_MODEL_MODE=real`.
Persist only redacted/allowlisted resolved values, never a full expanded key-bearing
config. The private packet must include and test these assertions before approval.
Record exact resolved values in the private run packet; public docs contain no
private host paths or credentials. Preserve the current Mac synthetic preview,
Ollama, Open WebUI, n8n, existing containers, volumes and receipts.

The packet must include exact CPU/memory limits and generation cap, verified against
available resources before approval. The normal UI has cooperative cancellation,
not the earlier supervisor's hard request budget or an inference kill switch.
Do not claim otherwise. If a hard budget is required, stop and prepare a compatible
reviewed proxy configuration before execution. No automatic retry or second run.

## Overall deadline and failure control

The proposed overall deadline is **1200 seconds**, monotonic from the first launch
attempt, including startup, manual UI steps, all four questions, capture and shutdown.
No new work after T+1100s; reserve at most60s for receipt capture,30s for shutdown
and10s for controller overhead. Owner inactivity or a failed check also enters this
same capture-then-stop path. The later private packet must implement/test an
independent deadline controller; browser polling or a human remembering to stop is
not that controller. No live launch until its concrete commands/limits are reviewed.

This controller stops only this unique test project's containers. It is not an
inference kill switch for shared Ollama: an already accepted model request may
finish there after an API disconnect. Record that limitation and do not signal,
restart or reconfigure the shared service. If that is unacceptable, stop planning
this form of run and review an appropriate isolation/budget design first.

## Small fixed fixture

Use only invented content in `ui-live-demo/`, each text/page below 900 characters:

| File | Exact facts | Expected chunks |
| --- | --- | --- |
| `operations/runbook.txt` | The ORION router recovery code is LANTERN. Restart requires approval from the on-call operator. | 1 |
| `inventory.csv` | Headers: asset,owner,location. One row: ORION,NetworkOps,Room 7. | 1 |
| `procedure.pdf` | Page 1: The maintenance window starts at 21:15 UTC. Page 2: Verify the blue indicator before ending maintenance. | 2 |

Generate a genuine two-page text PDF with the existing fixture generator, inspect
its parsed text offline, and confirm the four-chunk total before approving a run.
Hash all three files. Keep source files unchanged. Duplicate basenames, error paths
and replacement races remain covered by isolated tests; do not expand this live run.

## Proposed sequence and acceptance

1. Launch the reviewed Compose setup with `RAG_MODEL_MODE=real`. Check the UI shows
   the intended chat/embedding names, reachable metadata and both models available.
   Check an unauthenticated library request returns 401. Verify the actual container
   image identity and effective approved cap before ingestion. Never screenshot the key.
2. In the browser select the fixture folder, source `ui-live-demo-<run-id>`.
   Preview must show three eligible files, correct relative paths and byte total.
   Immediately before Start, save a private read-only `/api/tags` receipt and compare
   **both chat and embedding digests** with the frozen approved identities. A readiness
   `available` result is name-only, not digest verification; stop on a mismatch or
   unverifiable identity. Start once. Capture real file stages and the final saved job: three completed,
   zero failed/skipped/pending, four committed chunks. Stop on any discrepancy.
3. Refresh the browser, authenticate again, reopen the same job and verify its
   persisted results. Select **Documents from the selected job**.
4. Ask each question once, saving the full answer, retrieved excerpts, paths,
   PDF pages, response-bound `model_mode` and generation-completion evidence. Save
   each original response and hash **as it arrives, before assertions**; do not try
   to regenerate missing answers later. Check every `generation.num_predict` equals
   the approved cap and reject incomplete/unknown generation:
   - What is ORION's recovery code? Expected LANTERN, citing the runbook.
   - Who owns ORION and where is it located? Expected NetworkOps and Room 7,
     citing the inventory with field/value relationships intact.
   - When does maintenance start and what must be checked before it ends?
     Expected 21:15 UTC and blue indicator, supported by PDF pages 1 and 2.
   - What is ORION's purchase price? Expected an explicit statement that the
     documents do not provide it, with no invented price or misleading evidence.
5. Review semantic correctness, allowing accurate paraphrases. Relevant excerpts
   alone do not prove every generated claim. Wrong facts, missing support,
   incomplete/unknown generation, invented negative-answer facts or unexpected
   requests fail the demonstration. Keep failed evidence; do not silently rerun.

Expected successful path: four document embeddings plus four question embeddings
and four chat requests (8 embeddings / 4 chats). This is an expected count, not an
enforced proxy budget. Record observable request counts privately if available;
unattributable/shared counts are **unverified**, never a passed budget validation.
Do not infer attribution from the UI's progress or a mode label. No unchanged/replacement
live pass is included. With four indexed chunks and UI `top_k=5`, **every chunk can
reach the model**. This validates workflow/citation handling, not selective retrieval
or larger-library quality.

`real` is operator configuration, including in an ask response, not proof of live
inference. Private endpoint/routing and both model identities plus actual response
evidence must support any real-inference claim. Keep endpoint details private.

## Reviewed command template

These are **review templates, not execution authorization**. Substitute and freeze
verified values and the assertion/capture/deadline helpers in the private packet.
`live-ui.override.yaml` must pin the unique API image, approved
resource limits and model endpoint; `.env.live-ui` holds credentials and model names.
Use `RAG_BIND_IP`/`RAG_PORT` for publication; the override must not append ports.
Both are private, outside source control. The source roots stay unconfigured for
this first browser-upload run. No synthetic override is used.

```sh
# Bash, in the eventual isolated reviewed checkout. All values require review.
C=(docker compose --env-file .env.live-ui -p "$UI_PROJECT"
   -f compose.demo.yaml -f live-ui.override.yaml)
# PRE-APPROVAL preparation only after its scope is authorized:
"${C[@]}" build api
docker image inspect --format '{{.Id}}' "$UI_IMAGE"
# Freeze/review that ID and the locally present pinned Qdrant image; then stop
# for owner execution approval. No service launch is part of image preparation.

# POST-APPROVAL only, under the independent overall deadline controller:
# First run the packet's in-memory resolved-config assertions above.
"${C[@]}" up -d --no-build --pull never --wait --wait-timeout 90
API_CONTAINER=$("${C[@]}" ps -q api)
test -n "$API_CONTAINER"
test "$(docker inspect --format '{{.Image}}' "$API_CONTAINER")" = "$APPROVED_API_IMAGE_ID"
# Fail before ingestion if image/cap/routes/ports or either model digest differs.
# On the Mac, after verifying both unused ports:
ssh -N -o ExitOnForwardFailure=yes \
  -L "127.0.0.1:${MAC_UI_PORT}:127.0.0.1:${RIG_UI_PORT}" aiminirig
# Open http://127.0.0.1:<MAC_UI_PORT>/
```

## Capture before down, on success or any failure

The private packet must install an always-run finalization path **before launch**.
Its bounded collector runs the following project-scoped commands, keeping stdout,
stderr and exit/timeout status per command, with a60s aggregate deadline. Use a0600
header file for the API key (`x-api-key: ...`), not the key value in argv/history.
The writer must redact that exact key in memory before persistence, cap logs at
200 lines/2MiB and job JSON at1MiB, and record truncation/failed/missing captures
explicitly. No full inspect, environment dump, recursive storage or shared-service logs.

```sh
# Collector sources and these variables are fixed in the reviewed private packet.
# Each command below runs INSIDE the collector's aggregate deadline.
umask 077
timeout 8s "${C[@]}" logs --no-color --tail 200 api qdrant
timeout 5s "${C[@]}" ps --format json
curl --noproxy '*' --silent --show-error --fail \
  --connect-timeout 2 --max-time 5 --max-filesize 1048576 \
  --header "@$AUTH_HEADER_FILE" "$API_LOOPBACK/library/jobs"
# If JOB_ID was actually reached and validated as the returned job ID:
curl --noproxy '*' --silent --show-error --fail \
  --connect-timeout 2 --max-time 5 --max-filesize 1048576 \
  --header "@$AUTH_HEADER_FILE" "$API_LOOPBACK/library/jobs/$JOB_ID"
# Retain only the original observer's four fixed answer files/hashes if reached:
# ask-1.json .. ask-4.json (128KiB each,512KiB total), plus permitted screenshots.
# Missing/unreached answers are explicit, never placeholders or another POST /ask.
```

The observer must save only scoped response bodies/status/hashes, not headers or
a secret-bearing browser HAR. Collector output goes through the bounded/redacting
writer to private0600 receipts. If capture fails, record that failure; do not wait
indefinitely or skip shutdown. The future packet must test this collector and the
following controller envelope, including failure/timeout handling, before approval:

```sh
# Overall controller invokes this at work completion/failure or by T+1100s.
# capture-live-ui-receipts.sh contains the reviewed collector above and its writer.
capture_exit=0
timeout --signal=TERM --kill-after=2s 58s bash ./capture-live-ui-receipts.sh || capture_exit=$?
receipt_write_failed=0
printf '%s\n' "$capture_exit" > "$RECEIPT_DIR/capture-exit.txt" || receipt_write_failed=1
# Capture has ended BEFORE down can remove the only API/Qdrant containers/logs.
# Do not redirect the down command to a possibly broken receipt directory:
# a redirection failure would prevent down itself from running.
stop_exit=0
stop_output=$(timeout --signal=TERM --kill-after=2s 28s "${C[@]}" down --timeout 5 2>&1) || stop_exit=$?
printf '%s\n' "$stop_output" > "$RECEIPT_DIR/project-down.log" || receipt_write_failed=1
printf '%s\n' "$stop_exit" > "$RECEIPT_DIR/stop-exit.txt" || receipt_write_failed=1
printf 'capture=%s stop=%s receipt_write_failed=%s\n' \
  "$capture_exit" "$stop_exit" "$receipt_write_failed" >&2
test "$capture_exit" -eq 0 && test "$stop_exit" -eq 0 && test "$receipt_write_failed" -eq 0
```

No `-v`/`--volumes`; preserve both volumes, images, fixture bytes and historical
evidence. Verify the project's containers/listener/network stopped and the tunnel
closed, without touching another project or shared Ollama. A nonzero capture/stop
result or missing required evidence is FAILED/INCOMPLETE, never a successful run;
stop for review rather than retrying, escalating to global commands or silently
launching a second attempt. Return partial evidence and the exact unresolved state.

Return screenshots, hashes, job/results, all reached original answers, semantic
judgments, actual/expected/unverified counts, and scoped stop verification. A pass
demonstrates this fixture on these pins only, not broad retrieval quality, selective
retrieval, OCR, DOCX/RTF, performance or production readiness. Concrete private
host/configuration/capture/deadline review and separate owner execution approval
are still required; no helpers or live services are prepared by this document.
