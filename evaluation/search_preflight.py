"""Read-only selection and existing-vector checks for the pinned managed-library campaign."""

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
from collections import Counter
from contextlib import closing, nullcontext
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import httpx

from evaluation.campaign_resources import ARMS, ResourceStop, bridge_ip
from evaluation.registry_snapshot import DOCUMENT_FIELDS, committed_registry
from rag import folder_parser, library
from rag.config import Settings
from rag.folder_parser import DocumentError
from rag.library import Library

POINT_FIELDS = ("id", "document_id", "revision", "collection", "payload_sha256")
DOCUMENT_COUNT = 15
POINT_COUNT = 138
PINNED_BUILDS = {
    "baseline": "893d88369c9b8ca6123be08b612f690bfad3e6e8",
    "candidate": "9830d2e5bbbf6f8d3593ff6ae0f8f201f2671fc5",
}


def canonical_sha256(payload):
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def point_binding(collection, record):
    payload = record["payload"]
    return {
        "collection": collection,
        "id": record["id"],
        "document_id": payload["document_id"],
        "revision": payload["revision"],
        "payload_sha256": canonical_sha256(payload),
    }


def keyed(rows, fields):
    result = {}
    for row in rows:
        if set(row) != set(fields) or any(
            not isinstance(row[k], str) or not row[k] for k in fields
        ):
            raise ResourceStop("invalid snapshot identity fields")
        if row["id"] in result:
            raise ResourceStop("duplicate identity in snapshot or filtered results")
        result[row["id"]] = row
    return result


def require_same(label, expected, actual):
    missing = expected.keys() - actual.keys()
    extra = actual.keys() - expected.keys()
    changed = sum(expected[k] != actual[k] for k in expected.keys() & actual.keys())
    if missing or extra or changed:
        raise ResourceStop(
            f"{label} mismatch (missing={len(missing)}, extra={len(extra)}, changed={changed})"
        )


def validate_manifest(manifest, job_id):
    if set(manifest) != {"job_id", "documents", "points"} or manifest["job_id"] != job_id:
        raise ResourceStop("snapshot selected job mismatch")
    docs = keyed(manifest["documents"], DOCUMENT_FIELDS)
    points = keyed(manifest["points"], POINT_FIELDS)
    if len(docs) != DOCUMENT_COUNT or len(points) != POINT_COUNT:
        raise ResourceStop("snapshot must contain 15 committed documents and 138 points")
    if len({d["revision"] for d in docs.values()}) != len(docs):
        raise ResourceStop("duplicate committed revision")
    if {p["document_id"] for p in points.values()} != docs.keys():
        raise ResourceStop("snapshot points do not cover the selected documents")
    for point in points.values():
        doc = docs[point["document_id"]]
        if (point["revision"], point["collection"]) != (doc["revision"], doc["collection"]):
            raise ResourceStop("snapshot point binding differs from committed document")
        if not re.fullmatch(r"[0-9a-f]{64}", point["payload_sha256"]):
            raise ResourceStop("invalid snapshot payload digest")
    return docs, points


class SelectionAdapter(Library):
    """Run Library.ask/model_context against read-only rows. Stop at the retrieval boundary."""

    def __init__(self, connection, settings, tags):
        # Library.__init__ owns a writable ingestion registry and performs startup recovery.
        self.connection = connection
        self.config = settings
        self.tags = tags
        self.index_lock = nullcontext()

    def db(self):
        return nullcontext(self.connection)

    def get(self, url):
        if url != self.config.ollama_url.rstrip("/") + "/api/tags":
            raise ResourceStop("selection adapter only permits retained model metadata")
        return httpx.Response(200, json=self.tags, request=httpx.Request("GET", url))

    def get_engine(self, config):
        return SimpleNamespace(
            config=config, _client=lambda timeout: nullcontext(self), ask=self.scope
        )

    @staticmethod
    def scope(question, top_k, *, query_filter, collection_names):
        return query_filter, collection_names


