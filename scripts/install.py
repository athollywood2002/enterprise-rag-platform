"""Ubuntu-first installer. Standard library only; setup never sends model inference.

One private JSON record is authoritative. Compose inputs are snapshotted before
launch so --stop still works after a source update. Resolved config is never logged
or saved. No shell evaluation of config, global stop, volume deletion or key rotation.
"""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLLAMA_IMAGE = (
    "ollama/ollama:0.40.15@sha256:0e59999e0e8f9fd4e704bd788a89b7e4cad399367fb1365f8c102ac662288761"
)
QDRANT_IMAGE = (
    "qdrant/qdrant:v1.17.0@sha256:f1c7272cdac52b38c1a0e89313922d940ba50afd90d593a1605dbbc214e66ffb"
)
MODELS = ("nomic-embed-text:latest", "qwen3:8b")
DOCKER_DOCS = "https://docs.docker.com/engine/install/ubuntu/"
PERMISSION_DOCS = "https://docs.docker.com/engine/install/linux-postinstall/"
MAX_OUTPUT = 4 * 1024 * 1024


class InstallError(Exception):
    """Only fixed, secret-free messages cross the CLI boundary."""


def need(condition, message):
    if not condition:
        raise InstallError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def private_read(path):
    """Open without following links, then verify owner, type, mode and size."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            need(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_size <= MAX_OUTPUT,
                "Installation files must be owned regular files with mode 0600.",
            )
            return stream.read(MAX_OUTPUT + 1)
    except OSError:
        raise InstallError(
            "Cannot read private installation state; restore its backup, not a new key."
        ) from None


def atomic_private(path, raw):
    """Durable replacement; state writers are serialized by the installation lock."""
    if path.exists() or path.is_symlink():
        private_read(path)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)  # Only our uncommitted write, never installation data.


def durable_root(root):
    root = root.resolve()
    forbidden = ("/tmp", "/var/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
    need(
        not any(root == Path(p) or Path(p) in root.parents for p in forbidden),
        "Move the project to a durable directory, such as ~/rag, before setup.",
    )
    return root


def check_platform():
    need(sys.version_info >= (3, 11), "Python 3.11+ is required.")
    need(
        platform.system() == "Linux" and platform.machine() in ("x86_64", "amd64"),
        "This installer targets Ubuntu x86-64. macOS/ARM are not validated installer targets.",
    )
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        release = {}
    need(
        release.get("ID") == "ubuntu" and release.get("VERSION_ID") in ("22.04", "24.04"),
        "Use Ubuntu 22.04 or 24.04. Other distributions are not validated.",
    )
    if "microsoft" in platform.release().lower():
        print("WSL2 installation is provisional; the Windows browser/upload path is unverified.")


class Runner:
    """Bounded subprocess output stays in memory; never expose raw Docker errors/config."""

    def __init__(self):
        self.env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("COMPOSE_", "RAG_", "OLLAMA_", "INGEST_"))
        }

    def run(self, args, timeout=30, check=True, progress=False):
        # Download progress is opt-in for the fixed `ollama pull` command only.
        # A thread drains progress; all other subprocess output is bounded in memory.
        import threading

        stage = next(
            (
                name
                for name in (
                    "config",
                    "build",
                    "down",
                    "up",
                    "exec",
                    "inspect",
                    "pull",
                    "info",
                    "create",
                    "start",
                )
                if name in args
            ),
            "subprocess",
        )

        output, errors = bytearray(), bytearray()
        overflow = threading.Event()
        last_progress = [0.0]

        def read(pipe, target):
            while chunk := pipe.read(4096):
                if not progress and len(target) + len(chunk) > MAX_OUTPUT // 2:
                    overflow.set()
                    break
                target.extend(chunk)
                if progress:
                    del target[:-65536]  # Bounded tail even for hour-long downloads.
                    percentages = re.findall(rb"\b(\d{1,3})%", chunk)
                    if percentages and time.monotonic() - last_progress[0] >= 1:
                        percent = int(percentages[-1])
                        if percent <= 100:
                            print(f"Model download: {percent}%", file=sys.stderr, flush=True)
                            last_progress[0] = time.monotonic()

        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                env=self.env,
            )
        except FileNotFoundError:
            raise InstallError(
                "Required command is missing; install Docker Engine and Compose v2: " + DOCKER_DOCS
            ) from None
        readers = [
            threading.Thread(target=read, args=(pipe, target), daemon=True)
            for pipe, target in [(process.stdout, output), (process.stderr, errors)]
        ]
        for reader in readers:
            reader.start()
        try:
            deadline = time.monotonic() + timeout
            while process.poll() is None and not overflow.is_set():
                if time.monotonic() >= deadline:
                    raise InstallError(
                        "Command timed out during "
                        + stage
                        + ". State is retained; retry the same setup or use --stop."
                    )
                time.sleep(0.05)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()  # Only this subprocess, not any daemon/service.
                    process.wait(timeout=5)
            for reader in readers:
                reader.join(timeout=5)
            if not any(reader.is_alive() for reader in readers):
                process.stdout.close()
                process.stderr.close()
        need(
            not overflow.is_set() and not any(reader.is_alive() for reader in readers),
            "Command output exceeded its safety bound.",
        )
        text = (output if process.returncode == 0 else output + errors).decode(
            "utf-8", errors="replace"
        )
        if check:
            need(
                process.returncode == 0,
                "Docker command failed during "
                + stage
                + ". Check Docker/network/disk availability; state is retained. Use --status or --stop.",
            )
        return process.returncode, text


def parse_json(raw):
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        raise InstallError(
            "Invalid metadata response; no configuration or identity was changed."
        ) from None


def docker_preflight(runner, *, need_start=True):
    need(shutil.which("docker"), "Docker Engine is missing. Install it first: " + DOCKER_DOCS)
    _, context = runner.run(["docker", "context", "show"])
    _, raw = runner.run(["docker", "context", "inspect", context.strip()])
    contexts = parse_json(raw)
    host = runner.env.get("DOCKER_HOST") or contexts[0]["Endpoints"]["docker"]["Host"]
    need(
        host.startswith("unix://")
        and contexts[0]["Endpoints"]["docker"]["Host"].startswith("unix://")
        and not runner.env.get("DOCKER_TLS_VERIFY"),
        "Remote Docker endpoints are not supported. Run setup on the Docker host, then use SSH forwarding.",
    )
    code, raw = runner.run(["docker", "info", "--format", "{{json .}}"], check=False)
    if code:
        if "permission denied" in raw.lower():
            raise InstallError(
                "Docker access denied. See "
                + PERMISSION_DOCS
                + " Docker-group membership is root-equivalent; consider rootless Docker. Never chmod the socket."
            )
        raise InstallError("Cannot reach the local Docker daemon. Start Docker, then rerun setup.")
    info = parse_json(raw)
    need(info.get("OSType") == "linux", "Docker must run Linux containers.")
    code, version = runner.run(["docker", "compose", "version", "--short"], check=False)
    match = re.match(r"v?(\d+)\.", version.strip())
    need(
        code == 0 and match and int(match[1]) >= 2,
        "Docker Compose v2 is required: " + DOCKER_DOCS,
    )
    if not need_start:
        return version.strip()
    for command, flags in [
        ("config", ("--format", "--quiet")),
        ("up", ("--wait", "--wait-timeout", "--no-build", "--pull")),
        ("run", ("--pull", "--no-deps")),
    ]:
        _, help_text = runner.run(["docker", "compose", command, "--help"])
        need(
            all(flag in help_text for flag in flags),
            "Compose lacks required config/wait/pull features. Upgrade Compose v2.",
        )
    return version.strip()


def source_identity(root):
    paths = [
        root / "Dockerfile",
        root / "docker/requirements.lock",
        root / "setup.sh",
        root / "scripts/install.py",
        root / "compose.demo.yaml",
        root / "compose.install.yaml",
        root / "compose.gpu.yaml",
        root / "scripts/demo_smoke.py",
        root / "scripts/library_smoke.py",
    ]
    for directory in ("src", "demo"):
        paths += [
            p
            for p in (root / directory).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        ]
    result = hashlib.sha256()
    for path in sorted(set(paths)):
        need(not path.is_symlink(), "Source symlinks are not supported by this installer.")
        result.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes())
    return result.hexdigest()


def source_revision(root):
    if not (root / ".git").exists():
        return "archive (identified by saved source SHA-256)"
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown (identified by saved source SHA-256)"
    value = result.stdout.decode(errors="replace").strip()
    return (
        value if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", value) else "unknown"
    )


def image_id(runner, image):
    code, raw = runner.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image], check=False
    )
    if code:
        return None
    value = raw.strip()
    need(re.fullmatch(r"sha256:[0-9a-f]{64}", value), "Invalid Docker image identity.")
    return value


def model_digests(value):
    need(
        isinstance(value, dict) and isinstance(value.get("models"), list),
        "Invalid Ollama model metadata.",
    )
    found = {}
    for row in value["models"]:
        need(
            isinstance(row, dict)
            and isinstance(row.get("name"), str)
            and isinstance(row.get("digest"), str)
            and row["digest"],
            "Invalid Ollama model digest.",
        )
        name = row["name"] if ":" in row["name"] else row["name"] + ":latest"
        need(
            name not in found, "Duplicate model metadata; resolve the model identity before setup."
        )
        found[name] = row["digest"]
    return found


def validate_ollama_url(url):
    parsed = urllib.parse.urlsplit(url)
    need(
        parsed.scheme in ("http", "https")
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and not parsed.path.strip("/")
        and not any(c in url for c in "\r\n${}"),
        "Use an HTTP(S) Ollama origin without credentials or path.",
    )
    return url.rstrip("/")


def http_json(url, key=None):
    # Only metadata GET; external redirects/proxies never receive the application key.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    request = urllib.request.Request(url, headers={"x-api-key": key} if key else {})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(
            request, timeout=5
        ) as response:
            raw = response.read(1024 * 1024 + 1)
            need(len(raw) <= 1024 * 1024, "Metadata response too large.")
            return parse_json(raw)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise InstallError(
            "Service metadata unavailable. Check --status; setup has not tested inference."
        ) from None


class Installer:
    ollama_image = OLLAMA_IMAGE
    model_mode = "real"

    def __init__(self, root, runner=None):
        self.root = durable_root(Path(root))
        self.directory = self.root / ".rag-install"
        self.record = self.directory / "state.json"
        self.envfile = self.root / ".env.install"
        self.runner = runner or Runner()
        self.state = None

    @contextlib.contextmanager
    def locked(self, *, create=True):
        need(not self.directory.is_symlink(), "Installation state directory must not be a symlink.")
        if create:
            self.directory.mkdir(mode=0o700, exist_ok=True)
        need(self.directory.is_dir(), "No saved installation. Run setup first.")
        info = self.directory.stat()
        need(
            info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
            "Installation state directory must be owned with mode 0700.",
        )
        fd = os.open(self.directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            need(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600,
                "Invalid installation lock ownership/mode.",
            )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise InstallError(
                    "Another setup command is running for this installation."
                ) from None
            yield
        finally:
            os.close(fd)

    def save(self):
        atomic_private(
            self.record, (json.dumps(self.state, sort_keys=True, indent=2) + "\n").encode()
        )

    def read(self):
        if not self.record.exists() and not self.record.is_symlink():
            need(
                not self.envfile.exists() and not self.envfile.is_symlink(),
                "Installation record missing but key exists. Restore both from backup; no key was regenerated.",
            )
            return None
        value = parse_json(private_read(self.record))
        need(isinstance(value, dict), "Installation record must be an object. Restore its backup.")
        need(
            value.get("schema") == 1
            and value.get("root") == str(self.root)
            and re.fullmatch(r"rag-install-[0-9a-f]{32}", value.get("project", ""))
            and re.fullmatch(r"[A-Za-z0-9_-]{43}", value.get("key", ""))
            and value.get("phase") in ("provisioning", "ready")
            and value.get("mode") in ("managed", "external")
            and value.get("device") in ("pending", "cpu", "nvidia", "external")
            and type(value.get("port")) is int
            and 1024 <= value["port"] <= 65535,
            "Installation state is inconsistent. Restore its backup; do not create a new identity.",
        )
        self.state = value
        return value

    def env_bytes(self):
        return (
            "RAG_API_KEY="
            + self.state["key"]
            + "\nRAG_BIND_IP=127.0.0.1\nRAG_PORT="
            + str(self.state["port"])
            + "\nOLLAMA_URL="
            + self.state["url"]
            + "\nOLLAMA_CHAT_MODEL=qwen3:8b\nOLLAMA_EMBED_MODEL=nomic-embed-text:latest\nRAG_MODEL_MODE=real\n"
        ).encode()

    def ensure_env(self, *, repair=True):
        expected = self.env_bytes()
        if self.envfile.exists() or self.envfile.is_symlink():
            actual = private_read(self.envfile)
            if actual != expected:
                need(
                    self.state.get("env_previous_sha") == sha(actual),
                    "Installation config differs from saved identity. Restore its backup.",
                )
                need(
                    repair,
                    "A saved state update is pending. Resume setup or use --stop; this read-only command makes no repairs.",
                )
                atomic_private(self.envfile, expected)
        else:
            need(
                self.state["phase"] == "provisioning",
                "Saved key configuration is missing. Restore .env.install from backup.",
            )
            need(
                repair,
                "Initial configuration is incomplete. Resume setup; no repair was performed.",
            )
            atomic_private(self.envfile, expected)
        if repair and self.state.pop("env_previous_sha", None):
            self.save()

    def initialize(self, args):
        if (self.root / ".env.demo").exists():
            print("Existing manual demo left untouched; setup uses a new project and volumes.")
        url = args.ollama_url or "http://ollama:11434"
        url = validate_ollama_url(url)
        self.state = {
            "schema": 1,
            "root": str(self.root),
            "project": "rag-install-" + uuid.uuid4().hex,
            "key": secrets.token_urlsafe(32),
            "phase": "provisioning",
            "port": args.port or 18000,
            "mode": "external" if args.ollama_url else "managed",
            "url": url.rstrip("/"),
            "device": "external" if args.ollama_url else "pending",
            "models": {},
            "source": source_identity(self.root),
            "source_revision": source_revision(self.root),
            "api_image": None,
            "snapshots": {},
            "contention_accepted": False,
        }
        self.save()  # Authority exists before the recoverable .env view is written.
        self.ensure_env()

    def base_command(self, files=None):
        command = [
            "docker",
            "compose",
            "--project-directory",
            str(self.root),
            "--env-file",
            str(self.envfile),
            "-p",
            self.state["project"],
        ]
        snapshots = self.state["snapshots"]
        generation = self.state.get("input_directory", "")
        need(re.fullmatch(r"inputs-[0-9a-f]{32}", generation), "Invalid saved Compose generation.")
        parent = self.directory / generation
        need(
            not parent.is_symlink() and parent.is_dir(),
            "Saved Compose generation is missing or a symlink.",
        )
        info = parent.stat()
        need(
            info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
            "Saved Compose generation must be private and owned.",
        )
        order = ("compose.base.yaml", "compose.managed.yaml", "compose.gpu.yaml", "runtime.json")
        need(set(snapshots) <= set(order), "Unexpected saved Compose input.")
        for name in files or [name for name in order if name in snapshots]:
            path = self.directory / generation / name
            need(
                name
                in ("compose.base.yaml", "compose.managed.yaml", "compose.gpu.yaml", "runtime.json")
                and sha(private_read(path)) == snapshots[name],
                "Saved Compose input changed. Restore installation backup before stopping/starting.",
            )
            command += ["-f", str(path)]
        need(bool(snapshots), "No services have been configured yet; no Compose action required.")
        return command

    def compose(self, args, timeout=30, check=True, progress=False):
        return self.runner.run(self.base_command() + args, timeout, check, progress)

    def snapshot(self):
        # Original Compose files (unexpanded placeholders), plus our generated overrides.
        files = {"compose.base.yaml": (self.root / "compose.demo.yaml").read_bytes()}
        if self.state["mode"] == "managed":
            files["compose.managed.yaml"] = (self.root / "compose.install.yaml").read_bytes()
            if self.state["device"] == "nvidia":
                files["compose.gpu.yaml"] = (self.root / "compose.gpu.yaml").read_bytes()
        image = self.state["api_image"] or "enterprise-rag-install:" + self.state["project"]
        runtime = {
            "services": {
                "api": {
                    "image": image,
                    "build": {"context": str(self.root)},
                    "environment": {
                        "OLLAMA_URL": self.state["url"],
                        "RAG_MODEL_MODE": self.model_mode,
                    },
                }
            }
        }
        files["runtime.json"] = json.dumps(runtime).encode()
        # Revisioned snapshot directory updates would need a transaction. Here each
        # config change is staged to new names under a private generation directory.
        generation = self.directory / ("inputs-" + uuid.uuid4().hex)
        generation.mkdir(mode=0o700)
        for name, raw in files.items():
            atomic_private(generation / name, raw)
        self.state["input_directory"] = generation.name
        self.state["snapshots"] = {name: sha(raw) for name, raw in files.items()}
        self.save()

    def validate_config(self):
        self.compose(["config", "--quiet"])
        _, raw = self.compose(["config", "--format", "json"])
        config = parse_json(raw)  # Contains the key. Never save/log the resolved config.
        services = config.get("services", {})
        expected = (
            {"api", "qdrant", "ollama"} if self.state["mode"] == "managed" else {"api", "qdrant"}
        )
        need(set(services) == expected, "Unexpected services in effective Compose configuration.")
        api = services["api"]
        ports = api.get("ports", [])
        need(
            len(ports) == 1
            and ports[0].get("host_ip") == "127.0.0.1"
            and str(ports[0].get("published")) == str(self.state["port"])
            and ports[0].get("target") == 8000,
            "Installer requires exactly one loopback API port mapping.",
        )
        need(
            not services["qdrant"].get("ports") and services["qdrant"]["image"] == QDRANT_IMAGE,
            "Qdrant must be internal and digest-pinned.",
        )
        need(
            api["environment"]["API_KEY"] == self.state["key"]
            and api["environment"]["RAG_MODEL_MODE"] == self.model_mode
            and api["environment"]["OLLAMA_URL"] == self.state["url"],
            "API configuration does not match saved installation.",
        )
        need(
            api["image"]
            == (self.state["api_image"] or "enterprise-rag-install:" + self.state["project"]),
            "API image identity was overridden.",
        )
        volumes = config.get("volumes", {})
        names = {"library-state", "demo-qdrant"} | (
            {"ollama-models"} if "ollama" in services else set()
        )
        need(
            set(volumes) == names
            and all(
                not v.get("external") and v.get("name") == self.state["project"] + "_" + n
                for n, v in volumes.items()
            ),
            "Volumes must belong only to this installation.",
        )
        targets = {"api": ("library-state", "/data"), "qdrant": ("demo-qdrant", "/qdrant/storage")}
        if "ollama" in services:
            targets["ollama"] = ("ollama-models", "/root/.ollama")
        for service, (source, target) in targets.items():
            mounts = services[service].get("volumes", [])
            need(
                len(mounts) == 1
                and mounts[0].get("type") == "volume"
                and mounts[0].get("source") == source
                and mounts[0].get("target") == target,
                "Unexpected volume mount in installation configuration.",
            )
        if "ollama" in services:
            ollama = services["ollama"]
            need(
                ollama["image"] == self.ollama_image and not ollama.get("ports"),
                "Ollama image/port contract mismatch.",
            )
            devices = (
                ollama.get("deploy", {})
                .get("resources", {})
                .get("reservations", {})
                .get("devices", [])
            )
            need(
                bool(devices) == (self.state["device"] == "nvidia"),
                "GPU overlay does not match saved mode.",
            )
            if devices:
                need(
                    len(devices) == 1
                    and devices[0].get("driver") == "nvidia"
                    and devices[0].get("count") in ("all", -1)
                    and devices[0].get("capabilities") == ["gpu"],
                    "Unexpected GPU device reservation.",
                )
        return config

    def check_ownership(self):
        project = self.state["project"]
        _, raw = self.runner.run(
            ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + project]
        )
        ids = raw.split()
        if ids:
            _, raw = self.runner.run(["docker", "inspect", *ids])
            for row in parse_json(raw):
                labels = row["Config"].get("Labels", {})
                need(
                    labels.get("com.docker.compose.project.working_dir") == str(self.root)
                    and labels.get("com.docker.compose.project") == project,
                    "Project name is used by another installation; refusing to adopt or stop it.",
                )
        for suffix in ("library-state", "demo-qdrant", "ollama-models"):
            name = project + "_" + suffix
            code, raw = self.runner.run(["docker", "volume", "inspect", name], check=False)
            if code == 0:
                rows = parse_json(raw)
                need(
                    rows[0].get("Labels", {}).get("com.docker.compose.project") == project,
                    "A volume with this name has different ownership; refusing to adopt it.",
                )

    def check_port(self):
        # Own running API may already hold this port. Other listeners are not adopted.
        _, raw = self.compose(["ps", "-q", "api"])
        if raw.strip():
            return
        try:
            with socket.socket() as probe:
                # A stopped installation can leave TIME_WAIT connections. Bind AND
                # listen with reuse accepts those, but not another active listener.
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(("127.0.0.1", self.state["port"]))
                probe.listen(1)
        except OSError:
            raise InstallError("API port is occupied. Choose another with --port 18001.") from None

    def ensure_image(self, image):
        if image_id(self.runner, image) is None:
            need(
                self.state["phase"] == "provisioning",
                "Saved upstream image is missing. Restore its pinned image explicitly; resume never refreshes images.",
            )
            self.runner.run(["docker", "pull", "--platform", "linux/amd64", image], timeout=900)

    def contention(self):
        if self.state.get("contention_checked"):
            return
        occupied = False
        try:
            http_json("http://127.0.0.1:11434/api/tags")
            occupied = True
        except InstallError:
            pass
        if shutil.which("nvidia-smi"):
            code, text = self.runner.run(
                ["nvidia-smi", "--query-compute-apps=process_name", "--format=csv,noheader"],
                timeout=10,
                check=False,
            )
            occupied |= code == 0 and bool(text.strip())
        if occupied and not self.state["contention_accepted"]:
            print(
                "Another Ollama service or GPU workload may share VRAM. External Ollama is recommended."
            )
            need(
                sys.stdin.isatty(),
                "Contention detected. Rerun interactively to choose managed mode, or use --ollama-url on a new install.",
            )
            need(
                input("Continue with a separate managed Ollama? Type managed: ") == "managed",
                "Managed setup paused. No shared service was changed; see the external-mode guide.",
            )
            self.state["contention_accepted"] = True
        self.state["contention_checked"] = True
        self.save()

    def select_device(self, requested):
        if requested == "cpu":
            print("CPU mode selected. Real-model CPU latency/support has not been validated.")
            return "cpu"
        self.ensure_image(self.ollama_image)
        # A utility-only probe: nvidia-smi is supplied by the NVIDIA container runtime.
        # Never invokes ollama serve, pull, embed or generate.
        code, raw = self.runner.run(
            [
                "docker",
                "create",
                "--pull",
                "never",
                "--network",
                "none",
                "--gpus",
                "all",
                "--entrypoint",
                "/bin/sh",
                self.ollama_image,
                "-c",
                "command -v nvidia-smi >/dev/null || exit 42; nvidia-smi -L",
            ],
            timeout=30,
            check=False,
        )
        if code == 0:
            identifier = raw.strip()
            need(re.fullmatch(r"[0-9a-f]{64}", identifier), "Invalid probe container identity.")
            try:
                code, raw = self.runner.run(
                    ["docker", "start", "--attach", identifier], timeout=30, check=False
                )
            finally:
                # Only the ID returned by our successful create; never a shared service.
                self.runner.run(["docker", "rm", "-f", identifier], timeout=10)
        if code == 0:
            need(
                "GPU " in raw,
                "GPU probe returned no usable device; inspect Docker NVIDIA configuration.",
            )
            return "nvidia"
        unavailable = code == 42 or bool(
            re.search(
                r"could not select device driver.*gpu|no compatible GPUs were found",
                raw,
                re.IGNORECASE,
            )
        )
        need(
            unavailable,
            "GPU probe failed for an unknown/runtime reason; no automatic CPU fallback. Check NVIDIA Container Toolkit.",
        )
        need(
            requested == "auto",
            "NVIDIA was required but Docker cannot access it. Configure NVIDIA Container Toolkit or explicitly select --device cpu.",
        )
        print(
            "WARNING: Docker NVIDIA access unavailable; using CPU. CPU latency remains unvalidated."
        )
        return "cpu"

    def tags(self):
        if self.state["mode"] == "external":
            # Probe from API's network, not from the installer host.
            code = (
                "import urllib.request,json; o=urllib.request.build_opener(urllib.request.ProxyHandler({})); "
                "r=o.open(" + repr(self.state["url"] + "/api/tags") + ",timeout=5); "
                "b=r.read(1048577); assert len(b)<=1048576; print(b.decode())"
            )
            _, raw = self.compose(
                ["run", "--rm", "--no-deps", "--pull", "never", "-T", "api", "python", "-c", code],
                timeout=20,
            )
            return model_digests(parse_json(raw))
        # ollama list lacks a full digest. Read /api/tags from API network with its Python runtime.
        code = (
            "import urllib.request; r=urllib.request.urlopen('http://ollama:11434/api/tags',timeout=5); "
            "b=r.read(1048577); assert len(b)<=1048576; print(b.decode())"
        )
        _, raw = self.compose(
            ["run", "--rm", "--no-deps", "--pull", "never", "-T", "api", "python", "-c", code],
            timeout=20,
        )
        return model_digests(parse_json(raw))

    def wait_tags(self, seconds):
        deadline = time.monotonic() + seconds
        while True:
            try:
                return self.tags()
            except InstallError:
                if time.monotonic() >= deadline:
                    raise InstallError(
                        "Ollama metadata is not ready. Retry setup; completed model downloads are retained."
                    ) from None
                time.sleep(2)

    def provision_models(self, timeout):
        need(
            isinstance(self.state.get("models"), dict),
            "Model identity record is invalid. Restore its backup; --stop remains available.",
        )
        present = self.wait_tags(120)
        for model in MODELS:
            saved = self.state["models"].get(model)
            if saved:
                need(
                    present.get(model) == saved,
                    "Saved model is missing/changed. Restore the model digest or follow deliberate update/reindex guidance.",
                )
                continue
            need(
                self.state["phase"] == "provisioning",
                "Model identity record is incomplete. Restore installation backup.",
            )
            if model not in present:
                need(
                    self.state["mode"] == "managed",
                    "External Ollama is missing a model. Install it deliberately on that server; setup will not pull there.",
                )
                print("Downloading missing model: " + model, flush=True)
                self.compose(
                    ["exec", "-T", "ollama", "ollama", "pull", model],
                    timeout=timeout,
                    progress=True,
                )
                present = self.wait_tags(120)
            need(
                model in present,
                "Download finished without the required model metadata. Rerun setup to resume.",
            )
            self.state["models"][model] = present[model]
            self.save()

    def verify_api_image(self):
        _, raw = self.compose(["ps", "-q", "api"])
        ids = raw.split()
        need(len(ids) == 1, "Exactly one running API is required.")
        _, raw = self.runner.run(["docker", "inspect", "--format", "{{.Image}}", ids[0]])
        need(
            raw.strip() == self.state["api_image"],
            "Running API image differs from saved identity; stop and repair.",
        )

    def start(self, args):
        self.read()
        if self.state is None:
            self.initialize(args)
        elif args.ollama_url:
            url = validate_ollama_url(args.ollama_url)
            if self.state["mode"] == "managed":
                need(
                    self.state["phase"] == "provisioning"
                    and not self.state["api_image"]
                    and not self.state["models"],
                    "Switching an established backend is a migration; see the setup guide.",
                )
                _, running = self.runner.run(
                    [
                        "docker",
                        "ps",
                        "-aq",
                        "--filter",
                        "label=com.docker.compose.project=" + self.state["project"],
                    ]
                )
                need(not running.strip(), "Stop the initial project before choosing external mode.")
                self.state["env_previous_sha"] = sha(self.env_bytes())
                self.state.update(mode="external", device="external", url=url)
                self.save()
            need(
                self.state["mode"] == "external" and url == self.state["url"],
                "Switching an established backend is a migration; see the setup guide.",
            )
        self.ensure_env()
        identity = source_identity(self.root)
        need(
            identity == self.state["source"] or args.rebuild,
            "Source changed. Review the update, then explicitly run --rebuild; --stop remains available.",
        )
        if args.port and args.port != self.state["port"]:
            # Changing port is explicit, atomic state+derived-env repair on resume.
            self.state["env_previous_sha"] = sha(self.env_bytes())
            self.state["port"] = args.port
            self.save()
            self.ensure_env()
        self.snapshot()
        self.validate_config()
        self.check_ownership()
        self.check_port()
        if self.state["mode"] == "managed":
            self.contention()
            requested = args.device or (
                "auto" if self.state["device"] == "pending" else self.state["device"]
            )
            selected = self.select_device(requested)
            self.state["device"] = selected
            self.save()
        else:
            need(not args.device, "Device selection applies only to managed Ollama.")
        self.snapshot()
        self.validate_config()
        self.check_ownership()
        self.check_port()
        if self.state["api_image"]:
            need(
                image_id(self.runner, self.state["api_image"]) == self.state["api_image"]
                or args.rebuild,
                "Saved API image is missing. Restore it or explicitly use --rebuild.",
            )
        if not self.state["api_image"] or args.rebuild:
            # Build under an installation-specific tag, never the shared demo tag.
            previous = self.state["api_image"]
            self.state["api_image"] = None
            self.snapshot()
            try:
                print("Building this installation's API image.", flush=True)
                self.compose(["build", "api"], timeout=1800)
                value = image_id(self.runner, "enterprise-rag-install:" + self.state["project"])
                need(value, "Build produced no image. Retry --rebuild.")
            except InstallError:
                self.state["api_image"] = previous
                self.save()
                raise
            self.state["api_image"] = value
            self.state["api_verified"] = False
            self.state["source"] = identity
            self.state["source_revision"] = source_revision(self.root)
            self.save()
            self.snapshot()
            self.validate_config()
        if self.state.get("api_verified") is not True:
            need(
                self.state["phase"] == "provisioning" or args.rebuild,
                "API image readability was not verified. Explicitly rerun --rebuild.",
            )
            # Runs as Dockerfile USER10001; no inference, credentials or state mounts.
            self.runner.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--pull",
                    "never",
                    "--network",
                    "none",
                    "--entrypoint",
                    "python",
                    self.state["api_image"],
                    "-c",
                    (
                        "from pathlib import Path; assert __import__('os').getuid()==10001; "
                        "files=list(Path('/app/src').rglob('*.py')); assert files; "
                        "[p.read_bytes() for p in files]"
                    ),
                ],
                timeout=30,
            )
            self.state["api_verified"] = True
            self.save()
        need(
            self.state.get("api_verified") is True,
            "API image readability was not verified. Explicitly rerun --rebuild.",
        )
        self.ensure_image(QDRANT_IMAGE)
        if self.state["mode"] == "managed":
            self.ensure_image(self.ollama_image)
        upstream = ["qdrant"] + (["ollama"] if self.state["mode"] == "managed" else [])
        self.compose(
            [
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--wait",
                "--wait-timeout",
                "120",
                *upstream,
            ],
            timeout=150,
        )
        self.provision_models(args.download_timeout)
        self.compose(
            ["up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "120", "api"],
            timeout=150,
        )
        self.verify_api_image()
        url = "http://127.0.0.1:" + str(self.state["port"])
        http_json(url + "/health")
        metadata = http_json(url + "/library/readiness", self.state["key"])
        need(
            metadata.get("metadata_ready") is True and metadata.get("inference_tested") is False,
            "Services started but metadata readiness failed. Use --status; no inference was attempted.",
        )
        self.state["phase"] = "ready"
        self.save()
        print("Services ready (metadata only; answer generation is not yet tested).")
        print("Browser: " + url + "\nDevice: " + self.state["device"])
        print("Models: " + ", ".join(MODELS))
        print(
            "Get the application key: bash setup.sh --show-key\nStop, retaining data: bash setup.sh --stop"
        )

    def command(self, args):
        start = not (args.show_key or args.stop or args.status)
        if start:
            check_platform()
            version = docker_preflight(self.runner)
        with self.locked(create=start):
            self.read()
            if args.show_key:
                need(self.state is not None, "No saved installation key. Run setup first.")
                need(
                    sys.stdout.isatty(),
                    "--show-key requires terminal output; redirection is refused.",
                )
                self.ensure_env(repair=False)
                print(self.state["key"])
                return
            if args.stop or args.status:
                need(self.state is not None, "No saved installation. Nothing to stop or inspect.")
                self.ensure_env(repair=args.stop)
                docker_preflight(self.runner, need_start=False)
                if not self.state["snapshots"]:
                    print(
                        "Provisioning has not configured any services; saved identity is retained."
                    )
                    return
                self.check_ownership()
                if args.stop:
                    self.compose(["down", "--timeout", "15"], timeout=90)
                    print("This installation stopped. Configuration and all volumes retained.")
                else:
                    _, raw = self.compose(["ps", "--format", "json"])
                    # Never print raw container/config data, keys or model errors.
                    print(
                        "Installation: "
                        + self.state["project"]
                        + "\nSaved device: "
                        + self.state["device"]
                    )
                    print(
                        "Phase: "
                        + self.state["phase"]
                        + "; running service data available: "
                        + str(bool(raw.strip()))
                    )
                    try:
                        rows = (
                            json.loads(raw)
                            if raw.strip().startswith("[")
                            else [json.loads(line) for line in raw.splitlines() if line.strip()]
                        )
                    except ValueError:
                        rows = []
                    for row in rows:
                        if row.get("Service") in ("api", "qdrant", "ollama"):
                            status = row.get("State")
                            status = (
                                status
                                if status
                                in ("running", "exited", "created", "restarting", "paused")
                                else "unknown"
                            )
                            print(row["Service"] + ": " + status)
                    print("Configured models: " + ", ".join(MODELS))
                    try:
                        ready = http_json(
                            "http://127.0.0.1:" + str(self.state["port"]) + "/library/readiness",
                            self.state["key"],
                        )
                        print(
                            "Metadata ready: "
                            + str(ready.get("metadata_ready") is True)
                            + "; inference not tested by status."
                        )
                    except InstallError:
                        print("Metadata unavailable. No repairs performed.")
                return
            self.start(args)
            print("Compose checked: " + version)


def arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Install/resume the local folder library. Setup never tests inference."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--show-key", action="store_true")
    group.add_argument("--stop", action="store_true")
    group.add_argument("--status", action="store_true")
    parser.add_argument("--device", choices=("auto", "cpu", "nvidia"))
    parser.add_argument("--port", type=int)
    parser.add_argument("--ollama-url")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument(
        "--download-timeout",
        type=int,
        default=3600,
        help="Seconds per initial model pull (default3600).",
    )
    result = parser.parse_args(argv)
    need(result.port is None or 1024 <= result.port <= 65535, "Choose a port between1024 and65535.")
    need(
        60 <= result.download_timeout <= 86400,
        "Download timeout must be between60 and86400 seconds.",
    )
    need(
        not (
            (result.show_key or result.stop or result.status)
            and (result.device or result.port or result.ollama_url or result.rebuild)
        ),
        "Key/status/stop commands cannot change installation options.",
    )
    return result


def main():
    try:
        Installer(ROOT).command(arguments())
    except (InstallError, KeyboardInterrupt) as error:
        print(
            "Setup stopped. "
            + (
                str(error)
                if isinstance(error, InstallError)
                else "Interrupted; saved state/volumes retained. Resume the same setup or use --stop."
            ),
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        print(
            "Setup stopped: inconsistent state or local I/O error. Restore the installation backup; no automatic reset.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
