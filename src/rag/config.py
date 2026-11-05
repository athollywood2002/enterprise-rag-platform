import re

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .collection_safety import validate_writable_collection_name


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", validate_assignment=True)
    ollama_url: str = "http://localhost:11434"
    qdrant_url: str = "http://localhost:6333"
    ollama_chat_model: str = "qwen3:8b"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_num_predict: int | None = None
    qdrant_collection: str = "rag_documents_v1"
    api_key: str
    # Set to a persistent directory to enable the single-instance folder library.
    ingest_data_dir: str | None = None
    ingest_source_roots: dict[str, str] = Field(default_factory=dict)
    ingest_max_files: int = Field(default=500, ge=1, le=5000)
    ingest_max_file_bytes: int = Field(default=10 * 1024**2, ge=1, le=100 * 1024**2)
    ingest_max_batch_bytes: int = Field(default=100 * 1024**2, ge=1, le=1024**3)
    ingest_max_staged_bytes: int = Field(default=1024**3, ge=1)
    ingest_max_jobs: int = Field(default=100, ge=1, le=1000)
    ingest_max_documents: int = Field(default=5000, ge=1, le=10000)
    ingest_max_pages: int = Field(default=200, ge=1, le=2000)
    ingest_max_chars: int = Field(default=2_000_000, ge=100, le=10_000_000)
    ingest_max_chunks: int = Field(default=3000, ge=1, le=10000)
    ingest_upload_seconds: int = Field(default=120, ge=1, le=1800)
    ingest_parse_seconds: int = Field(default=30, ge=1, le=120)
    ingest_file_seconds: int = Field(default=300, ge=1, le=1800)

    @field_validator("ingest_source_roots")
    @classmethod
    def valid_source_roots(cls, roots):
        from pathlib import Path

        for name, path in roots.items():
            if (
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name)
                or not Path(path).is_absolute()
            ):
                raise ValueError("Source roots need stable labels and absolute container paths")
        return roots

    @field_validator("ollama_num_predict", mode="before")
    @classmethod
    def validate_generation_cap(cls, value: object) -> int | None:
        if value is None:
            return None
        # Accept decimal environment values, without int's bool/float coercion.
        if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
            value = int(value)
        if type(value) is not int or not 1 <= value <= 2_147_483_647:
            raise ValueError("OLLAMA_NUM_PREDICT must be an integer from 1 to 2147483647, or unset")
        return value

    @field_validator("qdrant_collection")
    @classmethod
    def validate_collection(cls, value: str) -> str:
        return validate_writable_collection_name(value)
