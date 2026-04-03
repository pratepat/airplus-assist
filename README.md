# AirPlus Assist

**AI FAQ assistant — answers from your documents, never from thin air**

AirPlus Assist is a RAG-based (Retrieval-Augmented Generation) assistant that answers questions strictly from the documents you provide, with precise source citations. It never invents answers.

> **Design constraint:** Answer quality and citation accuracy are the primary design constraints of this system. Every architectural decision — chunking strategy, embedding model, reranking, similarity thresholds — is made to serve retrieval precision, not convenience.

---

## Quick Start

```bash
docker compose up
```

The UI will be available at http://localhost:8501

---

## First Run: Pull the Ollama Model

Ollama does not pre-download the model. After the containers start, pull the model once:

```bash
docker exec -it airplus-assist-ollama-1 ollama pull phi3:mini
```

This is a one-time step. The model is stored in a named Docker volume and persists across restarts.

---

## Adding Documents

1. Drop your documents into the `docs/` folder.
   - Supported formats (Phase 2): PDF, DOCX, XLSX, plain text, URLs
   - For URLs: add them line-by-line to `docs/urls.txt`

2. Run the ingest pipeline:

```bash
docker compose run --rm ingest
```

   This parses, chunks, embeds, and stores your documents in ChromaDB.

3. Restart the API and UI (or they will pick up the new vectors automatically on next query).

---

## Demo via ngrok

To expose the assistant publicly for a demo:

```bash
ngrok http 8501
```

ngrok will print a public URL you can share.

---

## Environment Variables

Copy `.env.example` to `.env` and adjust as needed.

| Variable              | Default                                    | Description                                      |
|-----------------------|--------------------------------------------|--------------------------------------------------|
| `APP_NAME`            | `AirPlus Assist`                           | Display name                                     |
| `OLLAMA_MODEL`        | `phi3:mini`                                | LLM model to use (must be pulled in Ollama)      |
| `OLLAMA_BASE_URL`     | `http://ollama:11434`                      | Ollama service URL (use service name in Docker)  |
| `CHROMA_HOST`         | `chromadb`                                 | ChromaDB service host                            |
| `CHROMA_PORT`         | `8000`                                     | ChromaDB service port                            |
| `CHROMA_COLLECTION`   | `airplus_assist`                           | ChromaDB collection name                         |
| `EMBED_MODEL`         | `all-MiniLM-L6-v2`                         | Sentence-transformer model for embeddings        |
| `RERANK_MODEL`        | `cross-encoder/ms-marco-MiniLM-L-6-v2`    | Cross-encoder model for reranking                |
| `CHUNK_SIZE`          | `512`                                      | Token size per chunk                             |
| `CHUNK_OVERLAP`       | `80`                                       | Overlap between consecutive chunks              |
| `TOP_K_RETRIEVAL`     | `10`                                       | Candidates retrieved from vector store           |
| `TOP_K_RERANK`        | `3`                                        | Top chunks passed to LLM after reranking         |
| `SIMILARITY_THRESHOLD`| `0.40`                                     | Minimum similarity score to include a chunk      |
| `API_HOST`            | `http://api:8001`                          | FastAPI service URL (use service name in Docker) |

---

## Services

| Service    | Port  | Description                            |
|------------|-------|----------------------------------------|
| `ollama`   | 11434 | Local LLM inference                    |
| `chromadb` | 8000  | Vector store                           |
| `api`      | 8001  | FastAPI RAG backend                    |
| `ui`       | 8501  | Streamlit chat UI                      |

---

## Health Checks

The `api` and `ui` services will not start until Ollama passes a health check (`GET /api/tags` returns 200). This accounts for the 15–30 second model load time on cold start.
