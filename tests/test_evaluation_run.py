"""Authored synthetic CLI/HTTP flow only; services remain blocked by conftest."""

import json
import socket
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest

from evaluation import run, smoke
from rag import api, core


def config():
    return {
        "machine": "macbook-proposal",
        "api_url": "http://127.0.0.1:8000",
        "collection": "rag_eval_http_proposal_001",
        "embed_model": "synthetic-embed:plan-only",
        "chat_model": "synthetic-chat:plan-only",
        "embed_digest": "1" * 64,
        "chat_digest": "2" * 64,
    }


def test_fixture_is_deterministic_valid_three_page_pdf():
    from pypdf import PdfReader

    data = smoke.fixture_pdf()
    assert data == smoke.fixture_pdf()
    reader = PdfReader(BytesIO(data), strict=True)
    assert [p.extract_text().strip() for p in reader.pages] == list(smoke.FACTS)
    assert smoke.fixture_identity()["pages"] == 3


def test_real_routes_core_smoke_repeatable_and_restores_patches():
    original = (api.settings, api.engine, api.parse_document, core.httpx, socket.socket.connect)
    first = smoke.offline_http_smoke()
    assert first == smoke.offline_http_smoke()
    assert first["counts"] == {
        "stub_embeddings": 9,
        "stub_chats": 2,
        "stub_parser_passes": 2,
        "stub_searches": 3,
        "stub_points": 3,
    }
    assert len(first["checks"]) == 6
    assert original == (
        api.settings,
        api.engine,
        api.parse_document,
        core.httpx,
        socket.socket.connect,
    )


def test_fence_is_active_before_engine_construction(monkeypatch):
    def unsafe_constructor(*args, **kwargs):
        socket.create_connection(("127.0.0.1", 11434))

    monkeypatch.setattr(core, "RagEngine", unsafe_constructor)
    with pytest.raises(smoke.SmokeFailure):
        smoke.offline_http_smoke()


def test_fence_blocks_real_qdrant_and_restores_after_failure(monkeypatch):
    original = core.QdrantClient

    def unsafe_constructor(*args, **kwargs):
        core.QdrantClient(":memory:")

    monkeypatch.setattr(core, "RagEngine", unsafe_constructor)
    with pytest.raises(smoke.SmokeFailure):
        smoke.offline_http_smoke()
    assert core.QdrantClient is original


def test_cli_manifest_repeats_without_dates_paths_or_secrets(tmp_path, capsys):
    one, two = tmp_path / "one", tmp_path / "two"
    assert run.main(["--output", str(one)]) == run.main(["--output", str(two)]) == 0
    assert (one / "manifest.json").read_bytes() == (two / "manifest.json").read_bytes()
    manifest = json.loads((one / "manifest.json").read_text())
    assert manifest["mode"] == "offline" and manifest["status"] == "passed"
    assert manifest["real_operations"] == {
        "network_requests": 0,
        "model_calls": 0,
        "database_writes": 0,
    }
    assert "synthetic-smoke-only" not in (one / "manifest.json").read_text()
    assert str(tmp_path) not in (one / "manifest.json").read_text()
    assert manifest["provenance"]["code_sha256"]["src/rag/core.py"]
    assert "passed" in capsys.readouterr().out


def test_existing_output_refused_before_smoke(tmp_path, monkeypatch):
    runner = Mock()
    monkeypatch.setattr(run, "offline_http_smoke", runner)
    out = tmp_path / "existing"
    out.mkdir()
    (out / "preserved.txt").write_text("existing user work")
    with pytest.raises(SystemExit):
        run.main(["--output", str(out)])
    runner.assert_not_called()
    assert (out / "preserved.txt").read_text() == "existing user work"


def test_symlink_output_parent_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError):
        run.new_output(alias / "new")
    assert list(real.iterdir()) == []


def test_output_permissions_and_parent_traversal(tmp_path):
    out = tmp_path / "private"
    assert run.main(["--output", str(out)]) == 0
    assert out.stat().st_mode & 0o777 == 0o700
    assert (out / "manifest.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        run.new_output(tmp_path / ".." / "unused")


def test_provenance_rejects_another_checkout(monkeypatch):
    monkeypatch.setattr(
        run, "import_module", lambda name: Mock(__file__=str(Path("elsewhere.py").absolute()))
    )
    with pytest.raises(ValueError, match="this checkout"):
        run.provenance()


def test_failure_retains_sanitized_manifest_without_retry(tmp_path, monkeypatch):
    failure = Mock(side_effect=RuntimeError("SYNTHETIC_SECRET_DO_NOT_ECHO"))
    monkeypatch.setattr(run, "offline_http_smoke", failure)
    out = tmp_path / "failure"
    assert run.main(["--output", str(out)]) == 1
    data = (out / "manifest.json").read_text()
    assert json.loads(data)["status"] == "failed" and "SYNTHETIC_SECRET" not in data
    failure.assert_called_once()


def test_local_plan_writes_no_pass_claim_and_never_runs_http(tmp_path, monkeypatch):
    runner = Mock(side_effect=AssertionError("Must not execute HTTP"))
    monkeypatch.setattr(run, "offline_http_smoke", runner)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(config()))
    out = tmp_path / "planned"
    assert (
        run.main(["--mode", "local-plan", "--local-config", str(path), "--output", str(out)]) == 0
    )
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["status"] == "planned-not-executed"
    assert manifest["result"]["execution_allowed"] is False
    assert manifest["result"]["model_presence_verified"] is False
    assert manifest["result"]["collection_absence_verified"] is False
    runner.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"api_url": "https://example.invalid:8000"},
        {"api_url": "http://localhost:8000"},
        {"api_url": "http://user:secret@127.0.0.1:8000"},
        {"api_url": "http://127.0.0.1:8000?secret=x"},
        {"api_url": "http://127.0.0.1"},
        {"collection": "hdd_knowledge"},
        {"collection": "existing_data"},
        {"embed_digest": "0" * 64},
        {"chat_digest": "unpinned"},
        {"api_key": "never store credentials"},
        {"machine": "host; command"},
    ],
)
def test_local_plan_rejects_unsafe_or_ambiguous_config(changes):
    with pytest.raises(ValueError):
        run.local_plan(config() | changes)


def test_local_config_not_silently_used_in_offline_mode(tmp_path):
    with pytest.raises(SystemExit):
        run.main(["--local-config", "not-read.json", "--output", str(tmp_path / "unused")])
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize("content", ["[]", "{invalid-json", '{"machine": "only"}'])
def test_invalid_local_file_creates_no_output(tmp_path, content):
    path = tmp_path / "config.json"
    path.write_text(content)
    out = tmp_path / "unused"
    with pytest.raises(SystemExit):
        run.main(["--mode", "local-plan", "--local-config", str(path), "--output", str(out)])
    assert not out.exists()


def test_live_mode_is_not_available(tmp_path):
    with pytest.raises(SystemExit):
        run.main(["--mode", "local", "--output", str(tmp_path / "unused")])
    assert not (tmp_path / "unused").exists()


@pytest.mark.documents
def test_fixture_real_parser_preflight_only():
    from rag.documents import parse_document

    chunks = parse_document(smoke.fixture_pdf(), smoke.SOURCE)
    assert len(chunks) == 3
    assert [c.page_number for c in chunks] == [1, 2, 3]
    assert [c.text for c in chunks] == list(smoke.FACTS)
