"""
Document ingestion: parse all supported formats, chunk, embed, store in memory.

Supported formats: PDF, DOCX, XLSX, TXT (including Q&A format), URLs (urls.txt)
"""
import hashlib
import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import config

log = logging.getLogger(__name__)

_CACHE_FILE = Path(__file__).parent.parent / ".cache" / "ingest_cache.pkl"


def _fingerprint(docs_path: Path) -> str:
    """MD5 of all document file paths + mtimes + sizes + ingest-relevant config."""
    parts: list[str] = []
    if docs_path.exists():
        for f in sorted(docs_path.rglob("*")):
            if f.is_file() and not f.name.startswith("."):
                st = f.stat()
                parts.append(f"{f}:{st.st_mtime}:{st.st_size}")
    parts.append(f"embed_model:{config.embed_model}")
    parts.append(f"chunk_size:{config.chunk_size}")
    parts.append(f"chunk_overlap:{config.chunk_overlap}")
    return hashlib.md5("\n".join(parts).encode()).hexdigest()


def _load_cache(fp: str) -> "IngestResult | None":
    if not _CACHE_FILE.exists():
        return None
    try:
        with open(_CACHE_FILE, "rb") as fh:
            data = pickle.load(fh)
        if data.get("fingerprint") != fp:
            log.info("Documents changed — cache invalid, re-ingesting")
            return None
        r = IngestResult()
        r.chunks      = data["chunks"]
        r.embeddings  = data["embeddings"]
        r.products    = data["products"]
        r.total       = data["total"]
        r.ingested_at = data["ingested_at"]
        log.info("Cache hit — %d chunks, %d product(s) (skipping embed step)",
                 r.total, len(r.products))
        return r
    except Exception as exc:
        log.warning("Cache load failed (%s) — will re-ingest", exc)
        return None


def _save_cache(result: "IngestResult", fp: str) -> None:
    try:
        _CACHE_FILE.parent.mkdir(exist_ok=True)
        with open(_CACHE_FILE, "wb") as fh:
            pickle.dump({
                "fingerprint": fp,
                "chunks":      result.chunks,
                "embeddings":  result.embeddings,
                "products":    result.products,
                "total":       result.total,
                "ingested_at": result.ingested_at,
            }, fh)
        log.info("Ingest cache saved (%d chunks)", result.total)
    except Exception as exc:
        log.warning("Cache save failed: %s", exc)


# Module-level model cache so ingest and RAG share the same instance
_embed_model_cache: dict[str, Any] = {}


def get_embed_model(model_name: str):
    if model_name not in _embed_model_cache:
        from sentence_transformers import SentenceTransformer
        log.info("Loading embedding model: %s", model_name)
        _embed_model_cache[model_name] = SentenceTransformer(model_name)
    return _embed_model_cache[model_name]


def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
    )


def _base_meta(product: str, source_file: str, source_type: str) -> dict:
    return {
        "product": product,
        "source_file": source_file,
        "source_type": source_type,
        "page_number": None,
        "sheet_name": None,
        "question_text": None,
        "url": None,
        "section_title": None,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "chunk_index": 0,
    }


# ── Parsers ────────────────────────────────────────────────────────────────────

def parse_pdf(file_path: Path, product: str) -> list[dict]:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        log.warning("PyMuPDF not installed — skipping %s", file_path.name)
        return []

    chunks = []
    sp = _splitter()
    try:
        doc = fitz.open(str(file_path))
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text()
            if not text.strip():
                continue
            for i, piece in enumerate(sp.split_text(text)):
                meta = _base_meta(product, file_path.name, "pdf")
                meta["page_number"] = page_num
                meta["chunk_index"] = i
                chunks.append({"content": piece, "metadata": meta})
        doc.close()
    except Exception as e:
        log.error("PDF parse error %s: %s", file_path.name, e)
    return chunks


