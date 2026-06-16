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

## Step 5 — Retrieve the deployment outputs

```bash
az deployment group show \
  --resource-group airplus-assist-rg \
  --name main \
  --query properties.outputs \
  --output table
```

Note the values for `openAiEndpoint`, `searchEndpoint`, `acrLoginServer`, and `containerAppUrl` — you may need them for local testing or troubleshooting.

---

## Step 6 — Build the Docker image

> **Important:** The `docs/` folder must be present in the repository root before building. The Dockerfile copies documents into the image so the app can ingest them into Azure AI Search on startup.

Run from the repository root (where `Dockerfile` lives):

```bash
docker build --platform linux/amd64 -t airplusacr.azurecr.io/airplus-assist:latest .
```

> **Apple Silicon (M1/M2/M3/M4) users:** The `--platform linux/amd64` flag is required. Without it, Docker builds an `arm64` image by default, which Azure Container Apps rejects. Cross-platform builds are slower (~5–10 minutes on first run) but produce a correct `amd64` image.

The first build takes 2–10 minutes depending on your machine and platform. Subsequent builds are faster due to layer caching. The image is approximately 200 MB (no PyTorch or local ML models).

---

## Step 7 — Push the image to Azure Container Registry

```bash
# Authenticate Docker with your ACR instance
az acr login --name airplusacr

# Push the image
docker push airplusacr.azurecr.io/airplus-assist:latest
```

---

## Step 8 — Complete the Container App deployment

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

## Step 9 — Verify the deployment

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

On first startup the app ingests all documents into Azure AI Search (embeds via Azure OpenAI, uploads to the index). This takes **30–120 seconds** depending on the size of the document corpus. The homepage shows a "Loading knowledge base…" page until it is ready.

---

## Step 10 — Smoke test

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

The app re-ingests documents on every startup. For large corpora this adds to cold start time. To avoid re-ingesting on every restart, add a check in `ingest_documents()` that skips upload if the index already contains the expected document count.

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
