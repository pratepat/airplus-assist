"""
PDF parser for AirPlus Assist.

Extracts text page by page using PyMuPDF (fitz). Each page's text
is split into chunks. Page number and a detected section title
(first bold/heading-like line on the page) are carried as metadata
so every answer can be cited to an exact PDF page.
"""

import fitz  # PyMuPDF
from datetime import datetime, timezone
from pathlib import Path
from chunker import chunk_text


def _detect_section_title(page: fitz.Page) -> str | None:
    """Return the first bold or large-font text on the page, if any."""
    blocks = page.get_text("dict").get("blocks", [])
    for block in blocks:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                flags = span.get("flags", 0)
                size = span.get("size", 0)
                text = span.get("text", "").strip()
                if text and (flags & 16 or size >= 13):  # bold flag or large font
                    return text[:200]
    return None


def parse_pdf(file_path: Path, product: str) -> list[dict]:
    """
    Parse a PDF and return a list of chunk dicts.
    Each dict has 'content' (str) and 'metadata' (dict).
    """
    results = []
    chunk_size = 512
    overlap = 80

    doc = fitz.open(str(file_path))
    for page_num, page in enumerate(doc, start=1):
        text = page.get_text("text").strip()
        if not text:
            continue

        section_title = _detect_section_title(page)
        chunks = chunk_text(text, chunk_size, overlap)

        for idx, chunk in enumerate(chunks):
            chunk = chunk.strip()
            if not chunk:
                continue
            results.append({
                "content": chunk,
                "metadata": {
                    "product":       product,
                    "source_file":   file_path.name,
                    "source_type":   "pdf",
                    "page_number":   page_num,
                    "sheet_name":    None,
                    "question_text": None,
                    "url":           None,
                    "section_title": section_title,
                    "chunk_preview": chunk[:120],
                    "ingested_at":   datetime.now(timezone.utc).isoformat(),
                    "chunk_index":   idx,
                },
            })
    doc.close()
    return results
