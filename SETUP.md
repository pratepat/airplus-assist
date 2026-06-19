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
| Azure CLI | Latest | learn.microsoft.com/cli/azure/install-azure-cli |
| Python 3.12+ | Any | python.org (optional — for local dev and tests) |

Minimum hardware: 8GB RAM, 5GB free disk space.

---

## Step 1 — Clone the repository

```bash
git clone https://github.com/pratepat/airplus-assist.git
cd airplus-assist
```

---

## Step 2 — Get the required credentials

One file is NOT in the repository for security reasons.
Get it from the project owner:

**`.env`** — environment configuration  
Copy to the project root: `airplus-assist/.env`

It must contain:

```ini
AZURE_OPENAI_ENDPOINT=https://<name>.openai.azure.com/
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_EMBED_MODEL=text-embedding-3-small
AZURE_OPENAI_CHAT_MODEL=gpt-4o-mini
AZURE_OPENAI_API_VERSION=2024-02-01

AZURE_SEARCH_ENDPOINT=https://<name>.search.windows.net
AZURE_SEARCH_KEY=<key>
AZURE_SEARCH_INDEX=airplus-assist

AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=<name>;AccountKey=<key>;EndpointSuffix=core.windows.net
AZURE_STORAGE_CONTAINER=content
```

> **Note:** Documents are stored in Azure Blob Storage, not in the
> repository. You do not need a local `docs/` folder to run the app.

---

## Step 3 — Upload documents to Azure Blob Storage

Documents live in the `content` container in Azure Blob Storage.
The folder structure determines the product name:

```
content/                          ← Blob container
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

If documents are not yet in Blob Storage, upload them:

```bash
# Upload your local docs/ folder to the blob container
az storage blob upload-batch \
  --source docs/ \
  --destination content \
  --connection-string "<AZURE_STORAGE_CONNECTION_STRING from .env>"
```

Skip this step if documents are already in Blob Storage (production
is already populated — you only need to do this for a fresh environment).

---

## Step 4 — Run the application

### Option A — Docker (recommended)

```bash
docker build -t airplus-assist .
docker run --env-file .env -p 8000:8000 airplus-assist
```

### Option B — Local Python

```bash
cd neo-app
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Step 5 — First startup (automatic ingest)

On the first run against an empty Azure AI Search index, the app
automatically downloads all documents from Blob Storage and ingests them.
This takes 1–3 minutes depending on corpus size.

```
=== AirPlus Assist starting — blob container: content ===
Step 1/2 — Checking Azure AI Search index …
Index is empty — downloading from Blob Storage and ingesting …
Downloaded 12 file(s) from blob container 'content'
Ingesting product 'airplus_intelligence': 847 chunks
Ingesting product 'portal': 312 chunks
Step 2/2 — Building RAG pipeline (1159 chunks) …
=== Ready — 1159 chunks, 2 product(s) ===
```

On all subsequent startups the index is already populated, so ingest
is skipped and the app is ready in under 5 seconds.

---

## Step 6 — Open the UI

http://localhost:8000

---

## Step 7 — Run regression tests

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
# Start the app
docker run --env-file .env -p 8000:8000 airplus-assist
# or: uvicorn app.main:app ... (Option B)

# Add new documents
# 1. Upload the file to Blob Storage:
az storage blob upload \
  --container-name content \
  --name "portal/new-guide.pdf" \
  --file path/to/new-guide.pdf \
  --connection-string "<connection string>"

# 2. Trigger re-indexing:
curl -X POST http://localhost:8000/api/ingest

# 3. Monitor progress:
curl http://localhost:8000/api/health
# Wait until "status": "ok" and chunk_count increases

# Check app health
curl http://localhost:8000/api/health
```

---

## Troubleshooting

**App shows "Loading knowledge base…" indefinitely**  
Check the container logs. If you see `AZURE_STORAGE_CONNECTION_STRING is not set`,
the `.env` file is missing or not loaded.

**"Index is empty — downloading from Blob Storage" but no documents appear**  
The Blob container is empty. Run Step 3 to upload documents.

**`AZURE_OPENAI_API_KEY` or `AZURE_SEARCH_KEY` errors**  
The `.env` file has incorrect credentials. Get the latest from the project owner.

**POST /api/ingest returns 409**  
An ingest is already in progress. Check `GET /api/health` and wait for
`"ingest_running": false`.

**Tests failing**  
Ensure the app is running (`docker run ...` or `uvicorn ...`) and the index
is populated (`GET /api/health` shows `"status": "ok"`).

**Port 8000 already in use**  
Another service is using port 8000. Stop it or change `-p 8000:8000` to
`-p 8080:8000` and open http://localhost:8080.

---

## Project structure

```
airplus-assist/
├── neo-app/              ← Current application (Azure stack)
│   ├── app/
│   │   ├── main.py       ← FastAPI endpoints + startup logic
│   │   ├── rag.py        ← Retrieval + LLM pipeline
│   │   ├── ingest.py     ← Parsers, chunking, Blob download, Search upload
│   │   ├── config.py     ← Environment variable configuration
│   │   └── models.py     ← Request/response schemas
│   ├── templates/        ← Jinja2 HTML templates
│   └── static/           ← CSS, JS assets
├── tests/                ← Regression test suite
├── main.bicep            ← Azure infrastructure as code
├── Dockerfile            ← Container image definition
├── .env                  ← Config (gitignored)
├── .env.example          ← Config template
├── DEPLOYMENT.md         ← Azure deployment guide
├── TROUBLESHOOTING.md    ← Known issues and fixes
└── CLAUDE.md             ← AI architecture + Claude Code guide
```

---

## Getting help

- Read DEPLOYMENT.md for deploying to Azure
- Read TROUBLESHOOTING.md for known deployment issues
- Read CLAUDE.md before making code changes
- Run regression tests after any code change
- Contact the project owner for `.env` credentials
