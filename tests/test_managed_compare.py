"""Bounded comparison protocol tests use synthetic HTTP transports, never services."""

import asyncio
import gzip
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from search_fixture import CHAT, MODEL, PREFIX, backend, snapshot

from evaluation import campaign_resources as resources
from evaluation import managed_compare as run
from evaluation.campaign_resources import GIB, MIB, ROLES


def topology():
    services = {}
    for index, role in enumerate(ROLES, 1):
        cid = f"{index:064x}"
        limit = 12 * GIB if role == "ollama" else (256 if role == "runner" else 512) * MIB
        services[role] = {
            "id": cid,
            "image_id": "4" * 64,
            "cgroup": "/docker/" + cid,
            "campaign_label": "synthetic-campaign",
            "role_label": role,
            "memory_bytes": limit,
            "memory_swap_bytes": limit,
            "cpu_limits": [0, 0, 0, "0-5"],
            "restart_count": 0,
        }
    services["ollama"]["loading"] = {"OLLAMA_NUM_PARALLEL": "1", "OLLAMA_MAX_LOADED_MODELS": "2"}
    networks = {}
    for i, arm in enumerate(run.ARMS):
        api, db, model = services[arm + "-api"], services[arm + "-qdrant"], services["ollama"]
        api.update(
            bind_ip="127.0.0.1",
            bind_port=str(19001 + i),
            model_backend_id=model["id"],
            qdrant_backend_id=db["id"],
            qdrant_url="http://qdrant:6333",
            qdrant_collection=PREFIX,
            qdrant_ip=f"172.21.{i}.2",
            ollama_ip=f"172.21.{i}.3",
            model_settings={
                "chat_model": CHAT,
                "embed_model": MODEL,
                "num_predict": 1536,
                "think": "default",
            },
        )
        networks[f"{i + 20:064x}"] = [api["id"], db["id"], model["id"]]
    return {
        "campaign_id": "synthetic-campaign",
        "rendered_sha256": "8" * 64,
        "backend_mode": "campaign-only-shared-ollama",
        "services": services,
        "networks": networks,
        "observed_at": datetime.now(UTC).isoformat(),
        "storage": {
            r: {"path": "/test/" + r, "inode": [1, i]} for i, r in enumerate(ROLES) if r != "runner"
        },
        "protected_storage": [{"path": "/original/data", "inode": [1, 100]}],
    }


def sample(services, disk_path):
    return {
        "mem_total": 32 * GIB,
        "mem_available": 20 * GIB,
        "disk_free": 10 * GIB,
        "host_swap_used": 768 * 1024,
        "pswpin": 20,
        "pswpout": 200,
        "containers": {
            role: {
                "inode": i + 1,
                "limit": spec["memory_bytes"],
                "swap": 0,
                "swap_peak": 0,
                "swap_limit": "0",
                "events": {"oom": 0, "oom_kill": 0},
                "populated": 1,
            }
            for i, (role, spec) in enumerate(services.items())
        },
    }


