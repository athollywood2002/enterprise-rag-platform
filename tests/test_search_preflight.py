"""Offline campaign gates. Compose only renders configuration; SQLite and Qdrant are local fixtures."""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import httpx
import pytest
from search_fixture import PREFIX, backend, seed, snapshot
from test_campaign_resources import docker_view as docker_fixture
from test_managed_compare import execute, rewrite_state, rewrite_topology, transport_for
from test_managed_compare import plan_files as plan_fixture

from evaluation import managed_compare as runner
from evaluation import search_preflight as probe

plan_files = plan_fixture
docker_view = docker_fixture

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "evaluation/compose.managed-compare.yaml"


def render(tmp_path, wrong_arm=None, *, override=None):
    command = (
        [shutil.which("docker-compose")]
        if shutil.which("docker-compose")
        else [shutil.which("docker"), "compose"]
    )
    if not command[0]:
        if os.environ.get("GITHUB_ACTIONS") and os.environ.get("RUNNER_OS") == "Linux":
            pytest.fail("Linux CI requires the real Docker Compose renderer")
        pytest.skip("Docker Compose is required only for the render integration checks")
    args = [*command, "-f", str(COMPOSE)]
    if wrong_arm:
        override = {
            "services": {
                wrong_arm + "-api": {
                    "environment": {"QDRANT_URL": f"http://{wrong_arm}-qdrant:6333"}
                }
            }
        }
    if override:
        overlay = tmp_path / "override.json"
        overlay.write_text(json.dumps(override))
        args.extend(["-f", str(overlay)])
    env = {
        **os.environ,
        "COMPOSE_DISABLE_ENV_FILE": "1",
        "RAG_EVAL_CAMPAIGN": "pr36-offline-review",
        "RAG_EVAL_CPUS": "6",
        "RAG_EVAL_BASELINE_IMAGE": "rag-review-baseline:893d883",
        "RAG_EVAL_CANDIDATE_IMAGE": "rag-review-candidate:9830d2e",
        "RAG_EVAL_COLLECTION": PREFIX,
        "RAG_EVAL_BASELINE_KEY": "unused-fixture-baseline",
        "RAG_EVAL_CANDIDATE_KEY": "unused-fixture-candidate",
        "RAG_EVAL_STATE": "/srv/rag-evaluation/state",
        "RAG_EVAL_EVIDENCE": "/srv/rag-evaluation/evidence",
        "RAG_EVAL_RUNNER_CHECKOUT": "/srv/rag-evaluation/runner",
        "RAG_EVAL_BASELINE_PORT": "19001",
        "RAG_EVAL_CANDIDATE_PORT": "19002",
    }
    return subprocess.check_output([*args, "config", "--format", "json"], env=env, timeout=30)


def archived_bindings(data):
    ids = {p["id"] for p in data.manifest["points"]}
    return {
        "selected_points": [
            {"id": p["id"], "payload": p["payload"]} for p in data.records if p["id"] in ids
        ]
    }


