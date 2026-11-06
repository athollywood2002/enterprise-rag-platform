# Import the manual text/CSV demo

This workflow uses Read/Write Files from Disk, Extract from File, Code and HTTP
Request nodes. It is inactive and has no schedule, webhook, credential ID or key.
One manual two-host execution completed with the expected answer and both sources.
The automated Code-node checks cover the export separately.
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

## Collections and network access

This export calls the legacy `/ingest` and `/ask` routes. Its documents do not automatically appear in the browser's managed library. Import the files in the UI to use saved jobs and document replacement, or build a workflow against the [library job API](../../docs/folder-library.md#api--n8n-integration).

Compose binds the API to loopback by default. When n8n runs on another host, set `RAG_BIND_IP` to a trusted private interface, keep Qdrant internal and set `apiUrl` to an address reachable from the n8n runtime. Confirm it can reach the API's `/health` route. Use TLS before sending documents or keys across untrusted networks. For the local browser path, start with the [Docker quickstart](../../README.md#docker-browser-quickstart).

References: [n8n file nodes](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.readwritefile/),
[HTTP credentials](https://docs.n8n.io/integrations/builtin/credentials/httprequest/).