@pytest.fixture
def plan_files(tmp_path, monkeypatch):
    data = snapshot()
    documents = data.listing
    snapshot_bytes = run.encode(data.manifest)
    (tmp_path / "selected.json").write_bytes(snapshot_bytes)
    settings = {
        "think": "default",
        "num_predict": 1536,
        "model_timeout_seconds": 180,
        "embedding_timeout_seconds": 120,
        "top_k": 5,
        "job_id": "synthetic-job",
        "resources": {"cpu_count": 6, "memory_bytes": 512 * MIB},
        "chat_model": CHAT,
        "chat_digest": "a" * 64,
        "embed_model": MODEL,
        "embed_digest": "b" * 64,
        "corpus_sha256": "c" * 64,
        "index_sha256": "d" * 64,
        "documents_sha256": run.sha(run.encode(documents)),
    }
    questions = [{"id": f"fresh-{n}", "question": f"Synthetic question {n}?"} for n in range(12)]
    (tmp_path / "questions.json").write_bytes(run.encode(questions))
    ownership = topology()
    ownership["registry_snapshot_sha256"] = run.sha(snapshot_bytes)
    ownership["registry_checks"] = {arm: {"documents": 15, "points": 138} for arm in run.ARMS}
    (tmp_path / "host.json").write_bytes(run.encode(ownership))
    plan = {
        "campaign_id": ownership["campaign_id"],
        "runner": {"commit": "7" * 40, "source_sha256": run.runner_sources()},
        "order": run.ORDER,
        "budget": run.BUDGET,
        "ownership_receipt": "host.json",
        "ownership_sha256": run.sha(run.encode(ownership)),
        "selected_snapshot": "selected.json",
        "selected_snapshot_sha256": run.sha(snapshot_bytes),
        "rendered_sha256": ownership["rendered_sha256"],
        "questions": "questions.json",
        "questions_sha256": run.sha(run.encode(questions)),
        "freeze_sha256": "f" * 64,
        "custodian_receipt": "custodian-receipt.json",
        "arms": {},
    }
    receipt = {
        "question_export_sha256": plan["questions_sha256"],
        "sealed_bundle_sha256_unchanged": plan["freeze_sha256"],
        "question_export_count": 12,
        "question_export_fields": ["id", "question"],
    }
    (tmp_path / "custodian-receipt.json").write_bytes(run.encode(receipt))
    plan["custodian_receipt_sha256"] = run.sha(run.encode(receipt))
    for n, arm in enumerate(run.ARMS):
        state = {
            "isolated": True,
            "deployment": False,
            "campaign_id": ownership["campaign_id"],
            "api_container_id": ownership["services"][arm + "-api"]["id"],
            "git_commit": run.PINNED_BUILDS[arm],
            "observed_at": datetime.now(UTC).isoformat(),
            "inspection": "Synthetic test receipt; not actual machine evidence",
            "settings": settings,
        }
        raw = run.encode(state)
        (tmp_path / f"{arm}-state.json").write_bytes(raw)
        key_env = f"RAG_EVAL_{arm.upper()}_KEY"
        monkeypatch.setenv(key_env, "synthetic-secret-never-log")
        plan["arms"][arm] = {
            "url": f"http://127.0.0.1:{19001 + n}",
            "key_env": key_env,
            "state_receipt": f"{arm}-state.json",
            "state_sha256": run.sha(raw),
        }
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(run.encode(plan))
    auth_path = tmp_path / "authorization.json"
    auth_path.write_bytes(
        run.encode(
            {
                "owner_reference": "synthetic test ONLY",
                "campaign_id": ownership["campaign_id"],
                "plan_sha256": run.sha(plan_path.read_bytes()),
                "isolated_execution_authorized": True,
                "ledger_dir": str(tmp_path / "campaign-ledger"),
            }
        )
    )
    return plan_path, auth_path, tmp_path / "results", documents


def transport_for(documents, calls, *, answer="Synthetic fact [1].", fail=None, different=False):
    def handler(request):
        calls.append(request)
        if request.url.path == "/library/readiness":
            return httpx.Response(
                200,
                json={
                    "metadata_ready": True,
                    "mode": "real",
                    "chat_model": {"name": CHAT},
                    "embedding_model": {"name": MODEL},
                },
            )
        if request.url.path == "/library/documents":
            return httpx.Response(200, json=documents)
        if request.method == "GET" and request.url.path == "/library/jobs/synthetic-job":
            return httpx.Response(200, json=snapshot().job)
        assert request.method == "POST" and request.url.path == "/library/ask"
        if fail:
            return fail(request)
        payload = json.loads(request.content)
        assert set(payload) == {"question", "job_id", "top_k"}
        assert payload["job_id"] == "synthetic-job" and payload["top_k"] == 5
        return httpx.Response(
            200,
            json={
                "answer": answer,
                "sources": [
                    {
                        "text": "Different"
                        if different and request.url.port == 19002
                        else "Synthetic fact"
                    }
                ],
                "retrieval": {"ranking_lanes": ["dense", "bm25"], "lexical_scanned": 1},
                "generation": {
                    "num_predict": 1536,
                    "visible_empty": not answer,
                    "status": "limit" if not answer else "complete",
                },
            },
        )

    return httpx.MockTransport(handler)


def execute(files, transport, reader=sample, peers=None):
    plan, auth, output, _ = files
    return asyncio.run(
        run.compare(
            plan,
            auth,
            output,
            transport=transport,
            backend_transport=peers or backend(),
            reader=reader,
        )
    )


def rewrite_plan(files, mutate):
    path, auth, _, _ = files
    plan = json.loads(path.read_bytes())
    mutate(plan)
    path.write_bytes(run.encode(plan))
    authorization = json.loads(auth.read_bytes())
    authorization["plan_sha256"] = run.sha(path.read_bytes())
    auth.write_bytes(run.encode(authorization))


