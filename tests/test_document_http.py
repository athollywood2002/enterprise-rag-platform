"""In-process HTTP contract tests; never construct a real ingestion engine."""

import asyncio
import builtins
import threading
from importlib.util import find_spec
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag import api
from rag.collection_safety import UnsafeCollectionError
from rag.config import Settings
from rag.documents import SUPPORTED_EXTENSIONS, DocumentChunk, parse_document

UPLOAD_LIMIT = 10 * 1024 * 1024
DIAGNOSTIC = "SYNTHETIC_INTERNAL_DIAGNOSTIC_DO_NOT_ECHO"


@pytest.fixture
def http(monkeypatch):
    config = Settings(
        _env_file=None,
        api_key="synthetic-http-test-only",
        qdrant_collection="rag_http_unit_test",
        qdrant_url="http://qdrant.invalid:6333",
        ollama_url="http://ollama.invalid:11434",
    )
    monkeypatch.setattr(api, "settings", lambda: config)
    parser = Mock(side_effect=lambda data, name: [DocumentChunk("Synthetic fact.", name, 0, 1)])
    ingestion = Mock(spec=["ingest_chunks"])
    ingestion.ingest_chunks.side_effect = len
    factory = Mock(return_value=ingestion)
    monkeypatch.setattr(api, "parse_document", parser)
    monkeypatch.setattr(api, "engine", factory)
    # Keep the default raise_server_exceptions=True: unhandled failures must fail tests.
    with TestClient(api.app) as client:
        yield SimpleNamespace(
            client=client,
            parser=parser,
            ingestion=ingestion,
            factory=factory,
            headers={"x-api-key": config.api_key},
        )


def upload(http, data=b"synthetic upload", filename="fixture.pdf", headers=None):
    return http.client.post(
        "/ingest/document",
        headers=http.headers if headers is None else headers,
        files={"file": (filename, data, "application/octet-stream")},
    )


def no_ingestion(http):
    http.factory.assert_not_called()
    http.ingestion.ingest_chunks.assert_not_called()


