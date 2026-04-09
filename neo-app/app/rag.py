"""
RAG pipeline: retrieval, re-ranking, hallucination guard, LLM generation.

Two-layer hallucination guard (same as original):
  Layer 1 — cosine similarity gate (SIMILARITY_THRESHOLD)
  Layer 2 — cross-encoder re-ranker gate (RERANK_THRESHOLD)
"""
import asyncio
import json
import logging
import re
import time
from typing import AsyncIterator, Optional

import httpx
import numpy as np

from .config import config
from .ingest import IngestResult, get_embed_model
from .models import AskResponse, SourceReference

log = logging.getLogger(__name__)

NO_ANSWER = "I don't have enough information in my knowledge base to answer this question."

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    """Remove <think>…</think> blocks produced by reasoning models (qwen3, etc.)."""
    return _THINK_RE.sub("", text).strip()

SUPPORTED_LANGUAGES = ["EN", "DE", "FR", "ES", "IT", "NL"]


# ── Cross-encoder cache (same principle as embed model cache) ──────────────────

_rerank_model_cache: dict = {}


def get_rerank_model(model_name: str):
    if model_name not in _rerank_model_cache:
        from sentence_transformers import CrossEncoder
        log.info("Loading re-ranker: %s", model_name)
        _rerank_model_cache[model_name] = CrossEncoder(model_name)
    return _rerank_model_cache[model_name]


# ── RagPipeline ────────────────────────────────────────────────────────────────