def rewrite_state(files, arm, mutate):
    path = files[0].parent / f"{arm}-state.json"
    state = json.loads(path.read_bytes())
    mutate(state)
    path.write_bytes(run.encode(state))
    rewrite_plan(
        files, lambda plan: plan["arms"][arm].update(state_sha256=run.sha(path.read_bytes()))
    )


def rewrite_receipt(files, mutate):
    path = files[0].parent / "custodian-receipt.json"
    receipt = json.loads(path.read_bytes())
    mutate(receipt)
    path.write_bytes(run.encode(receipt))
    rewrite_plan(files, lambda p: p.update(custodian_receipt_sha256=run.sha(path.read_bytes())))


def rewrite_topology(files, mutate):
    path = files[0].parent / "host.json"
    value = json.loads(path.read_bytes())
    mutate(value)
    path.write_bytes(run.encode(value))
    rewrite_plan(files, lambda p: p.update(ownership_sha256=run.sha(path.read_bytes())))


def test_plan_only_never_contacts_services(plan_files, capsys):
    assert run.main(["--plan", str(plan_files[0])]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["network_calls"] == 0 and result["planned_requests"] == 24
    assert (result["API_seconds"], result["batch_seconds"], result["no_new_after_seconds"]) == (
        300,
        7200,
        6870,
    )
    assert result["order"] == run.ORDER
    assert not plan_files[2].exists()


@pytest.mark.parametrize(
    "answer", ["Synthetic fact [1].", "", "Wrong claim [1].", "Bad marker [7]."]
)
def test_once_each_raw_hashes_order_privacy_and_unreviewed_grades(plan_files, answer):
    calls = []
    assert execute(plan_files, transport_for(plan_files[3], calls, answer=answer)) == 0
    posts = [r for r in calls if r.method == "POST"]
    assert len(posts) == 24
    assert [r.url.port for r in posts] == [19001, 19002, 19002, 19001] * 6
    assert [json.loads(r.content)["question"] for r in posts] == [
        f"Synthetic question {n}?" for n in range(12) for _ in range(2)
    ]
    out = plan_files[2]
    assert len(list(out.glob("*.reserved.json"))) == 24
    summary = json.loads((out / "summary.json").read_bytes())
    assert summary["stop"] is None
    assert len(set(summary["attempts_including_uncertain"])) == 24
    assert summary["unattempted"] == []
    second_first = json.loads((out / "fresh-1-candidate.reserved.json").read_bytes())
    assert (second_first["ordinal"], second_first["position_in_pair"]) == (2, 1)
    for line in (out / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        assert run.sha((out / name).read_bytes()) == digest
        assert b"synthetic-secret-never-log" not in (out / name).read_bytes()
    review = json.loads((out / "fresh-0-candidate.review-needed.json").read_bytes())
    assert review["answer_grade"] == review["claim_support"] == "UNREVIEWED"
    assert review["citation_mapping"]["claim_support_verified"] is False
    assert review["citation_mapping"]["visible_empty"] == (not answer)
    with pytest.raises(ValueError, match="already exists"):
        execute(plan_files, transport_for(plan_files[3], []))
    # New output does NOT allow reusing the consumed execution authorization.
    with pytest.raises(FileExistsError):
        asyncio.run(
            run.compare(
                plan_files[0],
                plan_files[1],
                out.parent / "another",
                transport=transport_for(plan_files[3], []),
            )
        )
    # Renaming/reformatting unchanged authorization still hits the same ledger identity.
    copied_auth = plan_files[1].with_name("copied-authorization.json")
    copied_auth.write_text(json.dumps(json.loads(plan_files[1].read_bytes()), indent=4))
    with pytest.raises(FileExistsError):
        asyncio.run(
            run.compare(
                plan_files[0],
                copied_auth,
                out.parent / "third",
                transport=transport_for(plan_files[3], []),
            )
        )


@pytest.mark.parametrize("failure", ["no_response", "empty_body", "http_error", "invalid_json"])
def test_failure_preserved_no_resend_and_distinct_empty_states(plan_files, failure):
    def fail(request):
        if failure == "no_response":
            raise httpx.ReadTimeout("synthetic", request=request)
        return httpx.Response(
            503 if failure == "http_error" else 200,
            content=b"" if failure == "empty_body" else b"invalid",
        )

    calls = []
    assert execute(plan_files, transport_for(plan_files[3], calls, fail=fail)) == 1
    assert len([r for r in calls if r.method == "POST"]) == 1
    evidence = json.loads((plan_files[2] / "fresh-0-baseline.result.json").read_bytes())
    assert evidence["no_HTTP_response"] == (failure == "no_response")
    assert evidence["empty_HTTP_body"] == (failure == "empty_body")
    assert (plan_files[2] / "fresh-0-baseline.reserved.json").exists()
    assert (plan_files[2] / "fresh-0-baseline.body").exists()


def test_excerpts_mismatch_stops_and_preserves_both_arms(plan_files):
    calls = []
    assert execute(plan_files, transport_for(plan_files[3], calls, different=True)) == 1
    assert len([r for r in calls if r.method == "POST"]) == 2
    assert (plan_files[2] / "fresh-0-candidate.body").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["arms"]["candidate"].update(url="http://127.0.0.1:18000"),
        lambda p: p["arms"]["candidate"].update(url="http://shared.invalid:19002"),
        lambda p: p["arms"]["candidate"].update(url="http://127.0.0.1:19002/redirect"),
        lambda p: p["arms"]["candidate"].update(key_env="RAG_API_KEY"),
        lambda p: p.update(questions_sha256="0" * 64),
    ],
)
def test_invalid_plans_fail_before_output_or_network(plan_files, mutation):
    rewrite_plan(plan_files, mutation)
    with pytest.raises(ValueError):
        execute(plan_files, transport_for(plan_files[3], []))
    assert not plan_files[2].exists()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s.update(isolated=False),
        lambda s: s.update(shared_services=True),
        lambda s: s["settings"].update(num_predict=2048),
        lambda s: s["settings"].update(think="on"),
        lambda s: s.update(observed_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat()),
    ],
)
def test_unapproved_state_settings_or_stale_receipts_fail_closed(plan_files, mutation):
    rewrite_state(plan_files, "candidate", mutation)
    with pytest.raises(ValueError):
        execute(plan_files, transport_for(plan_files[3], []))
    assert not plan_files[2].exists()


