"""
RAG pipeline: retrieval via Azure AI Search, generation via Azure OpenAI.

Two-layer hallucination guard:
  Layer 1 — Azure AI Search vector similarity (filtered by top_k candidates)
  Layer 2 — Azure Semantic Ranking score gate (RERANK_THRESHOLD, 0–4 scale)

Two-stage retrieval (for products with stage_config.json):
  Stage 1 — Glossary + FAQ (high-precision sources, search_stage="1")
  Stage 2 — Guides + manuals (fallback, search_stage="2")
"""
import asyncio
import json
import logging
import re
from typing import AsyncIterator, Optional

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from openai import AzureOpenAI

from .config import config
from .ingest import IngestSummary
from .models import AskResponse, SourceReference

log = logging.getLogger(__name__)

NO_ANSWER = "I don't have enough information in my knowledge base to answer this question."

SUPPORTED_LANGUAGES = ["EN", "DE", "FR", "ES", "IT", "NL"]


# ── RagPipeline ────────────────────────────────────────────────────────────────

class RagPipeline:
    def __init__(self, summary: IngestSummary):
        self._summary = summary
        self._openai = AzureOpenAI(
            azure_endpoint=config.azure_openai_endpoint,
            api_key=config.azure_openai_api_key or None,
            api_version=config.azure_openai_api_version,
        )
        self._search = SearchClient(
            endpoint=config.azure_search_endpoint,
            index_name=config.azure_search_index,
            credential=AzureKeyCredential(config.azure_search_key),
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _embed_query(self, text: str) -> list[float]:
        response = self._openai.embeddings.create(
            input=[text],
            model=config.azure_openai_embed_model,
        )
        return response.data[0].embedding

    def _azure_chat(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.1,
    ) -> str:
        response = self._openai.chat.completions.create(
            model=config.azure_openai_chat_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return (response.choices[0].message.content or "").strip()

    def _search_azure(
        self,
        query_vec: list[float],
        product: Optional[str],
        stage: Optional[str] = None,
        top_k: int | None = None,
    ) -> list[dict]:
        """
        Vector search with Azure AI Search Semantic Ranking.
        Returns list of result dicts including '@search.reranker_score'.
        """
        top_k = top_k or config.top_k_retrieval

        # Build OData filter
        filters: list[str] = []
        if product:
            filters.append(f"product eq '{product}'")
        if stage is not None:
            filters.append(f"search_stage eq '{stage}'")
        odata_filter = " and ".join(filters) or None

        vector_query = VectorizedQuery(
            vector=query_vec,
            k_nearest_neighbors=top_k,
            fields="content_vector",
        )

        results = self._search.search(
            search_text=None,
            vector_queries=[vector_query],
            filter=odata_filter,
            query_type="semantic",
            semantic_configuration_name="semantic_config",
            top=top_k,
            select=[
                "content", "product", "source_file", "source_type", "search_stage",
                "page_number", "sheet_name", "question_text", "url",
                "section_title", "more_information", "ingested_at", "chunk_index",
            ],
        )

        hits = []
        for r in results:
            hits.append({
                "content":          r.get("content", ""),
                "score":            r.get("@search.reranker_score") or 0.0,
                "metadata": {
                    "product":          r.get("product", ""),
                    "source_file":      r.get("source_file", ""),
                    "source_type":      r.get("source_type", ""),
                    "search_stage":     r.get("search_stage"),
                    "page_number":      r.get("page_number"),
                    "sheet_name":       r.get("sheet_name"),
                    "question_text":    r.get("question_text"),
                    "url":              r.get("url"),
                    "section_title":    r.get("section_title"),
                    "more_information": r.get("more_information"),
                    "ingested_at":      r.get("ingested_at", ""),
                    "chunk_index":      r.get("chunk_index", 0),
                },
            })
        return sorted(hits, key=lambda h: h["score"], reverse=True)

    def _translate_to_english(self, question: str) -> str:
        prompt = (
            "Translate the following question to English. "
            "Return ONLY the translation, nothing else.\n\n"
            f"Question: {question}"
        )
        try:
            result = self._azure_chat(prompt, max_tokens=200, temperature=0.0)
            return result if result else question
        except Exception as e:
            log.warning("Translation failed (%s) — using original question", e)
            return question

    def _build_label(self, meta: dict) -> str:
        source_type = meta.get("source_type", "txt")
        source_file = meta.get("source_file", "")
        page        = meta.get("page_number")
        sheet       = meta.get("sheet_name")
        qt          = meta.get("question_text")
        section     = meta.get("section_title")
        url         = meta.get("url")

        if source_type == "url" and url:
            return url
        if source_type == "pdf" and page:
            return f"{source_file} — p.{page}"
        if source_type == "xlsx":
            return f"{source_file} — {sheet}: {qt or ''}" if sheet else source_file
        if source_type in ("docx", "glossary_docx") and section:
            return f"{source_file} — {section}"
        return source_file

    def _score_to_confidence(self, score: float) -> str:
        # Azure Semantic Ranking: 0–4 scale
        if score >= 3.0:
            return "high"
        if score >= 1.5:
            return "medium"
        return "low"

    def _build_source(self, rank: int, hit: dict) -> SourceReference:
        meta = hit["metadata"]
        return SourceReference(
            rank=rank,
            label=self._build_label(meta),
            excerpt=hit["content"][:200].strip(),
            confidence=self._score_to_confidence(hit["score"]),
            source_type=meta.get("source_type", "txt"),
            product=meta.get("product", ""),
            url=meta.get("url"),
            page_number=meta.get("page_number"),
            sheet_name=meta.get("sheet_name"),
            question_text=meta.get("question_text"),
            ingested_at=meta.get("ingested_at", ""),
            more_information=meta.get("more_information"),
        )

    def _build_context(self, hits: list[dict]) -> str:
        parts = []
        for i, hit in enumerate(hits, start=1):
            source_file = hit["metadata"].get("source_file", "unknown")
            parts.append(f"[Source {i} ({source_file})]\n{hit['content']}")
        return "\n\n---\n\n".join(parts)

    def _language_instruction(self, language: str, source_types: list[str]) -> str:
        has_xlsx = "xlsx" in source_types
        if not language or language == "EN":
            return "\nAnswer using only the English (EN) values from the context. Ignore all other language columns." if has_xlsx else ""
        if has_xlsx:
            return (
                f"\nAnswer using only the {language} values from the context. "
                f"If the {language} value is missing for a term, use the English (EN) value instead."
            )
        return (
            f"\nAnswer in {language}. "
            f"If the source content is in a different language, provide both the original text and a {language} translation."
        )

    def _build_prompt(
        self, question: str, context: str, language: str, source_types: list[str]
    ) -> str:
        lang_instr = self._language_instruction(language, source_types)
        return f"""You are AirPlus Assist, a precise knowledge assistant for AirPlus products.

Answer the user's question using ONLY the context provided below.
The context contains ranked sources — source 1 is most relevant, source {len(source_types)} is least relevant.

Rules:
- Keep your answer under 150 words. Prefer shorter answers.
- Answer in 2-5 sentences maximum. Be direct and actionable.
- If the answer requires steps, use a numbered list.
- Use a bullet list only if listing 3 or more parallel items.
- Do not repeat the question or say "Based on the context..."
- Never use prior knowledge. Never speculate.
- Never say "typically" or "generally" unless those exact words appear in the source context.

Contradiction rule (IMPORTANT):
- If two or more sources provide conflicting information on the same point, flag it exactly as:
  "Note: Sources differ on this — [Source A label] states [X], while [Source B label] states [Y]."
- Do not silently choose one source over another.

If the answer is not in the context, respond exactly with:
"{NO_ANSWER}"
{lang_instr}

Context:
{context}

Question: {question}"""

    def _no_answer(
        self,
        question: str,
        retrieval_q: str,
        scope: str,
        language: str,
        search_stage: str = "all",
    ) -> AskResponse:
        return AskResponse(
            answer=NO_ANSWER,
            confidence="none",
            product_scope=scope,
            language=language,
            original_question=question,
            retrieved_with=retrieval_q,
            sources=[],
            has_contradiction=False,
            search_stage=search_stage,
        )

    def _has_stage_data(self, product: str) -> bool:
        """Check if this product has staged chunks in the index by querying for stage="1"."""
        try:
            results = self._search.search(
                search_text=None,
                filter=f"product eq '{product}' and search_stage eq '1'",
                top=1,
                select=["id"],
            )
            return any(True for _ in results)
        except Exception:
            return False

    def _retrieve(
        self,
        query_vec: list[float],
        retrieval_q: str,
        product: Optional[str],
    ) -> tuple[list[dict], str] | None:
        """
        Two-stage retrieval (if product has staged data) or flat retrieval.
        Returns (hits, stage_label) or None if hallucination gate blocks.
        """
        if product and self._has_stage_data(product):
            return self._two_stage_retrieve(query_vec, retrieval_q, product)

        # Flat retrieval
        hits = self._search_azure(query_vec, product)
        if not hits or hits[0]["score"] < config.rerank_threshold:
            log.debug("Reranker gate blocked (top_score=%.3f)", hits[0]["score"] if hits else -1)
            return None
        return hits, "all"

    def _two_stage_retrieve(
        self,
        query_vec: list[float],
        retrieval_q: str,
        product: str,
    ) -> tuple[list[dict], str] | None:
        """
        Three-tier decision using Azure Semantic Ranking scores (0–4 scale):
          top1 < RERANK_THRESHOLD               → BLOCK
          top1 >= STAGE1_QUALITY_THRESHOLD       → return stage1
          else try stage2:
            top2 >= RERANK_THRESHOLD             → return stage2
            else                                 → BLOCK
        """
        hits1      = self._search_azure(query_vec, product, stage="1")
        top1_score = hits1[0]["score"] if hits1 else 0.0

        log.info(
            "[two-stage] stage1_top=%.3f gate=%.2f quality=%.2f",
            top1_score, config.rerank_threshold, config.stage1_quality_threshold,
        )

        if top1_score < config.rerank_threshold:
            log.info("[two-stage] BLOCKED at stage1")
            return None

        if top1_score >= config.stage1_quality_threshold:
            log.info("[two-stage] stage1 CONFIDENT")
            return hits1[:config.top_k_rerank], "stage1"

        hits2      = self._search_azure(query_vec, product, stage="2")
        top2_score = hits2[0]["score"] if hits2 else 0.0

        log.info("[two-stage] stage1=%.3f below quality → stage2=%.3f", top1_score, top2_score)

        if hits2 and top2_score >= config.rerank_threshold:
            log.info("[two-stage] stage2 passes gate")
            return hits2[:config.top_k_rerank], "stage2"

        log.info("[two-stage] BLOCKED — stage1=%.3f stage2=%.3f both below gate", top1_score, top2_score)
        return None

    # ── Public API ─────────────────────────────────────────────────────────────

    def ask(
        self,
        question: str,
        product: Optional[str] = None,
        language: str = "EN",
    ) -> AskResponse:
        scope = product or "all"

        retrieval_q = question
        if language and language != "EN":
            retrieval_q = self._translate_to_english(question)

        query_vec = self._embed_query(retrieval_q)
        result    = self._retrieve(query_vec, retrieval_q, product)

        if result is None:
            return self._no_answer(question, retrieval_q, scope, language)

        hits, search_stage = result
        answer_hits = hits[:config.top_k_answer]

        context      = self._build_context(answer_hits)
        source_types = [h["metadata"].get("source_type", "") for h in answer_hits]
        prompt       = self._build_prompt(question, context, language, source_types)
        answer       = self._azure_chat(prompt, max_tokens=512, temperature=0.1)

        top_score        = hits[0]["score"]
        has_contradiction = len({h["metadata"].get("source_file") for h in answer_hits}) >= 3
        confidence       = "high" if top_score >= 3.0 else "medium"
        sources = [
            self._build_source(i + 1, hit)
            for i, hit in enumerate(answer_hits)
        ]

        return AskResponse(
            answer=answer,
            confidence=confidence,
            product_scope=scope,
            language=language,
            original_question=question,
            retrieved_with=retrieval_q,
            sources=sources,
            has_contradiction=has_contradiction,
            search_stage=search_stage,
        )

    async def ask_stream(
        self,
        question: str,
        product: Optional[str] = None,
        language: str = "EN",
    ) -> AsyncIterator[str]:
        """Async generator yielding SSE-formatted events."""
        scope = product or "all"

        def sse(data: dict) -> str:
            return f"data: {json.dumps(data)}\n\n"

        yield sse({"stage": "searching", "message": "Searching knowledge base…", "icon": "🔍"})

        loop        = asyncio.get_event_loop()
        retrieval_q = question

        if language and language != "EN":
            yield sse({"stage": "translating", "message": "Translating question to English…", "icon": "🌐"})
            retrieval_q = await loop.run_in_executor(None, self._translate_to_english, question)

        query_vec = await loop.run_in_executor(None, self._embed_query, retrieval_q)
        result    = await loop.run_in_executor(None, self._retrieve, query_vec, retrieval_q, product)

        if result is None:
            resp = self._no_answer(question, retrieval_q, scope, language)
            yield sse({"stage": "complete", "result": resp.model_dump()})
            return

        hits, search_stage = result
        yield sse({
            "stage":   "retrieved",
            "message": f"Found {len(hits)} sources ({search_stage}). Generating answer…",
            "icon":    "📚",
        })

        answer_hits = hits[:config.top_k_answer]
        yield sse({
            "stage":   "generating",
            "message": f"Generating answer with {config.azure_openai_chat_model}…",
            "icon":    "🤖",
        })

        context      = self._build_context(answer_hits)
        source_types = [h["metadata"].get("source_type", "") for h in answer_hits]
        prompt       = self._build_prompt(question, context, language, source_types)
        answer       = await loop.run_in_executor(
            None, self._azure_chat, prompt, 512, 0.1
        )

        top_score         = hits[0]["score"]
        has_contradiction = len({h["metadata"].get("source_file") for h in answer_hits}) >= 3
        confidence        = "high" if top_score >= 3.0 else "medium"
        sources = [
            self._build_source(i + 1, hit)
            for i, hit in enumerate(answer_hits)
        ]

        resp = AskResponse(
            answer=answer,
            confidence=confidence,
            product_scope=scope,
            language=language,
            original_question=question,
            retrieved_with=retrieval_q,
            sources=sources,
            has_contradiction=has_contradiction,
            search_stage=search_stage,
        )
        yield sse({"stage": "complete", "result": resp.model_dump()})

    def analyse(
        self,
        text: str,
        product: Optional[str] = None,
        language: str = "EN",
        max_questions: int = 5,
    ) -> dict:
        """Extract distinct questions from text and answer each one."""
        import time
        start     = time.time()
        questions = self._extract_questions(text, max_questions)

        if not questions:
            return {
                "questions_found": 0,
                "results": [],
                "processing_time_seconds": round(time.time() - start, 1),
            }

        results = []
        for i, q in enumerate(questions, start=1):
            resp = self.ask(q, product, language)
            results.append({
                "question_number": i,
                "question":        q,
                "answer":          resp.answer,
                "confidence":      resp.confidence,
                "sources":         [s.model_dump() for s in resp.sources],
                "answered":        resp.confidence != "none",
            })

        return {
            "questions_found": len(questions),
            "results":         results,
            "processing_time_seconds": round(time.time() - start, 1),
        }

    def _extract_questions(self, text: str, max_questions: int = 5) -> list[str]:
        prompt = (
            f"Extract up to {max_questions} distinct questions from the message below. "
            "Rewrite each as a direct, clear question starting with How, What, When, Where, Why, or Can. "
            "Return a JSON array of strings only — no explanation, no markdown fences.\n\n"
            f"Message:\n{text}\n\nJSON array:"
        )
        try:
            raw     = self._azure_chat(prompt, max_tokens=300, temperature=0.2)
            cleaned = raw.strip()
            if "```" in cleaned:
                parts   = cleaned.split("```")
                cleaned = parts[1] if len(parts) > 1 else parts[0]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:].strip()
            return json.loads(cleaned)
        except Exception as e:
            log.warning("Question extraction failed: %s", e)
            return []

    def generate_reply(
        self,
        original_text: str,
        answered_results: list,
        language: str = "EN",
    ) -> dict:
        answered = [r for r in answered_results if r.get("answered")]
        excluded = [r for r in answered_results if not r.get("answered")]

        if not answered:
            return {
                "reply":                "",
                "questions_included":   0,
                "questions_excluded":   len(excluded),
                "excluded_questions":   [r.get("question", "") for r in excluded],
            }

        qa_block = "\n\n".join(
            f"Q: {r['question']}\nA: {r['answer']}" for r in answered
        )
        prompt = (
            f"Write a professional, friendly reply to the message below.\n"
            f"Use ONLY the provided Q&A pairs as the source of information.\n"
            f"Do not add any information not present in the Q&A pairs.\n"
            f"Language: {language}\n\n"
            f"Original message:\n{original_text}\n\n"
            f"Answers to include:\n{qa_block}\n\n"
            f"Reply:"
        )
        try:
            reply = self._azure_chat(prompt, max_tokens=600, temperature=0.3)
        except Exception as e:
            log.error("Reply generation failed: %s", e)
            reply = "Unable to generate reply at this time."

        return {
            "reply":              reply,
            "questions_included": len(answered),
            "questions_excluded": len(excluded),
            "excluded_questions": [r.get("question", "") for r in excluded],
        }

    def generate_summary(
        self,
        question: str,
        product: Optional[str] = None,
        language: str = "EN",
    ) -> dict:
        """Wider retrieval (top 10 hits) for comprehensive topic summary."""
        retrieval_q = question
        if language and language != "EN":
            retrieval_q = self._translate_to_english(question)

        query_vec = self._embed_query(retrieval_q)
        result    = self._retrieve(query_vec, retrieval_q, product)
        if result is None:
            return {"summary": NO_ANSWER, "sources": [], "sources_count": 0}

        hits, _    = result
        summary_hits = hits[:10]

        context      = self._build_context(summary_hits)
        source_types = [h["metadata"].get("source_type", "") for h in summary_hits]
        lang_instr   = self._language_instruction(language, source_types)

        prompt = (
            f"You are AirPlus Assist. Write a comprehensive summary (up to 300 words) "
            f"using ONLY the context below. Cover all key points across the sources.\n"
            f"{lang_instr}\n\n"
            f"Context:\n{context}\n\n"
            f"Topic: {question}\n\nSummary:"
        )
        try:
            summary = self._azure_chat(prompt, max_tokens=450, temperature=0.2)
        except Exception:
            summary = NO_ANSWER

        sources = [
            self._build_source(i + 1, hit)
            for i, hit in enumerate(summary_hits[:5])
        ]
        return {
            "summary":      summary,
            "sources":      [s.model_dump() for s in sources],
            "sources_count": len(summary_hits),
        }
