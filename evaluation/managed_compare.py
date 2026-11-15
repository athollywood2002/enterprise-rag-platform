"""One-shot, reviewer-run isolated HTTP comparison. Default mode is offline plan only."""

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from evaluation.grounding import citation_diagnostics
from evaluation.run import new_output

API_SECONDS = 300
BATCH_SECONDS = 3600
NO_NEW_AFTER_SECONDS = 3270
MAX_BYTES = 8 * 1024 * 1024
ARMS = ("baseline", "candidate")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode()


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
        "questions",
        "questions_sha256",
        "freeze_sha256",
        "arms",
        "custodian_receipt",
        "custodian_receipt_sha256",
    }:
        raise ValueError("Plan needs question export, frozen bundle and custodian receipt pins")
    receipt_raw = (path.parent / plan["custodian_receipt"]).read_bytes()
    if sha(receipt_raw) != plan["custodian_receipt_sha256"]:
        raise ValueError("Custodian receipt hash mismatch")
    receipt = json.loads(receipt_raw)
    questions_raw = (path.parent / plan["questions"]).read_bytes()
    if sha(questions_raw) != plan["questions_sha256"]:
        raise ValueError("Question bytes differ from frozen reviewer export")
    questions = json.loads(questions_raw)
    if not isinstance(questions, list) or not 8 <= len(questions) <= 12:
        raise ValueError("Require 8–12 frozen held-out questions")
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
                "shared_services",
                "settings",
                "observed_at",
                "inspection",
            }
            or not isinstance(state.get("inspection"), str)
            or not state["inspection"].strip()
            or state.get("isolated") is not True
            or state.get("deployment") is not False
            or state.get("shared_services") is not False
            or not re.fullmatch(r"[a-f0-9]{40}", state.get("git_commit", ""))
        ):
            raise ValueError("Need explicit isolated/nondeployed/nonshared inspected state")
        settings = state["settings"]
        if set(settings) != {
            "think",
            "num_predict",
            "model_timeout_seconds",
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
            or type(settings["top_k"]) is not int
            or settings["top_k"] != 5
            or not isinstance(settings["job_id"], str)
            or not settings["job_id"].strip()
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
    return plan, questions, states


async def request(client, method, url, headers, raw=None):
    body, status, complete, error = bytearray(), None, False, None
    start = time.monotonic()
    try:
        # Total wall deadline includes connection, headers, body and slow trickles.
        async with asyncio.timeout(API_SECONDS):
            async with client.stream(method, url, headers=headers, content=raw) as response:
                status = response.status_code
                async for chunk in response.aiter_bytes():
                    body.extend(chunk[: MAX_BYTES - len(body)])
                    if len(body) >= MAX_BYTES:
                        raise ValueError("Response byte ceiling reached")
                complete = True
    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
        error = type(exc).__name__  # Never log headers/exception text containing secrets.
    return bytes(body), {
        "status": status,
        "HTTP_response_received": status is not None,
        "no_HTTP_response": status is None,
        "empty_HTTP_body": complete and status is not None and not body,
        "body_complete": complete,
        "error_type": error,
        "elapsed_seconds": time.monotonic() - start,
        "raw_body_bytes": len(body),
        "raw_body_sha256": sha(body),
    }


def parsed(raw, result):
    if result["error_type"] or result["status"] != 200 or not result["body_complete"]:
        raise ValueError("HTTP request failed; stop, never resend")
    return json.loads(raw)


async def compare(plan_path, authorization_path, output, *, transport=None):
    plan_raw = plan_path.read_bytes()
    plan, questions, states = load_plan(plan_path, raw=plan_raw)
    authorization_raw = authorization_path.read_bytes()
    authorization = json.loads(authorization_raw)
    if (
        set(authorization)
        != {"owner_reference", "plan_sha256", "isolated_execution_authorized", "ledger_dir"}
        or not authorization["owner_reference"].strip()
        or authorization["isolated_execution_authorized"] is not True
        or authorization["plan_sha256"] != sha(plan_raw)
    ):
        raise ValueError("Separate owner authorization must pin this exact isolated plan")
    for state in states.values():
        observed = datetime.fromisoformat(state["observed_at"])
        if observed.tzinfo is None:
            raise ValueError("State receipt timestamps must include a timezone")
        age = (datetime.now(UTC) - observed).total_seconds()
        if not 0 <= age <= 900:
            raise ValueError("Inspected state receipts must be timezone-aware and <15min old")
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
    # Consume authorization BEFORE any network access, even if metadata fails.
    save(
        ledger / (sha(encode(authorization)) + ".consumed.json"),
        encode(
            {
                "output": str(out),
                "plan_sha256": sha(plan_raw),
                "consumed_at": datetime.now(UTC).isoformat(),
            }
        ),
    )
    save(out / "plan.json", plan_raw)
    save(out / "authorization.json", authorization_raw)
    for name, path_key, hash_key in (
        ("questions.json", "questions", "questions_sha256"),
        ("custodian-receipt.json", "custodian_receipt", "custodian_receipt_sha256"),
    ):
        raw = (plan_path.parent / plan[path_key]).read_bytes()
        if sha(raw) != plan[hash_key]:
            raise ValueError("Pinned input changed before dispatch; authorization remains consumed")
        save(out / name, raw)
    save(out / "state-receipts.json", encode(states))
    save(
        out / "runner-source-hashes.json",
        encode(
            {
                name: sha((Path(__file__).parent / name).read_bytes())
                for name in ("managed_compare.py", "grounding.py", "run.py")
            }
        ),
    )
    start = time.monotonic()
    completed, stop, sources_by_case = [], "INTERRUPTED_OR_UNCERTAIN", {}
    headers = {arm: {"X-API-Key": keys[arm], "Content-Type": "application/json"} for arm in ARMS}
    try:
        async with asyncio.timeout(BATCH_SECONDS):
            async with httpx.AsyncClient(
                transport=transport or httpx.AsyncHTTPTransport(retries=0),
                timeout=API_SECONDS,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                before_docs = {}
                for arm in ARMS:
                    for endpoint in ("readiness", "documents"):
                        raw, evidence = await request(
                            client,
                            "GET",
                            plan["arms"][arm]["url"] + "/library/" + endpoint,
                            headers[arm],
                        )
                        save(out / f"{arm}-before-{endpoint}.body", raw)
                        save(out / f"{arm}-before-{endpoint}.json", encode(evidence))
                        value = parsed(raw, evidence)
                        if endpoint == "readiness":
                            settings = states[arm]["settings"]
                            if (
                                value.get("metadata_ready") is not True
                                or value.get("mode") != "real"
                                or value["chat_model"]["name"] != settings["chat_model"]
                                or value["embedding_model"]["name"] != settings["embed_model"]
                            ):
                                raise ValueError("Runtime readiness/model names do not match")
                        else:
                            if sha(encode(value)) != states[arm]["settings"]["documents_sha256"]:
                                raise ValueError("Runtime documents differ from inspected snapshot")
                            before_docs[arm] = value
                if before_docs["baseline"] != before_docs["candidate"]:
                    raise ValueError("Runtime document records differ between arms")
                for case in questions:
                    for arm in ARMS:
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
                                    "request_sha256": sha(payload),
                                    "reserved_at": datetime.now(UTC).isoformat(),
                                    "retries": 0,
                                }
                            ),
                        )
                        raw, evidence = await request(
                            client,
                            "POST",
                            plan["arms"][arm]["url"] + "/library/ask",
                            headers[arm],
                            payload,
                        )
                        save(out / (stem + ".body"), raw)
                        save(out / (stem + ".result.json"), encode(evidence))
                        value = parsed(raw, evidence)
                        if not isinstance(value.get("answer"), str) or not isinstance(
                            value.get("sources"), list
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
                        if arm == "baseline":
                            sources_by_case[case["id"]] = (value["sources"], value.get("retrieval"))
                        elif sources_by_case[case["id"]] != (
                            value["sources"],
                            value.get("retrieval"),
                        ):
                            raise ValueError(
                                "Returned excerpts/retrieval differ; comparison confounded"
                            )
                for arm in ARMS:
                    raw, evidence = await request(
                        client, "GET", plan["arms"][arm]["url"] + "/library/documents", headers[arm]
                    )
                    save(out / f"{arm}-after-documents.body", raw)
                    save(out / f"{arm}-after-documents.json", encode(evidence))
                    if parsed(raw, evidence) != before_docs[arm]:
                        raise ValueError("Runtime document records changed")
                stop = None
    except (ValueError, KeyError, TypeError, TimeoutError, httpx.HTTPError) as exc:
        stop = type(exc).__name__
    finally:
        save(
            out / "summary.json",
            encode(
                {
                    "planned": len(questions) * 2,
                    "completed": completed,
                    "stop": stop,
                    "unresolved_reservations": [
                        p.name.removesuffix(".reserved.json")
                        for p in sorted(out.glob("*.reserved.json"))
                        if not p.with_name(
                            p.name.replace(".reserved.json", ".result.json")
                        ).exists()
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
    parser.add_argument("--execute-authorization", type=Path)
    args = parser.parse_args(argv)
    if args.execute_authorization:
        if args.output is None:
            parser.error("Execution requires a NEW --output")
        return asyncio.run(compare(args.plan, args.execute_authorization, args.output))
    _, questions, _ = load_plan(args.plan)
    print(
        json.dumps(
            {
                "mode": "offline-plan",
                "network_calls": 0,
                "questions_per_arm": len(questions),
                "planned_requests": 2 * len(questions),
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
