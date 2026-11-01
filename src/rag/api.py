"""Simple local-only authenticated RAG demonstration API."""

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .collection_safety import UnsafeCollectionError
from .config import Settings
from .core import RagEngine
from .documents import SUPPORTED_EXTENSIONS, parse_document, sanitize_document_filename

app = FastAPI(title="Enterprise RAG Platform", version="0.1.0")
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    route = request.scope.get("route")
    if request.method == "POST" and getattr(route, "path", None) == "/ingest/document":
        # The framework's default 422 includes rejected field input, which can
        # contain document text. Preserve other endpoints' existing contracts.
        return JSONResponse(status_code=422, content={"detail": "Invalid document upload"})
    return await request_validation_exception_handler(request, error)


@lru_cache
def settings() -> Settings:
    return Settings()


def authorize(x_api_key: str | None = Header(default=None)) -> None:
    expected = settings().api_key
    if (
        not expected
        or not x_api_key
        or not secrets.compare_digest(x_api_key.encode("utf-8"), expected.encode("utf-8"))
    ):
        raise HTTPException(status_code=401, detail="Invalid API key")


@lru_cache
def engine() -> RagEngine:
    return RagEngine(settings())


class IngestRequest(BaseModel):
    source: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=250_000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=10)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ingest", dependencies=[Depends(authorize)])
def ingest(request: IngestRequest):
    count = engine().ingest(request.text, request.source)
    return {"chunks_indexed": count, "source": request.source}


@app.post("/ask", dependencies=[Depends(authorize)])
def ask(request: AskRequest):
    return engine().ask(request.question, request.top_k)


@app.post("/ingest/document", dependencies=[Depends(authorize)])
async def ingest_document(file: Annotated[UploadFile, File()]):
    """Parse an upload with controlled errors; the size check is not a body/resource limit."""
    try:
        filename = sanitize_document_filename(file.filename or "")
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid filename") from error
    if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported document format")
    try:
        data = await file.read(MAX_DOCUMENT_BYTES + 1)
    except Exception as error:
        raise HTTPException(status_code=500, detail="Unable to read document upload") from error
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="Maximum upload size is 10 MiB")
    if not data:
        raise HTTPException(status_code=400, detail="Empty document")
    try:
        chunks = parse_document(data, filename)
    except (ImportError, LookupError) as error:
        raise HTTPException(status_code=503, detail="Document parser is unavailable") from error
    except ValueError as error:
        raise HTTPException(
            status_code=400, detail="Invalid document or no extractable text"
        ) from error
    except Exception as error:
        # Exception details may contain source text, paths or configuration.
        raise HTTPException(status_code=500, detail="Document processing failed") from error
    if not chunks:
        raise HTTPException(status_code=400, detail="Invalid document or no extractable text")
    try:
        count = engine().ingest_chunks(chunks)
    except UnsafeCollectionError as error:
        raise HTTPException(
            status_code=403, detail="Collection write policy forbids this operation"
        ) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail="Document ingestion failed") from error
    return {"source": filename, "chunks_indexed": count}
