# Deployment Troubleshooting Log

Issues encountered during the first deployment to Azure and how each was resolved.

---

## 1. Unresolved `sentence_transformers` import in PyCharm

**Symptom:** PyCharm showed "Unresolved reference" for `sentence_transformers` even after
installing requirements.

**Cause:** PyCharm was using the system Python interpreter instead of the project `.venv`.

**Fix:** In PyCharm → Settings → Python Interpreter, select the `.venv` interpreter from
the project root. The packages installed via `pip install -r requirements/api.txt` are
only visible to that interpreter.

---

## 2. Azure OpenAI SKU `Standard` not available in `swedencentral`

**Symptom:**
```
InvalidResourceProperties: The SKU 'Standard' is not supported in region 'swedencentral'
```

**Cause:** The Bicep template used `sku: { name: 'Standard' }` for the OpenAI model
deployments. The `Standard` SKU is not available in Sweden Central — only `GlobalStandard`.

**Fix:** Changed both `embeddingDeployment` and `chatDeployment` SKU names in `main.bicep`:
```bicep
sku: {
  name: 'GlobalStandard'   // was 'Standard'
  capacity: 50
}
```

---

## 3. Container App failed on first Bicep run (`MANIFEST_UNKNOWN`)

**Symptom:**
```
MANIFEST_UNKNOWN: manifest tagged by "latest" is not found
```

**Cause:** The Container App resource was created before the Docker image existed in the
Azure Container Registry. This is a chicken-and-egg problem on first deployment.

**Fix:** This is expected on first run. The correct sequence is:
1. Run Bicep once (Container App will fail — all other resources deploy fine)
2. Build and push the Docker image to ACR
3. Re-run Bicep (idempotent — only the Container App is updated this time)

---

## 4. Docker image rejected: `linux/arm64` not supported

**Symptom:**
```
image OS/Arc must be linux/amd64 but found linux/arm64
```

**Cause:** Building on Apple Silicon (M-series Mac) produces `arm64` images by default.
Azure Container Apps only accepts `linux/amd64`.

**Fix:** Always build with the `--platform` flag:
```bash
docker build --platform linux/amd64 -t airplusacr.azurecr.io/airplus-assist:latest .
```

---

## 5. `RequestConflict` on Azure OpenAI account

**Symptom:**
```
RequestConflict: Another operation is being performed on the parent resource
'/subscriptions/.../Microsoft.CognitiveServices/accounts/airplus-openai'
```

**Cause:** Azure was still running a background provisioning task on the OpenAI account
(triggered by the `defenderForAISettings` child resource) even after both model deployments
showed `Succeeded`.

**Fix:**
1. Removed the `defenderForAISettings` resource from `main.bicep` — it was cosmetic
   (disabling Defender) and caused the account-level lock.
2. Verified the account itself was `Succeeded` before retrying:
   ```bash
   az cognitiveservices account show \
     --name airplus-openai \
     --resource-group airplus-assist-rg \
     --query properties.provisioningState \
     --output tsv
   ```
3. Re-ran Bicep once the account was fully settled.

---

## 6. `Microsoft.App` resource provider not registered

**Symptom:**
```
Subscription is not registered for the Microsoft.App resource provider.
Please run "az provider register -n Microsoft.App --wait"
```

**Cause:** Azure Container Apps (`Microsoft.App`) was never used in this subscription
before, so the resource provider was not registered.

**Fix:**
```bash
az provider register -n Microsoft.App --wait
```

Then re-run the Bicep deployment.

---

## 7. Startup crash: `'str' object has no attribute 'name'`

**Symptom:** App started but health endpoint returned `chunk_count: 0`. Logs showed:
```
File "/app/app/ingest.py", line 82, in ensure_index
    existing = {idx.name for idx in client.list_index_names()}
'str' object has no attribute 'name'
```

**Cause:** `SearchIndexClient.list_index_names()` returns strings (index names directly),
not index objects with a `.name` attribute.

**Fix:** Changed `ingest.py` line 82:
```python
# Before
existing = {idx.name for idx in client.list_index_names()}

# After
existing = set(client.list_index_names())
```

---

## 8. UI returned 500: `Object of type Undefined is not JSON serializable`

**Symptom:** Browsing to the app URL returned HTTP 500. Logs showed:
```
File "/app/app/templates/index.html", line 187, in top-level template code
    window.OLLAMA_MODEL = {{ ollama_model | tojson }};
Object of type Undefined is not JSON serializable
```

**Cause:** The Jinja2 template referenced `ollama_model` but `main.py` was updated to
pass `chat_model` instead (as part of the migration from Ollama to Azure OpenAI).

**Fix:** Updated `neo-app/app/templates/index.html` line 187:
```html
<!-- Before -->
window.OLLAMA_MODEL = {{ ollama_model | tojson }};

<!-- After -->
window.OLLAMA_MODEL = {{ chat_model | tojson }};
```

---

## 9. `az containerapp update` did not pull new image

**Symptom:** After rebuilding and pushing the Docker image, the Container App continued
running the old revision. The fix from issue #8 was not reflected in the running app.

**Cause:** Azure Container Apps caches the image manifest. Updating with the same `latest`
tag does not always trigger a new revision pull.

**Fix:** Force a new revision by bumping an environment variable:
```bash
az containerapp update \
  --name airplus-assist \
  --resource-group airplus-assist-rg \
  --image airplusacr.azurecr.io/airplus-assist:latest \
  --set-env-vars DEPLOY_TS="$(date +%s)"
```

---

## 10. Long loading screen — rate limiting during ingest

**Symptom:** The "Loading knowledge base…" page stayed on screen for several minutes
instead of the expected 10–20 seconds.

**Cause:** Embedding 1525 chunks on startup hit the Azure OpenAI TPM (tokens per minute)
rate limit for the `GlobalStandard` SKU at 50K TPM capacity. The SDK auto-retried with
~60-second back-off windows, making the full ingest take 4–6 minutes.

**This is not a bug** — the app eventually loaded correctly. See the section below for
how to reduce ingest time in future deployments.

**Options to reduce ingest time:**
1. **Increase TPM quota** — In Azure Portal → OpenAI resource → Model deployments →
   `text-embedding-3-small` → edit capacity. `GlobalStandard` allows up to 350K TPM.
2. **Skip already-indexed chunks** — Add a check in `ingest_documents()` to count
   existing documents in the index and skip upload if the count matches. This avoids
   re-embedding on every restart.
3. **Run ingest separately** — Decouple ingest from app startup. Ingest once manually
   (or via a CI step) and have the app assume the index is populated.