def parse_docx(file_path: Path, product: str) -> list[dict]:
    try:
        from docx import Document
    except ImportError:
        log.warning("python-docx not installed — skipping %s", file_path.name)
        return []

    chunks = []
    sp = _splitter()
    try:
        doc = Document(str(file_path))
        current_section: str | None = None
        buffer: list[str] = []

        def flush():
            if not buffer:
                return
            text = "\n".join(buffer)
            for i, piece in enumerate(sp.split_text(text)):
                meta = _base_meta(product, file_path.name, "docx")
                meta["section_title"] = current_section
                meta["chunk_index"] = i
                chunks.append({"content": piece, "metadata": meta})

        for para in doc.paragraphs:
            style = para.style.name if para.style else ""
            text = para.text.strip()
            if not text:
                continue
            if style.startswith("Heading"):
                flush()
                buffer.clear()
                current_section = text
            else:
                buffer.append(text)
        flush()
    except Exception as e:
        log.error("DOCX parse error %s: %s", file_path.name, e)
    return chunks


def parse_excel(file_path: Path, product: str) -> list[dict]:
    try:
        import openpyxl
    except ImportError:
        log.warning("openpyxl not installed — skipping %s", file_path.name)
        return []

    chunks = []
    try:
        wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                continue

            headers = [str(h).strip() if h is not None else "" for h in rows[0]]
            key_idx = next((i for i, h in enumerate(headers) if h.lower() == "key"), None)
            if key_idx is None:
                continue

            content_cols = [
                (i, h) for i, h in enumerate(headers)
                if i != key_idx
                and not h.lower().rstrip("?").endswith("approved")
            ]

            for row_num, row in enumerate(rows[1:], start=2):
                key_val = row[key_idx] if key_idx < len(row) else None
                if not key_val:
                    continue
                key_val = str(key_val).strip()

                parts = [f"Term: {key_val}"]
                for i, col_name in content_cols:
                    val = row[i] if i < len(row) else None
                    if val is not None and str(val).strip():
                        parts.append(f"{col_name}: {str(val).strip()}")

                meta = _base_meta(product, file_path.name, "xlsx")
                meta["sheet_name"] = sheet_name
                meta["question_text"] = key_val
                meta["chunk_index"] = row_num
                chunks.append({"content": "\n".join(parts), "metadata": meta})
        wb.close()
    except Exception as e:
        log.error("XLSX parse error %s: %s", file_path.name, e)
    return chunks


def parse_txt(file_path: Path, product: str) -> list[dict]:
    try:
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = file_path.read_text(encoding="latin-1")
    except Exception as e:
        log.error("TXT read error %s: %s", file_path.name, e)
        return []

    # Auto-detect Q&A format
    is_qa = text.count("\nQ:") > 3 or text.startswith("Q:")
    chunks = []

    if is_qa:
        current_q: str | None = None
        current_a: list[str] = []
        pairs: list[tuple[str, str]] = []

        for line in text.splitlines():
            if line.startswith("Q:"):
                if current_q is not None:
                    pairs.append((current_q, "\n".join(current_a)))
                current_q = line[2:].strip()
                current_a = []
            elif line.startswith("A:"):
                current_a.append(line[2:].strip())
            else:
                current_a.append(line)
        if current_q:
            pairs.append((current_q, "\n".join(current_a)))

        for i, (q, a) in enumerate(pairs):
            meta = _base_meta(product, file_path.name, "txt")
            meta["question_text"] = q
            meta["section_title"] = "FAQ"
            meta["chunk_index"] = i
            chunks.append({"content": f"Q: {q}\nA: {a}", "metadata": meta})
    else:
        sp = _splitter()
        for i, piece in enumerate(sp.split_text(text)):
            meta = _base_meta(product, file_path.name, "txt")
            meta["chunk_index"] = i
            chunks.append({"content": piece, "metadata": meta})

    return chunks