@pytest.mark.parametrize("wrong_arm", [None, "baseline", "candidate"])
def test_rendered_env_against_real_selection_and_retained_bytes(tmp_path, wrong_arm):
    data = snapshot()
    rendered = json.loads(render(tmp_path, wrong_arm))
    for arm in runner.ARMS:
        assert set(rendered["services"][arm + "-api"]["networks"]) == {arm}
        assert rendered["services"][arm + "-qdrant"]["networks"][arm]["aliases"] == ["qdrant"]
    archive = tmp_path / "frozen.sqlite"
    with closing(sqlite3.connect(archive)) as db:
        seed(db, data)
    original = hashlib.sha256(archive.read_bytes()).hexdigest()
    with closing(sqlite3.connect(archive.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if wrong_arm:
            assert len(data.listing["documents"]) == 16 and len(data.records) == 149
            with pytest.raises(probe.ResourceStop, match="no_documents"):
                probe.offline_proof(
                    db, archived_bindings(data), rendered, "synthetic-job", "b" * 64
                )
        else:
            actual = probe.offline_proof(
                db, archived_bindings(data), rendered, "synthetic-job", "b" * 64
            )
            docs, points = probe.validate_manifest(actual, "synthetic-job")
            assert docs == {d["id"]: d for d in data.manifest["documents"]}
            assert points == {p["id"]: p for p in data.manifest["points"]}
            assert (len(docs), len(points)) == (15, 138)
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == original


@pytest.mark.parametrize(
    "override,reason",
    [
        ({"services": {"ollama": {"networks": {"baseline": {"aliases": ["qdrant"]}}}}}, "baseline"),
        (
            {"services": {"ollama": {"networks": {"candidate": {"aliases": ["QDRANT"]}}}}},
            "candidate",
        ),
        ({"services": {"ollama": {"container_name": "qdrant"}}}, "baseline"),
        ({"services": {"baseline-api": {"extra_hosts": {"qdrant": "192.0.2.1"}}}}, "baseline"),
        ({"services": {"candidate-api": {"hostname": "qdrant"}}}, "candidate"),
        ({"services": {"candidate-api": {"links": ["ollama:qdrant"]}}}, "candidate"),
        ({"services": {"baseline-api": {"external_links": ["other:qdrant"]}}}, "baseline"),
        ({"networks": {arm: {"name": "same-bridge"} for arm in runner.ARMS}}, "distinct"),
        (
            {"services": {"extra": {"image": "unused:fixture", "networks": ["baseline"]}}},
            "baseline",
        ),
    ],
    ids=[
        "baseline-alias",
        "candidate-alias",
        "container-name",
        "extra-host",
        "api-hostname",
        "link",
        "external-link",
        "same-bridge",
        "extra-member",
    ],
)
def test_archive_proof_rejects_ambiguous_or_shared_rendered_route(tmp_path, override, reason):
    data = snapshot()
    rendered = json.loads(render(tmp_path, override=override))
    with closing(sqlite3.connect(":memory:")) as db:
        seed(db, data)
        with pytest.raises(probe.ResourceStop, match=reason):
            probe.offline_proof(db, archived_bindings(data), rendered, "synthetic-job", "b" * 64)


def test_rendered_link_to_own_database_preserves_expected_route(tmp_path):
    override = {
        "services": {
            "candidate-api": {
                "links": ["candidate-qdrant:qdrant"],
                "extra_hosts": {"unrelated": "192.0.2.1"},
            }
        }
    }
    probe.verify_rendered_qdrant_routes(json.loads(render(tmp_path, override=override)))


@pytest.mark.parametrize("arm", ["baseline", "candidate"])
def test_wrong_rendered_host_fails_before_consumption_or_attempt(tmp_path, plan_files, arm):
    rendered = json.loads(render(tmp_path, arm))
    rewrite_topology(
        plan_files,
        lambda t: t["services"][arm + "-api"].update(
            qdrant_url=rendered["services"][arm + "-api"]["environment"]["QDRANT_URL"]
        ),
    )
    calls, peer_calls = [], []
    assert (
        execute(plan_files, transport_for(plan_files[3], calls), peers=backend(calls=peer_calls))
        == 1
    )
    summary = json.loads((plan_files[2] / "summary.json").read_bytes())
    assert "no_documents" in summary["stop"] and arm in summary["stop"]
    assert len(summary["unattempted"]) == 24 and summary["attempts_including_uncertain"] == []
    assert not summary["authorization_consumed"]
    assert not list(plan_files[2].glob("*.reserved.json"))
    assert not list((tmp_path / "campaign-ledger").glob("*"))
    assert all(q.method == "GET" for q in calls)
    assert all(q.url.path == "/api/tags" or "/points" in q.url.path for q in peer_calls)
    assert json.loads((plan_files[2] / "search-preflight.json").read_bytes())["status"] == "failed"


@pytest.mark.parametrize(
    "kind",
    [
        "missing-revision",
        "wrong-revision",
        "fingerprint",
        "collection",
        "missing-point",
        "wrong-point",
        "binding",
        "payload",
        "vector",
        "filtered-query",
        "extra-point",
        "wrong-job",
    ],
)
def test_same_counts_or_identical_listings_do_not_authorize_wrong_selection(plan_files, kind):
    listing = plan_files[3]
    if kind in {"missing-revision", "wrong-revision", "fingerprint", "collection"}:
        if kind == "missing-revision":
            listing["documents"].pop(0)
        else:
            field = {
                "wrong-revision": "revision",
                "fingerprint": "fingerprint",
                "collection": "collection",
            }[kind]
            listing["documents"][0][field] = "different"
        for arm in runner.ARMS:
            rewrite_state(
                plan_files,
                arm,
                lambda s: s["settings"].update(documents_sha256=runner.sha(runner.encode(listing))),
            )

    def mutate(request, result):
        if request.url.path.endswith("/scroll") and "offset" not in json.loads(request.content):
            if kind == "missing-point":
                result["points"].pop()
            elif kind == "wrong-point":
                result["points"][0]["id"] = "wrong-id"
            elif kind == "binding":
                result["points"][0]["payload"]["document_id"] = "doc-3"
            elif kind == "payload":
                result["points"][0]["payload"]["text"] = "changed"
            elif kind == "extra-point":
                result["points"].append({**result["points"][0], "id": "extra"})
        if kind == "vector" and request.url.path.endswith("/points"):
            result[0]["vector"] = None
        if kind == "filtered-query" and request.url.path.endswith("/query"):
            result["points"].pop()

    calls = []
    http = transport_for(listing, calls)

    def api(req):
        response = http.handle_request(req)
        if kind == "wrong-job" and "/jobs/" in req.url.path:
            value = response.json()
            value["files"].pop()
            return httpx.Response(200, json=value)
        return response

    assert execute(plan_files, httpx.MockTransport(api), peers=backend(mutate=mutate)) == 1
    assert not any(r.method == "POST" for r in calls)
    assert not (plan_files[0].parent / "campaign-ledger/campaign.consumed.json").exists()
    diagnostic = json.loads((plan_files[2] / "search-preflight.json").read_bytes())
    assert diagnostic["status"] == "failed" and diagnostic["question_requests"] == 0


def test_query_uses_existing_vector_and_exact_app_filter_with_no_inference(plan_files):
    data = snapshot()
    peers, api = [], []
    assert execute(plan_files, transport_for(plan_files[3], api), peers=backend(data, peers)) == 0
    checks = json.loads((plan_files[2] / "search-preflight.json").read_bytes())
    for arm in runner.ARMS:
        proof = checks["arms"][arm]
        assert (proof["documents"], proof["points"], proof["stored_vector_queries"]) == (15, 138, 1)
        c = proof["collection_probes"][0]
        assert (
            c["scroll_bindings_sha256"]
            == c["query_bindings_sha256"]
            == probe.canonical_sha256({p["id"]: p for p in data.manifest["points"]})
        )
        ip = "172.21.0.2" if arm == "baseline" else "172.21.1.2"
        sent = [q for q in peers if q.url.host == ip]
        scrolls = [q for q in sent if q.url.path.endswith("/scroll")]
        query = next(q for q in sent if q.url.path.endswith("/query"))
        body = json.loads(query.content)
        assert body["query"] == data.records[0]["vector"]
        assert all(json.loads(q.content)["filter"] == body["filter"] for q in scrolls)
        assert set(body["filter"]["must"][0]["match"]["any"]) == {
            d["revision"] for d in data.manifest["documents"]
        }
        assert "retired" not in str(body["filter"]) and "staging" not in str(body["filter"])
    assert all(r.url.path == "/api/tags" for r in peers if r.url.port == 11434)
    assert [r.url.port for r in api if r.method == "POST"] == [19001, 19002, 19002, 19001] * 6


def test_offline_cli_pins_original_archives_and_keeps_diagnostic(tmp_path, monkeypatch):
    import sys

    data = snapshot()
    archive = tmp_path / "library.sqlite3"
    with closing(sqlite3.connect(archive)) as db:
        seed(db, data)
    capture = tmp_path / "runtime-metadata.json"
    capture.write_text(json.dumps(archived_bindings(data)))
    rendered = tmp_path / "render.json"
    rendered.write_bytes(render(tmp_path))
    sql_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    pts_sha = hashlib.sha256(capture.read_bytes()).hexdigest()

    def invoke(out, points_sha):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "offline",
                "--sqlite",
                str(archive),
                "--sqlite-sha256",
                sql_sha,
                "--points",
                str(capture),
                "--points-sha256",
                points_sha,
                "--rendered-compose",
                str(rendered),
                "--embed-digest",
                "b" * 64,
                "--job",
                "synthetic-job",
                "--output",
                str(out),
            ],
        )
        return probe.main()

    assert invoke(tmp_path / "good", pts_sha) == 0
    record = json.loads((tmp_path / "good/offline-proof.json").read_bytes())
    assert (record["documents"], record["points"], record["runtime_stored_vector_query"]) == (
        15,
        138,
        "pending",
    )
    assert record["rendered_sha256"] == hashlib.sha256(rendered.read_bytes()).hexdigest()
    assert invoke(tmp_path / "bad", "0" * 64) == 1
    assert json.loads((tmp_path / "bad/offline-proof.json").read_bytes())["question_attempts"] == 0
    assert not (tmp_path / "bad/selected-snapshot.json").exists()
    with pytest.raises(FileExistsError):
        invoke(tmp_path / "good", pts_sha)


