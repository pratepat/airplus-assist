from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, field_validator

SUPPORTED_LANGUAGES = ["EN", "DE", "FR", "ES", "IT", "NL"]


class AskRequest(BaseModel):
    question: str
    product: Optional[str] = None   # "airplus_intelligence" | "portal" | None = all products
    language: str = "EN"            # one of SUPPORTED_LANGUAGES

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        code = v.upper()
        if code not in SUPPORTED_LANGUAGES:
            raise ValueError(f"language must be one of {SUPPORTED_LANGUAGES}")
        return code


class SourceReference(BaseModel):
    rank: int                    # 1-5, position after re-ranking
    label: str                   # human-readable e.g. "glossary.xlsx — Term: Payment"
    excerpt: str                 # up to 200 chars of chunk content
    confidence: str              # "high" | "medium" | "low"
    source_type: str             # "pdf" | "xlsx" | "url" | "docx" | "txt"
    product: str
    url: Optional[str] = None
    page_number: Optional[int] = None
    sheet_name: Optional[str] = None
    question_text: Optional[str] = None
    ingested_at: str


class AskResponse(BaseModel):
    answer: str
    confidence: str              # "high" | "medium" | "low" | "none"
    product_scope: str           # "airplus_intelligence" | "portal" | "all"
    language: str                # echo back the selected language
    original_question: str       # the question as typed by the user
    retrieved_with: str          # question used for retrieval (translated if non-EN)
    sources: List[SourceReference]
    has_contradiction: bool = False  # True if LLM detected conflict across sources


class IngestStatus(BaseModel):
    status: str
    message: str
