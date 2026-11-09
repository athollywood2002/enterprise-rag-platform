# Setup and recovery

The installer is a review-stage Ubuntu-first implementation, not a measured
platform certification. Use a reviewed revision containing `setup.sh`, retain the
whole project directory, and inspect the script and `scripts/install.py` before
running it. No image is published by this installer PR.

## Prerequisites

Targets: Ubuntu 22.04/24.04 x86-64, Bash, Python 3.10+, Docker Engine with local
daemon access, and a modern Compose plugin (v2+). The script checks CLI, daemon,
local Docker context and Compose config/wait/pull capabilities separately.
The host helper works with Ubuntu 22.04's stock Python 3.10. The application keeps
its separate Python 3.11+ development requirement and Python 3.12 container runtime.
The isolated synthetic check used Docker Desktop/Compose 5.5.1, not an Ubuntu
real-model deployment. The validation matrix below lists the remaining work.

- [Install Docker on Ubuntu](https://docs.docker.com/engine/install/ubuntu/).
- [Docker post-install options](https://docs.docker.com/engine/install/linux-postinstall/):
  Docker-group membership grants root-equivalent privileges. Consider rootless
  Docker. Never fix permission errors with `chmod` on the Docker socket.
- [Docker Desktop WSL2 integration](https://docs.docker.com/desktop/features/wsl/)
  is a proposed route, not an end-to-end verified installation path.
- [NVIDIA device reservations](https://docs.docker.com/compose/how-tos/gpu-support/)
  require a working NVIDIA driver and container runtime in the guest/host running Docker.

The installer does not install Docker, change groups, configure a daemon, install
drivers or modify shared services. Install prerequisites yourself, then rerun.
Remote Docker contexts are rejected; run setup on the Docker host instead.

## First install

From the project directory:

```sh
bash setup.sh
```

The default is managed Ollama, with NVIDIA detection inside Docker. Confirmed
unavailable GPU access selects CPU with a warning. Unknown probe/image/network
errors stop setup instead of silently selecting CPU. A visible existing Ollama or
GPU workload warns about contention and recommends external mode; a one-time
interactive choice is required before continuing managed mode.
This is a first-install check: starting another host Ollama/GPU workload later does
not automatically repeat the warning. Avoid contention or use external mode.

Useful explicit options:

```sh
bash setup.sh --device cpu
# Or require NVIDIA; never silently fall back:
bash setup.sh --device nvidia
# Change only this installation's API listener:
bash setup.sh --port 18001
# Slow initial model download: seconds per model, maximum 86400:
bash setup.sh --download-timeout 7200
```

These are alternatives, not a sequence to run before first use. The chosen project,
port and device are saved. A saved NVIDIA mode becoming unavailable fails with
guidance; CPU requires the explicit override. CPU timings are unmeasured against
the current 120-second embedding, 180-second chat and 300-second per-file budgets.

Setup builds an installation-specific API image, records its immutable ID, then
starts Qdrant and managed Ollama. Missing default models are pulled only during
initial provisioning. Completed model digests are saved individually, so interrupted
downloads can resume. Progress is reported without the application key.

Metadata checks confirm `/health`, authenticated library readiness, installed model
names/digests and Qdrant reachability. They send no ingestion or inference request.
Try a small folder and question to exercise actual generation. Setup errors name
the stage or failed contract without dumping resolved config, Docker environments
or raw service output.

## Application key

```sh
bash setup.sh --show-key
```

Run this in the installation terminal (on the server for a headless install).
It needs no Docker daemon, displays the existing key, refuses output redirection,
and never rotates it or starts services. This is the **FastAPI application key**,
not an Ollama key. Paste it into the browser's **API key** field and click **Connect**.
The browser keeps it in tab memory, not local/session storage. Refresh requires
connecting again. Clear any terminal recording before requesting the key.

## Headless server

The published port belongs to the server's loopback interface, not your laptop.
On the computer with your browser, keep this SSH command running:

```sh
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18000:127.0.0.1:18000 user@server
```

Open `http://localhost:18000` on that computer. If its port 18000 is occupied, use
`-L 127.0.0.1:18001:127.0.0.1:18000` and browse to `http://localhost:18001`.
If the server uses a different saved API port, change the right-hand port too.
Downloading an image alone does not expose a port. Container localhost, server
localhost and laptop localhost are different network endpoints.

The folder picker reads files on the **browser computer**. For server-only files,
use the separately configured [read-only server-root feature](folder-library.md).
Do not expose the shared-key prototype directly to a LAN or public interface.

## External Ollama

For a new installation with an already managed server and installed models:

```sh
bash setup.sh --ollama-url http://MODEL-HOST:11434
```

Choose an endpoint reachable **from the API container**, not just from your shell.
On Linux, the base configuration maps `host.docker.internal` to the host gateway;
a host-loopback-only service may still be unreachable. Do not silently change its
listener. HTTP is suitable only on a trusted private route; use HTTPS or private
transport elsewhere. URL credentials and query strings are rejected.

This mode omits the managed Ollama/GPU overlays, does not download external models
and does not stop external Ollama. The API and Qdrant still get fresh scoped volumes.
You may choose external mode after a paused first install only before an API image,
model identity or container has been established. An established backend switch is
a migration, not a repair flag.

## Durable state and recovery

Each installation has an owned `0700` `.rag-install` directory and private `0600`
`.env.install`. Both are ignored by Git. The state JSON also holds the key, model
digests, image ID and saved Compose-input hashes; treat the whole directory as
secret. Back it up together with the project and its three project-namespaced
volumes: `library-state`, `demo-qdrant`, and (managed mode) `ollama-models`.
Restore at the original project path; moving an established installation requires
a migration rather than editing the saved ownership record.
Do not put the project in `/tmp`, `/var/tmp` or macOS's purgeable temp directories.

State updates use atomic replacement and fsync under a per-installation lock.
An interrupted initial state write resumes from the committed identity. Uncommitted
Compose-input generations are not adopted. A partially written port update repairs
the derived env file only when its previous hash matches. Unexpected missing/changed
established state refuses startup instead of generating a new identity/key.

```sh
bash setup.sh --status
bash setup.sh --stop
bash setup.sh
```

Status performs no repairs, downloads or inference. Stop uses the saved, hash-checked
Compose inputs and project ownership, even after a source/image/model mismatch.
It stops only this project and retains all volumes. A stopped daemon must first be
restarted; a changed saved config must be restored from backup before stop can trust it.

Ordinary resume uses the saved image ID with no implicit build/pull. If the image
is missing or source changed, review the change and explicitly rebuild:

```sh
bash setup.sh --rebuild
```

An upstream pinned image missing after provisioning must be restored deliberately;
resume does not refresh it. Established missing/changed model digests fail with
repair guidance. Restore the saved model identity, or plan a deliberate model update.
The installer does not currently provide a model-refresh or in-place backend-migration
command. Do not delete state to bypass identity checks.

### Using different models

The installer currently provisions the two exact default tags only. For manual
deployments, `OLLAMA_CHAT_MODEL` and `OLLAMA_EMBED_MODEL` select model tags in
`.env.demo`. Chat changes generally do not require reindexing. Embedding changes can
change vector dimensions or the library fingerprint; reingest to make documents
searchable with the new embedding identity. Do not attach existing unrelated storage.

## Existing manual Docker quickstart

An existing `.env.demo` project stays separate; the installer does not adopt it.
To keep the manual external-Ollama setup, create config once (exclusive, no overwrite):

```sh
(
umask 077
python3 - <<'PY'
from pathlib import Path
import secrets
config = Path('.env.demo.example').read_text()
config = config.replace('RAG_API_KEY=\n', 'RAG_API_KEY=' + secrets.token_urlsafe(32) + '\n')
config = config.replace('RAG_MODEL_MODE=unknown', 'RAG_MODEL_MODE=real')
with open('.env.demo', 'x') as output:
    output.write(config)
PY
)
```

Edit the endpoint/model tags locally. Reuse your project name for every command:

```sh
docker compose --env-file .env.demo -f compose.demo.yaml config --quiet
docker compose --env-file .env.demo -f compose.demo.yaml up -d --build --wait --wait-timeout 90
# Open http://127.0.0.1:18000 and connect with the key from .env.demo.
docker compose --env-file .env.demo -f compose.demo.yaml down
```

Do not print expanded Compose config: it contains the key. Legacy n8n `/ingest`
and `/ask` use a different collection from browser-managed library jobs.

## Validation status

See [performed checks and concrete limits](installer-validation.md), including the
local synthetic lifecycle and the distinction between rendered GPU configuration
and actual GPU execution.

| Path | Evidence required / current limit |
| --- | --- |
| Offline state and command contracts | Focused tests cover private keys, rerun/image/model identity, interrupted writes, lock, device errors, ownership and scoped stop. |
| Isolated synthetic Docker/browser | Test-only stub instead of Ollama; no weights or real inference. Not a platform/model quality claim. |
| Ubuntu 22.04 / 24.04 CPU | Each real-model install/answer and peak memory/latency remain unverified. |
| Ubuntu NVIDIA / VM | Real GPU probe plus accelerated embedding/chat and contention behavior remain unverified. |
| Headless SSH route | Documented; installer-specific cross-host browser validation remains unverified. |
| Windows 11 / WSL2 | End-to-end Windows browser/upload validation remains unverified. |
| Apple Silicon | Deferred. The API image targets Linux amd64. No Metal acceleration claim. |

The pinned Ollama version is 0.40.15 with a registry-verified image index digest in
`compose.install.yaml`; its Ubuntu image provides `/bin/sh`. The NVIDIA utility is
supplied by the NVIDIA container runtime, not assumed from host GPU presence.
Actual NVIDIA execution is still a required later validation. No minimum hardware
guarantee is established: the discussed 16–32 GB RAM, ~30 GB disk and 12–16 GB VRAM
are preliminary planning estimates, not measured support requirements.
