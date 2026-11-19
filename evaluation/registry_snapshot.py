"""Read-only SQLite membership of the pinned application's committed selected job."""

import json
import sqlite3
from contextlib import closing

DOCUMENT_FIELDS = ("id", "revision", "fingerprint", "collection")


def committed_registry(db, job_id):
    """Independent expectation from the frozen SQLite authority, including its point memberships."""
    rows = db.execute(
        "SELECT d.id,d.revision,d.fingerprint,d.collection,d.points,r.points AS active_points,"
        "r.state,r.doc_id AS revision_owner,r.collection AS revision_collection FROM documents d "
        "LEFT JOIN revisions r ON r.id=d.revision "
        "WHERE d.id IN (SELECT doc_id FROM files WHERE job_id=?)",
        (job_id,),
    )
    docs, bindings = [], {}
    for row in rows:
        if (row["state"], row["revision_owner"], row["revision_collection"]) != (
            "active",
            row["id"],
            row["collection"],
        ):
            raise ValueError("archived document pointer is not its active revision")
        ids, active_ids = json.loads(row["points"]), json.loads(row["active_points"])
        if not ids or sorted(ids) != sorted(active_ids):
            raise ValueError("archived document and active revision point memberships differ")
        docs.append({key: row[key] for key in DOCUMENT_FIELDS})
        for point_id in ids:
            if point_id in bindings:
                raise ValueError("duplicate archived SQLite point")
            bindings[point_id] = (row["collection"], row["id"], row["revision"])
    return docs, bindings


def verify_registry(path, manifest):
    """Check a running arm's real SQLite authority within one read-only transaction."""
    uri = path.resolve(strict=True).as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        docs, bindings = committed_registry(db, manifest["job_id"])
    expected_docs = {d["id"]: d for d in manifest["documents"]}
    expected_points = {
        p["id"]: (p["collection"], p["document_id"], p["revision"]) for p in manifest["points"]
    }
    if (
        len(expected_docs) != 15
        or len(expected_points) != 138
        or len(manifest["documents"]) != 15
        or len(manifest["points"]) != 138
    ):
        raise ValueError("Expected exactly 15 unique documents and 138 unique points")
    if {d["id"]: d for d in docs} != expected_docs or bindings != expected_points:
        raise ValueError(
            "Real SQLite committed revisions or point memberships differ from the verified snapshot"
        )
    return {"documents": len(docs), "points": len(bindings)}
