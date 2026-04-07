import os
import time
from datetime import datetime, timezone
from typing import Optional

import requests
import streamlit as st

# ── Meta-answer content (no API call) ─────────────────────────────────────────

META_ANSWERS = {
    "how_to_use": {
        "answer": """**AirPlus Assist** is an AI-powered FAQ assistant that answers your questions directly from official AirPlus product documentation. Here's how it works:

- Type your question in plain language — no special commands needed
- The assistant searches the knowledge base and finds the most relevant content
- You receive a concise answer with the exact sources it was drawn from
- Click the **📚 Sources** panel below any answer to see which documents were used

**Try asking:**
- *"What is EUR Amount?"*
- *"How do I download my eBilling file?"*
- *"What does MERCHANT_CITY mean?"*
- *"How do I manage user access?"*

Use the **Knowledge Base** filter in the sidebar to focus on a specific product, or leave it on **All Products** for a broader search. Select your **language** from the sidebar — answers will be provided in your chosen language where available.""",
        "confidence": "high",
        "product_scope": "all",
        "sources": [],
        "has_contradiction": False,
        "is_meta": True,
        "response_time": 0,
    },

    "not_satisfied": {
        "answer": """If an answer doesn't fully address your question, here's what to do:

1. **Check the sources** — Click the 📚 Sources panel below the answer. Each source shows the exact document and page the answer came from. Read the full section for more detail.
2. **Rephrase your question** — Try asking differently. For example, instead of *"Where is fare basis?"* try *"How do I find the fare basis field?"*
3. **Change the knowledge base filter** — If you're searching All Products, try filtering to a specific product using the sidebar.
4. **Go to the source documents** — The source citations show you exactly which document to open. The answer may be part of a larger section that gives more context.

Remember: AirPlus Assist only answers from official documentation. If the information isn't in the knowledge base yet, it will say so honestly rather than guessing.""",
        "confidence": "high",
        "product_scope": "all",
        "sources": [],
        "has_contradiction": False,
        "is_meta": True,
        "response_time": 0,
    },

    "help_channels": {
        "answer": """If AirPlus Assist cannot answer your question or you need further support:

- **Product questions** — Reach out through the usual channels in your Product Management team
- **Technical issues with this tool** — Raise an incident through the standard IT support process
- **Missing information** — If you believe a document or topic should be in the knowledge base, contact the Product Management team to have it added
- **Urgent queries** — Use your standard escalation path for time-sensitive matters

AirPlus Assist is designed to reduce routine questions, but your teams are always available for complex or escalated issues.""",
        "confidence": "high",
        "product_scope": "all",
        "sources": [],
        "has_contradiction": False,
        "is_meta": True,
        "response_time": 0,
    },

    "tech_architecture": {
        "answer": """AirPlus Assist is built on a fully local, privacy-first RAG (Retrieval-Augmented Generation) architecture. No data leaves your machine at any point.

**📥 Ingestion pipeline**
Documents (PDF, Word, Excel, URLs) are parsed, chunked into ~512-token segments, and embedded as vectors using `paraphrase-multilingual-MiniLM-L12-v2` — a multilingual sentence transformer supporting EN, DE, FR, ES, IT and NL.

**🗄️ Vector store**
Chunks are stored in **ChromaDB** with full metadata — source file, page number, product, language, and ingestion timestamp.

**🔍 Retrieval**
Top 15 candidates retrieved by cosine similarity → re-ranked by `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`. Only the top 5 re-ranked chunks reach the language model.

**🛡️ Hallucination guard**
Two-layer gate: cosine pre-filter + re-ranker score threshold (−0.50). If no chunk scores above the threshold, the LLM is never called.

**🤖 Language model**
`mistral:7b` runs locally via **Ollama**. Temperature 0.1 for maximum factual consistency.

**🏗️ Infrastructure**
Four Docker containers — one command to start everything.""",
        "architecture_diagram": True,
        "confidence": "high",
        "product_scope": "all",
        "sources": [],
        "has_contradiction": False,
        "is_meta": True,
        "response_time": 0,
    },
}

ARCHITECTURE_DIAGRAM = """
<div style="margin:20px 0;padding:20px;
            background:#F9FAFB;border:1px solid #E5E7EB;
            border-radius:12px;font-family:monospace;
            font-size:12px;line-height:2;">
  <div style="color:#6B7280;font-size:11px;
              font-family:sans-serif;margin-bottom:12px;
              font-weight:600;letter-spacing:0.5px;">
    SYSTEM ARCHITECTURE
  </div>
  <div style="color:#1A1A2E;">

  <span style="color:#6B7280;">📁 docs/</span>
  <span style="color:#9CA3AF;"> ──────────────────────────────────────────┐</span><br>
  <span style="color:#6B7280;">   PDF · Excel · Word · URLs</span>
  <span style="color:#9CA3AF;">              │</span><br>
  <span style="color:#9CA3AF;">              ▼</span><br>
  <span style="background:#E8F5E9;color:#065F46;padding:2px 8px;border-radius:4px;">Ingest Pipeline</span>
  <span style="color:#9CA3AF;"> → chunk → embed → </span>
  <span style="background:#DBEAFE;color:#1E40AF;padding:2px 8px;border-radius:4px;">ChromaDB</span><br>
  <br>
  <span style="color:#9CA3AF;">                                              │</span><br>
  <span style="color:#9CA3AF;">              ┌───────────────────────────────┘</span><br>
  <span style="color:#9CA3AF;">              │  top 15 by cosine similarity</span><br>
  <span style="color:#9CA3AF;">              ▼</span><br>
  <span style="color:#6B7280;">🧑 User question</span>
  <span style="color:#9CA3AF;"> ──► </span>
  <span style="background:#E8F5E9;color:#065F46;padding:2px 8px;border-radius:4px;">FastAPI</span>
  <span style="color:#9CA3AF;"> ──► </span>
  <span style="background:#FEF3C7;color:#92400E;padding:2px 8px;border-radius:4px;">Re-ranker</span>
  <span style="color:#9CA3AF;"> ──► </span>
  <span style="background:#FCE7F3;color:#9D174D;padding:2px 8px;border-radius:4px;">Ollama</span>
  <span style="color:#9CA3AF;"> ──► </span>
  <span style="color:#00B050;font-weight:600;">Answer + Sources</span><br>
  <br>
  <span style="color:#9CA3AF;font-size:11px;">top 5 re-ranked  ↑ &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; mistral:7b · local · private</span>

  </div>
  <div style="margin-top:12px;padding-top:12px;
              border-top:1px solid #E5E7EB;
              font-family:sans-serif;font-size:11px;
              color:#9CA3AF;">
    🔒 Fully local · No external APIs · No data leaves your machine
  </div>
</div>
"""

