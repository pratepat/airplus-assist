# AirPlus Assist — neo-app

A single-process reimplementation of AirPlus Assist.
Same RAG pipeline, same hallucination guard, same UI appearance — dramatically simpler architecture.

## What it does

Answers questions about AirPlus products strictly from official documentation,
with precise source citations and a two-layer hallucination guard that prevents
the LLM from speculating or using prior knowledge.

## Architecture

```
docs/{product}/          ← your documents (PDF, DOCX, XLSX, TXT, URLs)
      │
      ▼ (at startup, cached to disk)
  ingest.py              parse → chunk → embed → in-memory numpy store
      │
      ▼
  rag.py                 cosine search → re-rank → LLM → answer + citations
      │
      ▼
  main.py (FastAPI)      GET /  → vanilla HTML/CSS/JS frontend
                         POST /api/ask
                         POST /api/ask/stream   (SSE)
                         POST /api/analyse
                         POST /api/generate_reply
                         POST /api/summary
```

**One process. No Docker required. No external databases.**

## Quick start

### 1. Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai) accessible (local or remote) with your model pulled:
  ```bash
  ollama pull qwen3:8b
  ```

### 2. Install

```bash
cd neo-app
pip install -r requirements.txt
```

The first run downloads the embedding and re-ranker models from HuggingFace (~500 MB total).

### 3. Configure

```bash
cp .env.example .env
# Edit .env — at minimum set OLLAMA_BASE_URL, OLLAMA_MODEL, DOCUMENTS_PATH
```

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `qwen2.5:7b` | LLM model (qwen3:8b recommended) |
| `EMBED_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | Multilingual sentence transformer |
| `RERANK_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder re-ranker |
| `DOCUMENTS_PATH` | `../docs` | Path to folder containing product sub-folders |
| `TOP_K_RETRIEVAL` | `15` | Initial retrieval candidates |
| `TOP_K_RERANK` | `5` | Candidates passed to re-ranker |
| `TOP_K_ANSWER` | `3` | Final chunks sent to LLM |
| `SIMILARITY_THRESHOLD` | `0.30` | Cosine gate — Layer 1 hallucination guard |
| `RERANK_THRESHOLD` | `-0.50` | Re-ranker gate — Layer 2 hallucination guard |
| `CHUNK_SIZE` | `512` | Token chunk size for text splitting |
| `CHUNK_OVERLAP` | `80` | Overlap between chunks |
| `TRANSLATION_TIMEOUT` | `45` | Seconds before translation request times out |

> **Do not raise `RERANK_THRESHOLD` above `-0.25`** without re-running gate tests.
> The margin between the weakest valid answer (-0.17) and the strongest invalid answer (-1.24) is 1.07 points.

> **Do not change `EMBED_MODEL`** after first ingest without deleting `.cache/` and re-ingesting.
> Embeddings must match the model used at ingest time.

### 4. Add documents

Place documents in the `docs/` folder (wherever `DOCUMENTS_PATH` points):

```
docs/
  airplus_intelligence/
    data_dictionary.xlsx
    user_guide.pdf
    faq.txt
  portal/
    limits_and_controls.txt
    faq.txt
    urls.txt        ← one URL per line, fetched at ingest time
```

Products are detected automatically from folder names — no code changes needed.

### 5. Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

With auto-reload during development (restarts on file changes):
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000`. While models are loading, a "Starting…" page is shown
that auto-refreshes every 3 seconds — the browser connects immediately, no waiting.

## Startup behaviour

Startup runs as a background task so the server binds and accepts connections immediately.

```
Step 1/3 — Ingest documents (or load from disk cache)
Step 2/3 — Build RAG pipeline
Step 3/3 — Warm up embed + re-ranker models (pre-warm PyTorch JIT)
=== Ready ===
```

**Disk cache** (`neo-app/.cache/ingest_cache.pkl`) stores the embeddings between runs.
If no documents changed, startup skips the embed step and loads from cache in ~2 seconds
instead of 30–60 seconds. The cache is invalidated automatically when any document file
changes, or when `EMBED_MODEL`, `CHUNK_SIZE`, or `CHUNK_OVERLAP` changes.

## Retrieval pipeline

```
Question
  → translate to EN (if non-EN, via Ollama)
  → embed with paraphrase-multilingual-MiniLM
  → cosine similarity search (top 15)
  → Layer 1 gate: cosine ≥ 0.30, else → "I don't have enough information"
  → cross-encoder re-rank (top 5)
  → Layer 2 gate: rerank score ≥ -0.50, else → "I don't have enough information"
  → build context with source labels
  → LLM (Ollama) with grounding prompt
  → structured response with citations
```

## Document formats

| Format | Chunking strategy |
|--------|------------------|
| PDF | Page-aware recursive split, 512 tokens |
| DOCX | Heading-aware recursive split, 512 tokens |
| XLSX | One row = one chunk (never split mid-row) |
| TXT (Q&A) | One Q+A pair = one chunk (auto-detected by `\nQ:` count) |
| TXT (other) | Recursive split, 512 tokens |
| `urls.txt` | URL fetched via trafilatura, then recursive split |

## UI features

- **Ask** — question answering with streaming SSE response and source citations
- **Analyse** — paste a customer message, extracts distinct questions and answers each
- **Draft Reply** — generates a professional reply email from analysed answers
- **Summary** — produces a structured knowledge summary for a topic
- Product filter — restrict answers to a single product folder
- Language selector — EN / DE / FR / ES / IT / NL (non-EN questions translated before retrieval)
- Confidence indicator — High / Medium / Low / None based on re-ranker score

## Simplifications vs the original

| Original | neo-app |
|----------|---------|
| 4 Docker containers | 1 Python process |
| ChromaDB (separate service) | In-memory numpy vectors + disk cache |
| Streamlit UI | Vanilla HTML / CSS / JS |
| Separate ingest container | Auto-ingest at startup |
| 3 `requirements*.txt` files | 1 `requirements.txt` |

## What is preserved from the original

- Embedding model — multilingual, supports EN / DE / FR / ES / IT / NL
- Two-layer hallucination guard (cosine gate + re-ranker gate)
- System prompt rules — no prior knowledge, contradiction flagging
- Chunking strategy — 512/80 tokens, Excel row-based, Q&A auto-detection
- All five document formats
- Product filtering by metadata
- Language selection and question translation
- Citation card structure and confidence levels

See `MIGRATION_NOTES.md` for full detail on architectural decisions and trade-offs.
