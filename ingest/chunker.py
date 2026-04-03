"""
Text chunker for AirPlus Assist.

Splits raw text into overlapping chunks using LangChain's
RecursiveCharacterTextSplitter. Used by PDF, DOCX, TXT, and URL
parsers. Excel rows bypass this — they are already atomic chunks.
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into chunks of chunk_size characters with overlap."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        length_function=len,
    )
    return splitter.split_text(text)
