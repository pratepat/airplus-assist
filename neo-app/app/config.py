"""Application configuration — reads from .env or environment variables."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


class Config:
    app_name: str              = os.getenv("APP_NAME", "AirPlus Assist")
    ollama_base_url: str       = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str          = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    embed_model: str           = os.getenv("EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
    rerank_model: str          = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
    documents_path: str        = os.getenv("DOCUMENTS_PATH", str(Path(__file__).parent.parent.parent / "docs"))
    top_k_retrieval: int       = int(os.getenv("TOP_K_RETRIEVAL", "15"))
    top_k_rerank: int          = int(os.getenv("TOP_K_RERANK", "5"))
    top_k_answer: int          = int(os.getenv("TOP_K_ANSWER", "3"))
    similarity_threshold: float = float(os.getenv("SIMILARITY_THRESHOLD", "0.30"))
    rerank_threshold: float    = float(os.getenv("RERANK_THRESHOLD", "-0.50"))
    translation_timeout: int   = int(os.getenv("TRANSLATION_TIMEOUT", "45"))
    chunk_size: int            = int(os.getenv("CHUNK_SIZE", "512"))
    chunk_overlap: int         = int(os.getenv("CHUNK_OVERLAP", "80"))
    host: str                  = os.getenv("HOST", "0.0.0.0")
    port: int                  = int(os.getenv("PORT", "8000"))


config = Config()