def application_scope(db, config, tags, job_id):
    # Both pinned builds have identical selector/parser bytes. Catch stale editable installs too.
    for module, expected in (
        (library, "853c1a92ed3d34d1af2230f1940af065817f168c6f960a969308c4af7ed07dc9"),
        (folder_parser, "2c987e0100ab8a19dce8843b0777b27cd5832512d590650fa751a83b2976224b"),
    ):
        if hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() != expected:
            raise ResourceStop(
                "selection adapter imported application code outside the pinned builds"
            )
    settings = Settings(_env_file=None, api_key="unused-offline-adapter", **config)
    try:
        query_filter, collections = SelectionAdapter(db, settings, tags).ask("", job_id=job_id)
    except DocumentError as exc:
        raise ResourceStop(f"pinned Library.ask selection rejected job: {exc.code}") from exc
    revisions = set(query_filter.must[0].match.any)
    rows = db.execute(
        "SELECT id, revision, fingerprint, collection FROM documents "
        "WHERE id IN (SELECT doc_id FROM files WHERE job_id=?)",
        (job_id,),
    )
    docs = [
        dict(row)
        for row in rows
        if row["revision"] in revisions and row["collection"] in collections
    ]
    return keyed(docs, DOCUMENT_FIELDS), query_filter.model_dump(mode="json", exclude_none=True)


def registry_scope(listing, job, config, tags, job_id):
    if job["id"] != job_id or any(row["job_id"] != job_id for row in job["files"]):
        raise ResourceStop("API returned a different selected job")
    # These are precisely the columns exposed by the two pinned API routes and read by Library.ask.
    with closing(sqlite3.connect(":memory:")) as db:
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE documents (id PRIMARY KEY, revision, fingerprint, collection)")
        db.execute("CREATE TABLE files (job_id, doc_id)")
        db.executemany(
            "INSERT INTO documents VALUES (:id,:revision,:fingerprint,:collection)",
            listing["documents"],
        )
        db.executemany("INSERT INTO files VALUES (:job_id,:doc_id)", job["files"])
        db.execute("PRAGMA query_only=ON")
        return application_scope(db, config, tags, job_id)


def selection_config(qdrant_url, collection, embed_model):
    return {
        "qdrant_url": qdrant_url,
        "qdrant_collection": collection,
        "ollama_embed_model": embed_model,
    }


async def backend_json(client, method, url, body=None):
    # Only private, inspected model metadata and read-only Qdrant endpoints call this helper.
    async with client.stream(
        method, url, json=body, headers={"Accept-Encoding": "identity"}
    ) as response:
        if response.status_code != 200:
            raise ResourceStop(f"backend HTTP {response.status_code} on {httpx.URL(url).path}")
        data = bytearray()
        async for part in response.aiter_bytes():
            data.extend(part)
            if len(data) > 8 * 1024 * 1024:
                raise ResourceStop("backend preflight response exceeds 8 MiB")
        return json.loads(data)


async def check_collection(client, base, collection, expected, query_filter):
    path = f"{base}/collections/{quote(collection, safe='')}/points"
    seen, cursors, offset = {}, set(), None
    while True:
        body = {
            "filter": query_filter,
            "with_payload": True,
            "with_vector": False,
            "limit": min(64, len(expected) + 1 - len(seen)),
        }
        if offset is not None:
            body["offset"] = offset
        page = (await backend_json(client, "POST", path + "/scroll", body))["result"]
        for record in page["points"]:
            point = point_binding(collection, record)
            if point["id"] in seen or len(seen) >= len(expected):
                raise ResourceStop("duplicate or extra filtered Qdrant point")
            seen[point["id"]] = point
        offset = page["next_page_offset"]
        if offset is None:
            break
        if offset in cursors or not page["points"]:
            raise ResourceStop("filtered Qdrant scroll made no progress")
        cursors.add(offset)
    require_same("eligible Qdrant points and payloads", expected, seen)

    probe_id = min(expected)
    record = (
        await backend_json(
            client,
            "POST",
            path,
            {
                "ids": [probe_id],
                "with_payload": True,
                "with_vector": True,
            },
        )
    )["result"]
    if len(record) != 1 or point_binding(collection, record[0]) != expected[probe_id]:
        raise ResourceStop("stored-vector probe point binding mismatch")
    vector = record[0]["vector"]
    if (
        not isinstance(vector, list)
        or not vector
        or not all(type(v) in (float, int) and math.isfinite(v) for v in vector)
    ):
        raise ResourceStop("probe point has no finite stored dense vector")
    result = (
        await backend_json(
            client,
            "POST",
            path + "/query",
            {
                "query": vector,
                "filter": query_filter,
                "params": {"exact": True},
                "limit": len(expected) + 1,
                "with_payload": True,
                "with_vector": False,
            },
        )
    )["result"]["points"]
    hits = keyed([point_binding(collection, r) for r in result], POINT_FIELDS)
    require_same("stored-vector query under the application revision filter", expected, hits)
    return {
        "collection": collection,
        "eligible_points": len(seen),
        "scroll_bindings_sha256": canonical_sha256(seen),
        "probe_point_id": probe_id,
        "stored_vector_sha256": canonical_sha256(vector),
        "query_bindings_sha256": canonical_sha256(hits),
    }


