"""Verify/register legacy provenance on a cold disposable registry copy.

Default is verification with rollback. No model calls or Qdrant writes.
See docs/index-compatibility.md for input provenance and rollback requirements.
"""

import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from qdrant_client import QdrantClient

from rag.index_compatibility import register_legacy_context


def backup_registry(db, path):
    path = Path(path).absolute()
    # Same-directory temporary file plus exclusive link: never replace a backup.
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix="registry-backup-", delete=False
    ) as stream:
        temp = Path(stream.name)
    try:
        with sqlite3.connect(temp) as target:
            db.backup(target)
        with temp.open("rb") as stream:
            os.fsync(stream.fileno())
        os.link(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temp.unlink(missing_ok=True)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None, *, client_factory=QdrantClient):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--working-copy", type=Path, required=True, help="Cold disposable data directory"
    )
    parser.add_argument(
        "--qdrant-url", required=True, help="Restored disposable backend, read operations only"
    )
    parser.add_argument(
        "--identity",
        type=Path,
        required=True,
        help="Independently pinned compatible parser/model/chunking identity JSON",
    )
    parser.add_argument("--identity-sha256", required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--provenance-sha256", required=True)
    parser.add_argument(
        "--apply", action="store_true", help="Commit registry metadata after verification"
    )
    parser.add_argument("--backup", type=Path, help="New backup file, required with --apply")
    args = parser.parse_args(argv)
    if args.apply and not args.backup:
        parser.error("--apply requires a new --backup path")
    identity = args.identity.read_bytes()
    if hashlib.sha256(identity).hexdigest() != args.identity_sha256:
        parser.error("Independently pinned identity checksum mismatch")
    signature = json.loads(identity)
    raw = args.provenance.read_bytes()
    root = args.working_copy.resolve(strict=True)
    registry = root / "library.sqlite3"
    if not registry.is_file() or registry.is_symlink():
        parser.error("Working copy must contain a regular library.sqlite3")
    # Do not construct Library: its normal startup recovery changes other state.
    with (root / "worker.lock").open("a") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        db = sqlite3.connect(registry.as_uri() + "?mode=rw", uri=True, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        client = client_factory(url=args.qdrant_url, timeout=30)
        try:

            def attempt():
                db.execute("BEGIN IMMEDIATE")
                return register_legacy_context(db, client, signature, raw, args.provenance_sha256)

            changed = attempt()
            db.rollback()
            result = {"verified": True, "applied": False, "changed": False}
            if args.apply and changed:
                result["backup_sha256"] = backup_registry(db, args.backup)
                result["changed"] = attempt()
                db.commit()
                result["applied"] = True
            return result
        finally:
            db.rollback()
            db.close()
            client.close()


if __name__ == "__main__":
    print(json.dumps(main(), sort_keys=True))
