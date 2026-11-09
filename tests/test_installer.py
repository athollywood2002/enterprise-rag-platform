"""Offline installer contracts. Fake Docker never starts a service or downloads weights."""

import json
import socket
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import install as m


class Docker:
    def __init__(self):
        self.env = {}
        self.calls = []
        self.images = {m.QDRANT_IMAGE: "sha256:" + "1" * 64, m.OLLAMA_IMAGE: "sha256:" + "2" * 64}
        self.models = {}
        self.owner = None
        self.running = False
        self.builds = 0
        self.gpu = "absent"
        self.remote = False
        self.info_error = None
        self.arch = "amd64"
        self.image_arches = {}

    def config(self):
        state = self.owner.state
        api = {
            "image": state["api_image"] or "enterprise-rag-install:" + state["project"],
            "ports": [{"host_ip": "127.0.0.1", "published": str(state["port"]), "target": 8000}],
            "environment": {
                "API_KEY": state["key"],
                "RAG_MODEL_MODE": "real",
                "OLLAMA_URL": state["url"],
            },
        }
        services = {"api": api, "qdrant": {"image": m.QDRANT_IMAGE}}
        volumes = ["library-state", "demo-qdrant"]
        if state["mode"] == "managed":
            services["ollama"] = {"image": self.owner.ollama_image}
            if state["device"] == "nvidia":
                services["ollama"]["deploy"] = {
                    "resources": {
                        "reservations": {
                            "devices": [
                                {"driver": "nvidia", "count": "all", "capabilities": ["gpu"]}
                            ]
                        }
                    }
                }
            volumes.append("ollama-models")
        targets = {"api": ("library-state", "/data"), "qdrant": ("demo-qdrant", "/qdrant/storage")}
        if "ollama" in services:
            targets["ollama"] = ("ollama-models", "/root/.ollama")
        for service, (source, target) in targets.items():
            services[service]["volumes"] = [{"type": "volume", "source": source, "target": target}]
            services[service]["platform"] = self.owner.docker_platform
        return {
            "services": services,
            "volumes": {n: {"name": state["project"] + "_" + n} for n in volumes},
        }

    def run(self, args, timeout=30, check=True, progress=False):
        self.calls.append(args)
        if args[1:3] == ["context", "show"]:
            return 0, "default"
        if args[1:3] == ["context", "inspect"]:
            return 0, json.dumps(
                [
                    {
                        "Endpoints": {
                            "docker": {
                                "Host": "ssh://remote"
                                if self.remote
                                else "unix:///var/run/docker.sock"
                            }
                        }
                    }
                ]
            )
        if args[1] == "info":
            return (
                (1, self.info_error)
                if self.info_error
                else (0, json.dumps({"OSType": "linux", "Architecture": self.arch}))
            )
        if args[1:3] == ["image", "inspect"]:
            value = self.images.get(args[-1])
            if args[-2] == "{{.Os}}/{{.Architecture}}":
                return (
                    (0, "linux/" + self.image_arches.get(args[-1], self.arch))
                    if value
                    else (1, "No such image")
                )
            return (0, value) if value else (1, "No such image")
        if args[1] == "pull":
            self.images[args[-1]] = "sha256:" + "a" * 64
            self.image_arches[args[-1]] = args[args.index("--platform") + 1].split("/")[1]
            return 0, ""
        if args[1:3] == ["volume", "inspect"]:
            return 1, "No such volume"
        if args[1] == "ps":
            return 0, ""
        if args[1] == "create":
            return (
                (0, "c" * 64)
                if self.gpu == "present"
                else (
                    125,
                    "could not select device driver with capabilities: [[gpu]]"
                    if self.gpu == "absent"
                    else "image/runtime/network failed",
                )
            )
        if args[1] == "start":
            return 0, "GPU 0: test NVIDIA"
        if args[1] == "rm":
            return 0, ""
        if args[1] == "run":
            return 0, ""
        if args[1] == "inspect":
            return 0, self.owner.state["api_image"]
        if args[1] == "compose":
            if "exec" in args and args[-1] == "import platform; print(platform.machine())":
                return 0, "aarch64" if self.arch == "arm64" else "x86_64"
            if args[2:3] == ["version"]:
                return 0, "2.40.3"
            if "--help" in args:
                return 0, "--format --quiet --wait --wait-timeout --no-build --pull --no-deps"
            if "config" in args:
                return 0, json.dumps(self.config()) if "--format" in args else ""
            if "build" in args:
                self.builds += 1
                self.images["enterprise-rag-install:" + self.owner.state["project"]] = (
                    "sha256:" + str(self.builds) * 64
                )
                self.images["sha256:" + str(self.builds) * 64] = "sha256:" + str(self.builds) * 64
                return 0, ""
            if "ps" in args:
                return 0, "container-id" if self.running and getattr(
                    self, "running_project", None
                ) == self.owner.state["project"] else ""
            if "up" in args:
                if args[-1] == "api":
                    self.running = True
                    self.running_project = self.owner.state["project"]
                return 0, ""
            if "down" in args:
                self.running = False
                return 0, ""
            if "pull" in args and "exec" in args:
                self.models[args[-1]] = "digest-" + args[-1]
                return 0, ""
            if "run" in args:
                return 0, json.dumps(
                    {"models": [{"name": n, "digest": d} for n, d in self.models.items()]}
                )
        raise AssertionError("Unexpected Docker call: " + repr(args[:4]))


