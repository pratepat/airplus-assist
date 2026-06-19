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
from .ingest import IngestSummary, ingest_documents, get_index_document_count, download_from_blob
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
_ingest_running: bool = False


def _build_summary_from_index() -> IngestSummary:
    """Reconstruct IngestSummary from the live index without re-ingesting."""
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    sc = SearchClient(
        endpoint=config.azure_search_endpoint,
        index_name=config.azure_search_index,
        credential=AzureKeyCredential(config.azure_search_key),
    )
    count_result = sc.search(search_text="*", top=0, include_total_count=True)
    total = count_result.get_count() or 0
    # Collect distinct product names without relying on facets (works with old indexes too)
    products: set[str] = set()
    ingested_at = ""
    for doc in sc.search(search_text="*", top=1000, select=["product", "ingested_at"]):
        if doc.get("product"):
            products.add(doc["product"])
        if not ingested_at and doc.get("ingested_at"):
            ingested_at = doc["ingested_at"]
    summary = IngestSummary()
    summary.products, summary.total, summary.ingested_at = sorted(products), total, ingested_at
    return summary


def _run_ingest_from_blob() -> IngestSummary:
    """Download docs from Blob to a temp dir and run ingest_documents()."""
    import tempfile
    import shutil
    tmp = tempfile.mkdtemp(prefix="airplus-ingest-")
    try:
        if download_from_blob(Path(tmp)) == 0:
            log.warning("Blob container is empty — nothing to ingest.")
            return IngestSummary()
        return ingest_documents(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        log.info("Temp ingest dir cleaned up")


async def _run_startup() -> None:
    """Check index population; skip ingest if already loaded, otherwise download from Blob."""
    global _ingest_summary, _pipeline, _startup_error
    try:
        loop = asyncio.get_event_loop()

        log.info("Step 1/2 — Checking Azure AI Search index …")
        doc_count = await loop.run_in_executor(None, get_index_document_count)

        if doc_count > 0:
            log.info("Index has %d document(s) — skipping ingest, building pipeline …", doc_count)
            _ingest_summary = await loop.run_in_executor(None, _build_summary_from_index)
        else:
            log.info("Index is empty — downloading from Blob Storage and ingesting …")
            _ingest_summary = await loop.run_in_executor(None, _run_ingest_from_blob)

        if not _ingest_summary or _ingest_summary.total == 0:
            log.warning("No documents found. Upload files to Blob Storage and call POST /api/ingest.")
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
    log.info("=== AirPlus Assist (neo-app) starting — blob container: %s ===",
             config.azure_storage_container)
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
                   "Ensure documents are in Azure Blob Storage and call POST /api/ingest.",
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
    <div class="detail">Loading knowledge base from Azure AI Search.<br>This takes about 3–10 seconds.</div>
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
        "status":         "ingesting" if _ingest_running else ("ok" if _pipeline else "no_documents"),
        "ingest_running": _ingest_running,
        "chat_model":     config.azure_openai_chat_model,
        "embed_model":    config.azure_openai_embed_model,
        "search_index":   config.azure_search_index,
        "chunk_count":    _ingest_summary.total       if _ingest_summary else 0,
        "products":       _ingest_summary.products    if _ingest_summary else [],
        "ingested_at":    _ingest_summary.ingested_at if _ingest_summary else "",
    }


@app.post("/api/ingest", status_code=202)
async def trigger_ingest():
    """Trigger a full re-ingest from Azure Blob Storage (runs in background)."""
    global _ingest_running, _ingest_summary, _pipeline, _startup_error

    if _ingest_running:
        raise HTTPException(status_code=409, detail="Ingest already in progress.")

    async def _do_ingest():
        global _ingest_running, _ingest_summary, _pipeline, _startup_error
        _ingest_running = True
        try:
            loop = asyncio.get_event_loop()
            summary = await loop.run_in_executor(None, _run_ingest_from_blob)
            if summary.total > 0:
                _ingest_summary = summary
                _pipeline = await loop.run_in_executor(None, RagPipeline, summary)
                log.info("Ingest complete via /api/ingest — %d chunks", summary.total)
            else:
                log.warning("/api/ingest: no chunks produced (blob container empty?)")
        except Exception as exc:
            _startup_error = str(exc)
            log.exception("/api/ingest failed: %s", exc)
        finally:
            _ingest_running = False

    asyncio.create_task(_do_ingest())
    return {"status": "accepted", "message": "Ingest started. Monitor via GET /api/health."}


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
