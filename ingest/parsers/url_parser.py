"""
URL parser for AirPlus Assist.

Fetches a URL with trafilatura (strips nav/ads/boilerplate).
On fetch failure or empty extraction, logs a warning and returns [].
Never crashes the ingest run on a bad URL.

source_file is the urls.txt filename for metadata traceability.
The original URL is stored in metadata.url for citation.
"""

import trafilatura
from datetime import datetime, timezone
from chunker import chunk_text


def parse_url(url: str, product: str, source_file: str) -> list[dict]:
    """
    Fetch and parse a URL. Returns a list of chunk dicts.
    Returns [] on failure — caller must log the skip.
    """
    chunk_size = 512
    overlap = 80

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        print(f"  [url_parser] WARNING: could not fetch {url} — skipping.")
        return []

    text = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=True,
        no_fallback=False,
    )
    if not text or not text.strip():
        print(f"  [url_parser] WARNING: no content extracted from {url} — skipping.")
        return []

    # Best-effort page title extraction
    metadata_obj = trafilatura.extract(downloaded, output_format="json", with_metadata=True)
    section_title: str | None = None
    if metadata_obj:
        import json
        try:
            meta = json.loads(metadata_obj)
            section_title = meta.get("title") or None
        except (json.JSONDecodeError, AttributeError):
            pass

    chunks = chunk_text(text.strip(), chunk_size, overlap)
    results = []
    for idx, chunk in enumerate(chunks):
        chunk = chunk.strip()
        if not chunk:
            continue
        results.append({
            "content": chunk,
            "metadata": {
                "product":       product,
                "source_file":   source_file,
                "source_type":   "url",
                "page_number":   None,
                "sheet_name":    None,
                "question_text": None,
                "url":           url,
                "section_title": section_title,
                "chunk_preview": chunk[:120],
                "ingested_at":   datetime.now(timezone.utc).isoformat(),
                "chunk_index":   idx,
            },
        })
    return results
