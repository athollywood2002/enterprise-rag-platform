from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    ollama_url: str = "http://localhost:11434"
    qdrant_url: str = "http://localhost:6333"
    ollama_chat_model: str = "qwen3:8b"
    ollama_embed_model: str = "nomic-embed-text"
    qdrant_collection: str = "rag_documents_v1"
    api_key: str
