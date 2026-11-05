"""Persisted single-instance ingestion with immutable vector revisions.

SQLite is the visibility authority: uncommitted Qdrant points are never queried.
Only one worker/instance may own a data directory. No source deletion semantics.
"""

import fcntl
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from qdrant_client import models

from .collection_safety import validate_writable_collection_name
from .core import RagEngine
from .folder_parser import FORMATS, PARSER_VERSION, DocumentError, chunks_from_pages
from .source_roots import inventory, open_beneath, relative_path

TERMINAL = {"completed", "failed", "skipped", "cancelled"}
ACTIVE = {"parsing", "chunking", "embedding", "indexing"}


def digest(value):
    return hashlib.sha256(value).hexdigest()


class Library:
    def __init__(self, config, engine_factory=RagEngine, start_worker=True):
        self.config = config
        self.engine_factory = engine_factory
        self.engines = {}
        self.engine_lock = threading.Lock()
        self.root = Path(config.ingest_data_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.staging = self.root / "staging"
        self.staging.mkdir(exist_ok=True, mode=0o700)
        self.owner = (self.root / "worker.lock").open("a")
        try:
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.owner.close()
            raise RuntimeError("Ingestion requires one API process per data directory") from None
        self.lock = threading.RLock()
        self.index_lock = threading.RLock()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, mode TEXT, source TEXT, status TEXT,
                    created REAL, cancel INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY, job_id TEXT, path TEXT, size INTEGER, status TEXT,
                    error TEXT DEFAULT '', code TEXT DEFAULT '', done INTEGER DEFAULT 0,
                    total INTEGER DEFAULT 0, doc_id TEXT, revision TEXT,
                    staged INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, source TEXT, path TEXT, content_hash TEXT,
                    fingerprint TEXT, revision TEXT, collection TEXT, points TEXT, indexed REAL);
                CREATE TABLE IF NOT EXISTS revisions (
                    id TEXT PRIMARY KEY, doc_id TEXT, collection TEXT, points TEXT, state TEXT);
                CREATE INDEX IF NOT EXISTS job_files ON files(job_id);
            """)
            # A crash can happen after the visibility transaction. Detect that commit;
            # otherwise require an explicit retry, never infer success from uploaded bytes.
            for row in db.execute(
                "SELECT * FROM files WHERE status IN ('parsing','chunking','embedding','indexing')"
            ).fetchall():
                committed = db.execute(
                    "SELECT 1 FROM documents WHERE id=? AND revision=?",
                    (row["doc_id"], row["revision"]),
                ).fetchone()
                db.execute(
                    "UPDATE files SET status=?,code=?,error=? WHERE id=?",
                    (
                        "completed" if committed else "failed",
                        "" if committed else "interrupted",
                        ""
                        if committed
                        else "Service restarted before this file committed. Retry the file.",
                        row["id"],
                    ),
                )
            db.execute(
                "UPDATE files SET status='failed',code='upload_interrupted',error='Upload was interrupted. Upload this file again.' WHERE status='uploading'"
            )
            # Uncommitted revisions can be removed on a later worker pass, never made visible.
            db.execute("UPDATE revisions SET state='retired' WHERE state='staging'")
        # Metadata can survive an interrupted upload even when its final rename did not.
        with self.db() as db:
            for row in db.execute(
                "SELECT id FROM files WHERE staged=1 AND status='queued'"
            ).fetchall():
                if not (self.staging / row["id"]).is_file():
                    db.execute(
                        "UPDATE files SET staged=0,status='failed',code='staging_missing',error='Staged file is missing. Upload again.' WHERE id=?",
                        (row["id"],),
                    )
        self.refresh_jobs()
        if start_worker:
            self.thread = threading.Thread(target=self.work, name="rag-ingestion", daemon=True)
            self.thread.start()

    @contextmanager
    def db(self):
        with self.lock:
            db = sqlite3.connect(self.root / "library.sqlite3", timeout=10)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            try:
                with db:
                    yield db
            finally:
                db.close()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=5)
        # Never release the process lock while an in-flight worker could still commit.
        if not self.thread or not self.thread.is_alive():
            self.owner.close()

    def public_config(self):
        c = self.config
        return {
            "formats": sorted(FORMATS),
            "roots": sorted(c.ingest_source_roots),
            "destination": c.qdrant_collection
            + " (managed library; isolated from legacy ingestion)",
            "max_files": c.ingest_max_files,
            "max_file_bytes": c.ingest_max_file_bytes,
            "max_batch_bytes": c.ingest_max_batch_bytes,
            "max_pages": c.ingest_max_pages,
            "concurrency": 1,
        }

    def source_root(self, source):
        if source not in self.config.ingest_source_roots:
            raise DocumentError("unknown_root", "Select a configured source root.")
        return self.config.ingest_source_roots[source]

    def preview(self, mode, source, files=None, folder=""):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", source):
            raise DocumentError(
                "source_name",
                "Source name must be 1–64 letters, digits, dots, dashes or underscores.",
            )
        if mode == "server":
            files = inventory(self.source_root(source), folder, self.config.ingest_max_files)
        elif mode != "browser":
            raise DocumentError("mode", "Choose a browser folder or a server folder.")
        files = files or []
        if not files or len(files) > self.config.ingest_max_files:
            raise DocumentError(
                "file_limit", "Select at least one file within the configured file-count limit."
            )
        total = 0
        seen = set()
        results = []
        for entry in files:
            path = relative_path(entry["path"])
            if path in seen:
                raise DocumentError(
                    "duplicate_path", "The selection contains a duplicate relative path."
                )
            seen.add(path)
            size = entry["size"]
            if type(size) is not int or size < 0:
                raise DocumentError("size", "File size must be a nonnegative integer.")
            total += size
            code = ""
            if entry.get("excluded"):
                code = "Symlinks and special files are excluded."
            elif Path(path).suffix.lower() not in FORMATS:
                code = "Unsupported format."
            elif size == 0:
                code = "Empty file."
            elif size > self.config.ingest_max_file_bytes:
                code = "File exceeds the configured size limit."
            results.append({"path": path, "size": size, "eligible": not code, "reason": code})
        if total > self.config.ingest_max_batch_bytes:
            raise DocumentError(
                "batch_limit", "Selection exceeds the batch byte limit. Choose a smaller folder."
            )
        preview = {
            "mode": mode,
            "source": source,
            "files": results,
            "total_size": total,
            "count": len(results),
            "eligible": sum(f["eligible"] for f in results),
            "formats": sorted(FORMATS),
        }
        # Bind job creation to the reviewed inventory, not a later silent rescan.
        # Canonical ordering ignores filesystem/browser enumeration order only.
        reviewed = {
            "mode": mode,
            "source": source,
            "folder": folder if mode == "server" else "",
            "files": sorted(
                [(f["path"], f["size"], f["eligible"]) for f in results], key=lambda f: f[0]
            ),
        }
        preview["preview_digest"] = digest(
            json.dumps(reviewed, sort_keys=True, separators=(",", ":")).encode()
        )
        return preview

    def create(self, mode, source, files=None, folder="", preview_digest=None):
        try:
            preview = self.preview(mode, source, files, folder)
        except DocumentError as error:
            if mode == "server" and preview_digest:
                raise DocumentError(
                    "selection_changed",
                    "Selection changed. Preview the folder again before starting.",
                ) from error
            raise
        if preview_digest != preview["preview_digest"]:
            raise DocumentError(
                "selection_changed", "Selection changed. Preview the folder again before starting."
            )
        job = uuid.uuid4().hex
        with self.db() as db:
            if db.execute("SELECT count(*) FROM jobs").fetchone()[0] >= self.config.ingest_max_jobs:
                raise DocumentError(
                    "job_limit",
                    "Job retention limit reached. Use another data volume or raise INGEST_MAX_JOBS.",
                )
            # Reserve declared bytes for all retained staged files, including pending uploads.
            reserved = db.execute(
                "SELECT coalesce(sum(size),0) FROM files WHERE code!='excluded'"
            ).fetchone()[0]
            if (
                reserved + sum(f["size"] for f in preview["files"] if f["eligible"])
                > self.config.ingest_max_staged_bytes
            ):
                raise DocumentError(
                    "storage_limit",
                    "Staging quota reached. Raise INGEST_MAX_STAGED_BYTES or use a new data volume.",
                )
            db.execute(
                "INSERT INTO jobs(id,mode,source,status,created) VALUES(?,?,?,?,?)",
                (job, mode, source, "uploading" if mode == "browser" else "queued", time.time()),
            )
            for file in preview["files"]:
                identity = digest(f"{mode}:{source}:{file['path']}".encode())
                state = (
                    ("pending" if mode == "browser" else "queued")
                    if file["eligible"]
                    else "skipped"
                )
                db.execute(
                    "INSERT INTO files(id,job_id,path,size,status,error,code,doc_id) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        uuid.uuid4().hex,
                        job,
                        file["path"],
                        file["size"],
                        state,
                        file["reason"],
                        "excluded" if not file["eligible"] else "",
                        identity,
                    ),
                )
        self.wake.set()
        return self.get_job(job)

    def get_job(self, job):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
            if not row:
                raise DocumentError("not_found", "Job was not found.")
            result = dict(row)
            result["files"] = [
                dict(r)
                for r in db.execute("SELECT * FROM files WHERE job_id=? ORDER BY rowid", (job,))
            ]
        counts = {"successful": 0, "failed": 0, "skipped": 0, "cancelled": 0, "pending": 0}
        for f in result["files"]:
            key = {
                "completed": "successful",
                "failed": "failed",
                "skipped": "skipped",
                "cancelled": "cancelled",
            }.get(f["status"], "pending")
            counts[key] += 1
        result["counts"] = counts
        return result

    def list_jobs(self):
        with self.db() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM jobs ORDER BY created DESC LIMIT 100")]
        return [self.get_job(i) for i in ids]

    def begin_upload(self, job, file_id):
        with self.db() as db:
            row = db.execute(
                "SELECT files.*,jobs.mode,jobs.cancel FROM files JOIN jobs ON jobs.id=files.job_id WHERE files.id=? AND job_id=?",
                (file_id, job),
            ).fetchone()
            if (
                not row
                or row["mode"] != "browser"
                or row["cancel"]
                or row["status"] not in {"pending", "failed", "cancelled"}
                or row["staged"]
            ):
                raise DocumentError(
                    "upload_state", "This file cannot be uploaded in its current state."
                )
            db.execute(
                "UPDATE files SET status='uploading',error='',code='' WHERE id=?", (file_id,)
            )
            return dict(row)

    def finish_upload(self, file_id, path):
        os.replace(path, self.staging / file_id)
        directory = os.open(self.staging, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        with self.db() as db:
            db.execute(
                "UPDATE files SET staged=1,status='queued',error='',code='' WHERE id=?", (file_id,)
            )
        # Start is explicit so the browser can finish staging the entire selection first.

    def start_job(self, job):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
            if not row or row["status"] != "uploading":
                raise DocumentError("job_state", "Job is not waiting for uploads.")
            if db.execute(
                "SELECT 1 FROM files WHERE job_id=? AND status IN ('pending','uploading')", (job,)
            ).fetchone():
                raise DocumentError(
                    "uploads_pending", "Finish staging files before starting ingestion."
                )
            db.execute("UPDATE jobs SET status='queued' WHERE id=?", (job,))
        self.wake.set()
        return self.get_job(job)

    def set_file(self, file_id, state, code="", error="", **values):
        updates = {"status": state, "code": code, "error": error, **values}
        assert set(updates) <= {
            "status",
            "code",
            "error",
            "done",
            "total",
            "revision",
            "attempts",
            "staged",
        }
        with self.db() as db:
            db.execute(
                "UPDATE files SET " + ",".join(k + "=?" for k in updates) + " WHERE id=?",
                (*updates.values(), file_id),
            )

    def cancel(self, job):
        self.get_job(job)
        with self.db() as db:
            db.execute("UPDATE jobs SET cancel=1 WHERE id=?", (job,))
            db.execute(
                "UPDATE files SET status='cancelled',code='cancelled',error='Cancelled before processing.' WHERE job_id=? AND status IN ('pending','queued')",
                (job,),
            )
        self.refresh_jobs()
        return self.get_job(job)

    def retry(self, job):
        with self.db() as db:
            if db.execute(
                "SELECT 1 FROM files WHERE job_id=? AND status IN ('uploading','parsing','chunking','embedding','indexing')",
                (job,),
            ).fetchone():
                raise DocumentError(
                    "job_busy", "Wait for the current operation to finish before retrying."
                )
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
            if not row:
                raise DocumentError("not_found", "Job was not found.")
            db.execute(
                "UPDATE files SET status=CASE WHEN staged=1 OR ?='server' THEN 'queued' ELSE 'pending' END,error='',code='',done=0,total=0 WHERE job_id=? AND status IN ('failed','cancelled')",
                (row["mode"], job),
            )
            pending = db.execute(
                "SELECT 1 FROM files WHERE job_id=? AND status='pending'", (job,)
            ).fetchone()
            db.execute(
                "UPDATE jobs SET status=?,cancel=0 WHERE id=?",
                ("uploading" if pending else "queued", job),
            )
        self.wake.set()
        return self.get_job(job)

    def refresh_jobs(self):
        with self.db() as db:
            for job in db.execute("SELECT * FROM jobs").fetchall():
                states = {
                    r[0]
                    for r in db.execute("SELECT status FROM files WHERE job_id=?", (job["id"],))
                }
                if states & (ACTIVE | {"uploading", "pending", "queued"}):
                    if job["status"] == "uploading":
                        continue
                    status = "running" if states & ACTIVE else "queued"
                else:
                    status = (
                        "cancelled"
                        if "cancelled" in states
                        else "completed_with_errors"
                        if "failed" in states
                        else "completed"
                    )
                db.execute("UPDATE jobs SET status=? WHERE id=?", (status, job["id"]))

    def checkpoint(self, job, deadline):
        if self.stop.is_set():
            raise DocumentError("interrupted", "Service stopped. Retry this file after restart.")
        with self.db() as db:
            cancelled = db.execute("SELECT cancel FROM jobs WHERE id=?", (job,)).fetchone()[0]
        if cancelled:
            raise DocumentError(
                "cancelled", "Cancelled between operations; an in-flight request may have finished."
            )
        if time.monotonic() >= deadline:
            raise DocumentError(
                "processing_limit",
                "File processing time limit reached. Retry after checking model health or adjusting limits.",
            )

    def get_engine(self, config):
        with self.engine_lock:
            if config.qdrant_collection not in self.engines:
                self.engines[config.qdrant_collection] = self.engine_factory(config)
            return self.engines[config.qdrant_collection]

    def model_context(self):
        # Ollama tags identify model bytes, not just mutable names. Fail closed on missing identity.
        base = self.get_engine(self.config)
        with base._client(15) as client:
            response = client.get(self.config.ollama_url.rstrip("/") + "/api/tags")
            response.raise_for_status()
            name = self.config.ollama_embed_model
            name = name if ":" in name else name + ":latest"
            model = next(
                (m for m in response.json()["models"] if m.get("name", m.get("model")) == name),
                None,
            )
        if not model or not isinstance(model.get("digest"), str) or not model["digest"]:
            raise DocumentError(
                "model_identity",
                "Embedding model identity unavailable. Check Ollama and the installed model.",
            )
        signature = {
            "parser": PARSER_VERSION,
            "model": name,
            "digest": model["digest"],
            "chunk_size": 900,
            "overlap": 150,
            "format": 1,
            "destination": self.config.qdrant_collection,
            "database": self.config.qdrant_url,
        }
        fingerprint = digest(json.dumps(signature, sort_keys=True).encode())
        collection = self.config.qdrant_collection[:100] + "_ui_" + fingerprint[:16]
        validate_writable_collection_name(collection)
        return fingerprint, self.get_engine(
            self.config.model_copy(update={"qdrant_collection": collection})
        )

    def parse(self, path, name):
        if sys.platform != "linux":
            raise DocumentError(
                "parser_platform",
                "Resource-isolated ingestion requires Linux. Run the Docker workspace on this platform.",
            )
        output = path.with_suffix(".parsed")
        try:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rag.folder_parser",
                    str(path),
                    name,
                    str(output),
                    str(self.config.ingest_max_pages),
                    str(self.config.ingest_max_chars),
                ],
                timeout=self.config.ingest_parse_seconds,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            result = json.loads(output.read_text(encoding="utf-8"))
            if "error" in result:
                raise DocumentError(result["error"], result["message"])
            return result["pages"]
        except (subprocess.SubprocessError, OSError, ValueError) as error:
            if isinstance(error, DocumentError):
                raise
            raise DocumentError(
                "parser_limit",
                "Parser failed or exceeded its time/memory limit. Check the file or reduce its size.",
            ) from error
        finally:
            output.unlink(missing_ok=True)

    def stage_server(self, row, source):
        target = self.staging / row["id"]
        with open_beneath(self.source_root(source), row["path"]) as fd:
            before = os.fstat(fd)
            if before.st_size != row["size"]:
                raise DocumentError(
                    "source_changed", "Source size changed after preview. Create a fresh selection."
                )
            with target.open("wb") as stream:
                total = 0
                while data := os.read(fd, 64 * 1024):
                    total += len(data)
                    if total > row["size"]:
                        raise DocumentError(
                            "source_changed", "Source changed during staging. Preview it again."
                        )
                    stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            after = os.fstat(fd)
            if total != row["size"] or (before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise DocumentError(
                    "source_changed", "Source changed during staging. Preview it again."
                )
        with self.db() as db:
            db.execute("UPDATE files SET staged=1 WHERE id=?", (row["id"],))

    @staticmethod
    def verify_points(engine, document):
        if not engine.db.collection_exists(document["collection"]):
            return False
        ids = json.loads(document["points"])
        for start in range(0, len(ids), 128):
            found = engine.db.retrieve(
                document["collection"],
                ids[start : start + 128],
                with_payload=True,
                with_vectors=False,
            )
            if len(found) != len(ids[start : start + 128]) or any(
                p.payload.get("revision") != document["revision"] for p in found
            ):
                return False
        return bool(ids)

    def process(self, row):
        file_id, job_id = row["id"], row["job_id"]
        deadline = time.monotonic() + self.config.ingest_file_seconds
        try:
            with self.db() as db:
                job = dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            self.checkpoint(job_id, deadline)
            self.set_file(file_id, "parsing", attempts=row["attempts"] + 1, revision=None)
            if job["mode"] == "server" and not row["staged"]:
                self.stage_server(row, job["source"])
            path = self.staging / file_id
            content_hash = digest(path.read_bytes())
            fingerprint, engine = self.model_context()
            collection = engine.config.qdrant_collection
            with self.db() as db:
                previous = db.execute(
                    "SELECT * FROM documents WHERE id=?", (row["doc_id"],)
                ).fetchone()
                count = db.execute("SELECT count(*) FROM documents").fetchone()[0]
            if not previous and count >= self.config.ingest_max_documents:
                raise DocumentError("document_limit", "Indexed document limit reached.")
            if (
                previous
                and previous["content_hash"] == content_hash
                and previous["fingerprint"] == fingerprint
                and self.verify_points(engine, previous)
            ):
                self.checkpoint(job_id, deadline)
                self.set_file(
                    file_id,
                    "skipped",
                    "unchanged",
                    "Unchanged document; compatible indexed chunks verified.",
                )
                return
            pages = self.parse(path, row["path"])
            self.checkpoint(job_id, deadline)
            self.set_file(file_id, "chunking")
            chunks = chunks_from_pages(pages, max_chunks=self.config.ingest_max_chunks)
            revision = uuid.uuid4().hex
            ids = [
                str(uuid.uuid5(uuid.NAMESPACE_URL, revision + ":" + str(i)))
                for i in range(len(chunks))
            ]
            with self.db() as db:
                db.execute(
                    "INSERT INTO revisions VALUES(?,?,?,?,?)",
                    (revision, row["doc_id"], collection, json.dumps(ids), "staging"),
                )
            self.set_file(file_id, "embedding", revision=revision, total=len(chunks), done=0)
            vectors = []
            for i, chunk in enumerate(chunks):
                self.checkpoint(job_id, deadline)
                vectors.append(engine.embed(chunk["text"]))
                self.set_file(file_id, "embedding", done=i + 1, total=len(chunks))
            self.checkpoint(job_id, deadline)
            self.set_file(file_id, "indexing", done=0)
            engine.ensure_collection(len(vectors[0]))
            source = f"{job['mode']}:{job['source']}/{row['path']}"
            points = [
                models.PointStruct(
                    id=pid,
                    vector=vector,
                    payload={
                        **chunk,
                        "source": source,
                        "document_id": row["doc_id"],
                        "revision": revision,
                    },
                )
                for pid, vector, chunk in zip(ids, vectors, chunks, strict=True)
            ]
            for start in range(0, len(points), 64):
                self.checkpoint(job_id, deadline)
                engine._assert_writable_target(collection)
                engine.db.upsert(
                    collection_name=collection, points=points[start : start + 64], wait=True
                )
                self.set_file(file_id, "indexing", done=min(start + 64, len(points)))
            if not self.verify_points(
                engine, {"points": json.dumps(ids), "collection": collection, "revision": revision}
            ):
                raise DocumentError(
                    "index_verification",
                    "Indexed chunks could not be verified. Previous revision remains searchable.",
                )
            with self.index_lock:
                current_fingerprint, _ = self.model_context()
                if current_fingerprint != fingerprint:
                    raise DocumentError(
                        "model_changed",
                        "Embedding model changed while processing. Retry with a stable model.",
                    )
                self.checkpoint(job_id, deadline)
                with self.db() as db:
                    if db.execute("SELECT cancel FROM jobs WHERE id=?", (job_id,)).fetchone()[0]:
                        raise DocumentError(
                            "cancelled", "Cancelled before publishing the new revision."
                        )
                    db.execute(
                        "UPDATE revisions SET state='retired' WHERE doc_id=? AND state='active'",
                        (row["doc_id"],),
                    )
                    db.execute("UPDATE revisions SET state='active' WHERE id=?", (revision,))
                    db.execute(
                        "INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            row["doc_id"],
                            f"{job['mode']}:{job['source']}",
                            row["path"],
                            content_hash,
                            fingerprint,
                            revision,
                            collection,
                            json.dumps(ids),
                            time.time(),
                        ),
                    )
                    db.execute(
                        "UPDATE files SET status='completed',done=total,error='',code='' WHERE id=?",
                        (file_id,),
                    )
            # Deletion is after visibility commits. Cleanup failure is explicit and retriable,
            # never roll back a successfully committed usable revision.
            self.cleanup()
        except DocumentError as error:
            self.set_file(
                file_id,
                "cancelled" if error.code == "cancelled" else "failed",
                error.code,
                str(error),
            )
        except Exception:  # noqa: BLE001 - retain safe errors without logging source data
            self.set_file(
                file_id,
                "failed",
                "service_error",
                "Processing failed. Check model/database availability and retry. Any previous committed document is retained.",
            )
        finally:
            with self.db() as db:
                db.execute(
                    "UPDATE revisions SET state='retired' WHERE doc_id=? AND state='staging'",
                    (row["doc_id"],),
                )
            self.refresh_jobs()

    def cleanup(self):
        with self.index_lock:
            with self.db() as db:
                rows = db.execute("SELECT * FROM revisions WHERE state='retired'").fetchall()
            for row in rows:
                try:
                    engine = self.get_engine(
                        self.config.model_copy(update={"qdrant_collection": row["collection"]})
                    )
                    engine._assert_writable_target(row["collection"])
                    if engine.db.collection_exists(row["collection"]):
                        engine.db.delete(
                            row["collection"],
                            models.FilterSelector(
                                filter=models.Filter(
                                    must=[
                                        models.FieldCondition(
                                            key="revision", match=models.MatchValue(value=row["id"])
                                        )
                                    ]
                                )
                            ),
                            wait=True,
                        )
                    with self.db() as db:
                        db.execute(
                            "DELETE FROM revisions WHERE id=? AND state='retired'", (row["id"],)
                        )
                except Exception:  # noqa: BLE001 - retain safe errors without logging source data
                    # Retained as cleanup_pending in the API, never returned by search.
                    return

    def work(self):
        while not self.stop.is_set():
            self.run_once()
            self.wake.wait(0.5)
            self.wake.clear()

    def run_once(self):
        with self.db() as db:
            row = db.execute(
                "SELECT files.* FROM files JOIN jobs ON jobs.id=files.job_id WHERE files.status='queued' AND jobs.status!='uploading' AND jobs.cancel=0 ORDER BY jobs.created,files.rowid LIMIT 1"
            ).fetchone()
        if row:
            self.process(dict(row))
        self.cleanup()
        self.refresh_jobs()

    def documents(self):
        with self.db() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM documents ORDER BY indexed DESC")]
            pending = db.execute("SELECT count(*) FROM revisions WHERE state='retired'").fetchone()[
                0
            ]
        for row in rows:
            row["chunks"] = len(json.loads(row.pop("points")))
        return {"documents": rows, "cleanup_pending": pending}

    def ask(self, question, top_k=5, job_id=None):
        fingerprint, engine = self.model_context()
        with self.index_lock:
            with self.db() as db:
                rows = db.execute(
                    "SELECT id,revision FROM documents WHERE fingerprint=?", (fingerprint,)
                ).fetchall()
                if job_id:
                    allowed = {
                        r[0]
                        for r in db.execute("SELECT doc_id FROM files WHERE job_id=?", (job_id,))
                    }
                    rows = [r for r in rows if r["id"] in allowed]
            if not rows:
                raise DocumentError(
                    "no_documents",
                    "No compatible indexed documents in this selection. Ingest documents first.",
                )
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="revision", match=models.MatchAny(any=[r["revision"] for r in rows])
                    )
                ]
            )
            return engine.ask(question, top_k, query_filter=query_filter)
