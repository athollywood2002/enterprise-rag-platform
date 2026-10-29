"""Simple local-only authenticated RAG demonstration API."""
from functools import lru_cache
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import Settings
from .core import RagEngine

app = FastAPI(title="Enterprise RAG Platform", version="0.1.0")


@lru_cache
def settings() -> Settings:
    return Settings()


def authorize(x_api_key: str | None = Header(default=None)) -> None:
    expected = settings().api_key
    if not expected or not x_api_key or not secrets.compare_digest(x_api_key, expected):
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
