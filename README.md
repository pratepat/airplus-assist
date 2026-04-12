# AirPlus Assist

> AI-powered FAQ assistant for AirPlus products.  
> Answers from your documents. Always with sources.

---

## What it does

AirPlus Assist is a fully local, privacy-first RAG 
(Retrieval-Augmented Generation) assistant that:

- Answers questions in plain language from official 
  AirPlus product documentation
- Cites the exact source document, page, and section 
  for every answer
- Supports 6 languages: EN · DE · FR · ES · IT · NL
- Never answers from prior knowledge — hallucination 
  guard blocks out-of-domain questions
- Analyses incoming emails/chats and drafts replies
- Generates comprehensive summaries from the full 
  knowledge base

**No data leaves AirPlus infrastructure. All AI 
processing is local.**

---

## Features

| Feature | Description |
|---------|-------------|
| 💬 Chat | Ask questions, get sourced answers |
| 📋 Complete Summary | Wider retrieval, deeper synthesis |
| 📧 Draft Reply | Paste an email, get a ready-to-send reply |
| 🌍 Multilingual | Ask in any of 6 languages |
| 🛡️ Hallucination guard | Two-layer gate blocks wrong answers |
| 📚 Source citations | Every answer traced to exact document |
| ⚡ Streaming | Real-time pipeline stage visibility |
| 🔒 Fully local | No external APIs, no data leakage |

---

## Quick start

### Prerequisites
- Docker Desktop
- Git
- 8GB RAM minimum (16GB recommended)

### 1. Clone the repo
```bash
git clone https://github.com/pratepat/airplus-assist.git
cd airplus-assist
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env if needed — defaults work for local dev
```

### 3. Add your documents
Drop files into the product folders:
```
docs/
├── airplus_intelligence/   ← PDF, Excel, Word, txt
│   └── urls.txt            ← one URL per line
└── portal/                 ← PDF, Excel, Word, txt
    └── urls.txt
```

Supported formats: PDF · DOCX · XLSX · TXT · URLs

See [CONTENT_GUIDE.md](CONTENT_GUIDE.md) for 
authoring standards.

### 4. Start everything
```bash
docker compose up
```

### 5. Pull the AI model (first time only)
```bash
docker exec -it airplus-assist-ollama-1 \
  ollama pull qwen2.5:7b
```
This downloads ~4.4GB. Do this before demo day.

### 6. Ingest your documents
```bash
docker compose --profile ingest run --rm ingest \
  python build_vectorstore.py
```
Or click **🔄 Refresh Knowledge Base** in the UI.

### 7. Open the UI
http://localhost:8501

---

## Architecture

```
docs/ (PDF·Excel·Word·URLs)
↓
Ingest Pipeline
└── Parse → Chunk → Embed
↓
ChromaDB (vectors + metadata)
↓
User question → FastAPI → Re-ranker → Gate
↓
qwen2.5:7b (Ollama)
↓
Answer + Sources → UI
```

Four Docker containers — one command to start:
```bash
docker compose up
```

| Container | Role | Port |
|-----------|------|------|
| Ollama | Local LLM (qwen2.5:7b) | 11434 |
| ChromaDB | Vector store | 8000 |
| FastAPI | RAG API | 8001 |
| Streamlit | Chat UI | 8501 |

---

## Knowledge base corpus

**Total: 2168 chunks** across two products.

### AirPlus Intelligence

| Stage | File | Format | Notes |
|-------|------|--------|-------|
| Stage 1 | glossary.xlsx | Excel | Human-readable key aliases |
| Stage 1 | attribute_information.xlsx | Excel | Human-readable key aliases |
| Stage 1 | All_FAQ.txt | TXT (Q&A) | Product team maintained |
| Stage 1 | emails_cleaned.faq.txt | TXT (Q&A) | LLM-extracted from support emails |
| Stage 2 | dataplus-quick-guide-en.pdf | PDF | |
| Stage 2 | urls.txt | URLs | One URL per line |

### Portal