def test_preflight_failure_does_not_spend_or_block_a_later_success(plan_files):
    path, auth, out, listing = plan_files

    def bad(req, result):
        if req.url.path.endswith("/query"):
            result["points"].clear()

    assert execute(plan_files, transport_for(listing, []), peers=backend(mutate=bad)) == 1
    assert not (out.parent / "campaign-ledger/campaign.consumed.json").exists()
    corrected = (path, auth, out.parent / "corrected", listing)
    assert execute(corrected, transport_for(listing, [])) == 0
    assert (out.parent / "campaign-ledger/campaign.consumed.json").is_file()
    with pytest.raises(FileExistsError):
        execute((path, auth, out.parent / "replay", listing), transport_for(listing, []))


def test_concurrent_passing_preflights_dispatch_one_campaign(plan_files):
    import asyncio

    from test_managed_compare import sample

    path, auth, out, listing = plan_files
    calls = []

    async def race():
        barrier = asyncio.Barrier(2)

        async def one(target):
            base = transport_for(listing, calls)

            async def handle(req):
                if req.url.port == 19002 and "/library/jobs/" in req.url.path:
                    await asyncio.wait_for(barrier.wait(), timeout=5)
                return base.handle_request(req)

            return await runner.compare(
                path,
                auth,
                target,
                transport=httpx.MockTransport(handle),
                backend_transport=backend(),
                reader=sample,
            )

        return await asyncio.gather(one(out), one(out.with_name("other-output")))

    assert sorted(asyncio.run(race())) == [0, 1]
    assert sum(q.method == "POST" for q in calls) == 24
    summaries = [
        json.loads((directory / "summary.json").read_bytes())
        for directory in (out, out.with_name("other-output"))
    ]
    assert sorted(len(s["attempts_including_uncertain"]) for s in summaries) == [0, 24]
    assert sum(s["authorization_consumed"] for s in summaries) == 1


