from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # === Groq LLM ===
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_MAX_TOKENS: int = 1400
    GROQ_TEMPERATURE: float = 0.2

    # === Ollama Embeddings ===
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"

    # === Google Drive ===
    # Paste comma-separated folder or file IDs from Google Drive share links
    # Example: "1A2B3C4D5E,1X2Y3Z4W5V"
    GDRIVE_IDS: str = ""
    # For private Drive: path to service account JSON
    GDRIVE_SERVICE_ACCOUNT_JSON: str = ""

    # === Vector Store ===
    VECTORSTORE_PATH: str = "/data/vectorstore"
    DOCS_PATH: str = "/data/docs"

    # === RAG Settings ===
    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 100
    RETRIEVAL_TOP_K: int = 12
    MIN_RELEVANCE_SCORE: float = 0.18
    MAX_CONTEXT_CHUNKS: int = 12

    # === App ===
    APP_TITLE: str = "Приёмная комиссия — ИИ-помощник"
    AUTO_SYNC_ON_START: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
