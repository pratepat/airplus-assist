"""
DOCX parser for AirPlus Assist.

Extracts paragraphs with python-docx, tracking the most recent
Heading 1 / Heading 2 as section_title for citation. Page numbers
are not reliably available in DOCX format and are set to None.
"""

from docx import Document
from datetime import datetime, timezone
from pathlib import Path
from chunker import chunk_text


def parse_docx(file_path: Path, product: str) -> list[dict]:
    """
    Parse a DOCX file and return a list of chunk dicts.
    Each dict has 'content' (str) and 'metadata' (dict).
    """
    results = []
    chunk_size = 512
    overlap = 80

    doc = Document(str(file_path))
    current_section = None
    buffer: list[str] = []

    def flush_buffer(section: str | None, chunk_offset: int) -> tuple[list[dict], int]:
        text = "\n".join(buffer).strip()
        if not text:
            return [], chunk_offset
        chunks = chunk_text(text, chunk_size, overlap)
        out = []
        for idx, chunk in enumerate(chunks):
            chunk = chunk.strip()
            if not chunk:
                continue
            out.append({
                "content": chunk,
                "metadata": {
                    "product":       product,
                    "source_file":   file_path.name,
                    "source_type":   "docx",
                    "page_number":   None,
                    "sheet_name":    None,
                    "question_text": None,
                    "url":           None,
                    "section_title": section,
                    "chunk_preview": chunk[:120],
                    "ingested_at":   datetime.now(timezone.utc).isoformat(),
                    "chunk_index":   chunk_offset + idx,
                },
            })
        return out, chunk_offset + len(out)

    chunk_offset = 0
    for para in doc.paragraphs:
        style = para.style.name if para.style else ""
        text = para.text.strip()

        if style.startswith("Heading 1") or style.startswith("Heading 2"):
            # flush accumulated text under old heading, then start new section
            flushed, chunk_offset = flush_buffer(current_section, chunk_offset)
            results.extend(flushed)
            buffer.clear()
            if text:
                current_section = text
        elif text:
            buffer.append(text)

    # flush remainder
    flushed, _ = flush_buffer(current_section, chunk_offset)
    results.extend(flushed)

    return results
