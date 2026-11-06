# Enterprise RAG Platform

Ask a question about a folder of documents and inspect the passages behind the answer. FastAPI serves the browser UI, Ollama embeds text and generates answers, and Qdrant stores the vectors. The managed library keeps jobs and document revisions in SQLite. You can try the browser workflow without installing n8n.

## Docker browser quickstart

**What you need:** Git, Python 3 (to create a local key), curl, a POSIX shell such as bash, a desktop browser with a folder picker, and Docker Engine or Desktop with Compose v2 supporting `up --wait`. The API builds locally for Linux amd64 (emulated on Apple Silicon). Allow network access for the first build and the pinned Qdrant image. Have an Ollama server reachable **from the API container**, with a chat model and an embedding model already installed. The example uses `qwen3:8b` and `nomic-embed-text`. Run `ollama list` on the Ollama host to see your tags.

### 1. Configure and start

Clone into Documents so the demo folder is easy to find in the browser picker. Run the remaining commands from the clone. If you already have a checkout, use that directory instead.

```sh
mkdir -p "$HOME/Documents"
cd "$HOME/Documents"
git clone https://github.com/athollywood2002/enterprise-rag-platform.git
cd enterprise-rag-platform
```

Create the configuration once. This generates a key for your installation and refuses to overwrite an existing file.

```sh
umask 077
python3 - <<'PY'
from pathlib import Path
import secrets
config = Path(".env.demo.example").read_text()
config = config.replace("RAG_API_KEY=\n", f"RAG_API_KEY={secrets.token_urlsafe(32)}\n")
config = config.replace("RAG_MODEL_MODE=unknown", "RAG_MODEL_MODE=real")
with open(".env.demo", "x") as output:
    output.write(config)
PY
```

Open `.env.demo` in your local editor. Keep `OLLAMA_URL=http://host.docker.internal:11434` for an Ollama service reachable at the Docker host gateway, or enter the URL of your own reachable Ollama server. Set `OLLAMA_CHAT_MODEL` and `OLLAMA_EMBED_MODEL` to your installed tags. Keep the generated `RAG_API_KEY` handy for **Connect**. This file is ignored by Git and excluded from the image.

```sh
docker compose --env-file .env.demo -f compose.demo.yaml config --quiet
docker compose --env-file .env.demo -f compose.demo.yaml up -d --build --wait --wait-timeout 90
curl -fsS http://127.0.0.1:18000/health
```

The default Compose project is `rag-text-csv-demo`. Use a fresh project for a clean library or resume your own existing project. The API binds to loopback by default. Qdrant has a project volume and no published port.

### 2. Select, preview and ingest

1. Open [the local UI](http://127.0.0.1:18000/). Paste **only the value** after `RAG_API_KEY=` from your local file into **API key**, then click **Connect**. Under **Models and services**, click **Check readiness** to check the model tags and Qdrant connection.
2. Choose **Folder on this computer**. Set **Source name** to `router-demo`. Click **Select a folder**, open **Documents → enterprise-rag-platform → demo**, select **fixtures** and confirm the browser picker. The service receives files from that folder, including subfolders.
3. Under **Review selection**, look for `runbook.txt` and `inventory.csv`, both eligible. Check the destination, byte count and any exclusions before clicking **Start ingestion**.
4. Wait for both files to show **completed** under **Ingestion progress**. Uploading stages bytes. Completion means the file is indexed. To check recovery, reload the browser, connect again with the same key and select the same **Saved job**.

### 3. Ask and inspect citations

Choose **Documents from the selected job**. Ask **“What is the recovery code for demo-router-01 and which team owns it?”** Click **Ask the library**. For these public fixtures, look for **ORION** in the cited runbook excerpt and **NetworkOps** in the inventory row. Check the filenames, text and citation numbers even when the answer sounds right.

The managed library accepts UTF-8 TXT, UTF-8 CSV with headers, and text-based PDFs. CSV rows retain their column labels. For a PDF, check the physical page number beside each cited excerpt. The [illustrated walkthrough](docs/ui-walkthrough.md) shows the interface and gives the results of a separate three-file live test.

### 4. Stop and retain the library

```sh
docker compose --env-file .env.demo -f compose.demo.yaml down
```

This removes the project's containers and network. The named volumes `library-state` (SQLite and staged uploads) and `demo-qdrant` (vectors) persist. Keep the same project name and configuration when restarting. Omit volume-removal flags. Ollama is managed separately.

### If something goes wrong

| Symptom | What to check |
| --- | --- |
| UI won't open | Run `docker compose --env-file .env.demo -f compose.demo.yaml ps`. If port 18000 is occupied, set a free `RAG_PORT` in the file, run the start command again, and use that port in the browser and health URL. |
| Connect returns 401 | Use the value of `RAG_API_KEY` from the file used to start this project. After a refresh the UI asks again. If you edited the key, run the start command to apply it. |
| Authenticated, but models or Qdrant unavailable | Use **Check readiness**. Match the model tags to `ollama list`. Inside the API container, localhost is the API itself. On Linux a host-loopback-only Ollama listener may be unreachable via the gateway. Use a privately reachable endpoint. Check the Qdrant service with the Compose `ps` command above. |
| Preview excludes a file or parsing fails | Read the per-file detail. Use UTF-8 text, CSV with unique nonempty headers and consistent rows, or an unencrypted PDF with extractable text on every page. Scans need OCR before import. Blank PDF pages can also cause rejection. The default per-file limit is 10 MiB. |

## Use n8n for automation

[Import the manual workflow](demo/n8n/text-csv-demo.json) and follow the [n8n setup steps](demo/n8n/README.md). n8n reads the two demo files from its own runtime, labels the CSV fields, calls `/ingest` twice and then `/ask`. Set its API URL and select an **HTTP Header Auth** credential on the three HTTP nodes. Set its header name to `x-api-key` and its value to your API key.

**The workflow writes to the legacy collection. Its documents do not automatically appear in the browser’s managed library.** To search those files in the UI, ingest the folder there. For a new automation targeting the managed library, use the [library job API](docs/folder-library.md#api--n8n-integration).

## Demonstrated scope and limits

The Docker/n8n text-and-CSV demo and the separate two-page PDF HTTP smoke both completed. In a later real browser run, three files produced four indexed chunks, the saved job reopened after refresh, and David accepted four answers and their citations. Attempt 3 formally remains `FAILED_INCOMPLETE` because the harness kept partial service logs. Shutdown was verified. The expected embedding/chat counts were not independently verified. [Results and development history](docs/CURRENT_STATUS.md)

This is a local, single-instance prototype with a shared API key. OCR, tenant isolation and broad retrieval-quality evaluation are outside its demonstrated scope. Four chunks fit within the live test's five-result retrieval limit. The next task is a modest test with competing documents.

[Operating guide and limits](docs/folder-library.md) · [Architecture](docs/architecture.md) · [Developer setup and tests](docs/developer-reference.md) · [Collection safety](docs/collection-safety.md) · [MIT license](LICENSE)