@pytest.mark.parametrize("headers", [{}, {"x-api-key": ""}, {"x-api-key": "wrong"}])
def test_authentication_rejects_before_parser_or_engine(http, headers):
    response = upload(http, headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid API key"}
    http.parser.assert_not_called()
    no_ingestion(http)


def test_non_ascii_authentication_is_controlled(http):
    response = upload(http, headers={b"x-api-key": b"\xff"})
    assert response.status_code == 401
    http.parser.assert_not_called()
    no_ingestion(http)


@pytest.mark.parametrize("extension", sorted(SUPPORTED_EXTENSIONS) + [".PDF"])
def test_allowed_extension_reaches_ingestion(http, extension):
    filename = "fixture" + extension
    response = upload(http, filename=filename)
    assert response.status_code == 200
    assert response.json() == {"source": filename, "chunks_indexed": 1}
    http.parser.assert_called_once_with(b"synthetic upload", filename)
    http.factory.assert_called_once_with()
    assert http.ingestion.ingest_chunks.call_args.args[0][0].source == filename


@pytest.mark.parametrize("filename", ["fixture.exe", "fixture.zip", "fixture", "fixture.pdf.exe"])
def test_unsupported_extension_never_parses_or_indexes(http, filename):
    response = upload(http, filename=filename)
    assert response.status_code == 415
    assert response.json() == {"detail": "Unsupported document format"}
    http.parser.assert_not_called()
    no_ingestion(http)


def test_empty_upload_is_controlled(http):
    response = upload(http, data=b"")
    assert response.status_code == 400
    assert response.json() == {"detail": "Empty document"}
    http.parser.assert_not_called()
    no_ingestion(http)


@pytest.mark.parametrize("size", [UPLOAD_LIMIT - 1, UPLOAD_LIMIT, UPLOAD_LIMIT + 1])
def test_upload_size_boundary(http, size):
    response = upload(http, data=b"x" * size)
    if size > UPLOAD_LIMIT:
        assert response.status_code == 413
        assert response.json() == {"detail": "Maximum upload size is 10 MiB"}
        http.parser.assert_not_called()
        no_ingestion(http)
    else:
        assert response.status_code == 200
        assert len(http.parser.call_args.args[0]) == size
        http.ingestion.ingest_chunks.assert_called_once()


@pytest.mark.parametrize("files", [None, {"other": ("fixture.pdf", b"synthetic")}])
def test_missing_file_field_is_422(http, files):
    response = http.client.post("/ingest/document", headers=http.headers, files=files)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid document upload"}
    http.parser.assert_not_called()
    no_ingestion(http)


def test_wrong_file_field_type_does_not_echo_input(http):
    response = http.client.post("/ingest/document", headers=http.headers, data={"file": DIAGNOSTIC})
    assert response.status_code == 422
    assert DIAGNOSTIC not in response.text
    assert response.json() == {"detail": "Invalid document upload"}
    http.parser.assert_not_called()
    no_ingestion(http)


def test_other_endpoint_validation_contract_is_unchanged(http):
    response = http.client.post("/ingest", headers=http.headers, json={})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    no_ingestion(http)


def test_mounted_document_route_keeps_validation_opaque(http):
    parent = FastAPI()
    parent.mount("/synthetic-prefix", api.app)
    with TestClient(parent) as client:
        response = client.post(
            "/synthetic-prefix/ingest/document", headers=http.headers, data={"file": DIAGNOSTIC}
        )
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid document upload"}
    assert DIAGNOSTIC not in response.text
    http.parser.assert_not_called()
    no_ingestion(http)


@pytest.mark.parametrize(
    "filename", ["../../fixture.pdf", r"C:\synthetic\fixture.pdf", "fixture.pdf"]
)
def test_response_and_parser_receive_only_basename(http, filename):
    response = upload(http, filename=filename)
    assert response.status_code == 200
    assert response.json()["source"] == "fixture.pdf"
    assert http.parser.call_args.args[1] == "fixture.pdf"
    assert http.ingestion.ingest_chunks.call_args.args[0][0].source == "fixture.pdf"


def test_control_character_filename_is_rejected(http):
    # Multipart builders percent-encode control bytes; send literal wire bytes
    # to exercise server-side control-character handling, not builder behavior.
    body = (
        b'--synthetic-boundary\r\nContent-Disposition: form-data; name="file"; '
        b'filename="fixture.pdf\x00"\r\nContent-Type: application/pdf\r\n\r\n'
        b"synthetic\r\n--synthetic-boundary--\r\n"
    )
    response = http.client.post(
        "/ingest/document",
        headers={
            **http.headers,
            "content-type": "multipart/form-data; boundary=synthetic-boundary",
        },
        content=body,
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid filename"}
    http.parser.assert_not_called()
    no_ingestion(http)


def test_encoded_control_filename_is_not_decoded_into_supported_extension(http):
    response = upload(http, filename="fixture.pdf%00")
    assert response.status_code == 415
    http.parser.assert_not_called()
    no_ingestion(http)


@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (ValueError(DIAGNOSTIC), 400, "Invalid document or no extractable text"),
        (ImportError(DIAGNOSTIC), 503, "Document parser is unavailable"),
        (ModuleNotFoundError(DIAGNOSTIC), 503, "Document parser is unavailable"),
        (LookupError(DIAGNOSTIC), 503, "Document parser is unavailable"),
        (KeyError(DIAGNOSTIC), 500, "Document processing failed"),
        (IndexError(DIAGNOSTIC), 500, "Document processing failed"),
        (RuntimeError(DIAGNOSTIC), 500, "Document processing failed"),
    ],
)
def test_parser_errors_are_sanitized(http, error, status, detail):
    http.parser.side_effect = error
    response = upload(http)
    assert response.status_code == status
    assert response.json() == {"detail": detail}
    assert DIAGNOSTIC not in response.text and "Traceback" not in response.text
    no_ingestion(http)


def test_missing_optional_parser_is_controlled(http, monkeypatch):
    # Base-only environments exercise real absence. Full parser environments
    # simulate the same import failure so this regression always runs.
    if find_spec("unstructured") is not None:
        original_import = builtins.__import__

        def no_parser(name, *args, **kwargs):
            if name == "unstructured" or name.startswith("unstructured."):
                raise ModuleNotFoundError(DIAGNOSTIC)
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_parser)
    monkeypatch.setattr(api, "parse_document", parse_document)
    response = upload(http, data=b"A synthetic text fact.", filename="fixture.txt")
    assert response.status_code == 503
    assert response.json() == {"detail": "Document parser is unavailable"}
    assert DIAGNOSTIC not in response.text and "Traceback" not in response.text
    no_ingestion(http)


def test_empty_parser_result_never_indexes(http):
    http.parser.side_effect = None
    http.parser.return_value = []
    response = upload(http)
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid document or no extractable text"}
    no_ingestion(http)


def test_provenance_is_passed_unchanged_to_ingestion(http):
    chunks = [
        DocumentChunk("Synthetic page one fact.", "fixture.pdf", 0, 1),
        DocumentChunk("Synthetic page two fact.", "fixture.pdf", 1, 2),
        DocumentChunk("Synthetic unknown-page fact.", "fixture.pdf", 2, None),
    ]
    http.parser.side_effect = None
    http.parser.return_value = chunks
    response = upload(http)
    assert response.json() == {"source": "fixture.pdf", "chunks_indexed": 3}
    http.ingestion.ingest_chunks.assert_called_once_with(chunks)
    assert http.ingestion.ingest_chunks.call_args.args[0] is chunks


