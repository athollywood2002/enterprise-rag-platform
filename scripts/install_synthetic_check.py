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
        origin = "http://127.0.0.1:" + str(installer.state["port"])
        response = page.goto(origin)
        assert response is not None and response.status == 200
        for route, filename in [
            ("/", "index.html"),
            ("/ui/app.js", "app.js"),
            ("/ui/style.css", "style.css"),
        ]:
            asset = page.request.get(origin + route)
            assert asset.status == 200
            assert m.sha(asset.body()) == m.sha(
                (installer.root / "src/rag/web" / filename).read_bytes()
            )

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


def image_asset_regression(installer):
    """A disposable container creates a fixture, drops to UID10001, then probes.

    No mounts, network or model calls. The source checkout/image is not chmodded.
    The negative case has readable Python but an owner-only root-owned HTML asset.
    """
    for readable in (True, False):
        probe = m.image_readability_probe("/tmp/readability-fixture")
        code = (
            "from pathlib import Path; import os; "
            "root=Path('/tmp/readability-fixture'); web=root/'rag/web'; "
            "web.mkdir(parents=True); "
            "[(p.chmod(0o755)) for p in (root,root/'rag',web)]; "
            "py=root/'rag/module.py'; py.write_text('value=1'); py.chmod(0o644); "
            "[(p.write_text('fixture'),p.chmod(0o644)) for p in "
            "[web/name for name in ('index.html','app.js','style.css')]]; "
            f"(web/'index.html').chmod({0o644 if readable else 0o600}); "
            "os.setgroups([]); os.setgid(10001); os.setuid(10001)\n"
            "try:\n"
            f" exec({probe!r})\n"
            "except PermissionError as error:\n"
            " assert str(error.filename).endswith('/index.html')\n"
            " raise SystemExit(42)\n"
        )
        status, _ = installer.runner.run(
            [
                "docker",
                "run",
                "--platform",
                installer.docker_platform,
                "--rm",
                "--pull",
                "never",
                "--network",
                "none",
                "--user",
                "0:0",
                "--cap-drop",
                "ALL",
                "--cap-add",
                "SETUID",
                "--cap-add",
                "SETGID",
                "--entrypoint",
                "python",
                installer.state["api_image"],
                "-c",
                code,
            ],
            timeout=30,
            check=False,
        )
        m.need(
            status == (0 if readable else 42),
            "Real UID10001 web-asset readability regression failed.",
        )


def main():
    root = Path(os.environ["INSTALLER_FIXTURE_DIR"]).resolve()
    m.durable_root(root)
    m.need(not root.exists(), "Synthetic fixture directory must be fresh.")
    root.mkdir(mode=0o700, parents=True)
    source = Path(__file__).resolve().parents[1]
    arch = m.native_architecture()
    requested = os.getenv("EXPECTED_ARCHITECTURE")
    m.need(
        not requested or m.normalize_architecture(requested) == arch,
        "Test runner architecture differs from requested native target; emulation is not validation.",
    )
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
    # Local Docker Desktop development may bypass OS only. Native architecture is
    # still enforced by preflight, image checks, API process checks and this driver.
    if m.platform.system() != "Linux":
        m.check_platform = m.native_architecture
    _, before = installer.runner.run(
        ["docker", "ps", "-a", "--no-trunc", "--format", "{{.ID}} {{.State}} {{.Ports}}"]
    )
    result = {
        "synthetic_only": True,
        "real_model_calls": 0,
        "weights_downloaded": False,
        "host_OS_check_bypassed_only_in_test_driver": m.platform.system() != "Linux",
        "host_architecture": arch,
    }
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    try:
        installer.command(m.arguments(["--device", "cpu", "--port", str(port)]))
        image_asset_regression(installer)
        _, raw = installer.runner.run(["docker", "info", "--format", "{{json .}}"])
        daemon_arch = m.normalize_architecture(m.parse_json(raw)["Architecture"])
        m.need(
            daemon_arch == arch,
            "Native test requires host and Docker daemon architecture agreement.",
        )
        result["docker_architecture"] = daemon_arch
        result["images"] = {}
        for service in ("api", "qdrant", "ollama"):
            _, identifier = installer.compose(["ps", "-q", service])
            _, image = installer.runner.run(
                ["docker", "inspect", "--format", "{{.Image}}", identifier.strip()]
            )
            platform = m.image_platform(installer.runner, image.strip())
            m.need(platform == "linux/" + arch, "Test service image is not native to runner.")
            result["images"][service] = {"id": image.strip(), "platform": platform}
        _, process_arch = installer.compose(
            ["exec", "-T", "api", "python", "-c", "import platform; print(platform.machine())"]
        )
        m.need(m.normalize_architecture(process_arch.strip()) == arch, "API process is not native.")
        result["api_process_architecture"] = process_arch.strip()
        # Reuse the existing real-container parsing/citation/idempotency smoke.
        _, smoke = installer.compose(
            ["exec", "-T", "api", "python", "scripts/library_smoke.py"], timeout=180
        )
        parsed = m.parse_json(smoke)
        m.need(
            parsed.get("result") == "PASS" and parsed.get("formats") == ["txt", "csv", "text-pdf"],
            "Native real-container parser/citation smoke failed.",
        )
        result["container_parser_smoke"] = {
            "result": parsed["result"],
            "formats": parsed["formats"],
        }
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
            real_UID10001_readable_and_unreadable_web_asset=True,
            public_UI_entry_and_asset_requests_verified=True,
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