class RagPipeline:
    def __init__(self, ingest_result: IngestResult):
        self._data = ingest_result
        self._embed = get_embed_model(config.embed_model)
        self._reranker = get_rerank_model(config.rerank_model)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _embed_query(self, text: str) -> np.ndarray:
        vec = self._embed.encode([text], normalize_embeddings=True)
        return vec[0].astype(np.float32)

    def _cosine_search(
        self, query_vec: np.ndarray, product: Optional[str]
    ) -> list[tuple[int, float]]:
        """Return (chunk_idx, cosine_score) sorted desc, optionally filtered by product."""
        if self._data.embeddings is None or not self._data.chunks:
            return []

        if product:
            indices = [
                i for i, c in enumerate(self._data.chunks)
                if c["metadata"].get("product") == product
            ]
        else:
            indices = list(range(len(self._data.chunks)))

        if not indices:
            return []

        subset = self._data.embeddings[indices]            # (N, D)
        scores = (subset @ query_vec).tolist()             # dot product = cosine (normalised)
        pairs = sorted(
            ((indices[i], scores[i]) for i in range(len(indices))),
            key=lambda x: x[1],
            reverse=True,
        )
        return pairs

    def _rerank(
        self, query: str, chunks: list[dict]
    ) -> list[tuple[float, dict]]:
        """Cross-encoder re-ranking. Returns [(score, chunk)] sorted desc."""
        pairs = [(query, c["content"]) for c in chunks]
        scores = self._reranker.predict(pairs).tolist()
        return sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)

    def _ollama(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.1,
        timeout: int = 90,
    ) -> str:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{config.ollama_base_url}/api/generate",
                json={
                    "model": config.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "think": False,          # disable thinking mode (qwen3 and similar)
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                },
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "").strip()
            return _strip_thinking(raw)

    def _translate_to_english(self, question: str) -> str:
        prompt = (
            "Translate the following question to English. "
            "Return ONLY the translation, nothing else.\n\n"
            f"Question: {question}"
        )
        try:
            result = self._ollama(prompt, max_tokens=200, temperature=0.0,
                                  timeout=config.translation_timeout)
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
        if source_type == "docx" and section:
            return f"{source_file} — {section}"
        return source_file

    def _score_to_confidence(self, score: float) -> str:
        if score >= 3.0:
            return "high"
        if score >= 0.0:
            return "medium"
        return "low"

    def _build_source(self, rank: int, chunk: dict, score: float) -> SourceReference:
        meta = chunk["metadata"]
        return SourceReference(
            rank=rank,
            label=self._build_label(meta),
            excerpt=chunk["content"][:200].strip(),
            confidence=self._score_to_confidence(score),
            source_type=meta.get("source_type", "txt"),
            product=meta.get("product", ""),
            url=meta.get("url"),
            page_number=meta.get("page_number"),
            sheet_name=meta.get("sheet_name"),
            question_text=meta.get("question_text"),
            ingested_at=meta.get("ingested_at", ""),
        )

    def _build_context(self, ranked: list[tuple[float, dict]]) -> str:
        parts = []
        for i, (_, chunk) in enumerate(ranked, start=1):
            meta = chunk["metadata"]
            label = f"Source {i} ({meta.get('source_file', 'unknown')})"
            parts.append(f"[{label}]\n{chunk['content']}")
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
        self, question: str, retrieval_q: str, scope: str, language: str
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
        )

    def _retrieve_and_rerank(
        self, retrieval_q: str, product: Optional[str]
    ) -> tuple[list[tuple[float, dict]], float] | None:
        """
        Embed → cosine search → gate check → re-rank → gate check.
        Returns (ranked_chunks, top_score) or None if any gate blocks.
        """
        query_vec = self._embed_query(retrieval_q)
        pairs = self._cosine_search(query_vec, product)

        if not pairs:
            return None
        top_sim = pairs[0][1]
        if top_sim < config.similarity_threshold:
            log.debug("Cosine gate blocked (top_sim=%.3f)", top_sim)
            return None

        top_chunks = [self._data.chunks[idx] for idx, _ in pairs[:config.top_k_retrieval]]
        ranked = self._rerank(retrieval_q, top_chunks)
        top_score = ranked[0][0]

        if top_score < config.rerank_threshold:
            log.debug("Reranker gate blocked (top_score=%.3f)", top_score)
            return None

        return ranked, top_score

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

        gate_result = self._retrieve_and_rerank(retrieval_q, product)
        if gate_result is None:
            return self._no_answer(question, retrieval_q, scope, language)

        ranked, top_score = gate_result
        answer_chunks = ranked[:config.top_k_answer]

        context = self._build_context(answer_chunks)
        source_types = [c["metadata"].get("source_type", "") for _, c in answer_chunks]
        # Use original question for non-English (translate only used for retrieval)
        prompt = self._build_prompt(question, context, language, source_types)

        answer = self._ollama(prompt, max_tokens=512, temperature=0.1)

        unique_files = {c["metadata"].get("source_file") for _, c in answer_chunks}
        has_contradiction = len(unique_files) >= 3

        confidence = "high" if top_score >= 3.0 else "medium"
        sources = [
            self._build_source(i + 1, chunk, score)
            for i, (score, chunk) in enumerate(answer_chunks)
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

        loop = asyncio.get_event_loop()
        retrieval_q = question

        if language and language != "EN":
            yield sse({"stage": "translating", "message": "Translating question to English…", "icon": "🌐"})
            retrieval_q = await loop.run_in_executor(None, self._translate_to_english, question)

        # Cosine search (fast numpy — run inline)
        query_vec = await loop.run_in_executor(None, self._embed_query, retrieval_q)
        pairs = self._cosine_search(query_vec, product)

        if not pairs or pairs[0][1] < config.similarity_threshold:
            result = self._no_answer(question, retrieval_q, scope, language)
            yield sse({"stage": "complete", "result": result.model_dump()})
            return

        top_chunks = [self._data.chunks[idx] for idx, _ in pairs[:config.top_k_retrieval]]
        yield sse({
            "stage": "retrieved",
            "message": f"Found {len(top_chunks)} candidates. Re-ranking…",
            "icon": "📚",
        })

        ranked = await loop.run_in_executor(None, self._rerank, retrieval_q, top_chunks)
        top_score = ranked[0][0]

        if top_score < config.rerank_threshold:
            result = self._no_answer(question, retrieval_q, scope, language)
            yield sse({"stage": "complete", "result": result.model_dump()})
            return

        answer_chunks = ranked[:config.top_k_answer]
        yield sse({
            "stage": "generating",
            "message": f"Generating answer with {config.ollama_model}…",
            "icon": "🤖",
        })

        context = self._build_context(answer_chunks)
        source_types = [c["metadata"].get("source_type", "") for _, c in answer_chunks]
        prompt = self._build_prompt(question, context, language, source_types)

        answer = await loop.run_in_executor(None, self._ollama, prompt, 512, 0.1, 90)

        unique_files = {c["metadata"].get("source_file") for _, c in answer_chunks}
        has_contradiction = len(unique_files) >= 3
        confidence = "high" if top_score >= 3.0 else "medium"
        sources = [
            self._build_source(i + 1, chunk, score)
            for i, (score, chunk) in enumerate(answer_chunks)
        ]

        result = AskResponse(
            answer=answer,
            confidence=confidence,
            product_scope=scope,
            language=language,
            original_question=question,
            retrieved_with=retrieval_q,
            sources=sources,
            has_contradiction=has_contradiction,
        )
        yield sse({"stage": "complete", "result": result.model_dump()})

    def analyse(
        self,
        text: str,
        product: Optional[str] = None,
        language: str = "EN",
        max_questions: int = 5,
    ) -> dict:
        """Extract distinct questions from text and answer each one."""
        start = time.time()
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
                "question": q,
                "answer": resp.answer,
                "confidence": resp.confidence,
                "sources": [s.model_dump() for s in resp.sources],
                "answered": resp.confidence != "none",
            })

        return {
            "questions_found": len(questions),
            "results": results,
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
            raw = self._ollama(prompt, max_tokens=300, temperature=0.2, timeout=60)
            cleaned = raw.strip()
            if "```" in cleaned:
                # Strip markdown code fences
                parts = cleaned.split("```")
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
                "reply": "",
                "questions_included": 0,
                "questions_excluded": len(excluded),
                "excluded_questions": [r.get("question", "") for r in excluded],
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
            reply = self._ollama(prompt, max_tokens=600, temperature=0.3, timeout=120)
        except Exception as e:
            log.error("Reply generation failed: %s", e)
            reply = "Unable to generate reply at this time."

        return {
            "reply": reply,
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
        """Wider retrieval (top 10 chunks) for comprehensive topic summary."""
        retrieval_q = question
        if language and language != "EN":
            retrieval_q = self._translate_to_english(question)

        gate_result = self._retrieve_and_rerank(retrieval_q, product)
        if gate_result is None:
            return {"summary": NO_ANSWER, "sources": [], "sources_count": 0}

        ranked, _ = gate_result
        summary_chunks = ranked[:10]

        context = self._build_context(summary_chunks)
        source_types = [c["metadata"].get("source_type", "") for _, c in summary_chunks]
        lang_instr = self._language_instruction(language, source_types)

        prompt = (
            f"You are AirPlus Assist. Write a comprehensive summary (up to 300 words) "
            f"using ONLY the context below. Cover all key points across the sources.\n"
            f"{lang_instr}\n\n"
            f"Context:\n{context}\n\n"
            f"Topic: {question}\n\nSummary:"
        )
        try:
            summary = self._ollama(prompt, max_tokens=450, temperature=0.2, timeout=120)
        except Exception:
            summary = NO_ANSWER

        sources = [
            self._build_source(i + 1, chunk, score)
            for i, (score, chunk) in enumerate(summary_chunks[:5])
        ]
        return {
            "summary": summary,
            "sources": [s.model_dump() for s in sources],
            "sources_count": len(summary_chunks),
        }