def test_collection_policy_rejection_is_controlled(http):
    http.ingestion.ingest_chunks.side_effect = UnsafeCollectionError(DIAGNOSTIC)
    response = upload(http)
    assert response.status_code == 403
    assert response.json() == {"detail": "Collection write policy forbids this operation"}
    assert DIAGNOSTIC not in response.text


def test_ingestion_failure_is_sanitized(http):
    http.ingestion.ingest_chunks.side_effect = RuntimeError(DIAGNOSTIC)
    response = upload(http)
    assert response.status_code == 500
    assert response.json() == {"detail": "Document ingestion failed"}
    assert DIAGNOSTIC not in response.text and "Traceback" not in response.text


def test_upload_read_failure_is_sanitized(http, monkeypatch):
    async def fail_read(*args, **kwargs):
        raise OSError(DIAGNOSTIC)

    monkeypatch.setattr("starlette.datastructures.UploadFile.read", fail_read)
    response = upload(http)
    assert response.status_code == 500
    assert response.json() == {"detail": "Unable to read document upload"}
    assert DIAGNOSTIC not in response.text
    http.parser.assert_not_called()
    no_ingestion(http)


def test_parsing_and_ingestion_run_off_event_loop(http, monkeypatch):
    from starlette.datastructures import UploadFile

    threads = {}
    original_read = UploadFile.read

    async def read(file, *args, **kwargs):
        asyncio.get_running_loop()  # Upload reading stays in the async route.
        threads["read"] = threading.get_ident()
        return await original_read(file, *args, **kwargs)

    def parser(data, name):
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        threads["parse"] = threading.get_ident()
        return [DocumentChunk("Synthetic fact.", name, 0, 1)]

    def ingest(chunks):
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        threads["ingest"] = threading.get_ident()
        return len(chunks)

    monkeypatch.setattr(UploadFile, "read", read)
    http.parser.side_effect = parser
    http.ingestion.ingest_chunks.side_effect = ingest
    response = upload(http)
    assert response.status_code == 200
    assert threads["read"] != threads["parse"] == threads["ingest"]


def test_health_can_complete_while_parser_is_waiting(http):
    started = threading.Event()
    release = threading.Event()

    def parser(data, name):
        started.set()
        assert release.wait(timeout=3), "Parser was not released while health completed"
        return [DocumentChunk("Synthetic fact.", name, 0, 1)]

    http.parser.side_effect = parser

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app), base_url="http://testserver"
        ) as client:
            task = asyncio.create_task(
                client.post(
                    "/ingest/document",
                    headers=http.headers,
                    files={"file": ("fixture.pdf", b"synthetic")},
                )
            )
            try:
                assert await asyncio.to_thread(started.wait, 1)
                response = await asyncio.wait_for(client.get("/health"), timeout=1)
                assert response.status_code == 200
                assert not task.done(), "Upload must still be waiting for parser release"
            finally:
                release.set()
                result = await asyncio.wait_for(task, timeout=3)
            assert result.status_code == 200

    asyncio.run(exercise())


@pytest.mark.documents
@pytest.mark.parametrize("kind", ["malformed", "truncated", "textless", "encrypted"])
def test_real_invalid_pdf_http_contract(http, monkeypatch, kind):
    from pypdf import PdfWriter

    if kind == "malformed":
        data = b"not a PDF"
    elif kind == "truncated":
        data = b"%PDF-1.4\ntruncated"
    else:
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        if kind == "encrypted":
            writer.encrypt("synthetic-fixture-only")
        buffer = BytesIO()
        writer.write(buffer)
        data = buffer.getvalue()
    monkeypatch.setattr(api, "parse_document", parse_document)
    response = upload(http, data=data)
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid document or no extractable text"}
    no_ingestion(http)


@pytest.mark.documents
def test_real_two_page_provenance_reaches_ingestion(http, monkeypatch, pdf_factory):
    facts = (
        "The synthetic lunar station stores exactly eleven copper mirrors.",
        "The synthetic river station stores exactly twenty-nine blue lanterns.",
    )
    monkeypatch.setattr(api, "parse_document", parse_document)
    response = upload(http, data=pdf_factory(facts), filename=r"C:\synthetic\two-page.pdf")
    assert response.status_code == 200
    assert response.json()["source"] == "two-page.pdf"
    chunks = http.ingestion.ingest_chunks.call_args.args[0]
    assert response.json()["chunks_indexed"] == len(chunks) > 0
    for page, fact in enumerate(facts, 1):
        hits = [chunk for chunk in chunks if fact in chunk.text]
        assert hits and all(chunk.page_number == page for chunk in hits)
        assert all(facts[2 - page] not in chunk.text for chunk in hits)
    assert all(chunk.source == "two-page.pdf" for chunk in chunks)
