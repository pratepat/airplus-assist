"""Application configuration — reads from .env or environment variables."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


class Config:
    app_name: str = os.getenv("APP_NAME", "AirPlus Assist")

    # ── Azure OpenAI ───────────────────────────────────────────────────────────
    azure_openai_endpoint: str    = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    azure_openai_api_key: str     = os.getenv("AZURE_OPENAI_API_KEY", "")
    azure_openai_embed_model: str = os.getenv("AZURE_OPENAI_EMBED_MODEL", "text-embedding-3-small")
    azure_openai_chat_model: str  = os.getenv("AZURE_OPENAI_CHAT_MODEL", "gpt-4o-mini")
    azure_openai_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")

    # ── Azure AI Search ────────────────────────────────────────────────────────
    azure_search_endpoint: str = os.getenv("AZURE_SEARCH_ENDPOINT", "")
    azure_search_key: str      = os.getenv("AZURE_SEARCH_KEY", "")
    azure_search_index: str    = os.getenv("AZURE_SEARCH_INDEX", "airplus-assist")

    # ── Azure Blob Storage ─────────────────────────────────────────────────────
    azure_storage_connection: str = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
    azure_storage_container: str  = os.getenv("AZURE_STORAGE_CONTAINER", "content")

    # ── Documents (local path for ingest) ─────────────────────────────────────
    documents_path: str = os.getenv("DOCUMENTS_PATH", str(Path(__file__).parent.parent.parent / "docs"))

    # ── Retrieval tuning ───────────────────────────────────────────────────────
    top_k_retrieval: int            = int(os.getenv("TOP_K_RETRIEVAL", "15"))
    top_k_rerank: int               = int(os.getenv("TOP_K_RERANK", "5"))
    top_k_answer: int               = int(os.getenv("TOP_K_ANSWER", "3"))

    # ── Hallucination gate thresholds (Azure Semantic Ranking: 0–4 scale) ─────
    # Do NOT raise RERANK_THRESHOLD above 1.5 without re-running gate tests.
    rerank_threshold: float         = float(os.getenv("RERANK_THRESHOLD", "0.8"))
    stage1_quality_threshold: float = float(os.getenv("STAGE1_QUALITY_THRESHOLD", "2.0"))

    # ── Chunking ───────────────────────────────────────────────────────────────
    chunk_size: int    = int(os.getenv("CHUNK_SIZE", "512"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "80"))

    # ── Server ─────────────────────────────────────────────────────────────────
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))


config = Config()