async def runtime_arm(client, api, settings, listing, job, manifest):
    job_id = settings["job_id"]
    docs, points = validate_manifest(manifest, job_id)
    tags = await backend_json(
        client, "GET", "http://" + bridge_ip(api["ollama_ip"]) + ":11434/api/tags"
    )
    installed = {m.get("name", m.get("model")): m.get("digest") for m in tags["models"]}
    for kind in ("chat", "embed"):
        name = settings[kind + "_model"]
        if installed.get(name if ":" in name else name + ":latest") != settings[kind + "_digest"]:
            raise ResourceStop(f"{kind} model digest mismatch")
    config = selection_config(api["qdrant_url"], api["qdrant_collection"], settings["embed_model"])
    selected, query_filter = registry_scope(listing, job, config, tags, job_id)
    require_same(
        "application-selected documents/revisions/fingerprints/collections", docs, selected
    )
    sizes = Counter(p["document_id"] for p in points.values())
    if any(
        row["chunks"] != sizes[row["id"]] for row in listing["documents"] if row["id"] in selected
    ):
        raise ResourceStop("live document point counts differ from the frozen point memberships")
    base = "http://" + bridge_ip(api["qdrant_ip"]) + ":6333"
    collections = sorted({p["collection"] for p in points.values()})
    probes = []
    for collection in collections:
        expected = {k: p for k, p in points.items() if p["collection"] == collection}
        probes.append(await check_collection(client, base, collection, expected, query_filter))
    return {
        "documents": len(docs),
        "points": len(points),
        "stored_vector_queries": len(collections),
        "selected_documents_sha256": canonical_sha256(selected),
        "revision_filter_sha256": canonical_sha256(query_filter),
        "collection_probes": probes,
    }


def verify_rendered_qdrant_routes(rendered):
    services = rendered["services"]
    if rendered["networks"]["baseline"]["name"] == rendered["networks"]["candidate"]["name"]:
        raise ResourceStop("the two rendered arms require distinct Docker bridges")

    for arm in ARMS:
        api_name, db_name = arm + "-api", arm + "-qdrant"
        api, database = services[api_name], services[db_name]
        members = {
            name: service
            for name, service in services.items()
            if arm in (service.get("networks") or {})
        }
        if (
            set(members) != {api_name, db_name, "ollama"}
            or set(api["networks"]) != {arm}
            or set(database["networks"]) != {arm}
        ):
            raise ResourceStop(f"{arm}: rendered bridge membership differs from the isolated pair")

        providers = set()
        for name, peer in members.items():
            attachment = peer["networks"][arm] or {}
            names = [name, peer.get("container_name") or "", *(attachment.get("aliases") or ())]
            if any(n.rstrip(".").lower() == "qdrant" for n in names):
                providers.add(name)
        for link in api.get("links") or ():
            target, _, alias = link.partition(":")
            if (alias or target).rstrip(".").lower() == "qdrant":
                providers.add(target)

        overrides = [api.get("hostname") or ""]
        overrides.extend(
            re.split(r"[=:]", entry, maxsplit=1)[0] for entry in (api.get("extra_hosts") or ())
        )
        overrides.extend(link.rsplit(":", 1)[-1] for link in (api.get("external_links") or ()))
        db_aliases = (database["networks"][arm] or {}).get("aliases") or ()
        if (
            api["environment"]["QDRANT_URL"] != "http://qdrant:6333"
            or "qdrant" not in db_aliases
            or providers != {db_name}
            or any(n.rstrip(".").lower() == "qdrant" for n in overrides)
        ):
            raise ResourceStop(f"{arm}: rendered qdrant name must resolve only to {db_name}")