def parse_urls(file_path: Path, product: str) -> list[dict]:
    try:
        import trafilatura
    except ImportError:
        log.warning("trafilatura not installed — skipping %s", file_path.name)
        return []

    try:
        raw = file_path.read_text(encoding="utf-8")
        urls = [u.strip() for u in raw.splitlines() if u.strip() and not u.startswith("#")]
    except Exception as e:
        log.error("URL file read error %s: %s", file_path.name, e)
        return []

    chunks = []
    sp = _splitter()

    for url in urls:
        try:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                continue
            text = trafilatura.extract(downloaded)
            if not text or not text.strip():
                continue
            meta_info = trafilatura.extract_metadata(downloaded)
            title = meta_info.title if meta_info and meta_info.title else url
            for i, piece in enumerate(sp.split_text(text)):
                meta = _base_meta(product, file_path.name, "url")
                meta["url"] = url
                meta["section_title"] = title
                meta["chunk_index"] = i
                chunks.append({"content": piece, "metadata": meta})
            log.info("  URL %s → %d chunks", url, i + 1)
        except Exception as e:
            log.warning("URL fetch error %s: %s", url, e)

    return chunks


# ── Ingest orchestrator ────────────────────────────────────────────────────────

class IngestResult:
    """Holds all ingested chunks and their precomputed embeddings."""
    chunks: list[dict]
    embeddings: np.ndarray | None
    products: list[str]
    total: int
    ingested_at: str

    def __init__(self):
        self.chunks = []
        self.embeddings = None
        self.products = []
        self.total = 0
        self.ingested_at = ""


def ingest_documents(docs_path: str | Path) -> IngestResult:
    """
    Scan docs_path/{product}/ folders, parse all supported documents,
    embed every chunk, and return an IngestResult ready for querying.

    Results are cached to disk keyed by a fingerprint of all document files
    and config values. Unchanged documents skip the embed step entirely.
    """
    docs_path = Path(docs_path)

    fp = _fingerprint(docs_path)
    cached = _load_cache(fp)
    if cached is not None:
        return cached

    result = IngestResult()

    if not docs_path.exists():
        log.warning("Documents path does not exist: %s", docs_path)
        return result

    all_chunks: list[dict] = []
    products: set[str] = set()

    for product_dir in sorted(docs_path.iterdir()):
        if not product_dir.is_dir() or product_dir.name.startswith("."):
            continue

        product = product_dir.name
        products.add(product)
        product_chunks: list[dict] = []

        for file_path in sorted(product_dir.iterdir()):
            if file_path.name.startswith(".") or not file_path.is_file():
                continue

            ext  = file_path.suffix.lower()
            name = file_path.name.lower()

            if ext == ".pdf":
                fc = parse_pdf(file_path, product)
            elif ext == ".docx":
                fc = parse_docx(file_path, product)
            elif ext in (".xlsx", ".xls"):
                fc = parse_excel(file_path, product)
            elif ext == ".txt" and name == "urls.txt":
                fc = parse_urls(file_path, product)
            elif ext == ".txt":
                fc = parse_txt(file_path, product)
            else:
                log.debug("Skipping unsupported file: %s", file_path.name)
                continue

            log.info("  %s → %d chunks", file_path.name, len(fc))
            product_chunks.extend(fc)

        log.info("Product '%s': %d chunks total", product, len(product_chunks))
        all_chunks.extend(product_chunks)

    if not all_chunks:
        log.warning("No chunks found in %s", docs_path)
        return result

    # Embed all chunks
    log.info("Embedding %d chunks with %s …", len(all_chunks), config.embed_model)
    model = get_embed_model(config.embed_model)
    texts = [c["content"] for c in all_chunks]
    embeddings = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)

    result.chunks = all_chunks
    result.embeddings = np.array(embeddings, dtype=np.float32)
    result.products = sorted(products)
    result.total = len(all_chunks)
    result.ingested_at = datetime.now(timezone.utc).isoformat()

    log.info(
        "Ingest complete: %d chunks from %d product(s): %s",
        result.total, len(result.products), result.products,
    )
    _save_cache(result, fp)
    return result
