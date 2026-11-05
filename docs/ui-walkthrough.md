# Reviewing the folder UI

The interface is served at `/` by the same Docker API. Follow
[the setup guide](folder-library.md), connect with your configured key, and use
this small review sequence:

1. Select a folder containing `runbook.txt`, `inventory.csv`, a text-based PDF,
   two nested files with the same basename, and an unsupported file.
2. Inspect file count, total size and the unsupported-file exclusion. Start.
3. Observe staged uploads followed by parsing, chunking, embedding and indexing.
   Refresh, reconnect and reopen the job. Counts and per-file results persist.
4. Ask a fact question, check source relative paths and PDF page numbers, and read
   the excerpt supporting each citation. Generation completion is shown separately.
5. Reingest the same folder: unchanged compatible documents skip. Change one file:
   its new revision replaces the old only after successful indexing. Remove one
   file from the selection: its previously indexed document remains.
6. Configure a read-only server mount using `compose.sources.example.yaml`. Browse
   within its label, preview the subtree and ingest through the same parser.
7. Cancel a larger job and observe that the in-flight operation can finish before
   cancellation is observed. Retry failed/cancelled files explicitly.

## Automated browser walkthrough

`scripts/ui_browser_check.py` drives the actual HTML/JS with Chromium and the real
FastAPI/job/parser implementation. `demo/serve_ui_fixture.py` supplies a temporary
SQLite registry and local-mode Qdrant with **synthetic model replies**; it cannot
be used as proof of live-model quality. The fixture server binds localhost only.

The `browser-workspace` CI job checks folder selection/upload, completed results,
refresh recovery, question/citation display, server browsing, keyboard focus and
390px viewport overflow. Its `actual-ui-screenshots` artifact contains preview,
results, server-source and mobile screenshots. The separate `container-smoke` job
uses a real Qdrant server and parsers from inside the built Docker image.

The execution workspace used for implementation cannot launch Chromium (its Unix
socket syscall is denied), and has no Docker daemon. CI performs those isolated
checks instead. The source is not deployed to shared n8n or AiMiniRig, and no real
model inference is performed by these tests.
