"""Repository-supported synthetic evaluation entry point; live execution is blocked."""

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit

from evaluation.smoke import fixture_identity, offline_http_smoke
from rag.collection_safety import validate_writable_collection_name


def local_plan(config: dict) -> dict:
    required = {
        "machine",
        "api_url",
        "collection",
        "embed_model",
        "embed_digest",
        "chat_model",
        "chat_digest",
    }
    if set(config) != required or any(
        not isinstance(v, str) or not v or v.strip() != v for v in config.values()
    ):
        raise ValueError("Local plan requires exactly the documented string fields; no credentials")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", config["machine"]):
        raise ValueError("Machine must be an explicit safe label")
    if not re.fullmatch(r"http://(?:127\.0\.0\.1|\[::1\]):[0-9]{1,5}/?", config["api_url"]):
        raise ValueError("Local API plan requires a numeric-loopback HTTP URL and explicit port")
    url = urlsplit(config["api_url"])
    if (
        url.scheme != "http"
        or url.hostname not in ("127.0.0.1", "::1")
        or not url.port
        or url.username
        or url.password
        or url.path not in ("", "/")
        or url.query
        or url.fragment
    ):
        raise ValueError(
            "Local API plan requires an explicit numeric-loopback HTTP port, no credentials/path/query"
        )
    validate_writable_collection_name(config["collection"])
    if not re.fullmatch(r"rag_eval_http_[a-z0-9_]{1,80}", config["collection"]):
        raise ValueError("Plan needs a new dedicated rag_eval_http_ collection")
    for key in ("embed_digest", "chat_digest"):
        if not re.fullmatch(r"[0-9a-f]{64}", config[key]) or int(config[key], 16) == 0:
            raise ValueError("Nonzero 64-hex model artifact digest required")
    for key in ("embed_model", "chat_model"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", config[key]):
            raise ValueError("Invalid model tag")
    return {
        "target": config,
        "execution_allowed": False,
        "collection_absence_verified": False,
        "model_presence_verified": False,
        "planned_limits": {
            "document_uploads": 2,
            "questions": 3,
            "max_embeddings": 9,
            "max_chats": 3,
        },
        "required_gates": [
            "Owner approval naming machine, services, isolated storage/collection and literal commands",
            "Independent command review; validate model/version/resource pins before dispatch",
            "Confirm new collection is absent, not an alias, and API server uses only that target",
            "Real-parser preflight: exact fixture hash, three physical pages and three chunks",
            "Bound wall/request timeouts and calls; fail closed, preserve failures, no retry/cleanup",
            "Human/agent semantic citation and negative review; no automatic quality credit",
        ],
    }


def provenance() -> dict:
    root = Path(__file__).resolve().parents[1]
    files = [
        "evaluation/run.py",
        "evaluation/smoke.py",
        "src/rag/api.py",
        "src/rag/core.py",
        "src/rag/chunking.py",
        "src/rag/documents.py",
        "src/rag/config.py",
        "src/rag/collection_safety.py",
        "pyproject.toml",
    ]
    for name in files:
        if name.startswith("src/rag/"):
            module = import_module(name.removeprefix("src/").removesuffix(".py").replace("/", "."))
            if Path(module.__file__).resolve() != root / name:
                raise ValueError("RAG imports must come from this checkout; use PYTHONPATH=src")
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=5, stderr=subprocess.DEVNULL
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=root, text=True, timeout=5
            )
        )
    except (OSError, subprocess.SubprocessError):
        commit, dirty = None, None
    return {
        "git_commit": commit,
        "worktree_dirty": dirty,
        "code_sha256": hashes,
        "python": platform.python_version(),
        "packages": {
            name: version(name)
            for name in (
                "fastapi",
                "starlette",
                "httpx",
                "qdrant-client",
                "pydantic-settings",
                "pydantic",
                "python-multipart",
            )
        },
    }


def new_output(path: Path) -> Path:
    path = path.absolute()  # Do not resolve away unsafe symlinks.
    if ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Unsafe output path")
    if os.path.lexists(path):
        raise ValueError("Output already exists; never overwrite or resume")
    old_mask = os.umask(0o077)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.mkdir(mode=0o700)
    finally:
        os.umask(old_mask)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline", "local-plan"), default="offline")
    parser.add_argument(
        "--local-config", type=Path, help="Plan-only JSON; never contacted or executed"
    )
    parser.add_argument("--output", type=Path, required=True, help="NEW private result directory")
    args = parser.parse_args(argv)
    if (args.mode == "local-plan") != (args.local_config is not None):
        parser.error("--local-config is required only for --mode local-plan")
    try:
        plan = None
        if args.local_config:
            if args.local_config.stat().st_size > 16384:
                raise ValueError("Local plan is too large")
            config = json.loads(args.local_config.read_text())
            if not isinstance(config, dict):
                raise ValueError("Local plan must be an object")
            plan = local_plan(config)
        code = provenance()
        out = new_output(args.output)
    except (OSError, ValueError) as error:
        parser.error(
            str(error)
            if isinstance(error, ValueError)
            else "Cannot read plan or reserve new output"
        )
    manifest = {
        "schema": "rag-synthetic-evaluation-v1",
        "mode": args.mode,
        "status": "planned-not-executed" if plan else "passed",
        "fixture": fixture_identity(),
        "provenance": code,
        "real_operations": {"network_requests": 0, "model_calls": 0, "database_writes": 0},
        "limitations": [
            "Synthetic smoke, not retrieval/answer-quality metrics or a private-pilot rerun",
            "Not a live/e2e service test; no parser/model/database validation in offline mode",
            "Local mode is plan-only; no live execution implementation in this slice",
        ],
        "result": plan,
    }
    try:
        if plan is None:
            manifest["result"] = offline_http_smoke()
    # CLI boundary: preserve a sanitized failure receipt for any smoke failure.
    # Do not catch interrupts/SystemExit or expose exception messages/payloads.
    except Exception as error:  # noqa: BLE001
        manifest["status"] = "failed"
        manifest["result"] = {
            "error_type": type(error).__name__,
            "detail": "Offline smoke failed; no automatic retry",
        }
    fd = os.open(out / "manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(
        json.dumps({"mode": args.mode, "status": manifest["status"], "artifact": "manifest.json"})
    )
    return 1 if manifest["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
