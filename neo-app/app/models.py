"""Pydantic request/response models."""
from typing import Optional, List
from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str
    product: Optional[str] = None
    language: str = "EN"


class AnalyseRequest(BaseModel):
    text: str
    language: str = "EN"
    product: Optional[str] = None
    max_questions: int = 5


class GenerateReplyRequest(BaseModel):
    original_text: str
    answered_results: list
    language: str = "EN"


class SummaryRequest(BaseModel):
    question: str
    product: Optional[str] = None
    language: str = "EN"


class SourceReference(BaseModel):
    rank: int
    label: str
    excerpt: str
    confidence: str          # "high" | "medium" | "low"
    source_type: str         # "pdf" | "xlsx" | "url" | "docx" | "txt"
    product: str
    url: Optional[str] = None
    page_number: Optional[int] = None
    sheet_name: Optional[str] = None
    question_text: Optional[str] = None
    ingested_at: str = ""
    more_information: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    confidence: str          # "high" | "medium" | "low" | "none"
    product_scope: str       # product key or "all"
    language: str
    original_question: str
    retrieved_with: str      # possibly translated retrieval question
    sources: List[SourceReference]
    has_contradiction: bool = False
    search_stage: str = "all"  # "stage1" | "stage2" | "all"
