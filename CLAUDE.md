# CLAUDE.md — AirPlus Assist

This file is read automatically by Claude Code 
when working in this repository. It contains 
project conventions, architecture decisions, 
and instructions for AI-assisted development.

---

## Project overview

AirPlus Assist is a RAG (Retrieval-Augmented 
Generation) FAQ assistant for AirPlus products.
It answers questions strictly from provided 
documents with precise source citations.

**North star constraint:**
> Answer quality and citation accuracy take 
> priority over every other design decision.
> Never compromise retrieval precision for speed 
> or simplicity.

---

## Architecture

```
docs/ → Ingest → ChromaDB → Re-ranker → Ollama → Answer
```

### Four Docker containers

| Container | Image | Port | Role |
|-----------|-------|------|------|
| ollama | ollama/ollama | 11434 | Local LLM |
| chromadb | chromadb/chroma | 8000 (internal) | Vector store |
| api | custom Python | 8001 | RAG pipeline |
| ui | custom Python | 8501 | Streamlit UI |

### Key files

| File | Purpose |
|------|---------|
| api/rag_chain.py | Core RAG logic — retrieval, re-ranking, generation |
| api/main.py | FastAPI endpoints |
| api/models.py | Pydantic request/response schemas |
| ingest/parsers/ | One parser per document format |
| ingest/build_vectorstore.py | Ingest orchestrator |
| ui/app.py | All UI logic |
| tests/regression_tests.py | 33 regression tests |

---

## AI model decisions

### Embedding model
`paraphrase-multilingual-MiniLM-L12-v2`

**Why:** Supports EN/DE/FR/ES/IT/NL — the six 
languages present in AirPlus documents and used 
by AirPlus customers. English-only models 
(e.g. all-MiniLM-L6-v2) gave poor retrieval 
for German/French queries.

**Do not change** without re-ingesting the 
entire corpus — embeddings must match the model 
used at ingest time.

### Re-ranker model
`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`

**Why:** Multilingual MS MARCO cross-encoder. 
The English-only alternative 
(ms-marco-MiniLM-L-6-v2) scored German PDF 
content at -10.9 against English questions, 
blocking valid answers. This model handles 
cross-lingual pairs correctly.

### LLM
`qwen2.5:7b` via Ollama

**Why:** Better instruction-following than 
mistral:7b and phi3:mini for grounded RAG. 
Correctly triggers contradiction detection 
(flags "Sources differ") where other models 
silently pick one source. Tested against 
actual AirPlus documents.

**Temperature:** 0.1 for answers (factual 
consistency), 0.2 for summaries (more fluent 
prose), 0.3 for reply generation (natural tone).

---

## Hallucination guard — critical, do not weaken

Two-layer gate prevents the LLM from answering 
out-of-domain questions:

**Layer 1 — Cosine similarity gate**
`SIMILARITY_THRESHOLD=0.40`
Blocks queries with no vector space overlap.
This model's score floor is ~0.70 so this 
layer catches only extreme mismatches.

**Layer 2 — Re-ranker gate (primary guard)**
`RERANK_THRESHOLD=-0.50`
The real hallucination guard. If the top 
re-ranker score is below -0.50, the LLM is 
never called. Returns "I don't have enough 
information" directly.

**Calibration evidence:**

| Question | Top rerank | Gate |
|----------|-----------|------|
| "What is MERCHANT_CITY?" | +6.09 | PASS |
| "What is insurance coverage?" | -0.17 | PASS |
| "Capital of France?" | -1.24 | BLOCK |
| "CEO of Apple?" | -6.10 | BLOCK |

**Do not raise RERANK_THRESHOLD above -0.25** 
without re-running all gate tests. The margin 
between the weakest legitimate pass (-0.17) 
and the strongest illegitimate pass (-1.24) 
is 1.07 points. Tightening the threshold 
risks blocking valid domain questions.

---

## Retrieval pipeline

```
Question
→ translate to EN (if non-EN)
→ embed with paraphrase-multilingual-MiniLM
→ ChromaDB cosine search (top 15)
→ cosine gate check
→ cross-encoder re-rank (top 5 for answers,
   top 10 for summaries)
→ re-ranker gate check
→ build context with source labels
→ qwen2.5:7b with grounding prompt
→ structured response with citations
```

### Two-stage retrieval

Two-stage retrieval applies to **any product that 
has a `stage_config.json` file** in its docs folder.
It is not portal-specific.

Stage 1 sources (FAQ, glossary) are queried first.
Stage 2 (guides, manuals) is queried only when the 
Stage 1 result is below `STAGE1_QUALITY_THRESHOLD`.

**Three-tier decision logic:**

