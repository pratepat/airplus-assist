# Azure Deployment Guide

Step-by-step instructions for deploying AirPlus Assist to Azure from scratch.

---

## Prerequisites

Install the following tools before starting:

```bash
# Azure CLI
brew install azure-cli       # macOS
# Windows/Linux: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli

# Docker Desktop
# https://www.docker.com/products/docker-desktop/

# Verify both are installed
az version
docker --version
```

---

## Step 1 — Log in to Azure

```bash
az login
# A browser window opens — sign in with your Azure account

# List available subscriptions
az account list --output table

# Set the subscription you want to deploy into
az account set --subscription "<your-subscription-id>"
```

---

## Step 2 — Choose resource names

Several Azure resources require **globally unique** names. Decide on them before starting and use them consistently throughout all commands.

| Resource | Naming rules | Example |
|---|---|---|
| Resource group | Any name, scoped to your subscription | `airplus-assist-rg` |
| Storage account | 3–24 chars, lowercase letters and digits only | `airplusstore24` |
| AI Search service | 2–60 chars, lowercase letters, digits, hyphens | `airplus-search` |
| OpenAI account | Alphanumeric and hyphens | `airplus-openai` |
| Container Registry | 5–50 chars, alphanumeric only | `airplusacr` |
| Container Apps environment | Alphanumeric and hyphens | `airplus-env` |

---

## Step 3 — Create a resource group

All resources will be deployed into this group. Using `swedencentral` ensures full model availability (GPT-4o-mini, text-embedding-3-small).

```bash
az group create \
  --name airplus-assist-rg \
  --location swedencentral
```

---

## Step 4 — Deploy the Bicep template (infrastructure)

Run from the repository root where `main.bicep` lives. Replace the placeholder names with your choices from Step 2.

```bash
az deployment group create \
  --resource-group airplus-assist-rg \
  --template-file main.bicep \
  --parameters \
    storageAccountName=airplusstore24 \
    searchServiceName=airplus-search \
    openAiAccountName=airplus-openai \
    acrName=airplusacr \
    caEnvName=airplus-env
```

This provisions:
- Azure OpenAI with `text-embedding-3-small` and `gpt-4o-mini` deployments
- Azure AI Search (Basic SKU, semantic ranking enabled)
- Azure Storage with a `content` blob container
- Azure Container Registry
- Azure Container Apps environment + app

> **Expected behaviour on first run:** Everything deploys successfully except the Container App, which will fail because the Docker image does not exist in the registry yet. This is normal — it will be resolved in Step 7. All other resources are fully created and ready.

---

## Step 5 — Retrieve the resource endpoints

