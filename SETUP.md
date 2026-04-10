# AirPlus Assist — Setup Guide

Step-by-step guide for new team members to get 
AirPlus Assist running locally after cloning.

---

## Prerequisites

Install these before starting:

| Tool | Version | Download |
|------|---------|----------|
| Docker Desktop | Latest | docker.com/products/docker-desktop |
| Git | Latest | git-scm.com |
| Python 3.11+ | Any | python.org (optional — for tests only) |

Minimum hardware: 16GB RAM, 20GB free disk space.

---

## Step 1 — Clone the repository

```bash
git clone https://github.com/pratepat/airplus-assist.git
cd airplus-assist
```

---

## Step 2 — Get the required files

Two files are NOT in the repository for security 
reasons. Get these from the project owner:

**`.env`** — environment configuration  
Copy to the project root: `airplus-assist/.env`

**`docs/` folder** — knowledge base documents  
Copy the entire docs/ folder to the project root.
Structure should be:
```
docs/
├── airplus_intelligence/
│   ├── glossary.xlsx
│   ├── attribute_information.xlsx
│   ├── All_FAQ.txt
│   ├── dataplus-quick-guide-en.pdf
│   └── urls.txt
└── portal/
    ├── faq-portal-en.pdf
    └── (other portal documents)
```

---

## Step 3 — Start Docker Desktop

Open Docker Desktop and wait for it to be ready 
(whale icon in taskbar stops animating).

---

## Step 4 — Start all containers

```bash
docker compose up
```

First run will download images (~2GB). 
Subsequent runs start in under 30 seconds.

You should see 4 containers running:
- airplus-assist-ollama-1
- airplus-assist-chromadb-1
- airplus-assist-api-1
- airplus-assist-ui-1

---

## Step 5 — Pull the AI model

**Do this once — takes 5-10 minutes (4.4GB download)**

```bash
docker exec -it airplus-assist-ollama-1 \
  ollama pull qwen2.5:7b
```

Do this on a good WiFi connection. 
The model is stored in a Docker volume and 
persists across restarts.

---

## Step 5b — Mac users: enable GPU acceleration (recommended)

Native Ollama on Mac uses the Apple Metal GPU, 
giving 5-10x faster responses than Docker Ollama.

In one terminal, start native Ollama:
```bash
ollama serve
```

Pull the model natively:
```bash
ollama pull qwen2.5:7b
```

In .env, change:
OLLAMA_BASE_URL=http://host.docker.internal:11434

Stop the Docker Ollama container (no longer needed):
```bash
docker compose stop ollama
```

Restart the API:
```bash
docker compose restart api
```

Expected response time: 5-10 seconds (vs 45-60s without GPU)

Note: Keep the "ollama serve" terminal open while using 
AirPlus Assist. On Windows, Docker Ollama is used instead
— GPU passthrough on Windows requires additional setup.

---

## Step 6 — Ingest the knowledge base

```bash
docker compose --profile ingest run --rm ingest \
  python build_vectorstore.py
```

Expected output:
```
Total chunks stored: ~1500+
No errors. All files ingested successfully.
```

This takes 2-5 minutes depending on corpus size.
Re-run this whenever documents are added or updated.

---

## Step 7 — Open the UI

http://localhost:8501

---

## Step 8 — Run regression tests

Verify everything is working:

```bash
pip3 install requests --break-system-packages
python3 tests/regression_tests.py
```

Expected: 33 tests, all passing.
`🟢 All tests passed — demo ready!`

---

## Daily workflow

```bash
# Start everything
docker compose up

# Stop everything
Ctrl+C   (or docker compose down)

# Add new documents
# 1. Drop files into docs/airplus_intelligence/ 
#    or docs/portal/
# 2. Re-ingest:
docker compose --profile ingest run --rm ingest \
  python build_vectorstore.py
# Or click Refresh Knowledge Base in the UI

# Switch AI model (optional)
# Edit OLLAMA_MODEL in .env, then:
docker compose restart api
```

---

## Troubleshooting

**"Cannot connect to Docker daemon"**  
Docker Desktop is not running. Open it and wait 
for the whale icon to stop animating.

**"Model not found" error**  
Run Step 5 again to pull the model.

**UI shows no answers**  
Run Step 6 to ingest documents into ChromaDB.

**Tests failing**  
Check all 4 containers are running:
```bash
docker compose ps
```
All should show "running" or "healthy".

**Port already in use**  
Another service is using port 8501 or 8001.
Stop it or change the port in docker-compose.yml.

**Windows: line ending issues**  
```bash
git config --global core.autocrlf false
# Then re-clone the repo
```

---

## Project structure

```
airplus-assist/
├── api/              ← FastAPI RAG pipeline
│   ├── main.py       ← API endpoints
│   ├── rag_chain.py  ← Retrieval + LLM logic
│   └── models.py     ← Request/response schemas
├── ingest/           ← Document ingestion
│   ├── parsers/      ← PDF, Excel, Word, URL parsers
│   ├── chunker.py    ← Text splitting
│   └── embedder.py   ← Sentence transformers
├── ui/               ← Streamlit frontend
│   └── app.py        ← Chat + Draft Reply UI
├── tests/            ← Regression test suite
├── docs/             ← Knowledge base (gitignored)
├── .streamlit/       ← Streamlit theme config
├── .env              ← Config (gitignored)
├── .env.example      ← Config template
├── CONTENT_GUIDE.md  ← Document authoring standards
├── CLAUDE.md         ← AI architecture + Claude Code guide
└── docker-compose.yml
```

---

## Getting help

- Read CONTENT_GUIDE.md before adding documents
- Read CLAUDE.md before making code changes
- Run regression tests after any code change
- Contact the project owner for .env and docs/
