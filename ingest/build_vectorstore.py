"""
Ingest pipeline orchestrator for AirPlus Assist.

Walks docs/ recursively, detects product from folder name,
dispatches each file to the appropriate parser, embeds all chunks,
and upserts into ChromaDB as a fresh collection (full replace).

Run with: docker compose --profile ingest run --rm ingest python build_vectorstore.py
"""

import os
import sys
import hashlib
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

import chromadb
from embedder import get_embedder, embed_texts
from parsers import parse_pdf, parse_docx, parse_excel, parse_txt, parse_url

# ── Config from environment ────────────────────────────────────────────────────
CHROMA_HOST       = os.environ["CHROMA_HOST"]
CHROMA_PORT       = int(os.environ["CHROMA_PORT"])
CHROMA_COLLECTION = os.environ["CHROMA_COLLECTION"]
EMBED_MODEL       = os.environ["EMBED_MODEL"]
DOCS_DIR          = Path(__file__).parent / "docs"

# ── Helpers ────────────────────────────────────────────────────────────────────

def make_chunk_id(chunk: dict) -> str:
    """Deterministic ID built from all identity fields to guarantee uniqueness."""
    m = chunk["metadata"]
    raw = "::".join([
        m["product"],
        m["source_file"],
        str(m.get("sheet_name") or ""),
        str(m.get("url") or ""),
        str(m["chunk_index"]),
        chunk["content"][:80],
    ])
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def collect_chunks_from_product(product_dir: Path) -> tuple[list[dict], list[str]]:
    """
    Process all supported files in one product folder.
    Returns (chunks, errors) where errors are human-readable skip messages.
    """
    product = product_dir.name
    chunks: list[dict] = []
    errors: list[str] = []

    for file_path in sorted(product_dir.iterdir()):
        if file_path.is_dir():
            continue

        suffix = file_path.suffix.lower()
        name   = file_path.name

        # Skip hidden / system files
        if name.startswith("."):
            continue

        try:
            if suffix == ".pdf":
                result = parse_pdf(file_path, product)
                chunks.extend(result)
                print(f"  [pdf]   {name}: {len(result)} chunks")

            elif suffix == ".docx":
                result = parse_docx(file_path, product)
                chunks.extend(result)
                print(f"  [docx]  {name}: {len(result)} chunks")

            elif suffix == ".xlsx":
                result = parse_excel(file_path, product)
                chunks.extend(result)
                print(f"  [xlsx]  {name}: {len(result)} chunks")

            elif suffix == ".txt" and name != "urls.txt":
                result = parse_txt(file_path, product)
                chunks.extend(result)
                print(f"  [txt]   {name}: {len(result)} chunks")

            elif name == "urls.txt":
                # Parse each URL in the file
                lines = file_path.read_text(encoding="utf-8").splitlines()
                urls  = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
                url_total = 0
                for url in urls:
                    try:
                        result = parse_url(url, product, name)
                        chunks.extend(result)
                        url_total += len(result)
                    except Exception as exc:
                        msg = f"URL {url}: {exc}"
                        errors.append(msg)
                        print(f"  [url]   WARNING: {msg}")
                print(f"  [url]   {name}: {url_total} chunks from {len(urls)} URL(s)")

            else:
                print(f"  [skip]  {name}: unsupported format")

        except Exception as exc:
            msg = f"{name}: {exc}"
            errors.append(msg)
            print(f"  [ERROR] {msg}")

    return chunks, errors


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("AirPlus Assist — Ingest Pipeline")
    print("=" * 60)

    if not DOCS_DIR.exists():
        print(f"ERROR: docs/ directory not found at {DOCS_DIR}")
        sys.exit(1)

    # ── Discover product folders ───────────────────────────────────────────────
    product_dirs = [d for d in sorted(DOCS_DIR.iterdir()) if d.is_dir() and not d.name.startswith(".")]
    if not product_dirs:
        print("No product folders found in docs/. Nothing to ingest.")
        sys.exit(0)

    all_chunks:  list[dict]  = []
    all_errors:  list[str]   = []
    per_product: dict[str, int] = {}
    per_file:    dict[str, int] = defaultdict(int)

    for product_dir in product_dirs:
        print(f"\nProduct: {product_dir.name}")
        print("-" * 40)
        chunks, errors = collect_chunks_from_product(product_dir)
        all_chunks.extend(chunks)
        all_errors.extend(errors)
        per_product[product_dir.name] = len(chunks)
        for c in chunks:
            per_file[c["metadata"]["source_file"]] += 1

    print(f"\nTotal chunks collected: {len(all_chunks)}")

    if not all_chunks:
        print("No chunks to embed. Exiting.")
        sys.exit(0)

    # ── Embed ──────────────────────────────────────────────────────────────────
    print(f"\nLoading embedding model: {EMBED_MODEL}")
    model = get_embedder(EMBED_MODEL)

    print(f"Embedding {len(all_chunks)} chunks…")
    texts      = [c["content"] for c in all_chunks]
    embeddings = embed_texts(texts, model)
    print("Embedding complete.")

    # ── ChromaDB ───────────────────────────────────────────────────────────────
    print(f"\nConnecting to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}")
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

    # Full replace: delete existing collection if present
    existing = [c.name for c in client.list_collections()]
    if CHROMA_COLLECTION in existing:
        print(f"Deleting existing collection '{CHROMA_COLLECTION}'…")
        client.delete_collection(CHROMA_COLLECTION)

    print(f"Creating collection '{CHROMA_COLLECTION}'…")
    collection = client.create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    # Upsert in batches of 500 to avoid request size limits
    BATCH = 500
    # Include global position as tiebreaker so truly identical rows never collide
    ids        = [make_chunk_id(c) + f"{i:06x}" for i, c in enumerate(all_chunks)]
    metadatas  = []
    for c in all_chunks:
        # ChromaDB metadata values must be str/int/float/bool — convert None → ""
        m = {k: (v if v is not None else "") for k, v in c["metadata"].items()}
        metadatas.append(m)

    for start in range(0, len(all_chunks), BATCH):
        end = start + BATCH
        collection.add(
            ids        = ids[start:end],
            embeddings = embeddings[start:end],
            documents  = texts[start:end],
            metadatas  = metadatas[start:end],
        )
        print(f"  Stored chunks {start + 1}–{min(end, len(all_chunks))} / {len(all_chunks)}")

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("INGEST SUMMARY")
    print("=" * 60)

    print("\nChunks by product:")
    for product, count in per_product.items():
        print(f"  {product:<40} {count:>6} chunks")

    print("\nChunks by file:")
    for fname, count in sorted(per_file.items()):
        print(f"  {fname:<40} {count:>6} chunks")

    print(f"\nTotal chunks stored : {len(all_chunks)}")
    print(f"Collection          : {CHROMA_COLLECTION}")
    print(f"Embed model         : {EMBED_MODEL}")

    if all_errors:
        print(f"\nErrors / skipped ({len(all_errors)}):")
        for err in all_errors:
            print(f"  FAILED: {err}")
    else:
        print("\nNo errors. All files ingested successfully.")

    print("=" * 60)


if __name__ == "__main__":
    main()
