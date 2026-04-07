"""
Plain-text parser for AirPlus Assist.

Reads .txt files (excluding urls.txt, which is handled by url_parser)
and splits them into chunks. Q&A formatted files are split on Q&A
boundaries; all other files use standard character-based chunking.
"""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from chunker import chunk_text


def parse_txt(file_path: Path, product: str) -> list[dict]:
    """
    Parse a plain-text file and return a list of chunk dicts.
    Each dict has 'content' (str) and 'metadata' (dict).

    Q&A detection: if the file contains more than 3 occurrences of
    '\\nQ:' or starts with 'Q:', each Q+A pair becomes one chunk.
    Otherwise, standard RecursiveCharacterTextSplitter chunking is used.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = file_path.read_text(encoding="latin-1")

    content = content.strip()
    if not content:
        return []

    ingested_at = datetime.now(timezone.utc).isoformat()
    source_file = file_path.name
    chunks = []

    is_qa_format = content.count("\nQ:") > 3 or content.startswith("Q:")

    if is_qa_format:
        pairs = re.split(r'\n(?=Q:)', content)

        for i, pair in enumerate(pairs):
            pair = pair.strip()
            if not pair:
                continue

            # Extract question text for metadata
            question_text = None
            for line in pair.split("\n"):
                if line.startswith("Q:"):
                    question_text = line[2:].strip()
                    break

            chunks.append({
                "content": pair,
                "metadata": {
                    "product":       product,
                    "source_file":   source_file,
                    "source_type":   "txt",
                    "page_number":   None,
                    "sheet_name":    None,
                    "question_text": question_text,
                    "url":           None,
                    "section_title": "FAQ",
                    "chunk_preview": pair[:120],
                    "ingested_at":   ingested_at,
                    "chunk_index":   i,
                },
            })

    else:
        chunk_size = int(os.getenv("CHUNK_SIZE", 512))
        overlap    = int(os.getenv("CHUNK_OVERLAP", 80))
        text_chunks = chunk_text(content, chunk_size, overlap)

        for i, text in enumerate(text_chunks):
            text = text.strip()
            if not text:
                continue
            chunks.append({
                "content": text,
                "metadata": {
                    "product":       product,
                    "source_file":   source_file,
                    "source_type":   "txt",
                    "page_number":   None,
                    "sheet_name":    None,
                    "question_text": None,
                    "url":           None,
                    "section_title": None,
                    "chunk_preview": text[:120],
                    "ingested_at":   ingested_at,
                    "chunk_index":   i,
                },
            })

    return chunks
