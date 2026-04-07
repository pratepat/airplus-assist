from __future__ import annotations

import json
import logging
import os
from typing import Optional

import httpx
import chromadb
from langdetect import detect as _langdetect, LangDetectException
from sentence_transformers import SentenceTransformer, CrossEncoder

from models import AskResponse, SourceReference

log = logging.getLogger(__name__)

# ── Language metadata ─────────────────────────────────────────────────────────

LANG_NAMES = {
    "EN": "English", "DE": "German", "FR": "French",
    "ES": "Spanish", "IT": "Italian", "NL": "Dutch",
}

NO_ANSWER = "I don't have enough information in my knowledge base to answer this question."

# ── System prompt template ────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are AirPlus Assist, a precise knowledge \
assistant for AirPlus products.

Answer the user's question using ONLY the context provided below.
The context contains up to 5 ranked sources — source 1 is most \
relevant, source 5 is least relevant.

Rules:
- Keep your answer under 150 words. Prefer shorter answers. \
  If listing steps, use at most 5 steps.
- Answer in 2-5 sentences maximum. Be direct and actionable.
- If the answer requires steps, use a numbered list.
- Use a bullet list only if listing 3 or more parallel items.
- Do not repeat the question or say "Based on the context..."
- Never use prior knowledge. Never speculate.
- Never say "typically" or "generally" unless those exact words \
  appear in the source context.

Contradiction rule (IMPORTANT):
- If two or more sources provide conflicting information on the \
  same point, you MUST flag it using exactly this format:
  "Note: Sources differ on this — [Source A label] states \
  [X], while [Source B label] states [Y]."
- Do not silently choose one source over another.
- Show both conflicting statements.