def test_expected_answers_cannot_enter_dispatch_export(plan_files):
    path = plan_files[0].parent / "questions.json"
    questions = json.loads(path.read_bytes())
    questions[0]["expected_answer"] = "grader only"
    path.write_bytes(run.encode(questions))
    rewrite_plan(plan_files, lambda p: p.update(questions_sha256=run.sha(path.read_bytes())))
    rewrite_receipt(
        plan_files, lambda r: r.update(question_export_sha256=run.sha(path.read_bytes()))
    )
    with pytest.raises(ValueError, match="grading fields"):
        run.load_plan(plan_files[0])


def test_preserves_exact_export_bytes_not_reencoded_json(plan_files):
    path = plan_files[0].parent / "questions.json"
    path.write_text(json.dumps(json.loads(path.read_bytes()), indent=4) + "\n")
    rewrite_plan(plan_files, lambda p: p.update(questions_sha256=run.sha(path.read_bytes())))
    rewrite_receipt(
        plan_files, lambda r: r.update(question_export_sha256=run.sha(path.read_bytes()))
    )
    assert execute(plan_files, transport_for(plan_files[3], [])) == 0
    assert (plan_files[2] / "questions.json").read_bytes() == path.read_bytes()


@pytest.mark.parametrize(
    "field,value",
    [
        ("question_export_sha256", "e" * 64),
        ("sealed_bundle_sha256_unchanged", "e" * 64),
        ("question_export_count", 8),
        ("question_export_fields", ["id", "question", "expected"]),
    ],
)
def test_export_and_frozen_bundle_must_match_pinned_custodian_receipt(plan_files, field, value):
    rewrite_receipt(plan_files, lambda r: r.update({field: value}))
    with pytest.raises(ValueError, match="custodian"):
        run.load_plan(plan_files[0])


def test_no_new_after_deadline_dispatches_nothing(plan_files, monkeypatch):
    monkeypatch.setattr(run, "NO_NEW_AFTER_SECONDS", 0)
    calls = []
    assert execute(plan_files, transport_for(plan_files[3], calls)) == 1
    assert not [r for r in calls if r.method == "POST"]
    assert not list(plan_files[2].glob("*.reserved.json"))


def test_total_wall_timeout_not_just_read_timeout(monkeypatch):
    async def slow(request):
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={})

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
            raw, result = await run.request(
                client, "POST", "http://127.0.0.1:19001/library/ask", {}
            )
            assert raw == b"" and result["error_type"] == "TimeoutError"
            assert result["no_HTTP_response"] and not result["empty_HTTP_body"]

    monkeypatch.setattr(run, "API_SECONDS", 0.01)
    asyncio.run(check())


