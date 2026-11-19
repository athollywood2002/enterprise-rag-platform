"""One-shot, reviewer-run isolated HTTP comparison. Default mode is offline plan only."""

import argparse
import asyncio
import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from evaluation.campaign_resources import (
    ARMS,
    Monitor,
    ResourceStop,
    resource_sample,
    validate_ownership,
)
from evaluation.grounding import citation_diagnostics
from evaluation.run import new_output
from evaluation.search_preflight import PINNED_BUILDS, runtime_arm, validate_manifest

API_SECONDS = 300
BATCH_SECONDS = 7200
NO_NEW_AFTER_SECONDS = 6870
MAX_BYTES = 8 * 1024 * 1024
BUDGET = {
    "http_seconds": API_SECONDS,
    "batch_seconds": BATCH_SECONDS,
    "no_new_after_seconds": NO_NEW_AFTER_SECONDS,
}
ORDER = "baseline-first-on-odd-candidate-first-on-even"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode()


def arm_order(ordinal):
    return ARMS if ordinal % 2 else ARMS[::-1]


def runner_sources():
    return {
        name: sha((Path(__file__).parent / name).read_bytes())
        for name in (
            "managed_compare.py",
            "campaign_resources.py",
            "search_preflight.py",
            "registry_snapshot.py",
            "compose.managed-compare.yaml",
            "grounding.py",
            "run.py",
        )
    }