If the answer is not in the context, respond exactly with:
"I don't have enough information in my knowledge base to \
answer this question."
{language_instruction}
Context:
{context}
"""

# ── Model cache ───────────────────────────────────────────────────────────────

_embed_model: Optional[SentenceTransformer] = None
_rerank_model: Optional[CrossEncoder] = None


def _get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        name = os.environ["EMBED_MODEL"]
        log.info("Loading embedding model: %s", name)
        _embed_model = SentenceTransformer(name)
    return _embed_model


def _get_rerank_model() -> CrossEncoder:
    global _rerank_model
    if _rerank_model is None:
        name = os.environ["RERANK_MODEL"]
        log.info("Loading re-rank model: %s", name)
        _rerank_model = CrossEncoder(name)
    return _rerank_model


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_label(meta: dict) -> str:
    src_type    = meta.get("source_type", "")
    source_file = meta.get("source_file", "")
    if src_type == "pdf":
        page = meta.get("page_number")
        return f"{source_file} — p.{page}" if page else source_file
    if src_type == "xlsx":
        sheet = meta.get("sheet_name") or ""
        qtext = meta.get("question_text") or ""
        parts = [p for p in [sheet, qtext] if p]
        suffix = " — " + ": ".join(parts) if parts else ""
        return f"{source_file}{suffix}"
    if src_type == "url":
        return meta.get("url") or source_file
    if src_type == "docx":
        section = meta.get("section_title")
        return f"{source_file} — {section}" if section else source_file
    return source_file


def _dedup_key(meta: dict) -> str:
    src_type = meta.get("source_type", "")
    if src_type == "pdf":
        return f"pdf::{meta.get('source_file')}::{meta.get('page_number')}"
    if src_type == "xlsx":
        return f"xlsx::{meta.get('source_file')}::{meta.get('sheet_name')}::{meta.get('question_text')}"
    if src_type == "url":
        return f"url::{meta.get('url')}"
    return f"{src_type}::{meta.get('source_file')}"


def _none_if_empty(v) -> Optional[str]:
    if v is None or v == "":
        return None
    return str(v)


def _all_xlsx(chunks: list[tuple]) -> bool:
    """True if every chunk in the top-k list is an xlsx source."""
    return all(meta.get("source_type") == "xlsx" for _, _, meta in chunks)


# ── RagChain ──────────────────────────────────────────────────────────────────

class RagChain:
    def __init__(self) -> None:
        self.chroma_host      = os.environ["CHROMA_HOST"]
        self.chroma_port      = int(os.environ["CHROMA_PORT"])
        self.collection_name  = os.environ["CHROMA_COLLECTION"]
        self.ollama_base_url  = os.environ["OLLAMA_BASE_URL"]
        self.ollama_model     = os.environ["OLLAMA_MODEL"]
        self.top_k_retrieval   = int(os.environ.get("TOP_K_RETRIEVAL", 10))
        self.top_k_rerank      = int(os.environ.get("TOP_K_RERANK", 3))
        self.sim_threshold     = float(os.environ.get("SIMILARITY_THRESHOLD", 0.30))
        self.rerank_threshold  = float(os.environ.get("RERANK_THRESHOLD", -0.50))

        log.info("Similarity threshold: %s", self.sim_threshold)

        self._embed  = _get_embed_model()
        self._rerank = _get_rerank_model()
        self._chroma = chromadb.HttpClient(
            host=self.chroma_host,
            port=self.chroma_port,
        )

    def _collection(self):
        return self._chroma.get_collection(self.collection_name)

    # ── Language helpers ──────────────────────────────────────────────────────

    def _translate_to_english(self, question: str) -> str:
        """
        Translate question to English via Ollama.

        Two-attempt strategy:
          1. Primary prompt  — shorter, 30 s budget
          2. Fallback prompt — simpler phrasing, configurable budget
        Returns original question only if both attempts fail.
        """
        translation_timeout = float(os.getenv("TRANSLATION_TIMEOUT", "45"))

        primary_prompt = (
            "Translate to English. "
            "Return only the translation, nothing else: "
            f"{question}"
        )
        fallback_prompt = f"English translation of: {question}"

        # Attempt 1 — primary prompt, 30 s
        try:
            result = self._ollama_raw(
                primary_prompt, max_tokens=128, timeout=30.0, raise_on_timeout=True
            )
            translated = result.strip()
            if translated:
                return translated
        except Exception as exc:
            log.warning("Translation attempt 1 failed (%s) — trying fallback.", exc)

        # Attempt 2 — fallback prompt, configurable timeout
        try:
            result = self._ollama_raw(
                fallback_prompt,
                max_tokens=128,
                timeout=translation_timeout,
                raise_on_timeout=True,
            )
            translated = result.strip()
            if translated:
                log.info("Translation succeeded on fallback attempt.")
                return translated
        except Exception as exc:
            log.warning("Translation attempt 2 failed (%s).", exc)

        log.warning(
            "WARNING: Translation failed after both attempts, "
            "using original question — retrieval quality may be reduced"
        )
        return question

    def _detect_chunk_language(self, text: str) -> str:
        """Detect language of chunk content. Returns ISO 639-1 lowercase code."""
        try:
            return _langdetect(text[:400])
        except LangDetectException:
            return "en"

    def _build_language_instruction(
        self,
        language: str,
        top_chunks: list[tuple],
    ) -> str:
        """
        Build the language-specific instruction injected into the system prompt.
        Handles xlsx vs non-xlsx source logic.
        """
        xlsx_chunks    = [c for c in top_chunks if c[2].get("source_type") == "xlsx"]
        nonxlsx_chunks = [c for c in top_chunks if c[2].get("source_type") != "xlsx"]

        parts: list[str] = []

        # ── xlsx instruction ──────────────────────────────────────────────────
        if xlsx_chunks:
            if language == "EN":
                parts.append(
                    "Answer using only the English (EN) values from the context. "
                    "Ignore all other language columns."
                )
            else:
                lang_name = LANG_NAMES.get(language, language)
                parts.append(
                    f"Answer using only the {language} ({lang_name}) values from the context. "
                    f"If the {language} value is missing for a term, use the English (EN) value instead."
                )

        # ── non-xlsx instruction ──────────────────────────────────────────────
        if nonxlsx_chunks:
            # Detect the dominant source language from the first non-xlsx chunk
            sample_text  = nonxlsx_chunks[0][1]
            source_lang  = self._detect_chunk_language(sample_text).upper()
            target_lang  = language

            if source_lang == target_lang or (source_lang == "EN" and target_lang == "EN"):
                # Languages match — answer directly
                pass
            else:
                # Option D: answer in source language then add English translation
                parts.append(
                    f"The source content is in {source_lang}. "
                    f"First provide the answer in {source_lang} as it appears in the source, "
                    f"then provide an English translation. "
                    f"Format exactly as:\n"
                    f"Original ({source_lang}):\n{{answer}}\n\nTranslation (EN):\n{{translation}}"
                )

        if parts:
            return "\n" + "\n".join(parts) + "\n"
        return "\n"

    # ── Retrieval helpers ─────────────────────────────────────────────────────

    def generate_reply(
        self,
        original_text: str,
        answered_results: list,
        language: str = "EN",
    ) -> str:
        """Generate a professional email/chat reply combining all answered Q&A pairs."""
        import re

        # Extract sender name from sign-off lines (last 5 lines)
        sender_name = None
        name_patterns = [
            r"(?:thanks|thank you|regards|best|cheers|sincerely|kind regards)[,\s]+([A-Z][a-z]+)",
            r"^([A-Z][a-z]+)\s*$",
        ]
        for line in reversed(original_text.strip().split("\n")[-5:]):
            line = line.strip()
            for pattern in name_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    sender_name = match.group(1)
                    break
            if sender_name:
                break

        # Build Q&A context block
        qa_pairs = ""
        for r in answered_results:
            qa_pairs += f"Question: {r['current_question']}\nAnswer: {r['answer']}\n\n"

        greeting = f"Hi {sender_name}" if sender_name else "Dear Customer"

        prompt = (
            f'You are writing a professional email reply on behalf of AirPlus customer support.\n\n'
            f'Write a reply to the following message using ONLY the provided answers below.\n\n'
            f'Rules:\n'
            f'- Start with: "{greeting},"\n'
            f'- Write in the same language as the original message\n'
            f'- Combine the answers into natural flowing prose\n'
            f'- Do not use numbered lists — write as paragraphs\n'
            f'- Professional but warm tone — not robotic\n'
            f'- Do not mention AI, knowledge base, or any tool\n'
            f'- Do not add information beyond what is in the answers\n'
            f'- End with: "Best regards,\\n[AirPlus Support]"\n'
            f'- Keep the reply concise — one paragraph per question\n\n'
            f'Original message:\n{original_text}\n\n'
            f'Answers to include in reply:\n{qa_pairs}\n'
            f'Write the reply now:'
        )

        return self._ollama_raw(prompt, max_tokens=1024, timeout=120.0)

    def _retrieve_and_rerank(
        self,
        retrieval_question: str,
        product: Optional[str],
    ) -> tuple[list, list, list, float] | None:
        """
        Embed, query ChromaDB, and re-rank.
        Returns (ranked_chunks, documents, metadatas, top_sim) or None on failure/no-results.
        """
        q_vec = self._embed.encode(
            [retrieval_question], convert_to_numpy=True
        )[0].tolist()

        query_kwargs: dict = dict(
            query_embeddings=[q_vec],
            n_results=self.top_k_retrieval,
            include=["documents", "metadatas", "distances"],
        )
        if product:
            query_kwargs["where"] = {"product": {"$eq": product}}

        try:
            col     = self._collection()
            results = col.query(**query_kwargs)
        except Exception as exc:
            log.error("ChromaDB query failed: %s", exc)
            return None

        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]

        if not documents:
            return None

        sim_scores = [1.0 - (d / 2.0) for d in distances]
        top_sim    = sim_scores[0]

        return documents, metadatas, distances, top_sim

    # ── Public entry points ───────────────────────────────────────────────────

    def ask(
        self,
        question: str,
        product: Optional[str],
        language: str = "EN",
    ) -> AskResponse:
        product_scope     = product if product else "all"
        original_question = question

        # Step 1 — translate question to English for retrieval if needed
        if language != "EN":
            retrieval_question = self._translate_to_english(question)
            log.info("Translated question: %r → %r", question, retrieval_question)
        else:
            retrieval_question = question

        # Steps 2-3 — embed and retrieve
        retrieved = self._retrieve_and_rerank(retrieval_question, product)
        if retrieved is None:
            return self._no_answer(product_scope, language, original_question, retrieval_question)

        documents, metadatas, distances, top_sim = retrieved

        # Step 4 — cosine similarity gate
        if top_sim < self.sim_threshold:
            log.info(
                "[AirPlus Assist] Q: %.60s | lang=%s | top_cosine=%.3f | "
                "top_rerank=n/a | gate=BLOCK | confidence=none",
                question, language, top_sim,
            )
            return self._no_answer(product_scope, language, original_question, retrieval_question)

        # Step 5 — re-rank
        pairs         = [(retrieval_question, doc) for doc in documents]
        rerank_scores = self._rerank.predict(pairs).tolist()

        ranked = sorted(
            zip(rerank_scores, documents, metadatas),
            key=lambda t: t[0],
            reverse=True,
        )
        top_chunks       = ranked[: self.top_k_rerank]
        top_rerank_score = top_chunks[0][0]

        if top_rerank_score < self.rerank_threshold:
            log.info(
                "[AirPlus Assist] Q: %.60s | lang=%s | top_cosine=%.3f | "
                "top_rerank=%.3f | gate=BLOCK | confidence=none",
                question, language, top_sim, top_rerank_score,
            )
            return self._no_answer(product_scope, language, original_question, retrieval_question)

        # Steps 6-8 — build context, call LLM
        return self._generate_answer(
            question=original_question,
            retrieval_question=retrieval_question,
            language=language,
            product_scope=product_scope,
            top_chunks=top_chunks,
            top_rerank_score=top_rerank_score,
            top_sim=top_sim,
        )

    def ask_streaming(
        self,
        question: str,
        product: Optional[str],
        language: str = "EN",
    ):
        """
        Generator that yields SSE stage events then the final result.
        Each event is a 'data: {...}\\n\\n' string for text/event-stream.
        """
        product_scope     = product if product else "all"
        original_question = question

        def event(data: dict) -> str:
            return f"data: {json.dumps(data)}\n\n"

        try:
            # Stage 1 — always first
            yield event({"stage": "searching", "message": "Searching knowledge base...", "icon": "🔍"})

            # Translation for non-EN
            retrieval_question = question
            if language != "EN":
                yield event({"stage": "translating", "message": "Translating question to English...", "icon": "🌐"})
                retrieval_question = self._translate_to_english(question)
                log.info("Translated question: %r → %r", question, retrieval_question)

            # Embed and retrieve
            retrieved = self._retrieve_and_rerank(retrieval_question, product)
            if retrieved is None:
                yield event({"stage": "complete", "result": self._no_answer(
                    product_scope, language, original_question, retrieval_question
                ).dict()})
                return

            documents, metadatas, distances, top_sim = retrieved

            # Cosine similarity gate
            if top_sim < self.sim_threshold:
                log.info(
                    "[AirPlus Assist] Q: %.60s | lang=%s | top_cosine=%.3f | "
                    "top_rerank=n/a | gate=BLOCK | confidence=none",
                    question, language, top_sim,
                )
                yield event({"stage": "complete", "result": self._no_answer(
                    product_scope, language, original_question, retrieval_question
                ).dict()})
                return

            # Stage 2 — after retrieval, before re-rank
            yield event({
                "stage":   "retrieved",
                "message": f"Found {len(documents)} relevant sources. Re-ranking...",
                "icon":    "📚",
            })

            # Re-rank
            pairs         = [(retrieval_question, doc) for doc in documents]
            rerank_scores = self._rerank.predict(pairs).tolist()

            ranked = sorted(
                zip(rerank_scores, documents, metadatas),
                key=lambda t: t[0],
                reverse=True,
            )
            top_chunks       = ranked[: self.top_k_rerank]
            top_rerank_score = top_chunks[0][0]

            # Re-ranker gate
            if top_rerank_score < self.rerank_threshold:
                log.info(
                    "[AirPlus Assist] Q: %.60s | lang=%s | top_cosine=%.3f | "
                    "top_rerank=%.3f | gate=BLOCK | confidence=none",
                    question, language, top_sim, top_rerank_score,
                )
                yield event({"stage": "complete", "result": self._no_answer(
                    product_scope, language, original_question, retrieval_question
                ).dict()})
                return

            # Stage 3 — gate passed, calling LLM
            model_display = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
            yield event({
                "stage":   "generating",
                "message": f"Generating answer with {model_display}...",
                "icon":    "🤖",
            })

            response = self._generate_answer(
                question=original_question,
                retrieval_question=retrieval_question,
                language=language,
                product_scope=product_scope,
                top_chunks=top_chunks,
                top_rerank_score=top_rerank_score,
                top_sim=top_sim,
            )

            yield event({"stage": "complete", "result": response.dict()})

        except Exception as e:
            log.error("ask_streaming failed: %s", e)
            yield event({"stage": "error", "message": f"Something went wrong: {str(e)}"})

    # ── Private helpers ───────────────────────────────────────────────────────

    def extract_questions(self, text: str, max_questions: int = 5) -> list[str]:
        """
        Use Ollama to extract distinct questions from unstructured email or chat text.
        Returns a list of question strings (max 5).
        """
        prompt = (
            f"Extract all distinct questions from the following message and rewrite "
            f"each one as a clear, direct question suitable for searching a knowledge base.\n\n"
            f"Rules:\n"
            f"- Convert implicit and indirect questions to explicit how/what questions\n"
            f"  e.g. \"I can't figure out how to X\" → \"How do I X?\"\n"
            f"  e.g. \"I'm not sure about Y\" → \"What is Y?\"\n"
            f"  e.g. \"Could you tell me about Z\" → \"What is Z?\"\n"
            f"  e.g. \"Can I do X?\" → \"How do I X?\"\n"
            f"  e.g. \"Is it possible to X?\" → \"How do I X?\"\n"
            f"  e.g. \"I'm wondering if I can X\" → \"How do I X?\"\n"
            f"- Return ONLY a JSON array of rewritten question strings\n"
            f"- Maximum {max_questions} questions\n"
            f"- Deduplicate similar questions — keep only one\n"
            f"- Preserve the original language of each question\n"
            f"- Remove greetings, sign-offs, pleasantries\n"
            f"- Do not include statements that are not questions\n"
            f"- Do not add explanation or preamble — JSON array only\n"
            f"- Each question should be concise and direct\n\n"
            f"Message:\n{text}\n\n"
            f"JSON array of clear, direct questions:"
        )

        try:
            raw = self._ollama_raw(prompt, max_tokens=512, timeout=60.0)
        except Exception as exc:
            log.error("extract_questions Ollama call failed: %s", exc)
            return []

        raw = raw.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else ""
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        try:
            questions = json.loads(raw)
            if not isinstance(questions, list):
                return []
            return [str(q) for q in questions if str(q).strip()][:max_questions]
        except json.JSONDecodeError:
            log.warning("extract_questions: could not parse JSON from: %r", raw[:200])
            return []

    def analyse(
        self,
        text: str,
        product: Optional[str],
        language: str = "EN",
        max_questions: int = 5,
    ) -> dict:
        """Extract questions from text and answer each one."""
        import time
        start = time.time()

        questions = self.extract_questions(text, max_questions)

        if not questions:
            return {
                "questions_found":       0,
                "original_text_length":  len(text),
                "language":              language,
                "results":               [],
                "processing_time_seconds": round(time.time() - start, 1),
            }

        results = []
        for i, question in enumerate(questions, 1):
            answer = self.ask(question=question, product=product, language=language)
            results.append({
                "question_number":    i,
                "extracted_question": question,
                "current_question":   question,
                "answer":             answer.answer,
                "confidence":         answer.confidence,
                "sources":            [s.dict() for s in answer.sources],
                "has_contradiction":  answer.has_contradiction,
                "product_scope":      answer.product_scope,
                "answered":           answer.confidence != "none",
            })

        return {
            "questions_found":       len(questions),
            "original_text_length":  len(text),
            "language":              language,
            "results":               results,
            "processing_time_seconds": round(time.time() - start, 1),
        }

    def _generate_answer(
        self,
        question: str,
        retrieval_question: str,
        language: str,
        product_scope: str,
        top_chunks: list,
        top_rerank_score: float,
        top_sim: float,
    ) -> AskResponse:
        """Build context, call Ollama, return AskResponse. Called by ask() and ask_streaming()."""
        confidence = "high" if top_rerank_score >= 3.0 else "medium"

        log.info(
            "[AirPlus Assist] Q: %.60s | lang=%s | top_cosine=%.3f | "
            "top_rerank=%.3f | gate=PASS | confidence=%s",
            question, language, top_sim, top_rerank_score, confidence,
        )

        # Contradiction detection (conservative: 3+ distinct source files → flag)
        unique_source_files = {meta.get("source_file", "") for _, _, meta in top_chunks}
        has_contradiction   = len(unique_source_files) >= 3

        # Build ranked context string and deduplicated sources list
        lang_instruction = self._build_language_instruction(language, top_chunks)
        context          = ""
        sources: list[SourceReference] = []
        seen: set[str]  = set()
        rank             = 0

        for score, doc, meta in top_chunks:
            dk = _dedup_key(meta)
            if dk in seen:
                continue
            seen.add(dk)
            rank += 1

            source_label = _build_label(meta)
            context += f"[Source {rank}: {source_label}]\n{doc}\n\n---\n\n"

            if score >= 3.0:
                chunk_confidence = "high"
            elif score >= 0.0:
                chunk_confidence = "medium"
            else:
                chunk_confidence = "low"

            sources.append(SourceReference(
                rank          = rank,
                label         = source_label,
                excerpt       = doc[:200],
                confidence    = chunk_confidence,
                source_type   = meta.get("source_type", ""),
                product       = meta.get("product", ""),
                url           = _none_if_empty(meta.get("url")),
                page_number   = meta.get("page_number") if meta.get("page_number") != "" else None,
                sheet_name    = _none_if_empty(meta.get("sheet_name")),
                question_text = _none_if_empty(meta.get("question_text")),
                ingested_at   = meta.get("ingested_at", ""),
            ))

        system_prompt = SYSTEM_PROMPT.format(
            language_instruction=lang_instruction,
            context=context,
        )
        full_prompt = system_prompt + f"\nQuestion: {question}"

        answer_text = self._ollama_raw(full_prompt, max_tokens=512)

        return AskResponse(
            answer            = answer_text,
            confidence        = confidence,
            product_scope     = product_scope,
            language          = language,
            original_question = question,
            retrieved_with    = retrieval_question,
            sources           = sources,
            has_contradiction = has_contradiction,
        )

    def _no_answer(
        self,
        product_scope: str,
        language: str,
        original_question: str,
        retrieved_with: str,
    ) -> AskResponse:
        return AskResponse(
            answer            = NO_ANSWER,
            confidence        = "none",
            product_scope     = product_scope,
            language          = language,
            original_question = original_question,
            retrieved_with    = retrieved_with,
            sources           = [],
            has_contradiction = False,
        )

    def _ollama_raw(
        self,
        prompt: str,
        max_tokens: int = 512,
        timeout: float = 120.0,
        raise_on_timeout: bool = False,
    ) -> str:
        """
        Send a prompt to Ollama and return the response text.

        When raise_on_timeout=True the caller receives the raw
        httpx.TimeoutException instead of a user-facing string —
        used by translation retries so they can attempt a fallback.
        """
        url     = f"{self.ollama_base_url}/api/generate"
        payload = {
            "model":  self.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "top_p":       0.9,
                "num_predict": max_tokens,
            },
        }
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json()["response"].strip()
        except httpx.TimeoutException:
            if raise_on_timeout:
                raise
            log.error("Ollama request timed out.")
            return "The language model did not respond in time. Please try again."
        except Exception as exc:
            log.error("Ollama request failed: %s", exc)
            return "The language model is currently unavailable. Please try again later."