# ── Config ────────────────────────────────────────────────────────────────────

API_HOST        = os.environ.get("API_HOST", "http://api:8001")
REQUEST_TIMEOUT = 90
OLLAMA_MODEL    = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

st.set_page_config(
    page_title="AirPlus Assist",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* Page background */
.stApp { background-color: #FFFFFF; }

/* Sidebar */
[data-testid="stSidebar"] {
    background-color: #F0FAF4;
    border-right: 1px solid #E5E7EB;
}

/* Hide Streamlit default header */
#MainMenu, footer, header { visibility: hidden; }

/* Chat input */
[data-testid="stChatInput"] input {
    border: 1.5px solid #00B050 !important;
    border-radius: 24px !important;
}

/* Primary button */
.stButton > button {
    background-color: #00B050;
    color: white;
    border: none;
    border-radius: 8px;
    font-weight: 500;
}
.stButton > button:hover {
    background-color: #009040;
    color: white;
}

/* Secondary button */
.stButton > button[kind="secondary"] {
    background-color: transparent !important;
    color: #6B7280 !important;
    border: 1px solid #E5E7EB !important;
}
.stButton > button[kind="secondary"]:hover {
    background-color: #F9FAFB !important;
    color: #1A1A2E !important;
    border: 1px solid #D1D5DB !important;
}

/* Selectbox label */
.stSelectbox label {
    color: #1A1A2E;
    font-weight: 500;
}

/* Chat messages */
[data-testid="stChatMessage"] {
    border-radius: 12px;
    margin-bottom: 8px;
}

/* User avatar — dark gray */
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"])
    [data-testid="chatAvatarIcon-user"] {
    background-color: #374151 !important;
    color: white !important;
}

/* Assistant avatar — AirPlus green */
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"])
    [data-testid="chatAvatarIcon-assistant"] {
    background-color: #00B050 !important;
    color: white !important;
}

/* Remove excess sidebar top padding */
[data-testid="stSidebar"] > div:first-child {
    padding-top: 1rem !important;
}
[data-testid="stSidebar"] .block-container {
    padding-top: 0.5rem !important;
}
section[data-testid="stSidebar"] > div {
    padding-top: 0.8rem !important;
}

/* Remove default main area top padding */
.main .block-container {
    padding-top: 1rem !important;
    padding-bottom: 1rem !important;
    max-width: 100% !important;
}
.stApp > header {
    height: 0 !important;
}
[data-testid="stAppViewContainer"] > [data-testid="stVerticalBlock"] {
    padding-top: 0 !important;
    gap: 0 !important;
}

/* Mode selector radio buttons */
div[data-testid="stRadio"] > div {
    gap: 4px;
}
div[data-testid="stRadio"] label {
    background: transparent;
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 500;
    color: #1A1A2E;
    cursor: pointer;
    transition: background 0.15s;
}
div[data-testid="stRadio"] label:hover {
    background: #E8F5E9;
}
div[data-testid="stRadio"] label[data-checked="true"] {
    background: #E8F5E9;
    color: #00B050;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []
if "language" not in st.session_state:
    st.session_state.language = "EN"
if "product" not in st.session_state:
    st.session_state.product = None
if "suggested_question" not in st.session_state:
    st.session_state.suggested_question = None
if "retry_question" not in st.session_state:
    st.session_state.retry_question = None
if "retry_product" not in st.session_state:
    st.session_state.retry_product = None
if "last_question" not in st.session_state:
    st.session_state.last_question = None
if "process_question" not in st.session_state:
    st.session_state.process_question = None
if "process_product" not in st.session_state:
    st.session_state.process_product = None
if "show_fallback" not in st.session_state:
    st.session_state.show_fallback = None
if "processing" not in st.session_state:
    st.session_state.processing = False
if "analyse_results" not in st.session_state:
    st.session_state.analyse_results = None
if "analyse_text" not in st.session_state:
    st.session_state.analyse_text = ""
if "generated_reply" not in st.session_state:
    st.session_state.generated_reply = None

# ── Very early: convert retry → process (must run before sidebar renders) ─────
# Setting product_select HERE means the selectbox reads the correct value
# when the sidebar block executes a few lines later.
if st.session_state.retry_question:
    st.session_state.process_question = st.session_state.retry_question
    st.session_state.process_product  = st.session_state.retry_product
    st.session_state.retry_question   = None
    st.session_state.retry_product    = None
    st.session_state.product_select   = "All Products"
    st.session_state.show_fallback    = None

# ── Helper functions ──────────────────────────────────────────────────────────

LANGUAGE_OPTIONS = {
    "🇬🇧 English":    "EN",
    "🇩🇪 Deutsch":    "DE",
    "🇫🇷 Français":   "FR",
    "🇪🇸 Español":    "ES",
    "🇮🇹 Italiano":   "IT",
    "🇳🇱 Nederlands": "NL",
}

PRODUCT_DISPLAY = {
    "airplus_intelligence": "AirPlus Intelligence",
    "portal":               "Portal",
}

PRODUCT_REVERSE = {v: k for k, v in PRODUCT_DISPLAY.items()}

SCOPE_DISPLAY = {
    "all":                  "All Products",
    "airplus_intelligence": "AirPlus Intelligence",
    "portal":               "Portal",
}

SOURCE_ICONS = {
    "xlsx": "📊",
    "pdf":  "📄",
    "url":  "🌐",
    "docx": "📝",
    "txt":  "📃",
}

PRODUCT_BADGES = {
    "airplus_intelligence": (
        '<span style="background:#DBEAFE;color:#1E40AF;'
        'padding:1px 8px;border-radius:10px;font-size:11px;">'
        "AirPlus Intelligence</span>"
    ),
    "portal": (
        '<span style="background:#D1FAE5;color:#065F46;'
        'padding:1px 8px;border-radius:10px;font-size:11px;">'
        "Portal</span>"
    ),
}


def display_name(product_key: str) -> str:
    return PRODUCT_DISPLAY.get(product_key, product_key.title())


def language_code(display: str) -> str:
    return LANGUAGE_OPTIONS.get(display, "EN")


def product_key(display: str) -> Optional[str]:
    if display == "All Products":
        return None
    return PRODUCT_REVERSE.get(display)


def _fmt_timestamp(iso: str) -> str:
    """Format an ISO timestamp to '04 Apr 2026 12:15 UTC', or return as-is."""
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%d %b %Y %H:%M UTC")
    except (ValueError, TypeError):
        return iso


# ── API calls ─────────────────────────────────────────────────────────────────

def call_ask(question: str, lang: str, prod: Optional[str]) -> dict:
    resp = requests.post(
        f"{API_HOST}/ask",
        json={"question": question, "language": lang, "product": prod},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def call_ask_streaming(question: str, language: str, product: Optional[str]):
    """Generator that yields parsed SSE event dicts from /ask/stream."""
    import json as _json
    url     = f"{API_HOST}/ask/stream"
    payload = {"question": question, "language": language, "product": product}
    try:
        with requests.post(url, json=payload, stream=True, timeout=300) as resp:
            for line in resp.iter_lines():
                if line:
                    line_str = line.decode("utf-8") if isinstance(line, bytes) else line
                    if line_str.startswith("data: "):
                        yield _json.loads(line_str[6:])
    except requests.exceptions.Timeout:
        yield {"stage": "error", "message": "The response timed out. Please try again."}
    except Exception:
        yield {"stage": "error", "message": "Cannot reach AirPlus Assist API. Is Docker running?"}


def call_products() -> list:
    resp = requests.get(f"{API_HOST}/products", timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("products", [])


def call_health() -> dict:
    resp = requests.get(f"{API_HOST}/health", timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def call_ingest() -> dict:
    resp = requests.post(f"{API_HOST}/ingest", timeout=180)
    resp.raise_for_status()
    return resp.json()


# ── Rendering helpers ─────────────────────────────────────────────────────────

CONFIDENCE_PILLS = {
    "high": (
        '<span style="background:#D1FAE5;color:#065F46;'
        'padding:2px 10px;border-radius:12px;font-size:12px;'
        'font-weight:500;">● High confidence</span>'
    ),
    "medium": (
        '<span style="background:#FEF3C7;color:#92400E;'
        'padding:2px 10px;border-radius:12px;font-size:12px;'
        'font-weight:500;">● Sources found</span>'
    ),
    "low": (
        '<span style="background:#FFE4E6;color:#9F1239;'
        'padding:2px 10px;border-radius:12px;font-size:12px;'
        'font-weight:500;">● Low confidence</span>'
    ),
}

RANK_SYMBOLS = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤"}

CONFIDENCE_BADGES = {
    "high": (
        '<span style="background:#D1FAE5;color:#065F46;'
        'padding:1px 8px;border-radius:10px;font-size:11px;'
        'font-weight:500;">● High</span>'
    ),
    "medium": (
        '<span style="background:#FEF3C7;color:#92400E;'
        'padding:1px 8px;border-radius:10px;font-size:11px;'
        'font-weight:500;">◐ Medium</span>'
    ),
    "low": (
        '<span style="background:#F3F4F6;color:#6B7280;'
        'padding:1px 8px;border-radius:10px;font-size:11px;'
        'font-weight:500;">○ Low</span>'
    ),
}


def _url_link(url: Optional[str]) -> str:
    if not url:
        return ""
    return (
        f'<a href="{url}" target="_blank" '
        f'style="color:#00B050;font-size:12px;display:inline-block;'
        f'margin-top:6px;">🔗 Open source →</a>'
    )


def _primary_card(source: dict, has_contradiction: bool) -> str:
    src_type     = source.get("source_type", "txt")
    icon         = SOURCE_ICONS.get(src_type, "📄")
    label        = source.get("label", "")
    excerpt      = source.get("excerpt", "")
    product      = source.get("product", "")
    url          = source.get("url")
    rank         = source.get("rank", 1)
    conf         = source.get("confidence", "medium")

    border_color = "#F59E0B" if has_contradiction else "#00B050"
    rank_sym     = RANK_SYMBOLS.get(rank, str(rank))
    badge        = PRODUCT_BADGES.get(product, "")
    conf_badge   = CONFIDENCE_BADGES.get(conf, CONFIDENCE_BADGES["medium"])

    return f"""
<div style="background:#F9FAFB;border:1px solid #E5E7EB;
            border-radius:8px;padding:14px;margin-bottom:8px;
            border-left:4px solid {border_color};">
  <div style="display:flex;justify-content:space-between;
              align-items:flex-start;margin-bottom:8px;">
    <div>
      <span style="font-size:11px;font-weight:700;
                   color:{border_color};margin-right:8px;">{rank_sym}</span>
      <span style="font-weight:600;font-size:13px;
                   color:#1A1A2E;">{icon} {label}</span>
    </div>
    <div style="display:flex;gap:6px;align-items:center;flex-shrink:0;margin-left:8px;">
      {badge}
      {conf_badge}
    </div>
  </div>
  <div style="font-size:12px;color:#4B5563;
              line-height:1.6;border-top:1px solid #E5E7EB;
              padding-top:8px;">
    {excerpt}
  </div>
  {_url_link(url)}
</div>
"""


def _further_card(source: dict) -> str:
    src_type   = source.get("source_type", "txt")
    icon       = SOURCE_ICONS.get(src_type, "📄")
    label      = source.get("label", "")
    excerpt    = source.get("excerpt", "")
    product    = source.get("product", "")
    url        = source.get("url")
    rank       = source.get("rank", 3)
    conf       = source.get("confidence", "low")

    rank_sym   = RANK_SYMBOLS.get(rank, str(rank))
    badge      = PRODUCT_BADGES.get(product, "")
    conf_badge = CONFIDENCE_BADGES.get(conf, CONFIDENCE_BADGES["low"])
    snippet    = excerpt[:150] + "…" if len(excerpt) > 150 else excerpt

    return f"""
<div style="background:#F9FAFB;border:1px solid #E5E7EB;
            border-radius:8px;padding:12px;margin-bottom:6px;
            border-left:4px solid #9CA3AF;">
  <div style="display:flex;justify-content:space-between;
              align-items:center;margin-bottom:6px;">
    <span>
      <span style="font-size:11px;font-weight:700;
                   color:#6B7280;margin-right:6px;">{rank_sym}</span>
      <span style="font-weight:600;font-size:13px;
                   color:#1A1A2E;">{icon} {label}</span>
    </span>
    <div style="display:flex;gap:6px;flex-shrink:0;margin-left:8px;">
      {badge}
      {conf_badge}
    </div>
  </div>
  <div style="font-size:12px;color:#6B7280;line-height:1.5;">
    {snippet}
  </div>
  {_url_link(url)}
</div>
"""


def render_source_card(source: dict) -> None:
    """Render a single source as a compact card — used in both chat and analyse tabs."""
    src_type   = source.get("source_type", "txt")
    icon       = SOURCE_ICONS.get(src_type, "📄")
    label      = source.get("label", "")
    excerpt    = source.get("excerpt", "")
    product    = source.get("product", "")
    url        = source.get("url")
    rank       = source.get("rank", 1)
    conf       = source.get("confidence", "medium")

    rank_sym   = RANK_SYMBOLS.get(rank, str(rank))
    badge      = PRODUCT_BADGES.get(product, "")
    conf_badge = CONFIDENCE_BADGES.get(conf, CONFIDENCE_BADGES["medium"])
    snippet    = excerpt[:200] + "…" if len(excerpt) > 200 else excerpt

    st.markdown(f"""
<div style="background:#F9FAFB;border:1px solid #E5E7EB;
            border-radius:8px;padding:12px;margin-bottom:6px;
            border-left:4px solid #00B050;">
  <div style="display:flex;justify-content:space-between;
              align-items:center;margin-bottom:6px;">
    <span>
      <span style="font-size:11px;font-weight:700;
                   color:#00B050;margin-right:6px;">{rank_sym}</span>
      <span style="font-weight:600;font-size:13px;
                   color:#1A1A2E;">{icon} {label}</span>
    </span>
    <div style="display:flex;gap:6px;flex-shrink:0;margin-left:8px;">
      {badge}
      {conf_badge}
    </div>
  </div>
  <div style="font-size:12px;color:#6B7280;line-height:1.5;">{snippet}</div>
  {_url_link(url)}
</div>
""", unsafe_allow_html=True)


def render_assistant_message(msg: dict) -> None:
    """Render a stored assistant message dict into the current chat context."""
    confidence        = msg.get("confidence", "none")
    answer            = msg.get("answer", "")
    sources           = msg.get("sources", [])
    has_contradiction = msg.get("has_contradiction", False)
    product_scope     = msg.get("product_scope", "all")
    response_time     = msg.get("response_time")

    # Confidence pill
    if confidence in CONFIDENCE_PILLS:
        st.markdown(CONFIDENCE_PILLS[confidence], unsafe_allow_html=True)
        st.markdown("")

    # Contradiction banner
    if has_contradiction:
        st.markdown("""
<div style="background:#FFFBEB;border:1px solid #FCD34D;
            border-radius:8px;padding:10px 14px;
            margin-bottom:12px;font-size:13px;color:#92400E;">
  ⚠️ <b>Multiple sources found with differing information.</b>
  Review all citations below for the complete picture.
</div>
""", unsafe_allow_html=True)

    # Scope indicator
    scope_label = SCOPE_DISPLAY.get(product_scope, "All Products")
    st.markdown(
        f'<span style="font-size:11px;color:#6B7280;">🔍 Searched: {scope_label}</span>',
        unsafe_allow_html=True,
    )

    # Answer text
    st.markdown(answer)

    # No-answer hint box — stop here, no source zones
    if confidence == "none":
        st.markdown("""
<div style="background:#FFF7ED;border:1px solid #FED7AA;
            border-radius:8px;padding:10px 14px;
            font-size:13px;color:#92400E;margin-top:8px;">
  💡 Try rephrasing your question or selecting a different knowledge base filter.
</div>
""", unsafe_allow_html=True)
        if response_time is not None:
            st.markdown(
                f'<div style="font-size:11px;color:#9CA3AF;'
                f'margin-top:8px;text-align:right;">'
                f'Answered in {response_time:.0f}s</div>',
                unsafe_allow_html=True,
            )
        return

    if not sources:
        if response_time is not None:
            st.markdown(
                f'<div style="font-size:11px;color:#9CA3AF;'
                f'margin-top:8px;text-align:right;">'
                f'Answered in {response_time:.0f}s</div>',
                unsafe_allow_html=True,
            )
        return

    # Split into primary (ranks 1-2) and further (ranks 3+)
    has_any_high = any(s.get("confidence") == "high" for s in sources)
    if has_any_high:
        primary = sources[:2]
        further = sources[2:]
    else:
        primary = sources
        further = []

    # ── Zone 1: Primary Sources ───────────────────────────────────────────────
    st.markdown("""
<div style="font-size:12px;font-weight:600;color:#6B7280;
            letter-spacing:0.5px;margin:16px 0 8px 0;">
  PRIMARY SOURCES
</div>
""", unsafe_allow_html=True)

    for source in primary:
        st.markdown(_primary_card(source, has_contradiction), unsafe_allow_html=True)

    if not has_any_high:
        st.markdown(
            '<div style="font-size:12px;color:#9CA3AF;margin-top:4px;">'
            "No high-confidence sources found — verify answers against original documents."
            "</div>",
            unsafe_allow_html=True,
        )

    # ── Zone 2: Further Reading ───────────────────────────────────────────────
    if further:
        with st.expander(
            f"📖 Further reading — {len(further)} additional source(s)",
            expanded=False,
        ):
            st.markdown("""
<div style="font-size:12px;color:#6B7280;margin-bottom:12px;">
  These sources contain related information that may help
  if the answer above doesn't fully address your question.
</div>
""", unsafe_allow_html=True)
            for source in further:
                st.markdown(_further_card(source), unsafe_allow_html=True)

    # Response time
    if response_time is not None:
        st.markdown(
            f'<div style="font-size:11px;color:#9CA3AF;'
            f'margin-top:8px;text-align:right;">'
            f'Answered in {response_time:.0f}s</div>',
            unsafe_allow_html=True,
        )


# ── Meta-question helpers ─────────────────────────────────────────────────────

def get_meta_answer(question: str) -> dict | None:
    """
    Check if question matches a meta intent.
    Returns a pre-built response dict or None if no match.
    Matching is case-insensitive; checks for any keyword phrase.
    """
    q = question.lower().strip()

    if any(phrase in q for phrase in [
        "how can i use", "how do i use", "how to use",
        "what is this tool", "how does this work",
        "how does it answer", "what can you do",
        "how do you work", "getting started",
    ]):
        return META_ANSWERS["how_to_use"]

    if any(phrase in q for phrase in [
        "not satisfied", "wrong answer", "incorrect",
        "bad answer", "improve", "not happy",
        "dissatisfied", "answer is wrong",
        "what if i don't", "what to do if",
    ]):
        return META_ANSWERS["not_satisfied"]

    if any(phrase in q for phrase in [
        "help channel", "support", "contact",
        "who do i contact", "reach out",
        "raise an incident", "get help", "need help",
        "help desk", "helpdesk",
    ]):
        return META_ANSWERS["help_channels"]

    if any(phrase in q for phrase in [
        "tech", "technical", "architecture",
        "how is this built", "technology",
        "under the hood", "how does the ai",
        "machine learning", "rag", "vector",
        "language model", "llm",
    ]):
        return META_ANSWERS["tech_architecture"]

    return None


def render_meta_answer(msg: dict) -> None:
    """Render a hardcoded meta answer in the chat."""
    answer = msg.get("answer", "")

    st.markdown(
        '<span style="background:#D1FAE5;color:#065F46;'
        'padding:2px 10px;border-radius:12px;font-size:12px;'
        'font-weight:500;">● AirPlus Assist</span>',
        unsafe_allow_html=True,
    )
    st.markdown("")
    st.markdown(answer)

    if msg.get("architecture_diagram"):
        st.markdown(ARCHITECTURE_DIAGRAM, unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    # ── Logo ──────────────────────────────────────────────────────────────────
    st.markdown("""
<div style="padding: 4px 0 4px 0;">
  <div style="font-size:24px;font-weight:700;
              color:#1A1A2E;letter-spacing:-0.5px;">
    AirPlus
  </div>
  <div style="font-size:14px;font-weight:500;
              color:#4B5563;margin-top:3px;
              letter-spacing:1.5px;">
    ASSIST
  </div>
</div>
""", unsafe_allow_html=True)

    st.markdown('<hr style="border:none;border-top:1px solid #E5E7EB;margin:8px 0;">', unsafe_allow_html=True)

    # ── Mode selector ─────────────────────────────────────────────────────────
    st.markdown("**Mode**")
    mode = st.radio(
        "Mode",
        options=["💬 Chat", "📧 Draft Reply"],
        index=0,
        key="app_mode",
        label_visibility="collapsed",
        horizontal=False,
    )

    st.markdown('<hr style="border:none;border-top:1px solid #E5E7EB;margin:8px 0;">', unsafe_allow_html=True)

    # ── Settings ──────────────────────────────────────────────────────────────
    st.markdown("**Settings**")

    lang_display = st.selectbox(
        "Language",
        options=list(LANGUAGE_OPTIONS.keys()),
        index=0,
        key="language_select",
    )
    selected_lang = language_code(lang_display)

    if st.session_state.language != selected_lang:
        if st.session_state.messages:
            st.toast(
                f"Language set to {selected_lang} — applies to new questions",
                icon="🌐",
            )
        st.session_state.language = selected_lang

    if "available_products" not in st.session_state:
        try:
            st.session_state.available_products = call_products()
        except Exception:
            st.session_state.available_products = []

    product_options = ["All Products"] + [
        display_name(p) for p in st.session_state.available_products
    ]
    prod_display = st.selectbox(
        "Knowledge Base",
        options=product_options,
        index=0,
        key="product_select",
    )
    selected_product = product_key(prod_display)
    st.session_state.product = selected_product  # keep session state in sync

    # Clear conversation button
    if st.button(
        "🗑️ Clear conversation",
        use_container_width=True,
        type="secondary",
    ):
        st.session_state.messages = []
        st.rerun()

    st.markdown('<hr style="border:none;border-top:1px solid #E5E7EB;margin:8px 0;">', unsafe_allow_html=True)

    # ── Knowledge base status ─────────────────────────────────────────────────
    st.markdown("**Knowledge Base**")

    try:
        health        = call_health()
        chunk_count   = health.get("chunk_count", "—")
        last_ingested = _fmt_timestamp(health.get("last_ingested", ""))
        status_color  = "#00B050"
        status_dot    = "●"
        kb_label      = "Knowledge base connected"
    except Exception:
        chunk_count   = "—"
        last_ingested = "API unreachable"
        status_color  = "#EF4444"
        status_dot    = "●"
        kb_label      = "API unreachable"

    st.markdown(f"""
<div style="background:#E8F5E9;border-radius:8px;
            padding:10px 12px;font-size:13px;">
  <span style="color:{status_color};">{status_dot}</span>
  <b>{kb_label}</b><br>
  <span style="color:#6B7280;font-size:11px;">
  {chunk_count} chunks · Last ingested: {last_ingested}</span>
</div>
""", unsafe_allow_html=True)

    st.markdown("")

    if st.button("🔄 Refresh Knowledge Base", use_container_width=True):
        with st.spinner("Refreshing knowledge base..."):
            try:
                result = call_ingest()
                if result.get("status") == "ok":
                    st.success("✓ Knowledge base refreshed")
                else:
                    st.warning(result.get("message", "Unknown error from ingest endpoint."))
            except requests.ConnectionError:
                st.error("Cannot reach API — is Docker running?")
            except Exception as exc:
                st.warning(str(exc))

    st.markdown('<hr style="border:none;border-top:1px solid #E5E7EB;margin:8px 0;">', unsafe_allow_html=True)

    # Footer
    st.markdown("""
<div style="font-size:11px;color:#6B7280;line-height:1.6;">
Answers are generated strictly from AirPlus documentation.
Sources are cited with every answer.
</div>
""", unsafe_allow_html=True)

# ── API reachability check ────────────────────────────────────────────────────

api_ok = True
try:
    call_health()
except Exception:
    api_ok = False

if not api_ok:
    st.warning("⚠️ AirPlus Assist is starting up. Please wait a moment and refresh the page.")

# ── Mode routing ──────────────────────────────────────────────────────────────

if mode == "💬 Chat":

    st.markdown("""
<div style="padding:24px 0 8px 0;">
  <h1 style="font-size:28px;font-weight:700;color:#1A1A2E;margin:0;">
    Ask AirPlus Assist
  </h1>
  <p style="color:#6B7280;font-size:15px;margin:4px 0 0 0;">
    Questions answered from AirPlus documentation — always with sources.
  </p>
</div>
<hr style="border:none;border-top:1px solid #E5E7EB;margin:12px 0 20px 0;">
""", unsafe_allow_html=True)

    # ── Consume any pending process or suggested question ─────────────────────

    question_to_process: Optional[str] = None
    effective_product_override: Optional[str] = None
    _has_override = False

    if st.session_state.process_question:
        question_to_process          = st.session_state.process_question
        effective_product_override   = st.session_state.process_product  # None = all
        _has_override                = True
        st.session_state.process_question = None
        st.session_state.process_product  = None

    elif st.session_state.suggested_question:
        question_to_process = st.session_state.suggested_question
        st.session_state.suggested_question = None

    # ── Welcome state ─────────────────────────────────────────────────────────

    if len(st.session_state.messages) == 0 and question_to_process is None:
        st.markdown("""
<div style="margin: 40px auto;max-width:600px;">
  <div style="text-align:center;margin-bottom:32px;">
    <div style="font-size:40px;margin-bottom:12px;">🤖</div>
    <h3 style="color:#1A1A2E;font-weight:600;margin:0;">
      How can I help you today?</h3>
    <p style="color:#6B7280;font-size:14px;margin-top:8px;">
      Ask anything about AirPlus products.
      I'll answer from the official documentation.
    </p>
  </div>
</div>
""", unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💡 How can I use this tool?", use_container_width=True):
                st.session_state.suggested_question = \
                    "How can I use this tool and how does it answer?"
                st.rerun()
            if st.button("🔧 I'm a tech enthusiast — tell me more", use_container_width=True):
                st.session_state.suggested_question = \
                    "I want to know the technical architecture of this tool"
                st.rerun()
        with col2:
            if st.button("😕 What if I'm not satisfied with the answer(s)?", use_container_width=True):
                st.session_state.suggested_question = \
                    "What to do if I am not satisfied with answers?"
                st.rerun()
            if st.button("📞 What are the help channels?", use_container_width=True):
                st.session_state.suggested_question = "What are the help channels?"
                st.rerun()

    # ── Replay chat history ───────────────────────────────────────────────────

    for i, msg in enumerate(st.session_state.messages):
        is_last_assistant = (
            msg["role"] == "assistant"
            and i == len(st.session_state.messages) - 1
            and st.session_state.get("processing", False)
        )
        if is_last_assistant:
            continue

        if msg["role"] == "user":
            if msg.get("content"):
                with st.chat_message("user", avatar="👤"):
                    st.markdown(msg["content"])
        elif msg["role"] == "assistant" and msg.get("answer") is not None:
            with st.chat_message("assistant", avatar="🤖"):
                if msg.get("is_meta"):
                    render_meta_answer(msg)
                else:
                    render_assistant_message(msg)

    # ── Chat input — must be last widget call so Streamlit anchors it to bottom ──

    _chat_input = st.chat_input("Ask a question about AirPlus products…")
    if _chat_input:
        question_to_process = _chat_input

    if question_to_process:
        with st.chat_message("user", avatar="👤"):
            st.markdown(question_to_process)
        st.session_state.messages.append({"role": "user", "content": question_to_process})
        st.session_state.last_question = question_to_process

        meta_response = get_meta_answer(question_to_process)
        effective_product = effective_product_override if _has_override else selected_product

        with st.chat_message("assistant", avatar="🤖"):
            if meta_response:
                render_meta_answer(meta_response)
                st.session_state.messages.append({
                    "role":               "assistant",
                    "answer":             meta_response["answer"],
                    "architecture_diagram": meta_response.get("architecture_diagram", False),
                    "sources":            [],
                    "confidence":         "high",
                    "has_contradiction":  False,
                    "is_meta":            True,
                    "product_scope":      "all",
                    "response_time":      0,
                })

            else:
                stage_placeholder = st.empty()
                stage_log         = []
                start_time        = time.time()
                final_response    = None

                st.session_state.processing = True

                for evt in call_ask_streaming(
                    question_to_process, selected_lang, effective_product
                ):
                    stage   = evt.get("stage")
                    elapsed = time.time() - start_time

                    if stage == "complete":
                        final_response = evt.get("result")
                        break

                    elif stage == "error":
                        stage_placeholder.empty()
                        st.session_state.processing = False
                        st.error(evt.get("message"))
                        st.session_state.messages.append({
                            "role":             "assistant",
                            "confidence":       "none",
                            "answer":           evt.get("message", ""),
                            "sources":          [],
                            "has_contradiction": False,
                            "product_scope":    "all",
                            "response_time":    elapsed,
                        })
                        break

                    else:
                        icon    = evt.get("icon", "⏳")
                        message = evt.get("message", "")
                        stage_log.append((icon, message))

                        rows = ""
                        for j, (ico, msg_txt) in enumerate(stage_log):
                            is_current = (j == len(stage_log) - 1)
                            color  = "#1A1A2E" if is_current else "#6B7280"
                            weight = "600"     if is_current else "400"
                            spinner_html = (
                                '<span style="display:inline-block;'
                                'animation:spin 1s linear infinite;">⟳</span> '
                                if is_current else "✓ "
                            )
                            rows += (
                                f'<div style="font-size:13px;color:{color};'
                                f'font-weight:{weight};margin:4px 0;">'
                                f'{spinner_html}{ico} {msg_txt}</div>'
                            )

                        stage_placeholder.markdown(f"""
<style>
@keyframes spin {{
  from {{ transform: rotate(0deg); }}
  to   {{ transform: rotate(360deg); }}
}}
</style>
<div style="background:#F0FAF4;border:1px solid #BBF7D0;
            border-radius:10px;padding:14px 18px;">
  {rows}
  <div style="font-size:11px;color:#9CA3AF;margin-top:10px;
              border-top:1px solid #E5E7EB;padding-top:8px;">
    ⏱ {elapsed:.0f}s · {OLLAMA_MODEL}
  </div>
</div>
""", unsafe_allow_html=True)

                stage_placeholder.empty()
                st.session_state.processing = False

                if final_response is not None:
                    elapsed_total = time.time() - start_time
                    render_assistant_message({**final_response, "response_time": elapsed_total})
                    st.session_state.messages.append({
                        "role":             "assistant",
                        "confidence":       final_response.get("confidence", "none"),
                        "answer":           final_response.get("answer", ""),
                        "sources":          final_response.get("sources", []),
                        "has_contradiction": final_response.get("has_contradiction", False),
                        "product_scope":    final_response.get("product_scope", "all"),
                        "language":         final_response.get("language", "EN"),
                        "response_time":    elapsed_total,
                        "last_question":    question_to_process,
                    })
                    st.session_state.last_question = question_to_process

    # ── Fallback: Search in All Products ──────────────────────────────────────

    _last_assistant = None
    for _msg in reversed(st.session_state.messages):
        if _msg["role"] == "assistant":
            _last_assistant = _msg
            break

    if (
        _last_assistant
        and not _last_assistant.get("is_meta", False)
        and _last_assistant.get("confidence") in ("none", "low")
        and st.session_state.product is not None
    ):
        _prod_label = display_name(st.session_state.product)
        st.markdown(f"""
<div style="background:#EFF6FF;border:1px solid #BFDBFE;
            border-radius:8px;padding:12px 16px;
            font-size:13px;color:#1E40AF;margin:8px 0 4px 0;">
  🔍 <b>Not finding what you need in {_prod_label}?</b><br>
  <span style="color:#6B7280;font-size:12px;">
  Try searching across all products for a broader result.
  </span>
</div>
""", unsafe_allow_html=True)
        if st.button(
            "Search in All Products →",
            key="search_all_persistent",
            type="secondary",
        ):
            st.session_state.retry_question = st.session_state.last_question
            st.session_state.retry_product  = None
            st.rerun()


# ── Draft Reply mode ─────────────────────────────────────────────────────────

elif mode == "📧 Draft Reply":

    st.markdown("""
<div style="padding:24px 0 8px 0;">
  <h1 style="font-size:28px;font-weight:700;color:#1A1A2E;margin:0;">
    Draft a Reply
  </h1>
  <p style="color:#6B7280;font-size:15px;margin:4px 0 0 0;">
    Paste an incoming message to extract questions, get answers,
    and generate a ready-to-send reply.
  </p>
</div>
<hr style="border:none;border-top:1px solid #E5E7EB;margin:12px 0 20px 0;">
""", unsafe_allow_html=True)

    message_text = st.text_area(
        "Message",
        placeholder=(
            "Paste an incoming email or chat message here...\n\n"
            "Example:\n"
            "Hi team, I'm trying to download my eBilling file but can't find it. "
            "Also what does EUR Amount mean in the report?\n\n"
            "Thanks, Sarah"
        ),
        height=200,
        key="analyse_input",
        label_visibility="collapsed",
    )

    char_count = len(message_text) if message_text else 0
    st.markdown(
        f'<div style="font-size:11px;color:'
        f'{"#EF4444" if char_count > 5000 else "#9CA3AF"};'
        f'text-align:right;margin-top:-8px;">'
        f'{char_count}/5000 characters</div>',
        unsafe_allow_html=True,
    )

    col_btn, col_clear = st.columns([3, 1])
    with col_btn:
        analyse_clicked = st.button(
            "🔍 Find Answers",
            type="primary",
            use_container_width=True,
            disabled=(char_count == 0 or char_count > 5000),
        )
    with col_clear:
        if st.button("🗑 Clear", use_container_width=True, type="secondary"):
            st.session_state.analyse_results  = None
            st.session_state.analyse_text     = ""
            st.session_state.generated_reply  = None
            st.rerun()

    if analyse_clicked and message_text.strip():
        _lang = st.session_state.get("language", "EN")
        _prod = st.session_state.get("product", None)
        with st.spinner("Analysing message and extracting questions..."):
            try:
                _resp = requests.post(
                    f"{API_HOST}/analyse",
                    json={
                        "text":          message_text,
                        "language":      _lang,
                        "product":       _prod,
                        "max_questions": 5,
                    },
                    timeout=300,
                )
                _resp.raise_for_status()
                st.session_state.analyse_results = _resp.json()
                st.session_state.analyse_text    = message_text
                st.session_state.generated_reply = None
            except Exception as _e:
                st.error(f"Analysis failed: {_e}")

    # ── Render results ────────────────────────────────────────────────────────

    if st.session_state.get("analyse_results"):
        _data      = st.session_state.analyse_results
        _n         = _data.get("questions_found", 0)
        _proc_time = _data.get("processing_time_seconds", 0)

        if _n == 0:
            st.info(
                "No questions were identified in this message. "
                "Try rephrasing or adding a question mark."
            )
        else:
            st.markdown(f"""
<div style="background:#F0FAF4;border:1px solid #BBF7D0;border-radius:8px;
            padding:12px 16px;margin:16px 0 20px 0;font-size:13px;color:#065F46;">
  ✅ Found <b>{_n} question{"s" if _n > 1 else ""}</b> in your message ·
  Processed in {_proc_time:.0f}s
</div>
""", unsafe_allow_html=True)

            _unanswered = sum(
                1 for r in _data["results"] if not r["answered"]
            )

            for _result in _data["results"]:
                _qnum       = _result["question_number"]
                _answered   = _result["answered"]
                _confidence = _result["confidence"]

                _border = (
                    "#00B050" if _confidence == "high"
                    else "#F59E0B" if _confidence == "medium"
                    else "#E5E7EB" if _answered
                    else "#FCA5A5"
                )
                _hicon = "✅" if _confidence in ("high", "medium") else "⚠️"

                st.markdown(f"""
<div style="border:1.5px solid {_border};border-radius:10px;
            padding:16px 16px 4px 16px;margin-bottom:4px;">
  <div style="font-size:11px;font-weight:600;color:#6B7280;
              letter-spacing:0.5px;margin-bottom:6px;">
    {_hicon} QUESTION {_qnum} OF {_n}
  </div>
</div>
""", unsafe_allow_html=True)

                _edited_q = st.text_input(
                    f"Question {_qnum}",
                    value=_result["current_question"],
                    key=f"q_{_qnum}",
                    label_visibility="collapsed",
                )
                _result["current_question"] = _edited_q

                if _answered:
                    _conf_styles = {
                        "high":   ("#D1FAE5", "#065F46", "● High confidence"),
                        "medium": ("#FEF3C7", "#92400E", "● Sources found"),
                        "low":    ("#FFE4E6", "#9F1239", "● Low confidence"),
                    }
                    _bg, _tc, _label = _conf_styles.get(
                        _confidence, ("#F3F4F6", "#6B7280", "● Unknown")
                    )
                    st.markdown(
                        f'<span style="background:{_bg};color:{_tc};'
                        f'padding:2px 10px;border-radius:12px;'
                        f'font-size:12px;font-weight:500;">{_label}</span>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(_result["answer"])

                    _sources = _result.get("sources", [])
                    if _sources:
                        with st.expander(f"📚 {len(_sources)} source(s)", expanded=False):
                            for _src in _sources:
                                render_source_card(_src)

                else:
                    st.markdown("""
<div style="background:#FFF7ED;border:1px solid #FED7AA;border-radius:8px;
            padding:12px 14px;font-size:13px;color:#92400E;margin:8px 0;">
  ○ <b>No information found</b> in the knowledge base for this question.
</div>
""", unsafe_allow_html=True)
                    st.markdown(
                        '<p style="font-size:12px;color:#6B7280;margin:4px 0 8px 0;">'
                        "💡 Try editing the question above and click Re-answer below.</p>",
                        unsafe_allow_html=True,
                    )

                    if st.button(f"🔄 Re-answer question {_qnum}", key=f"reanswer_{_qnum}"):
                        _rl = st.session_state.get("language", "EN")
                        _rp = st.session_state.get("product", None)
                        with st.spinner(f"Re-answering question {_qnum}..."):
                            try:
                                _rr = requests.post(
                                    f"{API_HOST}/ask",
                                    json={"question": _edited_q, "language": _rl, "product": _rp},
                                    timeout=120,
                                )
                                _new = _rr.json()
                                _result["answer"]     = _new.get("answer", "")
                                _result["confidence"] = _new.get("confidence", "none")
                                _result["sources"]    = _new.get("sources", [])
                                _result["answered"]   = _new.get("confidence") != "none"
                                st.session_state.analyse_results["results"][_qnum - 1] = _result
                                st.rerun()
                            except Exception as _e:
                                st.error(str(_e))

                st.markdown("<div style='margin-bottom:12px;'></div>", unsafe_allow_html=True)

            if _unanswered > 0:
                st.markdown("---")
                _btn_label = (
                    f"🔄 Re-answer all {_unanswered} unanswered question"
                    f"{'s' if _unanswered > 1 else ''}"
                )
                if st.button(_btn_label, type="secondary"):
                    _rl = st.session_state.get("language", "EN")
                    _rp = st.session_state.get("product", None)
                    with st.spinner("Re-answering..."):
                        for _result in st.session_state.analyse_results["results"]:
                            if not _result["answered"]:
                                _qn  = _result["question_number"]
                                _eq  = st.session_state.get(f"q_{_qn}", _result["current_question"])
                                try:
                                    _rr = requests.post(
                                        f"{API_HOST}/ask",
                                        json={"question": _eq, "language": _rl, "product": _rp},
                                        timeout=120,
                                    )
                                    _new = _rr.json()
                                    _result["answer"]     = _new.get("answer", "")
                                    _result["confidence"] = _new.get("confidence", "none")
                                    _result["sources"]    = _new.get("sources", [])
                                    _result["answered"]   = _new.get("confidence") != "none"
                                except Exception:
                                    pass
                    st.rerun()

            # ── Generate Reply section ────────────────────────────────────────

            _answered_results   = [r for r in _data["results"] if r["answered"]]
            _unanswered_results = [r for r in _data["results"] if not r["answered"]]
            _n_answered         = len(_answered_results)
            _n_unanswered       = len(_unanswered_results)

            st.markdown("---")

            if _n_answered > 0:
                # Warning about excluded questions
                if _n_unanswered > 0:
                    _excl_items = "".join(
                        f'<li style="margin:2px 0;">{r["current_question"]}</li>'
                        for r in _unanswered_results
                    )
                    st.markdown(f"""
<div style="background:#FFF7ED;border:1px solid #FED7AA;border-radius:8px;
            padding:12px 16px;font-size:13px;color:#92400E;margin-bottom:12px;">
  ⚠️ <b>{_n_unanswered} question{"s" if _n_unanswered > 1 else ""} could not be answered</b>
  and will be excluded from the reply:
  <ul style="margin:6px 0 0 0;padding-left:18px;">{_excl_items}</ul>
</div>
""", unsafe_allow_html=True)

                _btn_label = (
                    f"✅ Accept {_n_answered} answered question"
                    f"{'s' if _n_answered > 1 else ''} & Generate Reply"
                )
                if st.button(_btn_label, type="primary", use_container_width=True, key="generate_reply_btn"):
                    _lang = st.session_state.get("language", "EN")
                    # Sync any edited question text before sending
                    for _r in _answered_results:
                        _qn = _r["question_number"]
                        _r["current_question"] = st.session_state.get(f"q_{_qn}", _r["current_question"])
                    with st.spinner(f"Generating reply with {OLLAMA_MODEL}..."):
                        try:
                            _gr = requests.post(
                                f"{API_HOST}/generate_reply",
                                json={
                                    "original_text":    st.session_state.get("analyse_text", ""),
                                    "answered_results": _answered_results,
                                    "language":         _lang,
                                },
                                timeout=120,
                            )
                            _gr.raise_for_status()
                            st.session_state.generated_reply = _gr.json().get("reply", "")
                        except Exception as _e:
                            st.error(f"Failed to generate reply: {_e}")

            else:
                st.markdown("""
<div style="background:#F3F4F6;border:1px solid #E5E7EB;border-radius:8px;
            padding:12px 16px;font-size:13px;color:#6B7280;text-align:center;">
  No questions could be answered from the knowledge base.
  Edit the questions above and click Re-answer before generating a reply.
</div>
""", unsafe_allow_html=True)

            # ── Render generated reply ────────────────────────────────────────

            if st.session_state.get("generated_reply"):
                st.markdown("""
<div style="margin:20px 0 8px 0;">
  <span style="font-size:14px;font-weight:600;color:#1A1A2E;">✉️ Generated Reply</span>
  <span style="font-size:12px;color:#6B7280;margin-left:8px;">Review and edit before sending</span>
</div>
""", unsafe_allow_html=True)

                _edited_reply = st.text_area(
                    "Generated reply",
                    value=st.session_state.generated_reply,
                    height=300,
                    key="reply_text_area",
                    label_visibility="collapsed",
                )

                _col1, _col2, _col3 = st.columns([2, 2, 1])

                with _col1:
                    if st.button("📋 Copy to clipboard", use_container_width=True, key="copy_reply"):
                        _escaped = _edited_reply.replace("'", "\\'").replace("\n", "\\n")
                        st.markdown(
                            f"<script>navigator.clipboard.writeText('{_escaped}');</script>",
                            unsafe_allow_html=True,
                        )
                        st.success("Copied to clipboard!")

                with _col2:
                    import urllib.parse as _urlparse
                    _subject = _urlparse.quote("Re: Your AirPlus enquiry")
                    _body    = _urlparse.quote(_edited_reply)
                    _mailto  = f"mailto:?subject={_subject}&body={_body}"
                    st.markdown(
                        f'<a href="{_mailto}" target="_blank">'
                        f'<button style="width:100%;background:#1A1A2E;color:white;border:none;'
                        f'padding:8px 16px;border-radius:8px;font-size:14px;cursor:pointer;'
                        f'font-weight:500;">📧 Open in Mail</button></a>',
                        unsafe_allow_html=True,
                    )

                with _col3:
                    if st.button("🔄 Regenerate", use_container_width=True, key="regenerate_reply", type="secondary"):
                        st.session_state.generated_reply = None
                        st.rerun()

                st.markdown("""
<div style="font-size:11px;color:#9CA3AF;margin-top:12px;text-align:center;">
  This reply was generated from AirPlus documentation. Always review before sending.
</div>
""", unsafe_allow_html=True)
