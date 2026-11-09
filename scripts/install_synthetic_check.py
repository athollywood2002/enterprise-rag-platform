"""Opt-in isolated installer integration. Synthetic replies only; no Ollama weights.

Test-only subclass/host-check injection; there is no synthetic bypass in setup.sh.
INSTALLER_FIXTURE_DIR must name a fresh DURABLE directory. Keep it after this test.
Only this new project's services are stopped. Volumes, images and state are retained.
"""
# ruff: noqa: BLE001 -- Persist only safe failure types and always stop the owned fixture.

import json
import os
import shutil
import socket
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import install as m


class SyntheticInstaller(m.Installer):
    model_mode = "synthetic"

    def ensure_image(self, image):
        if image == self.ollama_image:
            if m.image_id(self.runner, image) is None:
                self.runner.run(["docker", "tag", self.state["api_image"], image])
        else:
            super().ensure_image(image)

    def contention(self):
        # Fixture never uses GPU or native Ollama; do not inspect shared workloads.
        self.state["contention_checked"] = True
        self.save()


def browser_check(installer, folder, *, import_files):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("CHROMIUM_PATH"):
            options["executable_path"] = os.environ["CHROMIUM_PATH"]
        browser = playwright.chromium.launch(**options)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(60000)
        page.goto("http://127.0.0.1:" + str(installer.state["port"]))

        def connect():
            page.locator("#api-key").fill(installer.state["key"])
            page.get_by_role("button", name="Connect", exact=True).click()
            expect(page.locator("#workspace")).to_be_visible()
            expect(page.locator("#model-mode")).to_contain_text("synthetic")
            expect(page.locator("#api-key")).to_have_value("")

        connect()
        installer.check_stage = "browser_connected"
        if import_files:
            page.locator("#source-name").fill("installer-smoke")
            page.locator("#folder-input").set_input_files(str(folder))
            page.get_by_role("button", name="Start ingestion", exact=True).click()
            expect(page.locator("#job-title")).to_contain_text("completed")
            expect(
                page.locator("#job-counts .metric").filter(has_text="successful").locator("strong")
            ).to_have_text("2")
            installer.check_stage = "initial_import_complete"
            saved = page.locator("#job-select").input_value()
            page.reload()
            connect()
            expect(page.locator("#job-select")).to_have_value(saved)
            installer.check_stage = "refresh_restored_job"
            page.locator("#search-scope").select_option("job")
            page.locator("#question").fill("What is the recovery code and who owns the router?")
            page.get_by_role("button", name="Ask the library", exact=True).click()
            expect(page.locator("#answer")).to_contain_text("ORION")
            expect(page.locator("#answer")).to_contain_text("NetworkOps")
            expect(page.locator("#generation")).to_contain_text("simulated reply")
            installer.check_stage = "cited_synthetic_answer"
            page.locator("#source-name").fill("installer-smoke")
            page.locator("#folder-input").set_input_files(str(folder))
            page.get_by_role("button", name="Start ingestion", exact=True).click()
            expect(page.locator("#job-title")).to_contain_text("completed")
            expect(
                page.locator("#job-counts .metric").filter(has_text="skipped").locator("strong")
            ).to_have_text("2")
            expect(page.locator("#job-rows")).to_contain_text("Unchanged document")
        else:
            expect(page.locator("#job-title")).to_contain_text("completed")
            expect(
                page.locator("#job-counts .metric").filter(has_text="skipped").locator("strong")
            ).to_have_text("2")
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        context.close()
        browser.close()


def main():
    root = Path(os.environ["INSTALLER_FIXTURE_DIR"]).resolve()
    m.durable_root(root)
    m.need(not root.exists(), "Synthetic fixture directory must be fresh.")
    root.mkdir(mode=0o700, parents=True)
    source = Path(__file__).resolve().parents[1]
    for name in ("src", "demo", "docker", "scripts"):
        shutil.copytree(
            source / name, root / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
    for name in ("Dockerfile", "compose.demo.yaml", "compose.gpu.yaml", "setup.sh"):
        shutil.copy2(source / name, root / name)
    tag = "enterprise-rag-installer-synthetic:" + uuid.uuid4().hex
    overlay = {
        "services": {
            "api": {"environment": {"NO_PROXY": "qdrant,ollama,localhost,127.0.0.1"}},
            "ollama": {
                "image": tag,
                "platform": "linux/amd64",
                "entrypoint": ["python", "/app/demo/ollama_stub.py"],
                "healthcheck": {
                    "test": [
                        "CMD",
                        "python",
                        "-c",
                        "import socket;socket.create_connection(('127.0.0.1',11434),2).close()",
                    ],
                    "interval": "2s",
                    "timeout": "3s",
                    "retries": 15,
                },
                "volumes": ["ollama-models:/root/.ollama"],
            },
        },
        "volumes": {"ollama-models": {}},
    }
    (root / "compose.install.yaml").write_text(json.dumps(overlay))
    installer = SyntheticInstaller(root)
    installer.ollama_image = tag
    m.check_platform = lambda: None  # Test host only; not a support claim or production option.
    _, before = installer.runner.run(
        ["docker", "ps", "-a", "--no-trunc", "--format", "{{.ID}} {{.State}} {{.Ports}}"]
    )
    result = {
        "synthetic_only": True,
        "real_model_calls": 0,
        "weights_downloaded": False,
        "host_platform_check_bypassed_only_in_test_driver": True,
    }
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    try:
        installer.command(m.arguments(["--device", "cpu", "--port", str(port)]))
        identity = installer.state["api_image"]
        key = installer.state["key"]
        browser_check(installer, root / "demo/fixtures", import_files=True)
        installer.command(m.arguments([]))
        m.need(
            installer.state["api_image"] == identity and installer.state["key"] == key,
            "Resume changed identity.",
        )
        installer.command(m.arguments(["--stop"]))
        installer.command(m.arguments([]))
        browser_check(installer, root / "demo/fixtures", import_files=False)
        result.update(
            status="PASS",
            initial_install=True,
            resume_same_image_and_key=True,
            browser_refresh_and_cited_synthetic_answer=True,
            unchanged_reimport=True,
            stop_start_saved_job=True,
        )
    except Exception as error:
        # Do not serialize raw browser fill errors (can contain the synthetic key).
        result.update(status="FAILED", error_type=type(error).__name__)
        result["last_check_stage"] = getattr(installer, "check_stage", "installer_start")
        if isinstance(error, m.InstallError):
            result["gate"] = str(error)
    finally:
        if installer.state and installer.state["snapshots"]:
            try:
                installer.command(m.arguments(["--stop"]))
                result["scoped_stop"] = True
            except Exception as error:
                result.update(status="FAILED", stop_error_type=type(error).__name__)
    _, after = installer.runner.run(
        ["docker", "ps", "-a", "--no-trunc", "--format", "{{.ID}} {{.State}} {{.Ports}}"]
    )
    result["shared_container_inventory_unchanged"] = sorted(before.splitlines()) == sorted(
        after.splitlines()
    )
    result["project"] = installer.state["project"] if installer.state else None
    result["all_test_volumes_images_and_state_retained"] = True
    if not result["shared_container_inventory_unchanged"]:
        result["status"] = "FAILED"
    m.atomic_private(root / "result.json", (json.dumps(result, indent=2) + "\n").encode())
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