| Condition | Outcome |
|-----------|---------|
| `stage1_top < RERANK_THRESHOLD (-0.50)` | BLOCK — neither stage passes |
| `stage1_top >= STAGE1_QUALITY_THRESHOLD (2.0)` | CONFIDENT — return Stage 1 answer |
| Between -0.50 and 2.0 → check Stage 2: | |
| `stage2_top >= RERANK_THRESHOLD (-0.50)` | Use Stage 2 answer |
| `stage2_top < RERANK_THRESHOLD (-0.50)` | BLOCK — neither stage passes |

Do not hardcode `product == "portal"` in retrieval 
logic — presence of `stage_config.json` controls 
whether staging is active for a given product.

### Threshold reference

| Constant | Value | Role |
|----------|-------|------|
| `RERANK_THRESHOLD` | -0.50 | Hallucination gate (blocks LLM call) |
| `STAGE1_QUALITY_THRESHOLD` | 2.0 | Stage fallback trigger |
| `SIMILARITY_THRESHOLD` | 0.40 | Cosine pre-filter |
| `CONFIDENCE_HIGH_THRESHOLD` | 3.0 | Named constant in rag_chain.py |
| `CONFIDENCE_MEDIUM_THRESHOLD` | 0.0 | Named constant in rag_chain.py |

### Chunking strategy

| Format | Strategy | Chunk size |
|--------|----------|-----------|
| PDF | Page-aware recursive split | 512 tokens |
| DOCX | Heading-aware recursive split | 512 tokens |
| XLSX | One row = one chunk (never split) | N/A |
| TXT (Q&A) | One Q+A pair = one chunk | N/A |
| TXT (other) | Recursive split | 512 tokens |
| URL | trafilatura extract + recursive split | 512 tokens |

**Excel rule:** Never change row-based chunking 
for Excel. Splitting mid-row loses the Q+A 
relationship between Key and definition columns.

**Q&A txt detection:** Files where content 
contains >3 occurrences of "\nQ:" are 
auto-detected as Q&A format and chunked 
per pair. Do not break this detection logic.

---

## Metadata schema

Every chunk in ChromaDB carries:

```python
{
  "product":        str,   # folder name
  "source_file":    str,   # filename
  "source_type":    str,   # pdf|xlsx|docx|txt|url
  "page_number":    int|None,
  "sheet_name":     str|None,
  "question_text":  str|None,  # Excel Key / Q&A question
  "url":            str|None,
  "section_title":  str|None,
  "chunk_preview":  str,   # first 120 chars
  "ingested_at":    str,   # ISO 8601 UTC
  "chunk_index":    int
}
```

**Do not remove fields from this schema.** 
The UI citation cards and regression tests 
depend on all fields being present.

---

## System prompt — do not weaken

The grounding prompt in rag_chain.py contains:
```
"Never use prior knowledge. Never speculate.
Never say 'typically' or 'generally' unless
those exact words appear in the source context."
```

And the contradiction rule:
```
"If two or more sources provide conflicting
information, flag it: 'Note: Sources differ...'"
```

Do not soften these instructions. They are the 
reason the hallucination guard works at the 
prompt level (Layer 3).

---

## Language pipeline

Non-EN questions follow this path:
1. Translate question to English via Ollama
2. Use translated question for ChromaDB retrieval
3. Use translated question for re-ranking
4. Answer using the selected language column 
   (for Excel chunks with EN/DE/FR/etc columns)
5. For PDF/DOCX in non-matching language: 
   show original + English translation (Option D)

**Translation timeout:** 45 seconds 
(`TRANSLATION_TIMEOUT` in .env). Increase if 
Ollama is under concurrent load.

---

## Excel key aliases

Keys in AirPlus Intelligence Excel files follow the 
pattern `dataplus.attribute.info.KEY_NAME`.

The `_humanise_key()` function in `excel_parser.py` 
automatically converts these to human-readable form:

```
dataplus.attribute.info.TRIP_DURATION_IN_DAYS
→ "Trip Duration In Days"
```

This alias is added to every Excel chunk as a second 
line (`Also known as: …`) so that conversational 
queries ("how long was the trip?") can match 
technical attribute names.

**Applies to all Excel files automatically** — no 
manual action needed when adding new Excel files. If 
a user asks using terminology not in the key name, 
add a synonym entry to `All_FAQ.txt` instead.

---

## Email extractor

Converts raw support email threads into Q&A pairs 
suitable for ingestion.

| Item | Detail |
|------|--------|
| Script | `ingest/preprocessors/email_extractor.py` |
| Input | `docs/{product}/emails_raw.txt` (gitignored — contains PII) |
| Output | `docs/{product}/emails_cleaned.faq.txt` (committed — reviewed) |