def offline_proof(db, capture, rendered, job_id, embed_digest):
    docs, membership = committed_registry(db, job_id)
    docs_by_id = keyed(docs, DOCUMENT_FIELDS)
    selected_points = []
    for record in capture["selected_points"]:
        if record["id"] not in membership:
            raise ResourceStop("extra point in archived selected_points outside SQLite membership")
        # The retained capture supplies the payload. Its independent SQLite owner supplies the collection.
        selected_points.append(point_binding(membership[record["id"]][0], record))
    manifest = {
        "job_id": job_id,
        "documents": sorted(docs, key=lambda d: d["id"]),
        "points": sorted(selected_points, key=lambda p: p["id"]),
    }
    _, expected = validate_manifest(manifest, job_id)
    require_same(
        "SQLite vs archived point/document/revision bindings",
        membership,
        {k: (p["collection"], p["document_id"], p["revision"]) for k, p in expected.items()},
    )
    for arm in ARMS:
        env = rendered["services"][arm + "-api"]["environment"]
        config = selection_config(
            env["QDRANT_URL"], env["QDRANT_COLLECTION"], env["OLLAMA_EMBED_MODEL"]
        )
        name = config["ollama_embed_model"]
        tags = {
            "models": [{"name": name if ":" in name else name + ":latest", "digest": embed_digest}]
        }
        try:
            selected, _ = application_scope(db, config, tags, job_id)
        except ResourceStop as error:
            raise ResourceStop(f"{arm}: {error}") from error
        require_same(arm + " application-selected snapshot", docs_by_id, selected)
    verify_rendered_qdrant_routes(rendered)
    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="Prove selected-job compatibility offline on a verified cold SQLite snapshot."
    )
    parser.add_argument("--sqlite", required=True, type=Path)
    parser.add_argument(
        "--sqlite-sha256", required=True, help="Independently verified retained database hash"
    )
    parser.add_argument(
        "--points",
        required=True,
        type=Path,
        help="Original retained arm runtime-metadata JSON with selected_points records (id and payload)",
    )
    parser.add_argument("--rendered-compose", required=True, type=Path)
    parser.add_argument(
        "--points-sha256", required=True, help="Verified archived point bindings input hash"
    )
    parser.add_argument("--job", required=True)
    parser.add_argument("--embed-digest", required=True)
    parser.add_argument("--output", required=True, type=Path, help="Fresh private directory")
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)

    def write(name, value):
        raw = (json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n").encode()
        with os.fdopen(
            os.open(args.output / name, os.O_EXCL | os.O_CREAT | os.O_WRONLY, 0o600), "wb"
        ) as f:
            f.write(raw)
        return hashlib.sha256(raw).hexdigest()

    evidence = {"question_attempts": 0}
    try:
        if any(Path(str(args.sqlite) + ext).exists() for ext in ("-wal", "-journal")):
            raise ResourceStop(
                "use a verified cold SQLite backup with all transactions checkpointed"
            )
        compose_bytes = args.rendered_compose.read_bytes()
        point_bytes = args.points.read_bytes()
        with args.sqlite.open("rb") as stream:
            sqlite_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        evidence.update(
            sqlite_sha256=sqlite_sha,
            points_input_sha256=hashlib.sha256(point_bytes).hexdigest(),
            rendered_sha256=hashlib.sha256(compose_bytes).hexdigest(),
        )
        if (
            sqlite_sha != args.sqlite_sha256
            or hashlib.sha256(point_bytes).hexdigest() != args.points_sha256
        ):
            raise ResourceStop("retained SQLite or points input hash mismatch")
        with closing(
            sqlite3.connect(
                args.sqlite.resolve(strict=True).as_uri() + "?mode=ro&immutable=1", uri=True
            )
        ) as db:
            db.row_factory = sqlite3.Row
            manifest = offline_proof(
                db,
                json.loads(point_bytes),
                json.loads(compose_bytes),
                args.job,
                args.embed_digest,
            )
        digest = write("selected-snapshot.json", manifest)
        write(
            "offline-proof.json",
            {
                "status": "pass",
                "documents": DOCUMENT_COUNT,
                "points": POINT_COUNT,
                "snapshot_sha256": digest,
                "sqlite_sha256": sqlite_sha,
                "points_input_sha256": args.points_sha256,
                "rendered_sha256": hashlib.sha256(compose_bytes).hexdigest(),
                "document_bindings_sha256": canonical_sha256(
                    keyed(manifest["documents"], DOCUMENT_FIELDS)
                ),
                "point_bindings_sha256": canonical_sha256(keyed(manifest["points"], POINT_FIELDS)),
                "question_attempts": 0,
                "runtime_stored_vector_query": "pending",
            },
        )
    except (ResourceStop, KeyError, TypeError, OSError, ValueError, sqlite3.Error) as error:
        write("offline-proof.json", {**evidence, "status": "failed", "reason": str(error)})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
