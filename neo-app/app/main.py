"""
AirPlus Assist — neo-app main entry point.

Boot order:
  1. HTTP server binds immediately — browser can connect at once
  2. Ingest + model loading runs in a background task
  3. GET / shows a "Starting up…" page with auto-refresh until ready
  4. Once ready, the full UI is served
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import config
from .ingest import IngestSummary, ingest_documents
from .models import (
    AskRequest,
    AskResponse,
    AnalyseRequest,
    GenerateReplyRequest,
    SummaryRequest,
)
from .rag import RagPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent

_ingest_summary: IngestSummary | None = None
_pipeline: RagPipeline | None = None
_startup_error: str | None = None


async def _run_startup() -> None:
    """Ingest documents into Azure AI Search and build the RAG pipeline."""
    global _ingest_summary, _pipeline, _startup_error
    try:
        loop = asyncio.get_event_loop()

        log.info("Step 1/2 — Ingesting documents into Azure AI Search …")
        _ingest_summary = await loop.run_in_executor(None, ingest_documents, config.documents_path)

        if _ingest_summary.total == 0:
            log.warning("No documents found — add files to DOCUMENTS_PATH and restart.")
            return

        log.info("Step 2/2 — Building RAG pipeline (%d chunks) …", _ingest_summary.total)
        _pipeline = await loop.run_in_executor(None, RagPipeline, _ingest_summary)

        log.info("=== Ready — %d chunks, %d product(s) ===",
                 _ingest_summary.total, len(_ingest_summary.products))
    except Exception as exc:
        _startup_error = str(exc)
        log.exception("Startup failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("=== AirPlus Assist (neo-app) starting — documents path: %s ===",
             config.documents_path)
    # Fire-and-forget: server binds immediately, startup runs in background
    asyncio.create_task(_run_startup())
    yield
    log.info("=== Shutting down ===")


app = FastAPI(title="AirPlus Assist", version="2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _require() -> RagPipeline:
    if _pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="RAG pipeline is not available. "
                   "Ensure documents exist in DOCUMENTS_PATH and restart the app.",
        )
    return _pipeline


# ── Frontend ───────────────────────────────────────────────────────────────────

_STARTING_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta http-equiv="refresh" content="3"/>
  <title>AirPlus Assist — Starting…</title>
  <style>
    body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
         background:#F0FAF4;display:flex;align-items:center;justify-content:center;height:100vh;}
    .box{text-align:center;padding:40px;}
    .logo{font-size:28px;font-weight:700;color:#1A1A2E;letter-spacing:-.5px;}
    .sub{font-size:14px;color:#4B5563;letter-spacing:1.5px;margin-top:2px;}
    .msg{margin-top:32px;font-size:15px;color:#1A1A2E;}
    .detail{margin-top:8px;font-size:13px;color:#6B7280;}
    .dot{display:inline-block;width:10px;height:10px;border-radius:50%;
         background:#00B050;margin:0 3px;animation:bounce 1.2s infinite;}
    .dot:nth-child(2){animation-delay:.2s;}
    .dot:nth-child(3){animation-delay:.4s;}
    @keyframes bounce{0%,80%,100%{transform:translateY(0)}40%{transform:translateY(-8px)}}
  </style>
</head>
<body>
  <div class="box">
    <div class="logo">AirPlus</div>
    <div class="sub">ASSIST</div>
    <div class="msg">
      <span class="dot"></span><span class="dot"></span><span class="dot"></span>
      <br><br>Loading knowledge base…
    </div>
    <div class="detail">Ingesting documents into Azure AI Search.<br>This takes about 10–20 seconds.</div>
  </div>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # Show a self-refreshing startup page while models are loading
    if _pipeline is None and _startup_error is None:
        return HTMLResponse(_STARTING_PAGE, status_code=200)

    if _startup_error:
        return HTMLResponse(
            f"<h2>Startup error</h2><pre>{_startup_error}</pre>", status_code=500
        )

    products    = _ingest_summary.products    if _ingest_summary else []
    chunk_count = _ingest_summary.total       if _ingest_summary else 0
    ingested_at = _ingest_summary.ingested_at if _ingest_summary else ""
    return templates.TemplateResponse(request, "index.html", {
        "products":    products,
        "chunk_count": chunk_count,
        "ingested_at": ingested_at,
        "chat_model":  config.azure_openai_chat_model,
    })


# ── Health & meta ──────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "status":      "ok" if _pipeline else "no_documents",
        "chat_model":  config.azure_openai_chat_model,
        "embed_model": config.azure_openai_embed_model,
        "search_index": config.azure_search_index,
        "chunk_count": _ingest_summary.total       if _ingest_summary else 0,
        "products":    _ingest_summary.products    if _ingest_summary else [],
        "ingested_at": _ingest_summary.ingested_at if _ingest_summary else "",
    }


@app.get("/api/products")
async def products():
    return {"products": _ingest_summary.products if _ingest_summary else []}


# ── Ask ────────────────────────────────────────────────────────────────────────

@app.post("/api/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    pipeline = _require()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, pipeline.ask, req.question, req.product, req.language
    )


@app.post("/api/ask/stream")
async def ask_stream(req: AskRequest):
    pipeline = _require()

    async def generate():
        async for chunk in pipeline.ask_stream(req.question, req.product, req.language):
            yield chunk

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Analyse / Reply ────────────────────────────────────────────────────────────

@app.post("/api/analyse")
async def analyse(req: AnalyseRequest):
    pipeline = _require()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, pipeline.analyse, req.text, req.product, req.language, req.max_questions
    )


@app.post("/api/generate_reply")
async def generate_reply(req: GenerateReplyRequest):
    pipeline = _require()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, pipeline.generate_reply, req.original_text, req.answered_results, req.language
    )


# ── Summary ────────────────────────────────────────────────────────────────────

@app.post("/api/summary")
async def summary(req: SummaryRequest):
    pipeline = _require()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, pipeline.generate_summary, req.question, req.product, req.language
    )
