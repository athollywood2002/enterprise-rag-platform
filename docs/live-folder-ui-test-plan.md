# Proposed real-model folder UI test — not executed

Purpose: one bounded, owner-observed mixed-folder UI demonstration after review of
the job-status/readiness follow-up. This is separate from the already completed
n8n and bounded PDF HTTP tests. Synthetic CI cannot substitute for this test.
Do not publish an image, merge, or change shared services as part of this plan.

## Freeze the packet before execution approval

Record the reviewed commit, locally built image ID, Docker base/Qdrant digests,
installed Ollama chat and embedding names/digests, and fixture SHA-256 hashes.
Do not pull models or upgrade dependencies. Read-only preflight must verify the
current AiMiniRig ports, available resources and Ollama endpoint reachable from
an isolated API container. Do not assume old host inventories remain current.

Prepare a unique Compose project, API image tag, key file (mode 0600), loopback
port and new SQLite/Qdrant volumes. Qdrant has no host port. The API binds only
AiMiniRig loopback; use a Mac SSH tunnel for the browser. No n8n changes are needed.
Record exact resolved values in the private run packet; public docs contain no
private host paths or credentials. Preserve the current Mac synthetic preview,
Ollama, Open WebUI, n8n, existing containers, volumes and receipts.

The packet must include exact CPU/memory limits and generation cap, verified against
available resources before approval. The normal UI has cooperative cancellation,
not the earlier supervisor's hard request budget or an inference kill switch.
Do not claim otherwise. If a hard budget is required, stop and prepare a compatible
reviewed proxy configuration before execution. No automatic retry or second run.

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
   Check an unauthenticated library request returns 401. Never screenshot the key.
2. In the browser select the fixture folder, source `ui-live-demo-<run-id>`.
   Preview must show three eligible files, correct relative paths and byte total.
   Start once. Capture real file stages and the final saved job: three completed,
   zero failed/skipped/pending, four committed chunks. Stop on any discrepancy.
3. Refresh the browser, authenticate again, reopen the same job and verify its
   persisted results. Select **Documents from the selected job**.
4. Ask each question once, saving the full answer, retrieved excerpts, paths,
   PDF pages and generation-completion evidence:
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
otherwise mark them unverified. No unchanged/replacement live pass is included.

## Reviewed command template

Substitute and freeze the verified values in the private packet before approval.
`live-ui.override.yaml` must pin the unique API image, unused loopback port, approved
resource limits and model endpoint; `.env.live-ui` holds credentials and model names.
Both are private, outside source control. The source roots stay unconfigured for
this first browser-upload run. No synthetic override is used.

```sh
# On AiMiniRig, from the isolated checkout of the reviewed commit:
docker compose --env-file .env.live-ui -p "$UI_PROJECT" \
  -f compose.demo.yaml -f live-ui.override.yaml config --quiet
docker compose --env-file .env.live-ui -p "$UI_PROJECT" \
  -f compose.demo.yaml -f live-ui.override.yaml build api
docker compose --env-file .env.live-ui -p "$UI_PROJECT" \
  -f compose.demo.yaml -f live-ui.override.yaml up -d --wait --wait-timeout 90
# On the Mac, after verifying both unused ports:
ssh -N -L "${MAC_UI_PORT}:127.0.0.1:${RIG_UI_PORT}" aiminirig
# Open http://127.0.0.1:<MAC_UI_PORT>/
# On AiMiniRig, stop only this unique project and preserve its data:
docker compose --env-file .env.live-ui -p "$UI_PROJECT" \
  -f compose.demo.yaml -f live-ui.override.yaml down
```

Return screenshots, hashes, job/result receipts, full answers, semantic judgments,
actual versus expected counts, and scoped stop verification. Preserve both new
volumes and all historical evidence. A pass demonstrates this fixture on these
pins only, not broad retrieval quality, OCR, DOCX/RTF or production readiness.