def test_batch_timeout_keeps_uncertain_dispatch_reserved(plan_files, monkeypatch):
    base = transport_for(plan_files[3], [])

    async def slow(request):
        if request.method == "POST":
            await asyncio.sleep(10)
        return base.handle_request(request)

    monkeypatch.setattr(run, "BATCH_SECONDS", 1)
    assert execute(plan_files, httpx.MockTransport(slow)) == 1
    summary = json.loads((plan_files[2] / "summary.json").read_bytes())
    assert summary["stop"] == "TimeoutError"
    assert summary["unresolved_reservations"] == ["fresh-0-baseline"]
    assert len(list(plan_files[2].glob("*.reserved.json"))) == 1
    assert not (plan_files[2] / "fresh-0-candidate.reserved.json").exists()


def test_redirect_not_followed(plan_files):
    calls = []

    def redirect(request):
        return httpx.Response(307, headers={"Location": "http://shared.invalid/library/ask"})

    assert execute(plan_files, transport_for(plan_files[3], calls, fail=redirect)) == 1
    assert len([r for r in calls if r.method == "POST"]) == 1
    result = json.loads((plan_files[2] / "fresh-0-baseline.result.json").read_bytes())
    assert result["status"] == 307


def test_headers_received_then_body_timeout_is_not_empty_http_body():
    class BrokenBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"partial"
            raise httpx.ReadTimeout("synthetic partial response")

    async def check():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=BrokenBody()))
        async with httpx.AsyncClient(transport=transport) as client:
            raw, result = await run.request(
                client, "POST", "http://127.0.0.1:19001/library/ask", {}
            )
            assert raw == b"partial" and result["HTTP_response_received"]
            assert not result["no_HTTP_response"] and not result["empty_HTTP_body"]
            assert not result["body_complete"]

    asyncio.run(check())


@pytest.mark.parametrize(
    "setting,value",
    [
        ("http_seconds", 301),
        ("batch_seconds", 3600),
        ("no_new_after_seconds", 6871),
        ("batch_seconds", 7200.0),
    ],
)
def test_unapproved_budget_rejected_before_ledger(plan_files, setting, value):
    rewrite_plan(plan_files, lambda p: p["budget"].update({setting: value}))
    with pytest.raises(ValueError, match="budget"):
        execute(plan_files, transport_for(plan_files[3], []))
    assert not plan_files[2].exists()


@pytest.mark.parametrize(
    "change",
    [
        lambda t: t["services"]["ollama"].update(campaign_label="deployed"),
        lambda t: t["services"]["baseline-api"].update(model_backend_id="a" * 64),
        lambda t: t["services"]["candidate-api"].update(
            qdrant_backend_id=t["services"]["baseline-qdrant"]["id"]
        ),
        lambda t: t["services"]["candidate-api"].update(bind_port="18000"),
        lambda t: next(iter(t["networks"].values())).append("e" * 64),
        lambda t: t["services"]["candidate-qdrant"].update(memory_bytes=GIB),
        lambda t: t["services"]["candidate-api"].update(cpu_limits=[0, 0, 0, "1"]),
        lambda t: t["services"]["ollama"].update(memory_swap_bytes=20 * GIB),
        lambda t: t["storage"].update({"candidate-qdrant": t["storage"]["baseline-qdrant"]}),
        lambda t: t["protected_storage"].append(t["storage"]["baseline-api"]),
        lambda t: t["services"]["baseline-api"]["model_settings"].update(think="off"),
    ],
)
def test_real_binding_and_resource_receipt_required(plan_files, change):
    rewrite_topology(plan_files, change)
    calls = []
    with pytest.raises(ValueError):
        execute(plan_files, transport_for(plan_files[3], calls))
    assert not calls and not plan_files[2].exists()


@pytest.mark.parametrize("field", ["sources", "retrieval"])
def test_candidate_first_pair_rejects_different_evidence(plan_files, field):
    calls = []

    def respond(request):
        response = base.handle_request(request)
        if request.method == "POST" and len([x for x in calls if x.method == "POST"]) == 4:
            value = response.json()
            if field == "sources":
                value["sources"][0]["text"] = "Changed passage at the second build"
            else:
                value["retrieval"]["lexical_scanned"] = 99
            return httpx.Response(200, json=value)
        return response

    base = transport_for(plan_files[3], calls)
    assert execute(plan_files, httpx.MockTransport(respond)) == 1
    posts = [r.url.port for r in calls if r.method == "POST"]
    assert posts == [19001, 19002, 19002, 19001]
    result = json.loads((plan_files[2] / "summary.json").read_bytes())
    assert result["stop"] == "returned-source-or-retrieval-parity-mismatch"
    assert len(result["unattempted"]) == 20