| Stage | File | Format | Notes |
|-------|------|--------|-------|
| Stage 1 | glossary-portal-en.docx | DOCX | 135 chunks, More Information field |
| Stage 1 | faq-portal-en.pdf | PDF | |
| Stage 1 | faq-virtual-cards-hotel-en.pdf | PDF | |
| Stage 2 | *(all guide PDFs)* | PDF | Step-by-step process documents |

Stage 1 = high-precision sources queried first.  
Stage 2 = deep-dive documents queried when Stage 1 
score is below `STAGE1_QUALITY_THRESHOLD=2.0`.

---

## API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /health | Service status + model info |
| GET | /products | Available knowledge base products |
| GET | /languages | Supported languages |
| GET | /stats | Chunk count + collection info |
| POST | /ask | Ask a question |
| POST | /ask/stream | Ask with streaming stages |
| POST | /analyse | Extract questions from text |
| POST | /summary | Generate complete summary |
| POST | /summary/stream | Summary with streaming |
| POST | /generate_reply | Draft a reply from answers |
| POST | /ingest | Trigger knowledge base refresh |

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| OLLAMA_MODEL | qwen2.5:7b | LLM model name |
| EMBED_MODEL | paraphrase-multilingual-MiniLM-L12-v2 | Embedding model |
| RERANK_MODEL | cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 | Re-ranker |
| CHROMA_COLLECTION | airplus_assist | ChromaDB collection |
| CHUNK_SIZE | 512 | Token chunk size |
| CHUNK_OVERLAP | 80 | Token overlap |
| TOP_K_RETRIEVAL | 15 | Candidates from ChromaDB |
| TOP_K_RERANK | 5 | Top chunks after re-ranking |
| RERANK_THRESHOLD | -0.50 | Gate threshold |
| SIMILARITY_THRESHOLD | 0.40 | Cosine pre-filter |
| SUMMARY_TOP_K_RETRIEVAL | 15 | Summary candidates |
| SUMMARY_TOP_K_RERANK | 10 | Summary top chunks |
| TRANSLATION_TIMEOUT | 45 | Translation timeout (s) |

---

## Running regression tests

Before every demo:
```bash
python3 tests/regression_tests.py
```

33 tests covering: health, hallucination guard, 
domain questions, product scoping, multilingual 
pipeline, source citations, response schema, 
ingest integrity, and API endpoints.

Exit code 0 = all passed · Exit code 1 = failures

---

## Demo setup (Windows laptop)

```bash
# 1. Install Docker Desktop for Windows
# 2. Clone repo
git clone https://github.com/pratepat/airplus-assist.git
cd airplus-assist

# 3. Copy .env from Mac (via USB or shared drive)

# 4. Copy docs/ folder from Mac

# 5. Start containers
docker compose up

# 6. Pull model (night before demo — 4.4GB)
docker exec -it airplus-assist-ollama-1 \
  ollama pull qwen2.5:7b

# 7. Ingest documents
docker compose --profile ingest run --rm ingest \
  python build_vectorstore.py

# 8. Set Windows to light mode
# Settings → Personalisation → Colours → Light
```

---

## Content authoring

See [CONTENT_GUIDE.md](CONTENT_GUIDE.md) for:
- How to structure Excel files
- FAQ document format
- Guide/manual best practices
- Folder naming conventions
- When to re-ingest

---

## Security notes

- No data sent to external services
- ChromaDB and Ollama ports not exposed externally
- No authentication (MVP scope — required for production)
- Documents stay in local docs/ folder
- See .env.example for configuration (never commit .env)

---

## Production roadmap

| Phase | Items |
|-------|-------|
| Infrastructure | Azure OpenAI · SharePoint integration · Kubernetes |
| Auth | Azure AD SSO · Role-based access |
| Frontend | React/Vue (replace Streamlit) |
| Integration | Portal embedded widget · Microsoft Teams bot |
| Analytics | Query logging · Feedback · Usage dashboard |

---

*AirPlus Assist — Built by Product Management · April 2026*
