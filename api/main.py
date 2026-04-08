from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import chromadb
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

load_dotenv()

from models import AskRequest, AskResponse, AnalyseRequest, GenerateReplyRequest, GenerateReplyResponse, IngestStatus, SummaryRequest, SummaryResponse
from rag_chain import RagChain

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger(__name__)

# Module-level chain instance — populated on startup
_chain: RagChain | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _chain
    embed_model  = os.environ.get("EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
    ollama_model = os.environ.get("OLLAMA_MODEL", "phi3:mini")
    log.info("AirPlus Assist API starting up…")
    log.info("Embedding model : %s", embed_model)
    log.info("Ollama model    : %s", ollama_model)
    try:
        _chain = RagChain()
        log.info("AirPlus Assist API ready")
    except Exception as exc:
        log.warning("RagChain init failed (ChromaDB may not be ready yet): %s", exc)
        _chain = None
    yield
    # shutdown — nothing to clean up


app = FastAPI(
    title="AirPlus Assist API",
    description="AI FAQ assistant — answers from your documents, never from thin air",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _chroma_client():
    return chromadb.HttpClient(
        host=os.environ["CHROMA_HOST"],
        port=int(os.environ["CHROMA_PORT"]),
    )


def _require_chain() -> RagChain:
    """Return the chain or raise 503 with a clear message."""
    global _chain
    if _chain is None:
        # Try lazy init — ChromaDB may have become ready after startup
        try:
            _chain = RagChain()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"RAG chain not ready: {exc}",
            )
    return _chain


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    ollama_model    = os.environ.get("OLLAMA_MODEL", "unknown")
    collection_name = os.environ.get("CHROMA_COLLECTION", "unknown")
    chroma_ok       = True
    chunk_count     = 0
    last_ingested   = "Unknown"
    try:
        client     = _chroma_client()
        client.heartbeat()
        collection = client.get_collection(collection_name)
        chunk_count = collection.count()
        results = collection.get(
            limit=1,
            include=["metadatas"],
            where={"ingested_at": {"$ne": ""}},
        )
        if results["metadatas"]:
            last_ingested = results["metadatas"][0].get("ingested_at", "Unknown")
    except Exception:
        chroma_ok = False

    if not chroma_ok:
        raise HTTPException(
            status_code=503,
            detail={"status": "degraded", "chromadb": "unreachable"},
        )
    return {
        "status":        "ok",
        "model":         ollama_model,
        "collection":    collection_name,
        "chunk_count":   chunk_count,
        "last_ingested": last_ingested,
    }


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")
    chain = _require_chain()
    return chain.ask(
        question=req.question.strip(),
        product=req.product,
        language=req.language,
    )


@app.get("/languages")
def languages():
    """Return the supported language codes and the default."""
    from models import SUPPORTED_LANGUAGES
    return {"languages": SUPPORTED_LANGUAGES, "default": "EN"}


@app.get("/products")
def products():
    """Return distinct product values currently stored in ChromaDB."""
    try:
        client     = _chroma_client()
        collection = client.get_collection(os.environ["CHROMA_COLLECTION"])
        # Fetch all metadatas in pages to extract distinct products
        # ChromaDB does not have a distinct-values API, so we fetch metadata only
        result     = collection.get(include=["metadatas"], limit=10_000)
        seen: set[str] = set()
        for meta in result["metadatas"]:
            p = meta.get("product")
            if p:
                seen.add(p)
        return {"products": sorted(seen)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ChromaDB unavailable: {exc}")


@app.post("/ask/stream")
def ask_stream(req: AskRequest):
    """Streaming version of /ask — yields SSE stage events then the final result."""
    chain = _require_chain()

    def generate():
        yield from chain.ask_streaming(
            question=req.question.strip(),
            product=req.product,
            language=req.language,
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/analyse")
def analyse(req: AnalyseRequest):
    if not req.text.strip():
        raise HTTPException(status_code=422, detail="Text cannot be empty")
    if len(req.text) > 5000:
        raise HTTPException(status_code=422, detail="Text too long — maximum 5000 characters")
    chain = _require_chain()
    return chain.analyse(
        text=req.text,
        product=req.product,
        language=req.language,
        max_questions=req.max_questions,
    )


@app.post("/generate_reply", response_model=GenerateReplyResponse)
def generate_reply(req: GenerateReplyRequest):
    if not req.answered_results:
        raise HTTPException(status_code=422, detail="No answered results provided")
    chain = _require_chain()
    reply = chain.generate_reply(
        original_text=req.original_text,
        answered_results=req.answered_results,
        language=req.language,
    )
    return GenerateReplyResponse(
        reply=reply,
        questions_included=len(req.answered_results),
        questions_excluded=0,
        excluded_questions=[],
    )


@app.post("/summary", response_model=SummaryResponse)
def summary(req: SummaryRequest):
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")
    chain = _require_chain()
    result = chain.generate_summary(
        question=req.question.strip(),
        product=req.product,
        language=req.language,
    )
    return SummaryResponse(**result)


@app.post("/summary/stream")
def summary_stream(req: SummaryRequest):
    """Streaming version of /summary — yields SSE stage events then the final result."""
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")
    chain = _require_chain()

    def generate():
        yield from chain.generate_summary_streaming(
            question=req.question.strip(),
            product=req.product,
            language=req.language,
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/stats")
def stats():
    """Return total chunk count in ChromaDB."""
    try:
        client = _chroma_client()
        collection = client.get_collection(os.environ.get("CHROMA_COLLECTION", "airplus_assist"))
        count = collection.count()
        return {
            "total_chunks": count,
            "collection": os.environ.get("CHROMA_COLLECTION", "airplus_assist"),
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"ChromaDB error: {str(e)}")


@app.post("/ingest", response_model=IngestStatus)
def ingest():
    """Ingest runs as a separate container — return clear guidance."""
    return IngestStatus(
        status="error",
        message=(
            "Ingest service runs separately. "
            "Use: docker compose --profile ingest "
            "run --rm ingest python build_vectorstore.py"
        ),
    )