def test_campaign_consumed_even_when_authorization_text_changes(plan_files):
    calls = []
    assert execute(plan_files, transport_for(plan_files[3], calls)) == 0
    path, auth, out, docs = plan_files
    value = json.loads(auth.read_bytes())
    value["owner_reference"] += " (reformatted approval)"
    auth.write_bytes(run.encode(value))
    second_calls = []
    with pytest.raises(FileExistsError):
        execute((path, auth, out.parent / "fresh-output", docs), transport_for(docs, second_calls))
    assert not second_calls
    assert len([c for c in calls if c.method == "POST"]) == 24


def test_deadline_during_reservation_has_positive_non_dispatch_record(plan_files, monkeypatch):
    durable_save = run.save

    def save_then_expire(path, raw):
        durable_save(path, raw)
        if path.name.endswith(".reserved.json"):
            monkeypatch.setattr(run, "NO_NEW_AFTER_SECONDS", 0)

    monkeypatch.setattr(run, "save", save_then_expire)
    calls = []
    assert execute(plan_files, transport_for(plan_files[3], calls)) == 1
    result = json.loads((plan_files[2] / "summary.json").read_bytes())
    assert not [c for c in calls if c.method == "POST"]
    assert (plan_files[2] / "fresh-0-baseline.undispatched.json").is_file()
    assert result["unresolved_reservations"] == result["attempts_including_uncertain"] == []


def test_oom_during_body_stops_once_and_saves_prefix(plan_files, monkeypatch):
    monkeypatch.setattr(resources, "SAMPLE_SECONDS", 0.01)
    started = False

    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal started
            yield b"body prefix"
            started = True
            await asyncio.sleep(30)

    def read(services, path):
        result = sample(services, path)
        if started:
            result["containers"]["ollama"]["events"]["oom"] += 1
        return result

    calls = []
    target = transport_for(
        plan_files[3], calls, fail=lambda req: httpx.Response(200, stream=SlowBody())
    )
    assert execute(plan_files, target, reader=read) == 1
    out = plan_files[2]
    summary = json.loads((out / "summary.json").read_bytes())
    assert summary["stop"] == "experiment-oom:ollama"
    assert (
        summary["unresolved_reservations"]
        == summary["attempts_including_uncertain"]
        == ["fresh-0-baseline"]
    )
    assert (out / "fresh-0-baseline.partial.body").read_bytes() == b"body prefix"
    assert not (out / "fresh-0-baseline.result.json").exists()
    assert len([c for c in calls if c.method == "POST"]) == 1


def test_idle_guest_swap_is_recorded_and_experiment_swap_stops(plan_files):
    count = 0

    def read(services, path):
        nonlocal count
        result = sample(services, path)
        result["pswpout"] += count
        count += 1
        if count == 4:
            result["containers"]["baseline-api"]["swap_peak"] = 4096
        return result

    calls = []
    assert execute(plan_files, transport_for(plan_files[3], calls), reader=read) == 1
    stats = [json.loads(s) for s in (plan_files[2] / "resources.jsonl").read_text().splitlines()]
    assert stats[0]["host_swap_used"] == 768 * 1024
    assert stats[0]["pswpout_delta"] == 0
    assert any(s["pswpout_delta"] == 2 for s in stats)
    assert (
        json.loads((plan_files[2] / "summary.json").read_bytes())["stop"]
        == "experiment-swap:baseline-api"
    )
    assert len([c for c in calls if c.method == "POST"]) == 1


def test_compressed_response_retains_original_http_entity_bytes(plan_files):
    wire = gzip.compress(b'{"answer":"synthetic"}')
    target = transport_for(
        plan_files[3],
        [],
        fail=lambda req: httpx.Response(
            200, stream=httpx.ByteStream(wire), headers={"Content-Encoding": "gzip"}
        ),
    )
    assert execute(plan_files, target) == 1
    stem = plan_files[2] / "fresh-0-baseline"
    assert stem.with_suffix(".body").read_bytes() == wire
    result = json.loads(stem.with_suffix(".result.json").read_bytes())
    assert result["raw_body_sha256"] == run.sha(wire) and result["body_complete"]