def save(path, raw):
    """Exclusive, durable private writes; a reservation is never removed or resumed."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def load_plan(path, *, raw=None):
    plan = json.loads(path.read_bytes() if raw is None else raw)
    if set(plan) != {
        "campaign_id",
        "runner",
        "order",
        "budget",
        "ownership_receipt",
        "ownership_sha256",
        "selected_snapshot",
        "selected_snapshot_sha256",
        "rendered_sha256",
        "questions",
        "questions_sha256",
        "freeze_sha256",
        "arms",
        "custodian_receipt",
        "custodian_receipt_sha256",
    }:
        raise ValueError("Require the balanced campaign plan with pinned custody and ownership")
    if (
        plan["order"] != ORDER
        or plan["budget"] != BUDGET
        or any(type(v) is not int for v in plan["budget"].values())
    ):
        raise ValueError("Require the approved balanced order and exact 300/7200/6870 budget")
    runner = plan["runner"]
    if (
        set(runner) != {"commit", "source_sha256"}
        or not re.fullmatch(r"[a-f0-9]{40}", runner["commit"])
        or runner["source_sha256"] != runner_sources()
    ):
        raise ValueError("Reviewed runner source hashes must match the executing runner")
    ownership_raw = (path.parent / plan["ownership_receipt"]).read_bytes()
    if sha(ownership_raw) != plan["ownership_sha256"]:
        raise ValueError("Pinned host ownership receipt mismatch")
    ownership = json.loads(ownership_raw)
    if not re.fullmatch(r"[a-f0-9]{64}", plan["rendered_sha256"]) or plan[
        "rendered_sha256"
    ] != ownership.get("rendered_sha256"):
        raise ValueError("Require the reviewed render bound to the inspected ownership receipt")
    receipt_raw = (path.parent / plan["custodian_receipt"]).read_bytes()
    if sha(receipt_raw) != plan["custodian_receipt_sha256"]:
        raise ValueError("Custodian receipt hash mismatch")
    receipt = json.loads(receipt_raw)
    questions_raw = (path.parent / plan["questions"]).read_bytes()
    if sha(questions_raw) != plan["questions_sha256"]:
        raise ValueError("Question bytes differ from frozen reviewer export")
    questions = json.loads(questions_raw)
    if not isinstance(questions, list) or len(questions) != 12:
        raise ValueError("Require exactly 12 frozen questions for 24 attempts")
    if (
        receipt.get("question_export_sha256") != plan["questions_sha256"]
        or receipt.get("sealed_bundle_sha256_unchanged") != plan["freeze_sha256"]
        or receipt.get("question_export_count") != len(questions)
        or receipt.get("question_export_fields") != ["id", "question"]
    ):
        raise ValueError("Question export is not bound to the custodian's frozen-bundle receipt")
    ids = set()
    for case in questions:
        if (
            set(case) != {"id", "question"}
            or not isinstance(case["id"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", case["id"])
            or case["id"] in ids
            or not isinstance(case["question"], str)
            or not case["question"].strip()
        ):
            raise ValueError("Question export permits unique id/question ONLY; no grading fields")
        ids.add(case["id"])
    if set(plan["arms"]) != set(ARMS):
        raise ValueError("Exactly baseline and candidate arms required")
    validate_ownership(plan["campaign_id"], ownership, plan["arms"])
    states = {}
    for arm in ARMS:
        target = plan["arms"][arm]
        if set(target) != {"url", "key_env", "state_receipt", "state_sha256"}:
            raise ValueError("Arm needs URL, key environment name and pinned state receipt")
        if not re.fullmatch(r"http://(?:127\.0\.0\.1|\[::1\]):[0-9]{1,5}", target["url"]):
            raise ValueError("Only numeric-loopback HTTP with explicit port allowed")
        if urlsplit(target["url"]).port in (None, 0, 18000):
            raise ValueError("Do not target deployed API port; use independently isolated services")
        if not re.fullmatch(r"RAG_EVAL_[A-Z0-9_]+_KEY", target["key_env"]):
            raise ValueError("Require dedicated RAG_EVAL_*_KEY environment variable")
        raw = (path.parent / target["state_receipt"]).read_bytes()
        if sha(raw) != target["state_sha256"]:
            raise ValueError("State receipt hash mismatch")
        state = states[arm] = json.loads(raw)
        if (
            set(state)
            != {
                "git_commit",
                "isolated",
                "deployment",
                "campaign_id",
                "api_container_id",
                "settings",
                "observed_at",
                "inspection",
            }
            or not isinstance(state.get("inspection"), str)
            or not state["inspection"].strip()
            or state.get("isolated") is not True
            or state.get("deployment") is not False
            or state["campaign_id"] != plan["campaign_id"]
            or state["api_container_id"] != ownership["services"][f"{arm}-api"]["id"]
            or state.get("git_commit") != PINNED_BUILDS[arm]
        ):
            raise ValueError("State receipt must bind the campaign's inspected API container")
        settings = state["settings"]
        observed = ownership["services"][f"{arm}-api"]
        if settings["resources"]["memory_bytes"] != observed["memory_bytes"] or any(
            settings.get(k) != observed["model_settings"].get(k)
            for k in ("chat_model", "embed_model", "num_predict", "think")
        ):
            raise ValueError("API settings differ from the inspected container")
        if set(settings) != {
            "think",
            "num_predict",
            "model_timeout_seconds",
            "embedding_timeout_seconds",
            "top_k",
            "job_id",
            "resources",
            "chat_model",
            "chat_digest",
            "embed_model",
            "embed_digest",
            "corpus_sha256",
            "index_sha256",
            "documents_sha256",
        }:
            raise ValueError("State receipt settings must match the documented schema")
        if (
            settings["think"] != "default"
            or type(settings["num_predict"]) is not int
            or settings["num_predict"] != 1536
            or settings["model_timeout_seconds"] != 180
            or settings["embedding_timeout_seconds"] != 120
            or type(settings["top_k"]) is not int
            or settings["top_k"] != 5
            or not isinstance(settings["job_id"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", settings["job_id"])
            or not isinstance(settings["resources"], dict)
            or set(settings["resources"]) != {"cpu_count", "memory_bytes"}
            or any(type(v) is not int or v <= 0 for v in settings["resources"].values())
        ):
            raise ValueError("Fixed default/1536/180s/top_k5/job/resources required")
        for key in (
            "chat_digest",
            "embed_digest",
            "corpus_sha256",
            "index_sha256",
            "documents_sha256",
        ):
            if not re.fullmatch(r"[a-f0-9]{64}", settings[key]) or int(settings[key], 16) == 0:
                raise ValueError("Need pinned model/corpus/index hashes")
    if states["baseline"]["settings"] != states["candidate"]["settings"]:
        raise ValueError("Arms differ in settings/models/index/corpus/job/resources")
    if states["baseline"]["git_commit"] == states["candidate"]["git_commit"]:
        raise ValueError("Require fixed distinct baseline/candidate commits")
    if plan["arms"]["baseline"]["url"] == plan["arms"]["candidate"]["url"]:
        raise ValueError("Require separate isolated endpoints")
    if not re.fullmatch(r"[a-f0-9]{64}", plan["freeze_sha256"]):
        raise ValueError("Need custodian frozen-bundle hash")
    return plan, questions, states, ownership


async def request(client, method, url, headers, raw=None, *, on_interrupt=None):
    body, status, complete, error = bytearray(), None, False, None
    content_encoding = None
    start = time.monotonic()

    def evidence():
        return {
            "status": status,
            "HTTP_response_received": status is not None,
            "no_HTTP_response": status is None,
            "empty_HTTP_body": complete and status is not None and not body,
            "body_complete": complete,
            "content_encoding": content_encoding,
            "error_type": error,
            "elapsed_seconds": time.monotonic() - start,
            "raw_body_bytes": len(body),
            "raw_body_sha256": sha(body),
        }

    try:
        # Total wall deadline includes connection, headers, body and slow trickles.
        async with asyncio.timeout(API_SECONDS):
            async with client.stream(method, url, headers=headers, content=raw) as response:
                status = response.status_code
                content_encoding = (
                    response.headers.get("Content-Encoding", "identity").strip().lower()
                )
                # HTTP transports expose raw bytes. Mock transports may supply an
                # already-buffered identity response with no decoding to reverse.
                if response.is_stream_consumed and content_encoding != "identity":
                    raise ValueError("Encoded response was already decoded by the transport")
                chunks = (
                    response.aiter_bytes() if response.is_stream_consumed else response.aiter_raw()
                )
                async for chunk in chunks:
                    remaining = MAX_BYTES - len(body)
                    body.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        raise ValueError("Response byte ceiling reached")
                complete = True
    except asyncio.CancelledError:
        if on_interrupt is not None:
            error = "CancelledError"
            on_interrupt(bytes(body), evidence())
        raise
    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
        error = type(exc).__name__  # Never log headers/exception text containing secrets.
    return bytes(body), evidence()


def parsed(raw, result):
    if result["error_type"] or result["status"] != 200 or not result["body_complete"]:
        raise ResourceStop(f"http-failure:{result['status']}:{result['error_type']}")
    if result["content_encoding"] != "identity":
        raise ResourceStop("unexpected-http-content-encoding-raw-bytes-retained")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ResourceStop("invalid-http-json") from exc
    if not isinstance(value, dict):
        raise ResourceStop("invalid-http-object")
    return value


def fresh_receipts(states, ownership):
    for state in (*states.values(), ownership):
        observed = datetime.fromisoformat(state["observed_at"])
        if observed.tzinfo is None:
            raise ResourceStop("State receipt timestamps must include a timezone")
        age = (datetime.now(UTC) - observed).total_seconds()
        if not 0 <= age <= 900:
            raise ResourceStop("Inspected state receipts must be timezone-aware and <15min old")


async def compare(
    plan_path,
    authorization_path,
    output,
    *,
    transport=None,
    backend_transport=None,
    reader=resource_sample,
    disk_path=None,
):
    plan_raw = plan_path.read_bytes()
    plan, questions, states, ownership = load_plan(plan_path, raw=plan_raw)
    authorization_raw = authorization_path.read_bytes()
    authorization = json.loads(authorization_raw)
    if (
        set(authorization)
        != {
            "owner_reference",
            "campaign_id",
            "plan_sha256",
            "isolated_execution_authorized",
            "ledger_dir",
        }
        or not authorization["owner_reference"].strip()
        or authorization["campaign_id"] != plan["campaign_id"]
        or authorization["isolated_execution_authorized"] is not True
        or authorization["plan_sha256"] != sha(plan_raw)
    ):
        raise ValueError("Separate owner authorization must pin this exact isolated plan")
    fresh_receipts(states, ownership)
    keys = {arm: os.environ[plan["arms"][arm]["key_env"]] for arm in ARMS}
    if any(not value for value in keys.values()):
        raise ValueError("Empty dedicated API key")
    ledger = Path(authorization["ledger_dir"])
    if (
        not ledger.is_absolute()
        or ".." in ledger.parts
        or any(p.is_symlink() for p in (ledger, *ledger.parents))
    ):
        raise ValueError("Require a fixed absolute nonsymlink campaign ledger directory")
    out = new_output(output)
    ledger.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(ledger.iterdir()):
        raise FileExistsError("Keep the existing campaign ledger intact")
    consumed = False
    save(out / "plan.json", plan_raw)
    save(out / "authorization.json", authorization_raw)
    for name, path_key, hash_key in (
        ("questions.json", "questions", "questions_sha256"),
        ("custodian-receipt.json", "custodian_receipt", "custodian_receipt_sha256"),
        ("ownership.json", "ownership_receipt", "ownership_sha256"),
    ):
        raw = (plan_path.parent / plan[path_key]).read_bytes()
        if sha(raw) != plan[hash_key]:
            raise ValueError("Pinned input changed before preflight")
        save(out / name, raw)
    save(out / "state-receipts.json", encode(states))
    save(out / "runner-source-hashes.json", encode(runner_sources()))
    start = time.monotonic()
    completed, stop = [], "INTERRUPTED_OR_UNCERTAIN"
    monitor = Monitor(ownership["services"], out / "resources.jsonl", disk_path or out, reader)
    headers = {
        arm: {
            "X-API-Key": keys[arm],
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
        }
        for arm in ARMS
    }

    async def dispatch():
        nonlocal consumed
        async with httpx.AsyncClient(
            transport=transport or httpx.AsyncHTTPTransport(retries=0),
            timeout=API_SECONDS,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            before_docs, arm_proofs = {}, {}
            stage = "snapshot"
            async with httpx.AsyncClient(
                transport=backend_transport, trust_env=False, follow_redirects=False, timeout=15
            ) as peers:
                try:
                    raw_manifest = (plan_path.parent / plan["selected_snapshot"]).read_bytes()
                    if sha(raw_manifest) != plan["selected_snapshot_sha256"]:
                        raise ResourceStop("expected snapshot manifest hash mismatch")
                    if ownership.get("registry_snapshot_sha256") != sha(
                        raw_manifest
                    ) or ownership.get("registry_checks") != {
                        arm: {"documents": 15, "points": 138} for arm in ARMS
                    }:
                        raise ResourceStop(
                            "fresh physical SQLite checks must bind both arms to the same frozen snapshot"
                        )
                    manifest = json.loads(raw_manifest)
                    validate_manifest(manifest, states[ARMS[0]]["settings"]["job_id"])
                    save(out / "selected-snapshot.json", raw_manifest)
                    for arm in ARMS:
                        stage = arm
                        settings = states[arm]["settings"]
                        for endpoint in ("readiness", "documents", "jobs/" + settings["job_id"]):
                            raw, evidence = await request(
                                client,
                                "GET",
                                plan["arms"][arm]["url"] + "/library/" + endpoint,
                                headers[arm],
                            )
                            label = "job" if endpoint.startswith("jobs/") else endpoint
                            save(out / f"{arm}-before-{label}.body", raw)
                            save(out / f"{arm}-before-{label}.json", encode(evidence))
                            value = parsed(raw, evidence)
                            if endpoint == "readiness":
                                if (
                                    value.get("metadata_ready") is not True
                                    or value.get("mode") != "real"
                                    or value["chat_model"]["name"] != settings["chat_model"]
                                    or value["embedding_model"]["name"] != settings["embed_model"]
                                ):
                                    raise ResourceStop("Runtime readiness/model names do not match")
                            elif endpoint == "documents":
                                if (
                                    sha(encode(value))
                                    != states[arm]["settings"]["documents_sha256"]
                                ):
                                    raise ResourceStop(
                                        "Runtime documents differ from inspected snapshot"
                                    )
                                before_docs[arm] = value
                            else:
                                arm_proofs[arm] = await runtime_arm(
                                    peers,
                                    ownership["services"][arm + "-api"],
                                    settings,
                                    before_docs[arm],
                                    value,
                                    manifest,
                                )
                    if before_docs["baseline"] != before_docs["candidate"]:
                        raise ResourceStop("Runtime document records differ between arms")
                except (
                    ResourceStop,
                    KeyError,
                    ValueError,
                    TypeError,
                    OSError,
                    sqlite3.Error,
                    httpx.HTTPError,
                ) as error:
                    reason = str(error) if isinstance(error, ResourceStop) else type(error).__name__
                    raise ResourceStop(f"search preflight ({stage}): {reason}") from error
            save(
                out / "search-preflight.json",
                encode(
                    {
                        "status": "pass",
                        "arms": arm_proofs,
                        "snapshot_sha256": sha(raw_manifest),
                        "rendered_sha256": plan["rendered_sha256"],
                    }
                ),
            )
            monitor.check()
            if time.monotonic() - start >= NO_NEW_AFTER_SECONDS:
                raise ResourceStop("no-new-request deadline before campaign consumption")
            # Concurrent successful preflights race only here. O_EXCL permits one dispatcher.
            fresh_receipts(states, ownership)
            try:
                save(
                    ledger / "campaign.consumed.json",
                    encode(
                        {
                            "output": str(out),
                            "campaign_id": plan["campaign_id"],
                            "plan_sha256": sha(plan_raw),
                            "authorization_sha256": sha(authorization_raw),
                            "consumed_at": datetime.now(UTC).isoformat(),
                        }
                    ),
                )
            except FileExistsError as error:
                raise ResourceStop("campaign consumed by a concurrent dispatcher") from error
            consumed = True
            for ordinal, case in enumerate(questions, 1):
                first_evidence = None
                for position, arm in enumerate(arm_order(ordinal), 1):
                    monitor.check()
                    if time.monotonic() - start >= NO_NEW_AFTER_SECONDS:
                        raise TimeoutError("No-new-request deadline")
                    payload = encode(
                        {
                            "question": case["question"],
                            "top_k": 5,
                            "job_id": states[arm]["settings"]["job_id"],
                        }
                    )
                    stem = f"{case['id']}-{arm}"
                    save(
                        out / (stem + ".reserved.json"),
                        encode(
                            {
                                "id": case["id"],
                                "arm": arm,
                                "ordinal": ordinal,
                                "position_in_pair": position,
                                "request_sha256": sha(payload),
                                "reserved_at": datetime.now(UTC).isoformat(),
                                "retries": 0,
                            }
                        ),
                    )
                    if time.monotonic() - start >= NO_NEW_AFTER_SECONDS:
                        save(
                            out / (stem + ".undispatched.json"),
                            encode({"reason": "no-new-request deadline"}),
                        )
                        raise TimeoutError("No-new-request deadline")

                    def preserve_partial(body, status, stem=stem):
                        save(out / (stem + ".partial.body"), body)
                        save(out / (stem + ".partial.json"), encode(status))

                    raw, evidence = await request(
                        client,
                        "POST",
                        plan["arms"][arm]["url"] + "/library/ask",
                        headers[arm],
                        payload,
                        on_interrupt=preserve_partial,
                    )
                    save(out / (stem + ".body"), raw)
                    save(out / (stem + ".result.json"), encode(evidence))
                    value = parsed(raw, evidence)
                    if (
                        not isinstance(value.get("answer"), str)
                        or not isinstance(value.get("sources"), list)
                        or not isinstance(value.get("retrieval"), dict)
                    ):
                        raise TypeError("Invalid answer response shape")
                    if value.get("generation", {}).get("num_predict") != 1536:
                        raise ValueError("Response generation cap differs")
                    diagnostics = citation_diagnostics(value["answer"], value["sources"])
                    save(
                        out / (stem + ".review-needed.json"),
                        encode(
                            {
                                "citation_mapping": diagnostics,
                                "passage_retrieval": "UNREVIEWED",
                                "claim_support": "UNREVIEWED",
                                "omitted_conditions": "UNREVIEWED",
                                "correct_abstention": "UNREVIEWED",
                                "answer_grade": "UNREVIEWED",
                            }
                        ),
                    )
                    completed.append(stem)
                    returned = encode([value["sources"], value["retrieval"]])
                    if position == 1:
                        first_evidence = returned
                    elif first_evidence != returned:
                        raise ResourceStop("returned-source-or-retrieval-parity-mismatch")
            for arm in ARMS:
                raw, evidence = await request(
                    client, "GET", plan["arms"][arm]["url"] + "/library/documents", headers[arm]
                )
                save(out / f"{arm}-after-documents.body", raw)
                save(out / f"{arm}-after-documents.json", encode(evidence))
                if parsed(raw, evidence) != before_docs[arm]:
                    raise ValueError("Runtime document records changed")

    try:
        async with asyncio.timeout(BATCH_SECONDS):
            await monitor.supervise(dispatch)
        stop = None
    except ResourceStop as exc:
        stop = str(exc)
    except (ValueError, KeyError, TypeError, TimeoutError, httpx.HTTPError) as exc:
        stop = type(exc).__name__
    finally:
        if not consumed and not (out / "search-preflight.json").exists():
            save(
                out / "search-preflight.json",
                encode({"status": "failed", "reason": stop, "question_requests": 0}),
            )
        schedule = [
            f"{case['id']}-{arm}"
            for ordinal, case in enumerate(questions, 1)
            for arm in arm_order(ordinal)
        ]
        reservations = [stem for stem in schedule if (out / (stem + ".reserved.json")).is_file()]
        attempts = [
            stem for stem in reservations if not (out / (stem + ".undispatched.json")).exists()
        ]
        save(
            out / "summary.json",
            encode(
                {
                    "planned": len(questions) * 2,
                    "authorization_consumed": consumed,
                    "campaign_id": plan["campaign_id"],
                    "runner_commit": plan["runner"]["commit"],
                    "order": plan["order"],
                    "budget": plan["budget"],
                    "attempts_including_uncertain": attempts,
                    "unattempted": [stem for stem in schedule if stem not in attempts],
                    "completed": completed,
                    "stop": stop,
                    "unresolved_reservations": [
                        stem for stem in attempts if not (out / (stem + ".result.json")).exists()
                    ],
                    "elapsed_seconds": time.monotonic() - start,
                    "retries": 0,
                    "semantic_validation": "PENDING reviewer grading of every success and failure",
                    "runtime_settings": "Operator-inspected receipts; readiness cannot attest digests/settings",
                }
            ),
        )
        files = sorted(p for p in out.iterdir() if p.is_file())
        save(
            out / "SHA256SUMS",
            "".join(f"{sha(p.read_bytes())}  {p.name}\n" for p in files).encode(),
        )
    return 0 if stop is None else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--disk-path",
        type=Path,
        help="Mount on the guest filesystem backing experiment data (default: output filesystem)",
    )
    parser.add_argument("--execute-authorization", type=Path)
    parser.add_argument(
        "--check-resources",
        action="store_true",
        help="Metadata-only cgroup/disk preflight in the prepared runner",
    )
    args = parser.parse_args(argv)
    if args.check_resources and (args.execute_authorization or args.disk_path is None):
        parser.error("--check-resources needs --disk-path and cannot dispatch requests")
    if args.execute_authorization:
        if args.output is None:
            parser.error("Execution requires a NEW --output")
        return asyncio.run(
            compare(args.plan, args.execute_authorization, args.output, disk_path=args.disk_path)
        )
    plan, questions, _, ownership = load_plan(args.plan)
    if args.check_resources:
        print(
            json.dumps(Monitor(ownership["services"], None, args.disk_path).check(), sort_keys=True)
        )
        return 0
    print(
        json.dumps(
            {
                "mode": "offline-plan",
                "network_calls": 0,
                "questions_per_arm": len(questions),
                "planned_requests": 2 * len(questions),
                "order": plan["order"],
                "campaign_id": plan["campaign_id"],
                "runner_commit": plan["runner"]["commit"],
                "API_seconds": API_SECONDS,
                "batch_seconds": BATCH_SECONDS,
                "no_new_after_seconds": NO_NEW_AFTER_SECONDS,
                "execution_requires_separate_isolated_owner_authorization": True,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