Because Step 4 intentionally fails (the Container App image doesn't exist yet), the deployment outputs are not populated. Retrieve the values you need directly from the created resources:

```bash
# Azure OpenAI endpoint
az cognitiveservices account show \
  --name airplus-openai \
  --resource-group airplus-assist-rg \
  --query properties.endpoint \
  --output tsv

# Azure AI Search endpoint
# Format: https://<searchServiceName>.search.windows.net
# e.g.  https://airplus-search.search.windows.net

# ACR login server (used in Steps 7 and 8)
az acr show \
  --name airplusacr \
  --resource-group airplus-assist-rg \
  --query loginServer \
  --output tsv
```

Note the ACR login server — you will need it in Steps 7 and 8. The Container App URL is not available until Step 9.

---

## Step 6 — Upload documents to Azure Blob Storage

Documents are stored in Azure Blob Storage, not in the Docker image. Upload them once before the first deployment (or whenever the corpus changes):

```bash
az storage blob upload-batch \
  --source docs/ \
  --destination content \
  --account-name airplusstore24 \
  --auth-mode key
```

Verify the upload:

```bash
az storage blob list \
  --container-name content \
  --account-name airplusstore24 \
  --auth-mode key \
  --output table
```

You should see files listed under `airplus_intelligence/` and `portal/` prefixes.

---

## Step 7 — Build the Docker image

Run from the repository root (where `Dockerfile` lives):

```bash
docker build --platform linux/amd64 -t airplusacr.azurecr.io/airplus-assist:latest .
```

> **Apple Silicon (M1/M2/M3/M4) users:** The `--platform linux/amd64` flag is required. Without it, Docker builds an `arm64` image by default, which Azure Container Apps rejects. Cross-platform builds are slower (~5–10 minutes on first run) but produce a correct `amd64` image.

The first build takes 2–10 minutes depending on your machine and platform. Subsequent builds are faster due to layer caching. The image is approximately 200 MB (no PyTorch or local ML models).

---

## Step 8 — Push the image to Azure Container Registry

```bash
# Authenticate Docker with your ACR instance
az acr login --name airplusacr

# Push the image
docker push airplusacr.azurecr.io/airplus-assist:latest
```

---

## Step 9 — Complete the Container App deployment

Re-run the same Bicep command from Step 4. Bicep is idempotent — existing resources are left unchanged. This time the Container App will succeed because the image now exists in the registry.

```bash
az deployment group create \
  --resource-group airplus-assist-rg \
  --template-file main.bicep \
  --parameters \
    storageAccountName=airplusstore24 \
    searchServiceName=airplus-search \
    openAiAccountName=airplus-openai \
    acrName=airplusacr \
    caEnvName=airplus-env
```

---

## Step 10 — Verify the deployment

```bash
# Get the public URL
az containerapp show \
  --name airplus-assist \
  --resource-group airplus-assist-rg \
  --query properties.configuration.ingress.fqdn \
  --output tsv
```

Open the URL in a browser, or hit the health endpoint:

```bash
curl https://<fqdn>/api/health
```

On the **first** startup the Azure AI Search index is empty, so the app automatically downloads all documents from Blob Storage and ingests them (embeds via Azure OpenAI, uploads to the index). This takes **30–120 seconds** depending on corpus size. The homepage shows a "Loading knowledge base…" page until ready.

On all **subsequent** startups (including after code redeployments or scale-up from zero), the index already has documents so ingest is skipped — the app is ready in under 5 seconds.

---

## Step 11 — Smoke test

```bash
curl -s -X POST https://<fqdn>/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is a virtual card?", "language": "EN"}' \
  | python3 -m json.tool
```

A healthy response will have:
- `"confidence"` set to `"high"` or `"medium"` (not `"none"`)
- `"search_stage"` set to `"stage1"` (glossary/FAQ hit) or `"stage2"` (guide hit)
- `"sources"` containing at least one entry with a `label` and `excerpt`

---

## Redeployment

After a code change or document update, rebuild and push the image, then force a new Container App revision:

```bash
docker build --platform linux/amd64 -t airplusacr.azurecr.io/airplus-assist:latest .
docker push airplusacr.azurecr.io/airplus-assist:latest

az containerapp update \
  --name airplus-assist \
  --resource-group airplus-assist-rg \
  --image airplusacr.azurecr.io/airplus-assist:latest
```

The app skips ingest on startup if the index already has documents, so redeployments are fast. To update the knowledge base after adding or changing documents in Blob Storage, trigger a manual re-ingest:

```bash
# 1. Upload the new or changed file
az storage blob upload \
  --container-name content \
  --name "portal/new-guide.pdf" \
  --file path/to/new-guide.pdf \
  --account-name airplusstore24 \
  --auth-mode key

# 2. Trigger re-ingest (returns immediately, runs in background)
curl -X POST https://<fqdn>/api/ingest

# 3. Monitor until complete
curl https://<fqdn>/api/health
# "status": "ingesting" while running → "status": "ok" when done
```

---

## Tear down

To delete all resources and stop all costs:

```bash
az group delete --name airplus-assist-rg --yes
```

This is irreversible. The Azure AI Search index, all embeddings, and all uploaded documents will be permanently deleted.

---

## Local development against Azure services

To run the app locally while using the Azure backend (useful for debugging):

```bash
# Copy the example env file
cp neo-app/.env.example neo-app/.env

# Fill in the values from Step 5 outputs and Azure Portal → Keys
# AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY
# AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY
# AZURE_STORAGE_CONNECTION_STRING

# Run locally
cd neo-app
uvicorn app.main:app --reload --port 8000
```

The app will ingest documents into the same Azure AI Search index as the cloud deployment. Use a separate index name (`AZURE_SEARCH_INDEX=airplus-assist-dev`) to avoid overwriting production data.
