# CONTENT_GUIDE.md — AirPlus Assist

Standards and procedures for adding content to the 
AirPlus Assist knowledge base.

---

## Supported formats

| Format | Use for |
|--------|---------|
| PDF | Guides, manuals, policy documents |
| XLSX | Glossaries, attribute dictionaries |
| DOCX | Structured glossaries with rich metadata |
| TXT (Q&A) | FAQ pairs — one `Q:` / `A:` block per entry |
| TXT (other) | Freeform reference text |
| URLs | Web pages — one URL per line in `urls.txt` |

---

## How to structure Excel files

- Include a **Key** column (exact header: `Key`)
- Language columns must use 2-letter codes as headers: 
  `EN`, `DE`, `FR`, `ES`, `IT`, `NL`
- Columns containing "location" or "context" 
  (case-insensitive) are rendered as 
  "You can find this in: … section"
- Columns ending in `Approved` or `Approved?` 
  are skipped — status flags only
- One row = one chunk. Never merge cells.
- Empty rows (no Key value) are skipped automatically.

---

## FAQ document format

Q&A `.txt` files must follow this structure:

```
Q: What is the trip duration?
A: The trip duration is the number of days between 
departure and return, inclusive.

Q: How is MERCHANT_CITY defined?
A: MERCHANT_CITY is the city where the merchant 
processed the transaction.
```

Rules:
- Each Q and A on its own line
- Blank line between pairs
- Files with more than 3 `\nQ:` occurrences are 
  auto-detected as Q&A format
- Filename convention: `All_FAQ.txt` (product team) 
  or `*.faq.txt` (LLM-extracted)

---

## Adding email Q&A

Use when support inbox emails contain useful Q&A 
content that isn't already in the knowledge base.

**Step 1** — Collect support emails into:
```
docs/{product}/emails_raw.txt
```

**Step 2** — Run the extractor:
```bash
python ingest/preprocessors/email_extractor.py \
  --input  docs/{product}/emails_raw.txt \
  --output docs/{product}/emails_cleaned.faq.txt
```

**Step 3** — Review `emails_cleaned.faq.txt` carefully.
The LLM extraction is not perfect. Remove or edit 
any incorrect, incomplete, or duplicate Q&A pairs.

**Step 4** — Edit/remove incorrect Q&A pairs in the 
cleaned file before proceeding.

**Step 5** — Run ingest:
```bash
docker compose --profile ingest run --rm ingest \
  python build_vectorstore.py
```

**Step 6** — Test the affected questions in the UI 
to confirm answers are correct and well-cited.

**Important:**
- `emails_raw.txt` is gitignored — it contains PII
- `emails_cleaned.faq.txt` is committed to git — 
  always review before committing

---

## Stage configuration

Products can use two-stage retrieval by adding a 
`stage_config.json` to their docs folder. Staging 
is not enabled without this file.

**Stage 1** = high-precision sources queried first:
- Curated Q&A content (FAQ files, email extracts)
- Glossary definitions
- Summary or overview documents

**Stage 2** = deep-dive documents queried when 
Stage 1 result score is below 2.0:
- Step-by-step process guides
- Technical reference documents
- Detailed how-to manuals

When adding a new file, assign it to Stage 1 if it 
is authoritative and concise; Stage 2 if it is 
detailed or procedural.

---

## Excel key naming convention

Keys in the format `dataplus.attribute.info.KEY_NAME` 
are automatically aliased to human-readable form by 
the Excel parser:

```
dataplus.attribute.info.TRIP_DURATION_IN_DAYS
→ "Trip Duration In Days"
```

This alias is embedded in every chunk so that 
conversational queries can match technical names.
**No manual action is needed** when adding Excel 
files with this key format.

However, if users commonly ask using terminology 
not derivable from the key name (e.g. a business 
nickname or synonym), add a Q&A entry to 
`All_FAQ.txt` as a synonym bridge:

```
Q: What is the "journey length"?
A: Journey length refers to TRIP_DURATION_IN_DAYS — 
the number of days between departure and return.
```

---

## Folder naming conventions

- Product folder names must be lowercase with 
  underscores: `airplus_intelligence`, `portal`
- The folder name becomes the `product` metadata 
  field on every chunk — keep it stable
- Display names are mapped separately in 
  `ui/app.py display_name()` — update that mapping 
  if you want a different UI label

---

## When to re-ingest

Re-ingest whenever you:
- Add, remove, or rename a document
- Edit content in an existing document
- Change the embedding model (full re-ingest required)

```bash
docker compose --profile ingest run --rm ingest \
  python build_vectorstore.py
```

Or click **Refresh Knowledge Base** in the UI.

---

*AirPlus Assist — Built by Product Management · April 2026*
