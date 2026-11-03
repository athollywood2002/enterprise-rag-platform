import re

from pydantic import field_validator
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
