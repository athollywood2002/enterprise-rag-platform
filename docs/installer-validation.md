# Installer checks and remaining platform work

This implementation was checked with synthetic model replies, not downloaded
model weights or real-model generation. It is a draft installer, not a supported
platform release.

## Checks performed

- **77 focused offline installer tests passed.** They cover credential permissions,
  redirection refusal, locks, interrupted writes at 25 commit points, image/model
  identity, independent installation rebuilds, external mode, GPU error classes,
  ownership checks, unsafe Compose inputs, status and scoped stop.
- **851 base tests passed; 62 skipped; 4 subtests passed.** The skips include optional
  parser coverage. One third-party Starlette/httpx deprecation warning was reported.
- Ruff check and format check passed. All 28 existing JavaScript checks passed.
- The 18 shell blocks in README/setup/developer/validation documentation passed shell syntax
  checks; 24 relative links/anchors in those files resolved. The normal installer
  refused macOS startup before creating installation state.
- A separate Ubuntu 22.04 CI job uses stock `/usr/bin/python3` (3.10), checks the
  platform guard and wrapper, and runs the installer module's tests without the
  application's conftest/dependencies. This does not lower the application's
  Python requirement or establish real-model Ubuntu support.
- Actual Compose rendering passed for managed CPU, managed NVIDIA and external
  Ollama configurations. This checked service/volume sets, private ports, GPU
  reservation normalization and ownership. Rendering is not a GPU execution test.

## Isolated Docker/browser check

`scripts/install_synthetic_check.py` creates a fresh project and uses the actual
installer methods with a test-only subclass. Its Ollama service is replaced by
the existing deterministic Python fixture in the API image. The test bypasses the
host-platform check only in its driver; `setup.sh` has no bypass flag.

The final helper, driver, wrapper and UI bytes matched the working tree at the time
of the successful check. On Docker Desktop 4.91 / Engine 29.8.0 / Compose 5.5.1 on
Apple Silicon (Linux amd64 API under emulation), headless Chrome verified:

1. Initial API build and metadata readiness, with no real model downloads.
2. Browser connection, folder ingestion, saved-job recovery after refresh, and a
   cited answer explicitly labeled synthetic.
3. Unchanged reimport skips while retaining searchable documents.
4. Installer resume using the same API image ID and key, without a rebuild.
5. Scoped stop/start, retained volumes and recovered saved job.
6. Final scoped stop with the pre-existing container inventory unchanged.

The web-asset follow-up extends the image's UID10001 probe beyond Python files to
`index.html`, `app.js` and `style.css`. A disposable no-network container creates a
root-owned fixture, drops to the real UID10001 and verifies that readable Python
plus owner-only HTML fails specifically with PermissionError; the readable control
passes. Neither the checkout nor the application image is chmodded. The installer
also requests and hash-checks the public UI entry and assets before reporting ready,
and the browser driver independently verifies their actual HTTP responses.

The generated synthetic key did not appear in the retained run log. Test images,
volumes and state were retained. Earlier failed synthetic iterations were also
retained: fixture healthcheck and browser-wait expectations were corrected, and
the installer port probe was changed to bind **and listen** with `SO_REUSEADDR`
so immediate restart accepts TIME_WAIT without accepting an active listener.

To repeat on an isolated Docker test host (this builds test images but no weights):

```sh
# Install the developer and Playwright dependencies first; choose a NEW durable path.
export INSTALLER_FIXTURE_DIR="$HOME/rag-installer-check-$(date +%s)"
python scripts/install_synthetic_check.py
```

Install Playwright's Chromium, or set `CHROMIUM_PATH` to an existing test browser.
Only the new project's services are stopped; its volumes are not deleted. Do not
point the driver at an existing installation.

## Not established

- No Ubuntu 22.04/24.04 real-model installation, inference timings or measured
  hardware minimums.
- No actual NVIDIA runtime/probe execution or acceleration measurement. The Ollama
  image version/index digest was checked against the registry; probe command design
  was checked against its upstream Ubuntu Dockerfile. Runtime utility injection
  still needs testing on an allocated NVIDIA host.
- No real model-pull/resume integration; offline tests exercise that state machine.
- No installer-specific cross-host SSH/browser or Windows/WSL2 end-to-end test.
- No Apple Silicon product support or Metal claim; the local synthetic check is
  only a development harness run with an explicit host-check bypass.
- No image publication, production security assessment or retrieval benchmark.

Use the [setup guide](setup.md) for the command contract and recovery rules. Real
platform validation is a separate, explicitly scoped action.
