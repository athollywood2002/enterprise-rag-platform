"""Endpoint-independent identities and explicit, verified legacy registration.

This module never calls a model or writes to Qdrant. Legacy provenance must come
from independently verified saved inputs, not from the backend being adopted.
"""

import hashlib
import json
import math
import re

from .collection_safety import validate_writable_collection_name
from .folder_parser import DocumentError

SIGNATURE_FIELDS = {"parser", "model", "digest", "chunk_size", "overlap", "format", "destination"}
DOCUMENT_FIELDS = (
    "id",
    "source",
    "path",
    "content_hash",
    "fingerprint",
    "revision",
    "collection",
    "points",
    "indexed",
)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def checksum(value):
    return hashlib.sha256(encode(value)).hexdigest()


def fingerprint(signature):
    return checksum({"identity_version": 2, **signature})


def collection_name(signature, fp):
    return validate_writable_collection_name(signature["destination"][:100] + "_ui_" + fp[:16])


def legacy_identity(signature):
    # Match the original serialization exactly, including spaces and database.
    fp = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    return fp, collection_name(signature, fp)


def invalid(message):
    raise DocumentError("index_compatibility", message)


def validate_signature(signature):
    if not isinstance(signature, dict) or set(signature) != SIGNATURE_FIELDS:
        invalid("Incomplete parser/model/chunking identity; no metadata changed.")
    if any(
        not isinstance(signature[k], str) or not signature[k]
        for k in ("parser", "model", "digest", "destination")
    ):
        invalid("Missing parser/model identity; no metadata changed.")
    if any(type(signature[k]) is not int for k in ("chunk_size", "overlap", "format")):
        invalid("Invalid chunking identity; no metadata changed.")
    if not (signature["chunk_size"] > signature["overlap"] >= 0 and signature["format"] > 0):
        invalid("Invalid chunking identity; no metadata changed.")
    validate_writable_collection_name(signature["destination"])


def parse_provenance(raw, expected_sha256):
    if (
        not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or "")
        or hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        invalid("Saved provenance checksum mismatch; no metadata changed.")
    try:
        proof = json.loads(raw)
        if (
            set(proof) != {"schema", "legacy_signature", "documents", "points"}
            or proof["schema"] != 1
        ):
            invalid("Unsupported legacy provenance; no metadata changed.")
        legacy = proof["legacy_signature"]
        if (
            set(legacy) != SIGNATURE_FIELDS | {"database"}
            or not isinstance(legacy["database"], str)
            or not legacy["database"]
        ):
            invalid("Original endpoint and full legacy identity are required.")
        signature = {k: v for k, v in legacy.items() if k != "database"}
        validate_signature(signature)
        old_fp, collection = legacy_identity(legacy)
        docs = proof["documents"]
        if (
            not isinstance(docs, list)
            or not docs
            or any(set(d) != set(DOCUMENT_FIELDS) for d in docs)
        ):
            invalid("Saved document provenance is missing or incomplete.")
        seen_docs, seen_revisions, memberships = set(), set(), {}
        for doc in docs:
            if (
                doc["id"] in seen_docs
                or doc["revision"] in seen_revisions
                or not doc["id"]
                or not doc["revision"]
            ):
                invalid("Duplicate or empty saved document/revision identity.")
            seen_docs.add(doc["id"])
            seen_revisions.add(doc["revision"])
            if doc["fingerprint"] != old_fp or doc["collection"] != collection:
                invalid("Saved legacy fingerprint or collection does not reproduce.")
            ids = json.loads(doc["points"])
            if not isinstance(ids, list) or not ids:
                invalid("Saved point memberships are empty.")
            for pid in ids:
                if not isinstance(pid, str) or not pid or pid in memberships:
                    invalid("Duplicate or invalid saved point identity.")
                memberships[pid] = (doc["id"], doc["revision"])
        points = proof["points"]
        if not isinstance(points, list) or len(points) != len(memberships):
            invalid("Saved points do not cover the registered documents.")
        seen = set()
        for point in points:
            if set(point) != {"id", "document_id", "revision", "payload_sha256", "vector_sha256"}:
                invalid("Full saved payload and vector hashes are required.")
            pid = point["id"]
            if pid in seen or memberships.get(pid) != (point["document_id"], point["revision"]):
                invalid("Saved point/document/revision bindings do not match.")
            seen.add(pid)
            if any(
                not re.fullmatch(r"[0-9a-f]{64}", point[k])
                for k in ("payload_sha256", "vector_sha256")
            ):
                invalid("Invalid saved payload or vector checksum.")
    except DocumentError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        invalid("Malformed legacy provenance; no metadata changed.")
    return proof, signature, old_fp, collection


def registered_context(db, signature):
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='index_contexts'"
    ).fetchone():
        return None
    row = db.execute(
        "SELECT * FROM index_contexts WHERE identity=?", (fingerprint(signature),)
    ).fetchone()
    if row is None:
        return None
    row = dict(row)
    _proof, saved, fp, collection = parse_provenance(
        row["provenance"].encode(), row["provenance_sha256"]
    )
    if saved != signature or fp != row["fingerprint"] or collection != row["collection"]:
        invalid("Registered legacy identity is corrupt; restore the registry backup.")
    return row


