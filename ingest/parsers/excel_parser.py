"""
Excel parser for AirPlus Assist.

Uses openpyxl to read any Excel file with a Key column.
Column discovery is fully dynamic — no column names are hardcoded.
Columns ending in "Approved" or "Approved?" are skipped (status flags).

One row = one chunk. Chunk content is a structured text block:
  Term: {key}
  {col1}: {val1}
  {col2}: {val2}
  ...
Empty/NaN values are omitted from the block.
"""

import openpyxl
from datetime import datetime, timezone
from pathlib import Path


def _is_approved_col(name: str) -> bool:
    """Return True if the column is an approval-status flag."""
    n = str(name).strip()
    return n.endswith("Approved") or n.endswith("Approved?")


def _cell_value(cell) -> str | None:
    """Return stripped string value or None for empty/NaN cells."""
    v = cell.value
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def parse_excel(file_path: Path, product: str) -> list[dict]:
    """
    Parse an Excel file and return one chunk dict per non-empty row.
    Each dict has 'content' (str) and 'metadata' (dict).
    """
    results = []
    wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=False))
        if not rows:
            continue

        # Read header row
        header_row = rows[0]
        headers = [_cell_value(c) for c in header_row]

        # Find the Key column index
        key_col_idx = None
        for i, h in enumerate(headers):
            if h and h.strip().lower() == "key":
                key_col_idx = i
                break

        if key_col_idx is None:
            print(f"  [excel] Sheet '{sheet_name}' in {file_path.name}: no 'Key' column found, skipping.")
            continue

        # Identify content columns (skip Key and Approved cols)
        content_col_indices = [
            i for i, h in enumerate(headers)
            if i != key_col_idx and h and not _is_approved_col(h)
        ]

        chunk_index = 0
        for row in rows[1:]:
            key_val = _cell_value(row[key_col_idx]) if key_col_idx < len(row) else None
            if not key_val:
                continue  # skip rows with no Key

            lines = [f"Term: {key_val}"]
            for col_idx in content_col_indices:
                if col_idx >= len(row):
                    continue
                col_name = headers[col_idx]
                col_val = _cell_value(row[col_idx])
                if col_val:
                    lines.append(f"{col_name}: {col_val}")

            content = "\n".join(lines)
            results.append({
                "content": content,
                "metadata": {
                    "product":       product,
                    "source_file":   file_path.name,
                    "source_type":   "xlsx",
                    "page_number":   None,
                    "sheet_name":    sheet_name,
                    "question_text": key_val,
                    "url":           None,
                    "section_title": None,
                    "chunk_preview": content[:120],
                    "ingested_at":   datetime.now(timezone.utc).isoformat(),
                    "chunk_index":   chunk_index,
                },
            })
            chunk_index += 1

    wb.close()
    return results
