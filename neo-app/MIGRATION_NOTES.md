# MIGRATION NOTES — neo-app

## What was found in the original app

### Architecture
- 4 Docker containers: `ollama`, `chromadb`, `api` (FastAPI), `ui` (Streamlit)
- Separate `ingest` container (profile-gated, run manually)
- Documents in `docs/{product}/` folders
- Supported formats: PDF, DOCX, XLSX, TXT (Q&A auto-detect), URLs (urls.txt)

### RAG pipeline (`api/rag_chain.py`)
- Embedding: `paraphrase-multilingual-MiniLM-L12-v2` (multilingual, supports EN/DE/FR/ES/IT/NL)
- Retrieval: top-15 cosine search via ChromaDB
- Re-ranking: `cross-encoder/ms-marco-MiniLM-L-6-v2` (English) or mmarco variant
- Two-layer hallucination guard:
  - Layer 1: cosine similarity gate (threshold 0.30)
  - Layer 2: cross-encoder re-ranker gate (threshold -0.50)
- LLM: `qwen2.5:7b` via Ollama (temperature 0.1 for answers)
- Language: non-EN questions translated to EN for retrieval; answer delivered in requested language
- Contradiction detection: 3+ unique source files → `has_contradiction=True` + LLM prompt rule

### UI (`ui/app.py` — Streamlit, ~1650 lines)
- Two modes: Chat and Draft Reply
- Sidebar: logo, mode radio, language selector (6 languages), product filter, clear button, KB status
- Welcome state with 4 suggested question buttons
- SSE streaming with stage progress (searching → retrieved → generating)
- Confidence pills (high/medium/low/none)
- Contradiction warning banner
- Citation cards: primary (ranks 1-2, green border) + further reading (ranks 3+, collapsible)
- Summary feature per message (wider retrieval, 300-word synthesis)
- Draft Reply: email input → question extraction → per-question answers → generated reply
- Meta-answers (no API call) for how-to-use, not-satisfied, help-channels, tech-architecture
- Fallback banner when product filter yields no result

### API (`api/main.py`)
- Endpoints: `/ask`, `/ask/stream`, `/analyse`, `/generate_reply`, `/summary`, `/summary/stream`,
  `/health`, `/products`, `/languages`, `/stats`, `/ingest` (stub)

---

## What is preserved

| Feature | Status |
|---------|--------|
| Same embedding model | ✅ Preserved |
| Same re-ranking model | ✅ Preserved |
| Same hallucination guard (both layers, same thresholds) | ✅ Preserved |
| Same system prompt rules (no speculation, contradiction flag) | ✅ Preserved |
| Same chunking strategy (512/80, Excel row-based, Q&A detection) | ✅ Preserved |
| Same document format support (PDF/DOCX/XLSX/TXT/URL) | ✅ Preserved |
| Same product filtering via metadata | ✅ Preserved |
| Same language support + translation for retrieval | ✅ Preserved |
| Same API endpoints and response shapes | ✅ Preserved |
| Same UI layout, colors, controls | ✅ Reproduced in HTML/CSS/JS |
| Same confidence pills, citation cards, further reading | ✅ Reproduced |
| Same streaming progress stages | ✅ Reproduced |
| Same Draft Reply workflow | ✅ Reproduced |
| Same meta-answers (exact text) | ✅ Preserved |
| Same fallback banner for product filter miss | ✅ Preserved |
| Same summary feature | ✅ Preserved (non-streaming, simpler) |

---

## What is simplified

| Original | Neo-app |
|----------|---------|
| ChromaDB server (Docker container) | **In-memory numpy array** (cosine dot product on normalised vectors) |
| Streamlit frontend (~1650 lines) | **Vanilla HTML/CSS/JS** (static files served by FastAPI) |
| 4 Docker containers | **1 Python process** (`uvicorn app.main:app`) |
| Separate ingest container (manual run) | **Auto-ingest at startup** (same process) |
| SSE summary streaming | **Single POST /api/summary** (no streaming for summary — simpler JS) |
| `requirements/api.txt`, `ui.txt`, `ingest.txt` | **Single `requirements.txt`** |
| Pydantic settings / separate config per service | **Simple `Config` class with env vars + dotenv** |

---

## Intentional deviations

### 1. Cross-encoder model
The original CLAUDE.md specifies `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (multilingual).
The original `rag_chain.py` code actually uses `cross-encoder/ms-marco-MiniLM-L-6-v2` (English).

**Decision:** Use the same model as the running code (`ms-marco-MiniLM-L-6-v2`).
This is configurable via `RERANK_MODEL` in `.env` — change to the mmarco variant if desired.

### 2. Summary streaming removed
The original app had `/summary/stream` (SSE). In neo-app, summary uses a regular POST.
The UI shows a spinner while loading. This simplifies both server and client code substantially
without any functional loss — the user still gets the full summary.

### 3. `/summary/stream` and `/languages` and `/stats` endpoints removed
These were either unused by the new UI or trivial. They can be added back if needed.
`/api/health` and `/api/products` are preserved.

### 4. Model-level embedding cache
Both ingest and RAG share the same SentenceTransformer instance via a module-level dict cache.
This avoids loading the 400MB model twice at startup.

### 5. Contradiction threshold
The original uses `>= 3 unique source files` as the contradiction heuristic (conservative).
Neo-app preserves this exact heuristic.

---

## Anti-hallucination guard — unchanged

Both gates are preserved with identical defaults:

| Gate | Threshold | Behaviour |
|------|-----------|-----------|
| Cosine similarity (Layer 1) | 0.30 | Blocks if top cosine score < 0.30 |
| Re-ranker score (Layer 2) | -0.50 | Blocks if top cross-encoder score < -0.50 |

If either gate blocks, the LLM is never called and the response is:
> "I don't have enough information in my knowledge base to answer this question."

The system prompt also contains Layer 3 (prompt-level): contradiction detection rules and
grounding instructions ("Never use prior knowledge. Never speculate.").

**Do not raise RERANK_THRESHOLD above -0.25** without re-running gate calibration tests.
