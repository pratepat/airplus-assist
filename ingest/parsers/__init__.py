"""
Parser package for AirPlus Assist ingest pipeline.
"""

from .pdf_parser import parse_pdf
from .docx_parser import parse_docx
from .excel_parser import parse_excel
from .text_parser import parse_txt
from .url_parser import parse_url

__all__ = ["parse_pdf", "parse_docx", "parse_excel", "parse_txt", "parse_url"]