**Run before ingesting a new email batch:**
```bash
python ingest/preprocessors/email_extractor.py \
  --input  docs/airplus_intelligence/emails_raw.txt \
  --output docs/airplus_intelligence/emails_cleaned.faq.txt
```

**Always review the output** before ingesting. The 
LLM extraction is not perfect — remove or edit any 
incorrect Q&A pairs before running ingest.

Raw email files are gitignored (PII risk).  
Cleaned `.faq.txt` files are committed to git.

---

## Portal glossary

| Item | Detail |
|------|--------|
| File | `glossary-portal-en.docx` |
| Parser | `ingest/parsers/glossary_docx_parser.py` |
| Chunking | One table row = one chunk |
| Columns | Col 0: Letter (ignored) · Col 1: Topic · Col 2: Description · Col 3: More Information |

The `more_information` field is stored as-is in 
chunk metadata and shown in UI source cards as 
"Further reading". It is the only parser that 
populates this metadata field.

---

## Adding a new product

1. Create `docs/{product_name}/` folder
2. Add documents (see CONTENT_GUIDE.md)
3. Re-ingest:
```bash
docker compose --profile ingest run --rm ingest \
  python build_vectorstore.py
```
4. The product appears in the UI automatically — 
   no code changes needed.

Product name = folder name. Use lowercase 
with underscores. Display name is mapped in 
ui/app.py `display_name()` function — update 
that mapping if you want a different label.

---

## Adding a new document format

1. Create `ingest/parsers/{format}_parser.py`
2. Implement `parse_{format}(file_path, product) -> List[Dict]`
3. Each dict must have `content` and `metadata` 
   keys with all metadata schema fields
4. Register in `ingest/parsers/__init__.py`
5. Add detection logic in 
   `ingest/build_vectorstore.py`
6. Add pip dependency to 
   `requirements/ingest.txt`
7. Rebuild ingest container:
```bash
docker compose build ingest
```

---

## API conventions

All endpoints follow this pattern:
- POST /ask — synchronous, returns AskResponse
- POST /ask/stream — SSE streaming, same result
- POST /summary — synchronous
- POST /summary/stream — SSE streaming

SSE event format:
```json
{"stage": "searching", "message": "...", "icon": "🔍"}
{"stage": "retrieved", "message": "Found N sources", "icon": "📚"}
{"stage": "generating", "message": "Generating with model...", "icon": "🤖"}
{"stage": "complete", "result": {full response dict}}
{"stage": "error", "message": "Error description"}
```

When adding new streaming endpoints, follow 
this exact protocol so the UI consumer 
(call_ask_streaming, call_summary_streaming) 
can handle them without changes.

---

## Running tests

```bash
python3 tests/regression_tests.py
```

**Run after every code change.**
33 tests covering all critical paths.
Exit 0 = pass, Exit 1 = failures.

Do not delete or weaken existing tests.
Add new tests when adding new features.

Key tests to never break:
- gate_blocks_capital_of_france
- gate_blocks_ceo_of_apple
- citations_have_required_fields
- ingest_chunk_count

---

## Knowledge base corpus

**Total: 2168 chunks** across two products.

| Product | Stage | Files |
|---------|-------|-------|
| airplus_intelligence | 1 | glossary.xlsx, attribute_information.xlsx, All_FAQ.txt, emails_cleaned.faq.txt |
| airplus_intelligence | 2 | dataplus-quick-guide-en.pdf, urls.txt |
| portal | 1 | glossary-portal-en.docx (135 chunks), faq-portal-en.pdf, faq-virtual-cards-hotel-en.pdf |
| portal | 2 | All guide PDFs |

---

## What NOT to do

- Do not use localhost in docker-compose service 
  definitions — use service names
- Do not store sensitive data in session state 
  that persists across users
- Do not call the LLM without going through the 
  re-ranker gate first
- Do not change the metadata schema without 
  updating all parsers and tests
- Do not raise RERANK_THRESHOLD above -0.25
- Do not lower TOP_K_RETRIEVAL below 10
- Do not use a single requirements.txt — keep 
  ingest/api/ui requirements separate
- Do not commit .env or docs/ to git
- Do not hardcode product names — derive from 
  folder names or ChromaDB metadata
- Do not hardcode `product == "portal"` in 
  retrieval logic — use `stage_config.json` 
  to control two-stage retrieval per product

---

## Known limitations (MVP scope)

| Limitation | Production fix |
|------------|---------------|
| No authentication | Azure AD SSO |
| Streamlit UI | React/Vue frontend |
| Local Ollama | Azure OpenAI / GPU server |
| docs/ folder | SharePoint integration |
| Manual re-ingest | Auto-trigger on file change |
| No query logging | Analytics database |
| Single-threaded LLM | Async queue + GPU |

---

## Contact

Built by AirPlus Product Management — April 2026.
For architecture questions contact the project owner.
