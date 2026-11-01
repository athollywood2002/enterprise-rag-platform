from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .collection_safety import validate_writable_collection_name


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", validate_assignment=True)
    ollama_url: str = "http://localhost:11434"
    qdrant_url: str = "http://localhost:6333"
    ollama_chat_model: str = "qwen3:8b"
    ollama_embed_model: str = "nomic-embed-text"
    qdrant_collection: str = "rag_documents_v1"
    api_key: str

    @field_validator("qdrant_collection")
    @classmethod
    def validate_collection(cls, value: str) -> str:
        return validate_writable_collection_name(value)