def verify_documents(db, documents):
    for doc in documents:
        revisions = db.execute(
            "SELECT * FROM revisions WHERE doc_id=? AND state='active'", (doc["id"],)
        ).fetchall()
        if len(revisions) != 1:
            invalid("Registered document must have exactly one active revision.")
        revision = revisions[0]
        if (revision["id"], revision["collection"], revision["points"]) != (
            doc["revision"],
            doc["collection"],
            doc["points"],
        ):
            invalid("Active document/revision/collection/point bindings mismatch.")


def verify_backend(client, collection, documents, anchors=()):
    """Read exact registered points; reject absent, duplicate or mismatched data."""
    if any(a.alias_name == collection for a in client.get_aliases().aliases):
        invalid("A managed collection cannot be an alias.")
    if not client.collection_exists(collection):
        invalid("Registered collection is absent from this backend.")
    vectors = client.get_collection(collection).config.params.vectors
    if isinstance(vectors, dict) or vectors is None or vectors.distance != "Cosine":
        invalid("Registered collection must retain its unnamed cosine vector configuration.")
    anchors = {p["id"]: p for p in anchors}
    for doc in documents:
        try:
            ids = json.loads(doc["points"])
        except (ValueError, TypeError):
            invalid("Invalid registered point memberships.")
        if (
            not isinstance(ids, list)
            or not ids
            or any(not isinstance(pid, str) for pid in ids)
            or len(ids) != len(set(ids))
        ):
            invalid("Registered points are empty or duplicated.")
        for start in range(0, len(ids), 128):
            batch = ids[start : start + 128]
            points = client.retrieve(collection, batch, with_payload=True, with_vectors=True)
            if len(points) != len(batch) or {str(p.id) for p in points} != set(batch):
                invalid("Registered points are missing or mismatched on this backend.")
            for point in points:
                vector = point.vector
                if (
                    not isinstance(vector, list)
                    or len(vector) != vectors.size
                    or not vector
                    or any(
                        type(value) not in (int, float) or not math.isfinite(value)
                        for value in vector
                    )
                ):
                    invalid("Stored managed point has a missing or invalid dense vector.")
                payload = point.payload or {}
                if (
                    payload.get("document_id") != doc["id"]
                    or payload.get("revision") != doc["revision"]
                ):
                    invalid("Stored point document/revision binding mismatch.")
                anchor = anchors.get(str(point.id))
                if (
                    anchor
                    and (anchor["document_id"], anchor["revision"]) == (doc["id"], doc["revision"])
                    and (
                        checksum(payload) != anchor["payload_sha256"]
                        or checksum(point.vector) != anchor["vector_sha256"]
                    )
                ):
                    invalid("Stored point payload or vector differs from saved provenance.")


def register_legacy_context(db, client, signature, raw, expected_sha256):
    """Register on a cold working copy inside the caller's SQLite transaction.

    Caller must hold the application process lock, BEGIN IMMEDIATE before this
    function, and commit/rollback afterward. `signature` is independently pinned
    parser/model metadata, not model output. There are no model-server requests.
    """
    if not db.in_transaction:
        invalid("Legacy registration requires an explicit SQLite transaction.")
    validate_signature(signature)
    proof, saved, old_fp, collection = parse_provenance(raw, expected_sha256)
    if saved != signature:
        invalid("Legacy parser/model/chunking/destination identity is incompatible.")
    actual = [
        dict(r)
        for r in db.execute("SELECT * FROM documents WHERE fingerprint=? ORDER BY id", (old_fp,))
    ]
    if actual != sorted(proof["documents"], key=lambda d: d["id"]):
        invalid("Registry differs from saved provenance; no metadata changed.")
    if db.execute(
        "SELECT 1 FROM documents WHERE collection=? AND fingerprint!=?", (collection, old_fp)
    ).fetchone():
        invalid("Collection has conflicting registered identities.")
    if db.execute(
        "SELECT 1 FROM documents WHERE fingerprint=?", (fingerprint(signature),)
    ).fetchone():
        invalid("A native identity already exists; legacy registration would be ambiguous.")
    verify_documents(db, actual)
    verify_backend(client, collection, actual, proof["points"])
    existing = registered_context(db, signature)
    if existing:
        if existing["provenance_sha256"] != expected_sha256:
            invalid("Conflicting legacy registration; preserve and inspect the original metadata.")
        return False
    # Do not use executescript: it can commit an outstanding transaction.
    db.execute("""CREATE TABLE IF NOT EXISTS index_contexts (
        identity TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
        collection TEXT UNIQUE NOT NULL, provenance TEXT NOT NULL,
        provenance_sha256 TEXT NOT NULL)""")
    db.execute(
        "INSERT INTO index_contexts VALUES(?,?,?,?,?)",
        (fingerprint(signature), old_fp, collection, raw.decode(), expected_sha256),
    )
    return True
