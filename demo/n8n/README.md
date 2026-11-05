# Import the manual text/CSV demo

This workflow uses Read/Write Files from Disk, Extract from File, Code and HTTP
Request nodes. It is inactive and has no schedule, webhook, credential ID or key.
The JSON and Code-node tests do not establish an actual n8n import/execution.
Verify node availability in the installed n8n version before import. Read/Write
Files from Disk v1.1 is required so a missing file raises an error rather than
silently ending the workflow without output.

1. Review [text-csv-demo.json](text-csv-demo.json). In n8n choose **Import from
   File** and select it. Leave it inactive; use **Execute Workflow** once when
   the API and files are ready.
2. Set the **Demo configuration** node's `apiUrl` to the reviewed private RAG API
   URL, and `demoFolder` to the path visible **inside the n8n execution runtime**.
   Do not use `localhost` to refer to another host.
3. Put exactly the repository's `runbook.txt` and `inventory.csv` in that folder.
   Read access must already be allowed by n8n's file restrictions and container
   mounts. For containerized n8n, a host path alone is insufficient. Do not alter
   a running container or disable file restrictions as part of import; report
   missing access for review. No filesystem access from Code nodes is needed.
4. Create an **HTTP Header Auth** credential: Name `x-api-key`, Value equal to
   the API's private key. Select that credential on **Ingest runbook**, **Ingest
   inventory**, and **Ask demo question**. Never paste the key into Code nodes,
   the URL, JSON body, or headers in the exported workflow.
5. Execute manually. The sequence reads TXT, ingests it, reads/parses CSV,
   combines rows as labeled text, ingests under `inventory.csv`, and asks once.
   CSV quoting is handled by Extract from File, not by splitting on commas.
6. The last node must show `demoCheck: PASS`, an answer with **ORION** and
   **NetworkOps**, and citations resolving to **both** `runbook.txt` and
   `inventory.csv`. Inspect the answer's meaning in the output. Wrong content,
   missing citations, incomplete generation and mismatched payloads fail. These
   fixture assertions are not a general semantic evaluator or retrieval benchmark.

The workflow uses serial execution and no HTTP retries; failures stop the run.
It validates each ingest returned one chunk. Keep fixtures under 700 characters
each for this two-chunk smoke. Editing documents can leave old chunks, so use a
new dedicated demo volume/collection when changing fixtures, after review.
The workflow does not install dependencies, manage containers, or run shell commands.

## Two-host deployment review

From the Mac, `ssh agent` reaches ubuntu-agent/n8n; `ssh aiminirig` reaches the
Docker/Ollama host. These aliases are not assumed to resolve inside containers.
Before live execution record:

| Item | Required observation |
| --- | --- |
| API listener | Unused port and exact private bind address on Docker host |
| Ollama | Existing reachable endpoint and installed embedding/chat model tags |
| n8n | Actual version, runtime/container, node availability and allowed demo path |
| Route | API `/health` reachable from the actual n8n runtime; unauthenticated `/ask` returns 401 |
| Qdrant | New Compose project volume and no published host ports |

Compose defaults to loopback for local testing. After review, `RAG_BIND_IP` may be
set to the verified private interface and `apiUrl` to that interface/port. This
does not configure a firewall or TLS. Use only the reviewed trusted private
network; do not expose it publicly. Do not change existing Ollama/Open WebUI
listeners, firewall rules, or n8n settings to work around a failed route.

During preflight, inspect only required container names, image versions, ports
and mounts; do not dump container environments or credential stores. Copying
fixtures, importing the workflow and running it are explicit live-demo steps
after setup review. Retain the n8n execution output with the Compose/image
identity. Stop only the newly created Compose project after the demo; leave
Ollama, Open WebUI and n8n running.

References: [n8n file nodes](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.readwritefile/),
[HTTP credentials](https://docs.n8n.io/integrations/builtin/credentials/httprequest/).