@pytest.fixture
def installation(tmp_path, monkeypatch):
    # tmp_path is safe for disposable test fixtures ONLY, never real installer state.
    monkeypatch.setattr(m, "durable_root", lambda p: p.resolve())
    monkeypatch.setattr(m, "check_platform", lambda: None)
    monkeypatch.setattr(m.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(m.shutil, "which", lambda name: "/bin/docker" if name == "docker" else None)
    monkeypatch.setattr(m, "source_identity", lambda root: m.sha((root / "source").read_bytes()))

    def metadata(url, key=None):
        if ":11434" in url:
            raise m.InstallError("No native server")
        return {"metadata_ready": True, "inference_tested": False}

    monkeypatch.setattr(m, "http_json", metadata)
    (tmp_path / "source").write_text("source-v1")
    root = Path(__file__).resolve().parents[1]
    for name in ["compose.demo.yaml", "compose.install.yaml", "compose.gpu.yaml"]:
        (tmp_path / name).write_bytes((root / name).read_bytes())
    web = tmp_path / "src/rag/web"
    web.mkdir(parents=True)
    for name in ("index.html", "app.js", "style.css"):
        (web / name).write_bytes((root / "src/rag/web" / name).read_bytes())

    def asset(url, key=None):
        path = {"/": "index.html", "/ui/app.js": "app.js", "/ui/style.css": "style.css"}[
            m.urllib.parse.urlsplit(url).path
        ]
        return (web / path).read_bytes()

    monkeypatch.setattr(m, "http_bytes", asset)
    runner = Docker()
    installer = m.Installer(tmp_path, runner)
    installer.directory.mkdir(mode=0o700)
    monkeypatch.setattr(installer, "check_port", lambda: None)
    runner.owner = installer
    return installer, runner


def test_full_first_install_resume_stop_and_image_identity(installation, capsys):
    installer, docker = installation
    installer.command(m.arguments(["--device", "cpu"]))
    first = dict(installer.state)
    assert first["phase"] == "ready" and docker.builds == 1 and len(first["models"]) == 2
    assert stat.S_IMODE(installer.envfile.stat().st_mode) == 0o600
    assert stat.S_IMODE(installer.record.stat().st_mode) == 0o600
    assert first["key"] not in capsys.readouterr().out
    docker.calls.clear()
    installer.command(m.arguments([]))
    assert installer.state["key"] == first["key"] and installer.state["project"] == first["project"]
    assert installer.state["api_image"] == first["api_image"] and docker.builds == 1
    assert not any("pull" in call and "exec" in call for call in docker.calls)
    assert all(
        "--no-build" in call and "never" in call
        for call in docker.calls
        if "up" in call and "--help" not in call
    )
    (installer.root / "source").write_text("source-v2")
    with pytest.raises(m.InstallError, match="Source changed"):
        installer.command(m.arguments([]))
    installer.command(m.arguments(["--stop"]))
    assert not docker.running and installer.state["key"] == first["key"]
    assert not any("--volumes" in call or "prune" in call for call in docker.calls)


@pytest.mark.parametrize(
    "value,expected",
    [("x86_64", "amd64"), ("amd64", "amd64"), ("aarch64", "arm64"), ("arm64", "arm64")],
)
def test_architecture_aliases(value, expected):
    assert m.normalize_architecture(value) == expected


@pytest.mark.parametrize("value", [None, "armv7l", "riscv64", "linux/arm64", ""])
def test_unsupported_architecture(value):
    with pytest.raises(m.InstallError, match="Unsupported architecture"):
        m.normalize_architecture(value)


def test_arm_install_cpu_platform_and_resume(installation, monkeypatch):
    installer, docker = installation
    monkeypatch.setattr(m.platform, "machine", lambda: "aarch64")
    docker.arch = "arm64"
    # A cached amd64 manifest must be replaced by the native pinned manifest.
    docker.image_arches[m.QDRANT_IMAGE] = "amd64"
    installer.command(m.arguments([]))
    first = dict(installer.state)
    env = installer.envfile.read_bytes()
    assert first["architecture"] == "arm64" and first["device"] == "cpu"
    assert all(s["platform"] == "linux/arm64" for s in docker.config()["services"].values())
    pulls = [c for c in docker.calls if c[1] == "pull"]
    assert pulls == [["docker", "pull", "--platform", "linux/arm64", m.QDRANT_IMAGE]]
    assert not any(c[1] == "create" or "--gpus" in c for c in docker.calls)
    installer.command(m.arguments(["--stop"]))
    installer.command(m.arguments([]))
    assert {k: v for k, v in installer.state.items() if k != "input_directory"} == {
        k: v for k, v in first.items() if k != "input_directory"
    }
    assert installer.envfile.read_bytes() == env
    assert docker.builds == 1


def test_arm_nvidia_rejected_without_gpu_probe(installation, monkeypatch):
    installer, docker = installation
    monkeypatch.setattr(m.platform, "machine", lambda: "arm64")
    docker.arch = "arm64"
    with pytest.raises(m.InstallError, match="CPU mode only"):
        installer.command(m.arguments(["--device", "nvidia"]))
    assert not any(c[1] in ("create", "build", "pull") for c in docker.calls)
    assert docker.builds == 0


def test_daemon_mismatch_refused_before_creating_state(installation):
    installer, docker = installation
    docker.arch = "arm64"
    with pytest.raises(m.InstallError, match="daemon architecture differs"):
        installer.command(m.arguments([]))
    assert not installer.record.exists()


@pytest.mark.parametrize("legacy", [True, False])
def test_incompatible_resume_preserves_identity_and_recovery(
    installation, monkeypatch, capsys, legacy
):
    installer, docker = installation
    installer.command(m.arguments(["--device", "cpu"]))
    if legacy:
        installer.state.pop("architecture")
        installer.save()
    record = installer.record.read_bytes()
    env = installer.envfile.read_bytes()
    monkeypatch.setattr(m.platform, "machine", lambda: "aarch64")
    docker.arch = "arm64"
    docker.calls.clear()
    with pytest.raises(m.InstallError, match="Saved installation architecture"):
        installer.command(m.arguments(["--rebuild"]))
    assert installer.record.read_bytes() == record and installer.envfile.read_bytes() == env
    installer.command(m.arguments(["--status"]))
    assert "Saved architecture:" in capsys.readouterr().out
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    installer.command(m.arguments(["--show-key"]))
    assert installer.state["key"] in capsys.readouterr().out
    installer.command(m.arguments(["--stop"]))
    assert not docker.running
    assert installer.record.read_bytes() == record and installer.envfile.read_bytes() == env
    assert not any(c[1] in ("pull", "run", "create") or "build" in c for c in docker.calls)


def test_legacy_amd64_migration_only_after_source_review(installation):
    installer, docker = installation
    installer.command(m.arguments(["--device", "cpu"]))
    installer.state.pop("architecture")
    installer.save()
    original = dict(installer.state)
    env = installer.envfile.read_bytes()
    (installer.root / "source").write_text("source-v2")
    with pytest.raises(m.InstallError, match="Source changed"):
        installer.command(m.arguments([]))
    assert installer.state == original
    (installer.root / "source").write_text("source-v1")
    installer.command(m.arguments([]))
    assert {k: v for k, v in installer.state.items() if k != "input_directory"} == {
        k: v for k, v in {**original, "architecture": "amd64"}.items() if k != "input_directory"
    }
    assert installer.envfile.read_bytes() == env and docker.builds == 1


def test_saved_image_architecture_mismatch_prevents_rebuild(installation):
    installer, docker = installation
    installer.command(m.arguments(["--device", "cpu"]))
    original = installer.record.read_bytes()
    docker.image_arches[installer.state["api_image"]] = "arm64"
    with pytest.raises(m.InstallError, match="Saved API image architecture"):
        installer.command(m.arguments(["--rebuild"]))
    assert installer.record.read_bytes() == original and docker.builds == 1


def test_api_process_architecture_mismatch(installation, monkeypatch):
    installer, docker = installation
    run = docker.run

    def wrong_process(args, *positional, **kwargs):
        if args[-1] == "import platform; print(platform.machine())":
            return 0, "aarch64"
        return run(args, *positional, **kwargs)

    monkeypatch.setattr(docker, "run", wrong_process)
    with pytest.raises(m.InstallError, match="API process architecture differs"):
        installer.command(m.arguments(["--device", "cpu"]))
    assert installer.state["phase"] == "provisioning"


def test_compose_platform_override_rejected(installation, monkeypatch):
    installer, docker = installation
    config = docker.config

    def override():
        value = config()
        value["services"]["qdrant"]["platform"] = "linux/arm64"
        return value

    monkeypatch.setattr(docker, "config", override)
    with pytest.raises(m.InstallError, match="Every service must use"):
        installer.command(m.arguments(["--device", "cpu"]))
    assert docker.builds == 0


@pytest.mark.parametrize("arch", ["x86_64", "amd64", "aarch64", "arm64"])
def test_linux_platform_guard_accepts_native_aliases(monkeypatch, arch):
    monkeypatch.setattr(m.platform, "system", lambda: "Linux")
    monkeypatch.setattr(m.platform, "machine", lambda: arch)
    monkeypatch.setattr(
        m.platform, "freedesktop_os_release", lambda: {"ID": "ubuntu", "VERSION_ID": "24.04"}
    )
    m.check_platform()


def test_arm_external_mode_native_services_only(installation, monkeypatch):
    installer, docker = installation
    monkeypatch.setattr(m.platform, "machine", lambda: "arm64")
    docker.arch = "arm64"
    docker.models = {name: "digest-" + name for name in m.MODELS}
    installer.command(m.arguments(["--ollama-url", "http://model-host:11434"]))
    services = docker.config()["services"]
    assert set(services) == {"api", "qdrant"}
    assert all(s["platform"] == "linux/arm64" for s in services.values())
    assert installer.state["device"] == "external"
    assert not any("exec" in call and "pull" in call for call in docker.calls)


@pytest.mark.parametrize("stage", ["build", "pull"])
def test_non_native_image_result_is_refused(installation, monkeypatch, stage):
    installer, docker = installation
    original = m.image_platform
    if stage == "pull":
        docker.images.pop(m.QDRANT_IMAGE)

    def wrong_result(runner, image):
        if (stage == "build" and image.startswith("sha256:")) or (
            stage == "pull" and image == m.QDRANT_IMAGE
        ):
            return "linux/arm64"
        return original(runner, image)

    monkeypatch.setattr(m, "image_platform", wrong_result)
    with pytest.raises(m.InstallError, match="non-native API image|Pulled image does not match"):
        installer.command(m.arguments(["--device", "cpu"]))
    assert installer.state["phase"] == "provisioning"


def test_default_platform_environment_is_not_inherited(monkeypatch):
    monkeypatch.setenv("DOCKER_DEFAULT_PLATFORM", "linux/amd64")
    assert "DOCKER_DEFAULT_PLATFORM" not in m.Runner().env


def test_explicit_rebuild_and_missing_image(installation):
    installer, docker = installation
    installer.command(m.arguments(["--device", "cpu"]))
    initial = installer.state["api_image"]
    docker.images.pop(initial)
    with pytest.raises(m.InstallError, match="Saved API image is missing"):
        installer.command(m.arguments([]))
    installer.command(m.arguments(["--rebuild"]))
    assert docker.builds == 2 and installer.state["api_image"] != initial


@pytest.mark.parametrize("change", ["missing", "changed", "record"])
def test_established_model_identity_never_silently_repulled(installation, change):
    installer, docker = installation
    installer.command(m.arguments(["--device", "cpu"]))
    if change == "missing":
        docker.models.pop(m.MODELS[0])
    elif change == "changed":
        docker.models[m.MODELS[0]] = "different"
    else:
        installer.state["models"].pop(m.MODELS[0])
        installer.save()
    docker.calls.clear()
    with pytest.raises(m.InstallError, match="model|Model"):
        installer.command(m.arguments([]))
    assert not any("pull" in call for call in docker.calls if "exec" in call)


def test_partial_model_pull_resumes_only_missing_initial_step(installation, monkeypatch):
    installer, docker = installation
    original = docker.run

    def interrupted(args, *a, **kw):
        if "exec" in args and args[-1] == m.MODELS[1]:
            raise m.InstallError("Interrupted download")
        return original(args, *a, **kw)

    monkeypatch.setattr(docker, "run", interrupted)
    with pytest.raises(m.InstallError, match="Interrupted"):
        installer.command(m.arguments(["--device", "cpu"]))
    installer.read()
    assert (
        set(installer.state["models"]) == {m.MODELS[0]}
        and installer.state["phase"] == "provisioning"
    )
    key = installer.state["key"]
    monkeypatch.setattr(docker, "run", original)
    docker.calls.clear()
    installer.command(m.arguments([]))
    pulls = [call[-1] for call in docker.calls if "exec" in call and "pull" in call]
    assert pulls == [m.MODELS[1]] and installer.state["key"] == key


@pytest.mark.parametrize(
    "device,gpu,expected",
    [("auto", "absent", "cpu"), ("nvidia", "present", "nvidia"), ("cpu", "unknown", "cpu")],
)
def test_gpu_selection(installation, device, gpu, expected):
    installer, docker = installation
    installer.initialize(m.arguments([]))
    docker.gpu = gpu
    assert installer.select_device(device) == expected
    assert not any(
        "serve" in call or "generate" in call or "embed" in call for call in docker.calls
    )
    if gpu == "present":
        assert any(
            call[:3] == ["docker", "rm", "-f"] and call[-1] == "c" * 64 for call in docker.calls
        )


@pytest.mark.parametrize("device,gpu", [("nvidia", "absent"), ("auto", "unknown")])
def test_gpu_required_or_unknown_error_never_silent_fallback(installation, device, gpu):
    installer, docker = installation
    installer.initialize(m.arguments([]))
    docker.gpu = gpu
    with pytest.raises(m.InstallError):
        installer.select_device(device)


def test_remote_daemon_and_docker_permission_are_distinct(installation):
    _, docker = installation
    docker.remote = True
    with pytest.raises(m.InstallError, match="Remote Docker"):
        m.docker_preflight(docker)
    docker.remote = False
    docker.info_error = "permission denied"
    with pytest.raises(m.InstallError, match="root-equivalent"):
        m.docker_preflight(docker)
    docker.info_error = "connection refused"
    with pytest.raises(m.InstallError, match="Start Docker"):
        m.docker_preflight(docker)


def test_key_retrieval_no_docker_no_rotation_and_refuses_redirect(
    installation, monkeypatch, capsys
):
    installer, docker = installation
    installer.initialize(m.arguments([]))
    key = installer.state["key"]
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(m.InstallError, match="redirection"):
        installer.command(m.arguments(["--show-key"]))
    output = []
    monkeypatch.setattr(
        sys, "stdout", SimpleNamespace(isatty=lambda: True, write=output.append, flush=lambda: None)
    )
    installer.command(m.arguments(["--show-key"]))
    assert "".join(output).strip() == key and not docker.calls


@pytest.mark.parametrize("fault", ["symlink", "public", "env-missing", "record-missing"])
def test_private_state_safety(installation, fault):
    installer, _ = installation
    installer.initialize(m.arguments([]))
    installer.state["phase"] = "ready"
    installer.save()
    if fault == "symlink":
        installer.envfile.unlink()
        installer.envfile.symlink_to(installer.record)
    elif fault == "public":
        installer.envfile.chmod(0o644)
    elif fault == "env-missing":
        installer.envfile.unlink()
    else:
        installer.record.unlink()
    with pytest.raises(m.InstallError):
        installer.read()
        installer.ensure_env()


def test_lock_and_snapshot_corruption(installation):
    installer, _ = installation
    with (
        installer.locked(),
        pytest.raises(m.InstallError, match="Another setup"),
        installer.locked(),
    ):
        pass
    installer.command(m.arguments(["--device", "cpu"]))
    path = installer.directory / installer.state["input_directory"] / "runtime.json"
    path.write_text("changed")
    with pytest.raises(m.InstallError, match="Saved Compose input changed"):
        installer.command(m.arguments(["--stop"]))


def test_model_metadata_rejects_missing_digest_and_duplicates():
    for rows in [
        [{"name": "a"}],
        [{"name": "a", "digest": "x"}, {"name": "a:latest", "digest": "x"}],
    ]:
        with pytest.raises(m.InstallError):
            m.model_digests({"models": rows})


@pytest.mark.parametrize(
    "url",
    ["http://user:key@host:11434", "http://host/?key=bad", "file:///x", "http://host/\nBAD=yes"],
)
def test_external_url_rejects_credentials_and_injection(url):
    with pytest.raises(m.InstallError):
        m.validate_ollama_url(url)


def test_port_transition_recovers_after_record_write(installation):
    installer, _ = installation
    installer.command(m.arguments(["--device", "cpu"]))
    key = installer.state["key"]
    installer.state["env_previous_sha"] = m.sha(installer.env_bytes())
    installer.state["port"] = 18002
    installer.save()  # Simulated interruption BEFORE writing .env.install.
    installer.read()
    installer.ensure_env()
    assert b"RAG_PORT=18002" in installer.envfile.read_bytes() and installer.state["key"] == key


def test_runner_metadata_stdout_is_not_polluted_by_stderr():
    runner = m.Runner()
    code, output = runner.run(
        [sys.executable, "-c", "import sys;print('{}');print('progress',file=sys.stderr)"]
    )
    assert code == 0 and json.loads(output) == {}


def test_runner_timeout_and_output_bounds():
    runner = m.Runner()
    with pytest.raises(m.InstallError, match="timed out"):
        runner.run([sys.executable, "-c", "import time;time.sleep(2)"], timeout=0.05)
    with pytest.raises(m.InstallError, match="output exceeded"):
        runner.run([sys.executable, "-c", "print('x'*3000000)"])


def test_model_progress_retains_only_bounded_tail(capsys):
    code, output = m.Runner().run([sys.executable, "-c", "print('50% '*800000)"], progress=True)
    assert code == 0 and len(output.encode()) <= 65536
    assert "50%" in capsys.readouterr().err


def test_temporary_root_is_rejected():
    with pytest.raises(m.InstallError, match="durable"):
        m.durable_root(Path("/tmp/a"))


def test_option_conflicts_and_ports():
    for args in [["--stop", "--rebuild"], ["--port", "80"], ["--status", "--device", "cpu"]]:
        with pytest.raises(m.InstallError):
            m.arguments(args)


@pytest.mark.parametrize("write_number", range(1, 26))
def test_interrupted_durable_writes_resume_without_new_identity(
    installation, monkeypatch, write_number
):
    installer, _ = installation
    original = m.atomic_private
    writes = 0

    def interrupted(path, raw):
        nonlocal writes
        original(path, raw)
        writes += 1
        if writes == write_number:
            raise m.InstallError("Simulated interruption after durable replacement")

    monkeypatch.setattr(m, "atomic_private", interrupted)
    with pytest.raises(m.InstallError, match="Simulated interruption"):
        installer.command(m.arguments(["--device", "cpu"]))
    persisted = json.loads(m.private_read(installer.record))
    monkeypatch.setattr(m, "atomic_private", original)
    installer.command(m.arguments(["--device", "cpu"]))
    assert installer.state["project"] == persisted["project"]
    assert installer.state["key"] == persisted["key"] and installer.state["phase"] == "ready"


def test_external_mode_never_manages_ollama_or_downloads_models(installation):
    installer, docker = installation
    docker.models = {name: "external-" + name for name in m.MODELS}
    installer.command(m.arguments(["--ollama-url", "http://model-host:11434"]))
    assert installer.state["mode"] == "external" and installer.state["device"] == "external"
    assert "compose.managed.yaml" not in installer.state["snapshots"]
    assert not any("exec" in call and "pull" in call for call in docker.calls)
    assert not any("create" in call for call in docker.calls)


def test_noninteractive_contention_requires_owner_choice(installation, monkeypatch):
    installer, docker = installation
    monkeypatch.setattr(m, "http_json", lambda *a, **kw: {"models": []})
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(m.InstallError, match="Contention detected"):
        installer.command(m.arguments(["--device", "cpu"]))
    assert not any("up" in call and "--help" not in call for call in docker.calls)
    assert not any("pull" in call and "exec" in call for call in docker.calls)


def test_occupied_port_rejected_before_build_or_device_probe(installation, monkeypatch):
    installer, docker = installation

    def occupied():
        raise m.InstallError("API port is occupied")

    monkeypatch.setattr(installer, "check_port", occupied)
    with pytest.raises(m.InstallError, match="port is occupied"):
        installer.command(m.arguments([]))
    assert not any(
        "build" in call or "create" in call or "pull" in call
        for call in docker.calls
        if "--help" not in call
    )


def test_missing_docker_reported_before_state_is_created(installation, monkeypatch):
    installer, _ = installation
    monkeypatch.setattr(m.shutil, "which", lambda *a: None)
    with pytest.raises(m.InstallError, match="Docker Engine is missing"):
        installer.command(m.arguments([]))
    assert not installer.record.exists() and not installer.envfile.exists()


def test_status_is_read_only_when_models_missing(installation):
    installer, docker = installation
    installer.command(m.arguments(["--device", "cpu"]))
    saved = installer.record.read_bytes()
    docker.models.clear()
    docker.calls.clear()
    installer.command(m.arguments(["--status"]))
    assert installer.record.read_bytes() == saved
    assert not any(
        "up" in call or "build" in call or "pull" in call
        for call in docker.calls
        if "--help" not in call
    )


def test_independent_installation_build_cannot_retag_first_saved_image(installation):
    first, docker = installation
    first.command(m.arguments(["--device", "cpu"]))
    saved = first.state["api_image"]
    other = first.root / "independent"
    other.mkdir()
    (other / "source").write_text("different-source")
    for name in ["compose.demo.yaml", "compose.install.yaml", "compose.gpu.yaml"]:
        (other / name).write_bytes((first.root / name).read_bytes())
    (other / "src/rag/web").mkdir(parents=True)
    for name in ("index.html", "app.js", "style.css"):
        (other / "src/rag/web" / name).write_bytes((first.root / "src/rag/web" / name).read_bytes())
    second = m.Installer(other, docker)
    docker.owner = second
    second.command(m.arguments(["--device", "cpu"]))
    assert second.state["api_image"] != saved
    docker.owner = first
    docker.images["enterprise-rag-platform:folder-ui-v1"] = "sha256:" + "f" * 64
    first.command(m.arguments([]))
    assert first.state["api_image"] == saved
    assert first.validate_config()["services"]["api"]["image"] == saved


def test_gpu_overlay_order_survives_sorted_json_record(installation):
    installer, _docker = installation
    installer.initialize(m.arguments([]))
    installer.state["device"] = "nvidia"
    installer.snapshot()
    installer.read()
    command = installer.base_command()
    files = [command[i + 1] for i, x in enumerate(command) if x == "-f"]
    assert [Path(x).name for x in files] == [
        "compose.base.yaml",
        "compose.managed.yaml",
        "compose.gpu.yaml",
        "runtime.json",
    ]


def test_foreign_project_is_not_adopted_or_stopped(installation, monkeypatch):
    installer, docker = installation
    installer.initialize(m.arguments([]))
    original = docker.run

    def foreign(args, *a, **kw):
        if args[1] == "ps":
            return 0, "foreign-id"
        if args[1] == "inspect":
            return 0, json.dumps(
                [
                    {
                        "Config": {
                            "Labels": {"com.docker.compose.project.working_dir": "/someone-else"}
                        }
                    }
                ]
            )
        return original(args, *a, **kw)

    monkeypatch.setattr(docker, "run", foreign)
    with pytest.raises(m.InstallError, match="another installation"):
        installer.check_ownership()
    assert not any("down" in call for call in docker.calls)


@pytest.mark.parametrize("fault", ["public-port", "qdrant-port", "external-volume", "host-mount"])
def test_effective_config_rejects_unsafe_overlays(installation, monkeypatch, fault):
    installer, docker = installation
    installer.initialize(m.arguments([]))
    installer.snapshot()
    original = docker.config

    def invalid():
        value = original()
        if fault == "public-port":
            value["services"]["api"]["ports"][0]["host_ip"] = "0.0.0.0"
        elif fault == "qdrant-port":
            value["services"]["qdrant"]["ports"] = [{"target": 6333}]
        elif fault == "external-volume":
            value["volumes"]["library-state"]["external"] = True
        else:
            value["services"]["api"]["volumes"][0]["type"] = "bind"
        return value

    monkeypatch.setattr(docker, "config", invalid)
    with pytest.raises(m.InstallError):
        installer.validate_config()


@pytest.mark.parametrize("version", ["1.29.0", "", "not-a-version"])
def test_absent_or_old_compose_stops_before_install(installation, monkeypatch, version):
    installer, docker = installation
    original = docker.run

    def altered(args, *a, **kw):
        if args[1:3] == ["compose", "version"]:
            return 0, version
        return original(args, *a, **kw)

    monkeypatch.setattr(docker, "run", altered)
    with pytest.raises(m.InstallError, match="Compose v2"):
        installer.command(m.arguments([]))
    assert not installer.record.exists()


def test_status_does_not_repair_an_interrupted_port_update(installation):
    installer, _ = installation
    installer.command(m.arguments(["--device", "cpu"]))
    installer.state["env_previous_sha"] = m.sha(installer.env_bytes())
    installer.state["port"] = 18003
    installer.save()
    record, env = installer.record.read_bytes(), installer.envfile.read_bytes()
    with pytest.raises(m.InstallError, match="read-only"):
        installer.command(m.arguments(["--status"]))
    assert installer.record.read_bytes() == record and installer.envfile.read_bytes() == env


def test_port_probe_rejects_real_active_listener(installation):
    installer, _ = installation
    installer.initialize(m.arguments([]))
    installer.snapshot()
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        installer.state["port"] = listener.getsockname()[1]
        with pytest.raises(m.InstallError, match="port is occupied"):
            m.Installer.check_port(installer)


def test_port_probe_accepts_real_time_wait_in_isolated_process():
    # Only our own ephemeral loopback socket; no database/inference/network service.
    code = """
import errno,socket
from scripts.install import Installer
with socket.socket() as server:
 server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
 server.bind(('127.0.0.1',0));port=server.getsockname()[1];server.listen(1)
 with socket.create_connection(('127.0.0.1',port),timeout=2) as client:
  accepted,_=server.accept();accepted.close();assert client.recv(1)==b''
with socket.socket() as plain:
 try:plain.bind(('127.0.0.1',port))
 except OSError as error:assert error.errno==errno.EADDRINUSE
 else:raise AssertionError('TIME_WAIT not reproduced')
installer=Installer.__new__(Installer);installer.state={'port':port}
installer.compose=lambda *args,**kwargs:(0,'')
installer.check_port()
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, timeout=10, check=False
    )
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.parametrize("version,accepted", [((3, 9), False), ((3, 10), True), ((3, 12), True)])
def test_ubuntu2204_stock_python_floor(monkeypatch, version, accepted):
    monkeypatch.setattr(m.sys, "version_info", version)
    monkeypatch.setattr(m.platform, "system", lambda: "Linux")
    monkeypatch.setattr(m.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        m.platform, "freedesktop_os_release", lambda: {"ID": "ubuntu", "VERSION_ID": "22.04"}
    )
    monkeypatch.setattr(m.platform, "release", lambda: "generic")
    if accepted:
        m.check_platform()
    else:
        with pytest.raises(m.InstallError, match="Python 3.10"):
            m.check_platform()


def test_unreadable_web_asset_never_marks_image_verified_or_starts_services(
    installation, monkeypatch, capsys
):
    installer, docker = installation
    original = docker.run

    def unreadable(args, *a, **kw):
        if args[1] == "run" and args[-1] == m.image_readability_probe():
            assert all(name in args[-1] for name in ["index.html", "app.js", "style.css"])
            assert "chmod" not in args[-1]
            raise m.InstallError("Unreadable web asset")
        return original(args, *a, **kw)

    monkeypatch.setattr(docker, "run", unreadable)
    with pytest.raises(m.InstallError, match="Unreadable"):
        installer.command(m.arguments(["--device", "cpu"]))
    installer.read()
    assert installer.state["api_verified"] is False
    assert not any("up" in call and "--help" not in call for call in docker.calls)
    assert "Services ready" not in capsys.readouterr().out


def test_bad_public_ui_response_prevents_ready_report(installation, monkeypatch, capsys):
    installer, _ = installation
    monkeypatch.setattr(m, "http_bytes", lambda *a, **kw: b"wrong asset")
    with pytest.raises(m.InstallError, match="Browser UI"):
        installer.command(m.arguments(["--device", "cpu"]))
    installer.read()
    assert installer.state["phase"] == "provisioning"
    assert "Services ready" not in capsys.readouterr().out


@pytest.mark.parametrize("mapping", ["old-port", "wrong-address", "correct"])
def test_owned_container_only_excuses_matching_published_port(installation, monkeypatch, mapping):
    installer, _ = installation
    installer.initialize(m.arguments([]))
    installer.snapshot()
    monkeypatch.setattr(installer, "compose", lambda *a, **k: (0, "owned-api"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        installer.state["port"] = port
        inspected = [
            {
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": installer.state["project"],
                        "com.docker.compose.project.working_dir": str(installer.root),
                        "com.docker.compose.service": "api",
                    }
                },
                "State": {"Running": True},
                "NetworkSettings": {
                    "Ports": {
                        "8000/tcp": [
                            {
                                "HostIp": "0.0.0.0" if mapping == "wrong-address" else "127.0.0.1",
                                "HostPort": str(port + 1 if mapping == "old-port" else port),
                            }
                        ]
                    }
                },
            }
        ]
        monkeypatch.setattr(installer.runner, "run", lambda *a, **k: (0, json.dumps(inspected)))
        if mapping == "correct":
            m.Installer.check_port(installer)
        else:
            with pytest.raises(m.InstallError, match="port is occupied"):
                m.Installer.check_port(installer)
