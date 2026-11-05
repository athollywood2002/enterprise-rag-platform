"""Authenticated folder ingestion endpoints; reusable from n8n HTTP nodes."""

import asyncio
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .folder_parser import DocumentError
from .source_roots import browse


class FileSpec(BaseModel):
    path: str = Field(max_length=1024)
    size: int = Field(ge=0, strict=True)


class Selection(BaseModel):
    mode: Literal["browser", "server"]
    source: str = Field(min_length=1, max_length=64)
    folder: str = Field(default="", max_length=1024)
    files: list[FileSpec] = Field(default_factory=list, max_length=5000)


class ReviewedSelection(Selection):
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=10)
    job_id: str | None = Field(default=None, max_length=32)


def routes(authorize, manager):
    router = APIRouter(prefix="/library", dependencies=[Depends(authorize)])

    @router.get("/config")
    def config():
        return manager().public_config()

    @router.get("/browse")
    def folders(root: str, path: str = ""):
        lib = manager()
        return {
            "root": root,
            "path": path,
            "entries": browse(lib.source_root(root), path, lib.config.ingest_max_files),
        }

    @router.post("/preview")
    def preview(selection: Selection):
        return manager().preview(**selection.model_dump())

    @router.post("/jobs", status_code=201)
    def create(selection: ReviewedSelection):
        return manager().create(**selection.model_dump())

    @router.get("/jobs")
    def jobs():
        return manager().list_jobs()

    @router.get("/jobs/{job}")
    def status(job: str):
        return manager().get_job(job)

    @router.put("/jobs/{job}/files/{file_id}")
    async def upload(job: str, file_id: str, request: Request):
        lib = manager()
        row = lib.begin_upload(job, file_id)
        path = lib.staging / (file_id + ".upload")
        try:
            size = 0
            # Raw stream avoids multipart spooling before authentication/limits.
            async with asyncio.timeout(lib.config.ingest_upload_seconds):
                with path.open("wb") as stream:
                    async for data in request.stream():
                        size += len(data)
                        if size > row["size"] or size > lib.config.ingest_max_file_bytes:
                            raise DocumentError(
                                "size_mismatch",
                                "Upload exceeds its declared size or configured limit.",
                            )
                        stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            if size != row["size"]:
                raise DocumentError(
                    "size_mismatch",
                    "Upload size differs from the preview. Select the folder again.",
                )
            # Cancellation may arrive while this upload was in flight.
            if lib.get_job(job)["cancel"]:
                raise DocumentError("cancelled", "Upload cancelled.")
            lib.finish_upload(file_id, path)
        except TimeoutError as error:
            lib.set_file(file_id, "failed", "upload_timeout", "Upload timed out. Retry the file.")
            raise HTTPException(408, "Upload timed out. Retry the file.") from error
        except DocumentError as error:
            lib.set_file(
                file_id,
                "cancelled" if error.code == "cancelled" else "failed",
                error.code,
                str(error),
            )
            raise
        except BaseException:
            lib.set_file(
                file_id, "failed", "upload_failed", "Upload failed. Retry and reselect this file."
            )
            raise
        finally:
            path.unlink(missing_ok=True)
        return {"status": "staged", "bytes": size, "ready_to_search": False}

    @router.post("/jobs/{job}/start")
    def start(job: str):
        return manager().start_job(job)

    @router.post("/jobs/{job}/cancel")
    def cancel(job: str):
        return manager().cancel(job)

    @router.post("/jobs/{job}/retry")
    def retry(job: str):
        return manager().retry(job)

    @router.get("/documents")
    def documents():
        return manager().documents()

    @router.post("/ask")
    def ask(question: Question):
        try:
            return manager().ask(question.question, question.top_k, question.job_id)
        except DocumentError:
            raise
        except Exception as error:
            raise HTTPException(
                503, "Search service unavailable. Check Ollama and Qdrant."
            ) from error

    return router


def install(app, authorize, manager):
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    @app.exception_handler(DocumentError)
    async def document_error(request, error):
        return JSONResponse(
            status_code=404 if error.code == "not_found" else 400,
            content={"detail": str(error), "code": error.code},
        )

    from .web_limits import WebLimits

    app.add_middleware(WebLimits)
    app.include_router(routes(authorize, manager))
    web = Path(__file__).parent / "web"
    app.mount("/ui", StaticFiles(directory=web), name="ui")

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(web / "index.html", headers={"Cache-Control": "no-store"})
