"""
Plain-text parser for AirPlus Assist.

Reads .txt files (excluding urls.txt, which is handled by url_parser)
and splits them into chunks. All source-type-specific metadata fields
are set to None.
"""

from datetime import datetime, timezone
from pathlib import Path
from chunker import chunk_text


def parse_txt(file_path: Path, product: str) -> list[dict]:
    """
    Parse a plain-text file and return a list of chunk dicts.
    Each dict has 'content' (str) and 'metadata' (dict).
    """
    chunk_size = 512
    overlap = 80

    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = file_path.read_text(encoding="latin-1")

    text = text.strip()
    if not text:
        return []

    chunks = chunk_text(text, chunk_size, overlap)
    results = []
    for idx, chunk in enumerate(chunks):
        chunk = chunk.strip()
        if not chunk:
            continue
        results.append({
            "content": chunk,
            "metadata": {
                "product":       product,
                "source_file":   file_path.name,
                "source_type":   "txt",
                "page_number":   None,
                "sheet_name":    None,
                "question_text": None,
                "url":           None,
                "section_title": None,
                "chunk_preview": chunk[:120],
                "ingested_at":   datetime.now(timezone.utc).isoformat(),
                "chunk_index":   idx,
            },
        })
    return results
