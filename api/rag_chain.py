from __future__ import annotations

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

_SYSTEM_BASE = """You are AirPlus Assist, a precise knowledge assistant for AirPlus products.

Answer the user's question using ONLY the context provided below.

Rules:
- If the answer is not in the context, respond exactly with:
  "I don't have enough information in my knowledge base to answer this question."
- Never use prior knowledge. Never speculate.
- Never say "typically" or "generally" unless those exact words appear in the source context.
- Be concise: answer in 2-4 sentences maximum.
- Use a bullet list only if the answer contains 3 or more distinct items.
- Do not repeat the question.
- Do not say "Based on the context..." or "According to the provided information..."
- Do not add caveats or suggest consulting other sources.
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
        self.top_k_retrieval  = int(os.environ.get("TOP_K_RETRIEVAL", 10))
        self.top_k_rerank     = int(os.environ.get("TOP_K_RERANK", 3))
        self.sim_threshold    = float(os.environ.get("SIMILARITY_THRESHOLD", 0.30))

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
        """Translate question to English via Ollama. Returns original on failure."""
        prompt = (
            "Translate the following question to English. "
            "Return only the translated question, nothing else.\n"
            f"Question: {question}"
        )
        try:
            result = self._ollama_raw(prompt, max_tokens=128)
            translated = result.strip()
            if translated:
                return translated
        except Exception as exc:
            log.warning("Question translation failed: %s — using original.", exc)
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

    # ── Public entry point ────────────────────────────────────────────────────

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

        # Step 2 — embed the (possibly translated) question
        q_vec = self._embed.encode(
            [retrieval_question], convert_to_numpy=True
        )[0].tolist()

        # Step 3 — retrieve from ChromaDB
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
            return self._no_answer(product_scope, language, original_question, retrieval_question)

        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]

        if not documents:
            return self._no_answer(product_scope, language, original_question, retrieval_question)

        # Step 4 — cosine similarity gate (coarse filter)
        sim_scores = [1.0 - (d / 2.0) for d in distances]
        top_sim    = sim_scores[0]

        if top_sim < self.sim_threshold:
            log.info(
                "[AirPlus Assist] Q: %.60s | lang=%s | top_cosine=%.3f | "
                "top_rerank=n/a | gate=BLOCK | confidence=none",
                question, language, top_sim,
            )
            return self._no_answer(product_scope, language, original_question, retrieval_question)

        # Step 5 — re-rank using the English retrieval question
        pairs         = [(retrieval_question, doc) for doc in documents]
        rerank_scores = self._rerank.predict(pairs).tolist()

        ranked = sorted(
            zip(rerank_scores, documents, metadatas),
            key=lambda t: t[0],
            reverse=True,
        )
        top              = ranked[: self.top_k_rerank]
        top_rerank_score = top[0][0]

        # Re-ranker gate — primary hallucination guard
        if top_rerank_score < -0.25:
            log.info(
                "[AirPlus Assist] Q: %.60s | lang=%s | top_cosine=%.3f | "
                "top_rerank=%.3f | gate=BLOCK | confidence=none",
                question, language, top_sim, top_rerank_score,
            )
            return self._no_answer(product_scope, language, original_question, retrieval_question)

        confidence = "high" if top_rerank_score >= 3.0 else "medium"

        log.info(
            "[AirPlus Assist] Q: %.60s | lang=%s | top_cosine=%.3f | "
            "top_rerank=%.3f | gate=PASS | confidence=%s",
            question, language, top_sim, top_rerank_score, confidence,
        )

        # Step 6 — build prompt with language instruction
        lang_instruction = self._build_language_instruction(language, top)
        context_parts    = []
        for _, doc, meta in top:
            label = _build_label(meta)
            context_parts.append(f"[Source: {label}]\n{doc}")
        context = "\n---\n".join(context_parts)

        system_prompt = _SYSTEM_BASE.format(
            language_instruction=lang_instruction,
            context=context,
        )
        full_prompt = system_prompt + f"\nQuestion: {original_question}"

        # Step 7 — call Ollama
        answer_text = self._ollama_raw(full_prompt, max_tokens=512)

        # Step 8 — build sources (deduplicated)
        sources: list[SourceReference] = []
        seen: set[str] = set()
        for _, _doc, meta in top:
            dk = _dedup_key(meta)
            if dk in seen:
                continue
            seen.add(dk)
            sources.append(SourceReference(
                label         = _build_label(meta),
                preview       = meta.get("chunk_preview") or _doc[:120],
                source_type   = meta.get("source_type", ""),
                product       = meta.get("product", ""),
                url           = _none_if_empty(meta.get("url")),
                page_number   = meta.get("page_number") if meta.get("page_number") != "" else None,
                sheet_name    = _none_if_empty(meta.get("sheet_name")),
                question_text = _none_if_empty(meta.get("question_text")),
                ingested_at   = meta.get("ingested_at", ""),
            ))

        return AskResponse(
            answer            = answer_text,
            confidence        = confidence,
            product_scope     = product_scope,
            language          = language,
            original_question = original_question,
            retrieved_with    = retrieval_question,
            sources           = sources,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

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
        )

    def _ollama_raw(self, prompt: str, max_tokens: int = 512) -> str:
        """Send a prompt to Ollama and return the response text."""
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
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json()["response"].strip()
        except httpx.TimeoutException:
            log.error("Ollama request timed out.")
            return "The language model did not respond in time. Please try again."
        except Exception as exc:
            log.error("Ollama request failed: %s", exc)
            return "The language model is currently unavailable. Please try again later."