def test_each_rendered_database_alias_resolves_only_to_its_arm(tmp_path, docker_view):
    from evaluation.campaign_resources import resolve_backend

    nodes, _, _ = docker_view
    services = json.loads(render(tmp_path))["services"]
    for arm in runner.ARMS:
        db = nodes[arm + "-qdrant"]
        next(iter(db["NetworkSettings"]["Networks"].values()))["Aliases"] = services[
            arm + "-qdrant"
        ]["networks"][arm]["aliases"]
    for arm in runner.ARMS:
        api = nodes[arm + "-api"]
        url = services[arm + "-api"]["environment"]["QDRANT_URL"]
        assert resolve_backend(api, url, 6333, list(nodes.values())) == nodes[arm + "-qdrant"]["Id"]


def test_fresh_sqlite_proof_for_a_different_manifest_fails_without_attempt(plan_files):
    rewrite_topology(plan_files, lambda t: t.update(registry_snapshot_sha256="f" * 64))
    calls = []
    assert execute(plan_files, transport_for(plan_files[3], calls)) == 1
    assert not calls
    out = plan_files[2]
    assert not (out.parent / "campaign-ledger/campaign.consumed.json").exists()
    assert "SQLite" in json.loads((out / "search-preflight.json").read_bytes())["reason"]
