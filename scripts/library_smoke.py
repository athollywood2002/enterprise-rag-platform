"""Inside-image integration: real API, parser, SQLite and Qdrant; synthetic Ollama."""

import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from demo.library_fixtures import text_pdf

BASE = "http://127.0.0.1:8000"
HEADERS = {"x-api-key": os.environ["API_KEY"]}


def request(method, path, **kwargs):
    with httpx.Client(timeout=120) as client:
        response = client.request(method, BASE + path, headers=HEADERS, **kwargs)
        response.raise_for_status()
        return response.json()


def stage(files, source="container-smoke"):
    selection = {
        "mode": "browser",
        "source": source,
        "files": [{"path": p, "size": len(data)} for p, data in files.items()],
    }
    job = create_job(selection)
    for file in job["files"]:
        if file["status"] == "pending":
            response = request(
                "PUT", f"/library/jobs/{job['id']}/files/{file['id']}", content=files[file["path"]]
            )
            assert response["ready_to_search"] is False
    return job["id"]


def create_job(selection):
    preview = request("POST", "/library/preview", json=selection)
    return request(
        "POST", "/library/jobs", json=selection | {"preview_digest": preview["preview_digest"]}
    )


def wait(job, target=None, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = request("GET", f"/library/jobs/{job}")
        if target and any(f["status"] == target for f in result["files"]):
            return result
        if not target and result["status"] in {"completed", "completed_with_errors", "cancelled"}:
            return result
        time.sleep(0.2)
    raise AssertionError("Job did not reach expected state before deadline")


def office_smoke():
    from demo.office_fixtures import office_files

    formats = request("GET", "/library/config")["formats"]
    original = office_files(formats)
    changed = office_files(formats, "replacement")
    assert set(original) == {f[1:] for f in formats if f in {".docx", ".rtf", ".pptx", ".xlsx"}}
    for extension, data in original.items():
        source = "office-" + extension
        path = "nested/same." + extension
        job = stage({path: data}, source)
        request("POST", f"/library/jobs/{job}/start")
        assert wait(job)["counts"]["successful"] == 1
        answer = request(
            "POST",
            "/library/ask",
            json={
                "question": "What is the recovery code and who owns it?",
                "top_k": 10,
                "job_id": job,
            },
        )
        assert answer["sources"] and all(s.get("location") for s in answer["sources"])
        assert all(s["page_number"] is None for s in answer["sources"])
        if extension == "pptx":
            assert all(s["slide_number"] == 1 for s in answer["sources"])
        if extension == "xlsx":
            assert all(s["sheet_name"] == "Assets" and s["cell_range"] for s in answer["sources"])
            comparison = request(
                "POST",
                "/library/ask",
                json={
                    "question": "Compare Gatehouse SSO and Beacon security RTOs and RPOs.",
                    "top_k": 5,
                    "job_id": job,
                },
            )
            rows = {s["row"]: s for s in comparison["sources"] if s.get("row_kind") == "data"}
            assert {4, 5} <= rows.keys()
            for row in (4, 5):
                assert rows[row]["header_row"] == 3
                assert rows[row]["header_range"] == "A3:E3"
                assert "RTO hours" in rows[row]["text"] and "RPO minutes" in rows[row]["text"]
            assert '"E RPO minutes": "0"' in rows[4]["text"]
            assert '"E RPO minutes": "5"' in rows[5]["text"]
        again = stage({path: data}, source)
        request("POST", f"/library/jobs/{again}/start")
        assert wait(again)["counts"]["skipped"] == 1
        new = stage({path: changed[extension]}, source)
        request("POST", f"/library/jobs/{new}/start")
        assert wait(new)["counts"]["successful"] == 1
        before = {d["id"]: d["revision"] for d in request("GET", "/library/documents")["documents"]}
        bad = stage({path: b"corrupt"}, source)
        request("POST", f"/library/jobs/{bad}/start")
        assert wait(bad)["counts"]["failed"] == 1
        after = {d["id"]: d["revision"] for d in request("GET", "/library/documents")["documents"]}
        assert before == after
    return sorted(original)


def run():
    readiness = request("GET", "/library/readiness")
    assert readiness["mode"] == "synthetic"
    assert readiness["metadata_ready"] and not readiness["inference_tested"]
    with httpx.Client() as client:
        assert client.get(BASE + "/library/jobs").status_code == 401
        assert client.get(BASE + "/").status_code == 200
        assert "Content-Security-Policy" in client.get(BASE + "/").headers
    files = {
        "demo/runbook.txt": b"The recovery code for demo-router-01 is ORION.",
        "demo/inventory.csv": b"asset,owner\ndemo-router-01,NetworkOps\n",
        "demo/a/same.txt": b"First nested document.",
        "demo/b/same.txt": b"Second nested document.",
        "demo/two-page.pdf": text_pdf(
            "The cobalt observatory stores seventeen brass telescopes.",
            "The amber greenhouse grows forty-three violet orchids.",
        ),
        "demo/excluded.exe": b"unsupported",
    }
    job = stage(files)
    request("POST", f"/library/jobs/{job}/start")
    done = wait(job)
    assert done["counts"] == {
        "successful": 5,
        "failed": 0,
        "skipped": 1,
        "cancelled": 0,
        "pending": 0,
    }, done
    answer = request(
        "POST",
        "/library/ask",
        json={"question": "What is the recovery code and who owns it?", "top_k": 10, "job_id": job},
    )
    assert "ORION" in answer["answer"] and "NetworkOps" in answer["answer"]
    assert answer["generation"]["status"] == "complete"
    assert answer["model_mode"] == "synthetic"
    assert len({s["source"] for s in answer["sources"]}) == 5
    pdf = request(
        "POST",
        "/library/ask",
        json={"question": "How many brass telescopes are there?", "top_k": 10, "job_id": job},
    )
    import re

    cite = int(re.search(r"\[(\d+)\]", pdf["answer"])[1])
    assert pdf["sources"][cite - 1]["page_number"] == 1
    assert pdf["sources"][cite - 1]["source"].endswith("two-page.pdf")
    second = stage(files)
    request("POST", f"/library/jobs/{second}/start")
    assert wait(second)["counts"]["skipped"] == 6
    changed = stage({"demo/a/same.txt": b"Changed nested document."})
    request("POST", f"/library/jobs/{changed}/start")
    assert wait(changed)["counts"]["successful"] == 1
    failed = stage(
        {"demo/runbook.txt": b"SIMULATE_EMBED_FAILURE", "demo/broken.pdf": b"%PDF-broken"}
    )
    request("POST", f"/library/jobs/{failed}/start")
    assert wait(failed)["counts"]["failed"] == 2
    answer = request(
        "POST",
        "/library/ask",
        json={"question": "What is the recovery code and who owns it?", "top_k": 10},
    )
    assert "ORION" in answer["answer"]  # previous committed revision survived
    assert any(s["text"] == "Changed nested document." for s in answer["sources"])
    assert not any(s["text"] == "First nested document." for s in answer["sources"])
    cancelled = stage({"demo/cancel.txt": b"Do not process."})
    assert request("POST", f"/library/jobs/{cancelled}/cancel")["status"] == "cancelled"
    request("POST", f"/library/jobs/{cancelled}/retry")
    assert wait(cancelled)["counts"]["successful"] == 1
    # Source-root preview and copy run through the same parser/worker, under a read-only mount.
    config = request("GET", "/library/config")
    if "fixture-root" in config["roots"]:
        server = create_job({"mode": "server", "source": "fixture-root"})
        assert wait(server["id"])["counts"]["successful"] == 2
    office_formats = office_smoke()
    print(
        json.dumps(
            {
                "office_formats": office_formats,
                "result": "PASS",
                "scope": "real container/API/parsers/Qdrant; synthetic model responses",
                "formats": ["txt", "csv", "text-pdf"],
                "answer": pdf,
            }
        )
    )


def seed_restart():
    pending = stage({"restart/pending.txt": b"Pending upload is fully staged."}, "restart-fixture")
    working = stage({"restart/working.txt": b"WAIT_FOR_RESTART"}, "restart-fixture")
    request("POST", f"/library/jobs/{working}/start")
    wait(working, "embedding")
    Path("/data/restart-smoke.json").write_text(
        json.dumps({"pending": pending, "working": working})
    )
    print("Restart seed ready; worker is embedding, second job is staged but not started.")


def check_restart():
    jobs = json.loads(Path("/data/restart-smoke.json").read_text())
    working = request("GET", "/library/jobs/" + jobs["working"])
    assert working["files"][0]["status"] == "failed" and working["files"][0]["code"] in {
        "interrupted",
        "service_error",
    }, working
    pending = request("GET", "/library/jobs/" + jobs["pending"])
    assert pending["status"] == "uploading" and pending["files"][0]["staged"]
    request("POST", f"/library/jobs/{pending['id']}/start")
    assert wait(pending["id"])["counts"]["successful"] == 1
    request("POST", f"/library/jobs/{working['id']}/retry")
    assert wait(working["id"])["counts"]["successful"] == 1
    print("PASS: restart is explicit, staged uploads recover, interrupted file retry commits once.")


if __name__ == "__main__":
    {"run": run, "seed-restart": seed_restart, "check-restart": check_restart}[
        sys.argv[1] if len(sys.argv) > 1 else "run"
    ]()
