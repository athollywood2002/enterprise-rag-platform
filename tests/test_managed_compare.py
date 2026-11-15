"""Bounded comparison protocol tests use synthetic HTTP transports, never services."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from evaluation import managed_compare as run


@pytest.fixture
def plan_files(tmp_path, monkeypatch):
    documents = {"documents": [{"id": "synthetic", "revision": "one", "chunks": 1}]}
    settings = {
        "think": "default",
        "num_predict": 1536,
        "model_timeout_seconds": 180,
        "top_k": 5,
        "job_id": "synthetic-job",
        "resources": {"cpu_count": 2, "memory_bytes": 4294967296},
        "chat_model": "synthetic-chat:fixed",
        "chat_digest": "a" * 64,
        "embed_model": "synthetic-embed:fixed",
        "embed_digest": "b" * 64,
        "corpus_sha256": "c" * 64,
        "index_sha256": "d" * 64,
        "documents_sha256": run.sha(run.encode(documents)),
    }
    questions = [{"id": f"fresh-{n}", "question": f"Synthetic question {n}?"} for n in range(8)]
    (tmp_path / "questions.json").write_bytes(run.encode(questions))
    plan = {
        "questions": "questions.json",
        "questions_sha256": run.sha(run.encode(questions)),
        "freeze_sha256": "f" * 64,
        "arms": {},
    }
    for n, arm in enumerate(run.ARMS):
        state = {
            "isolated": True,
            "deployment": False,
            "shared_services": False,
            "git_commit": str(n + 1) * 40,
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
                "plan_sha256": run.sha(plan_path.read_bytes()),
                "isolated_execution_authorized": True,
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
                    "chat_model": {"name": "synthetic-chat:fixed"},
                    "embedding_model": {"name": "synthetic-embed:fixed"},
                },
            )
        if request.url.path == "/library/documents":
            return httpx.Response(200, json=documents)
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
                "generation": {
                    "num_predict": 1536,
                    "visible_empty": not answer,
                    "status": "limit" if not answer else "complete",
                },
            },
        )

    return httpx.MockTransport(handler)


def execute(files, transport):
    plan, auth, output, _ = files
    return asyncio.run(run.compare(plan, auth, output, transport=transport))


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


def test_plan_only_never_contacts_services(plan_files, capsys):
    assert run.main(["--plan", str(plan_files[0])]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["network_calls"] == 0 and result["planned_requests"] == 16
    assert not plan_files[2].exists()


@pytest.mark.parametrize(
    "answer", ["Synthetic fact [1].", "", "Wrong claim [1].", "Bad marker [7]."]
)
def test_once_each_raw_hashes_order_privacy_and_unreviewed_grades(plan_files, answer):
    calls = []
    assert execute(plan_files, transport_for(plan_files[3], calls, answer=answer)) == 0
    posts = [r for r in calls if r.method == "POST"]
    assert len(posts) == 16
    assert [r.url.port for r in posts] == [19001, 19002] * 8
    assert [json.loads(r.content)["question"] for r in posts] == [
        f"Synthetic question {n}?" for n in range(8) for _ in range(2)
    ]
    out = plan_files[2]
    assert len(list(out.glob("*.reserved.json"))) == 16
    assert json.loads((out / "summary.json").read_bytes())["stop"] is None
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
    with pytest.raises(ValueError, match="grading fields"):
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
