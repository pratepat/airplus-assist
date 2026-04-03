import os
from typing import Optional

import requests
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────

API_HOST = os.environ.get("API_HOST", "http://api:8001")
REQUEST_TIMEOUT = 90

st.set_page_config(
    page_title="AirPlus Assist",
    page_icon="✈️",
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
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []
if "language" not in st.session_state:
    st.session_state.language = "EN"
if "product" not in st.session_state:
    st.session_state.product = None

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


# ── API calls ─────────────────────────────────────────────────────────────────

def call_ask(question: str, lang: str, prod: Optional[str]) -> dict:
    resp = requests.post(
        f"{API_HOST}/ask",
        json={"question": question, "language": lang, "product": prod},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def call_products() -> list:
    resp = requests.get(f"{API_HOST}/products", timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("products", [])


def call_health() -> dict:
    resp = requests.get(f"{API_HOST}/health", timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def call_ingest() -> dict:
    resp = requests.post(f"{API_HOST}/ingest", timeout=REQUEST_TIMEOUT)
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


def render_source_card(source: dict) -> str:
    src_type = source.get("source_type", "txt")
    icon     = SOURCE_ICONS.get(src_type, "📄")
    label    = source.get("label", "")
    preview  = source.get("preview", "")
    product  = source.get("product", "")
    url      = source.get("url")

    badge    = PRODUCT_BADGES.get(product, "")
    url_link = (
        f'<a href="{url}" target="_blank" '
        f'style="color:#00B050;font-size:12px;">🔗 Open source →</a>'
        if url else ""
    )

    return f"""
<div style="background:#F9FAFB;border:1px solid #E5E7EB;
            border-radius:8px;padding:12px;margin-bottom:8px;
            border-left:3px solid #00B050;">
  <div style="display:flex;justify-content:space-between;
              align-items:center;margin-bottom:4px;">
    <span style="font-weight:600;font-size:13px;color:#1A1A2E;">
      {icon} {label}
    </span>
    {badge}
  </div>
  <div style="font-size:12px;color:#6B7280;font-style:italic;">
    {preview}
  </div>
  {url_link}
</div>
"""


def render_assistant_message(msg: dict) -> None:
    """Render a stored assistant message dict into the current chat context."""
    confidence = msg.get("confidence", "none")
    answer     = msg.get("answer", "")
    sources    = msg.get("sources", [])

    # Confidence pill
    if confidence in CONFIDENCE_PILLS:
        st.markdown(CONFIDENCE_PILLS[confidence], unsafe_allow_html=True)
        st.markdown("")   # breathing room

    # Answer text
    st.markdown(answer)

    # No-answer hint box
    if confidence == "none":
        st.markdown("""
<div style="background:#FFF7ED;border:1px solid #FED7AA;
            border-radius:8px;padding:10px 14px;
            font-size:13px;color:#92400E;margin-top:8px;">
  💡 Try rephrasing your question or selecting a different knowledge base filter.
</div>
""", unsafe_allow_html=True)

    # Sources expander
    if sources:
        with st.expander(f"📚 {len(sources)} source(s) cited", expanded=False):
            for source in sources:
                st.markdown(render_source_card(source), unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    # Logo
    st.markdown("""
<div style="padding: 16px 0 8px 0;">
  <div style="font-size:24px;font-weight:700;color:#1A1A2E;letter-spacing:-0.5px;">
    Air<span style="color:#00B050;">Plus</span>
  </div>
  <div style="font-size:12px;color:#6B7280;margin-top:2px;letter-spacing:0.5px;">
    ASSIST
  </div>
</div>
""", unsafe_allow_html=True)

    st.divider()

    # ── Settings ──────────────────────────────────────────────────────────────
    st.markdown("**Settings**")

    lang_display = st.selectbox(
        "Language",
        options=list(LANGUAGE_OPTIONS.keys()),
        index=0,
        key="language_select",
    )
    selected_lang = language_code(lang_display)

    # Toast when language changes after first message
    if st.session_state.language != selected_lang:
        if st.session_state.messages:
            st.toast(
                f"Language set to {selected_lang} — applies to new questions",
                icon="🌐",
            )
        st.session_state.language = selected_lang

    # Product list — fetched once, cached in session state
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

    st.divider()

    # ── Knowledge base status ─────────────────────────────────────────────────
    st.markdown("**Knowledge Base**")

    try:
        health       = call_health()
        chunk_count  = health.get("chunk_count", "—")
        last_updated = health.get("last_updated", "unknown")
        status_color = "#00B050"
        status_dot   = "●"
    except Exception:
        chunk_count  = "—"
        last_updated = "API unreachable"
        status_color = "#EF4444"
        status_dot   = "●"

    st.markdown(f"""
<div style="background:#E8F5E9;border-radius:8px;
            padding:10px 12px;font-size:13px;">
  <span style="color:{status_color};">{status_dot}</span>
  <b>Knowledge base connected</b><br>
  <span style="color:#6B7280;font-size:11px;">
  Last updated: {last_updated}</span>
</div>
""", unsafe_allow_html=True)

    st.markdown("")

    if st.button("🔄 Refresh Knowledge Base", use_container_width=True):
        with st.spinner("Re-indexing knowledge base…"):
            try:
                result = call_ingest()
                if result.get("status") == "ok":
                    st.success("Knowledge base refreshed successfully.")
                else:
                    st.error(f"Ingest failed: {result.get('message', 'unknown error')}")
            except Exception as exc:
                st.error(f"Could not reach the API: {exc}")

    st.divider()

    # Footer
    st.markdown("""
<div style="font-size:11px;color:#6B7280;line-height:1.6;">
Answers are generated strictly from AirPlus documentation.
Sources are cited with every answer.
</div>
""", unsafe_allow_html=True)

# ── Main area ─────────────────────────────────────────────────────────────────

st.markdown("""
<div style="padding: 24px 0 8px 0;">
  <h1 style="font-size:28px;font-weight:700;color:#1A1A2E;margin:0;">
    Ask AirPlus Assist
  </h1>
  <p style="color:#6B7280;font-size:15px;margin:4px 0 0 0;">
    Questions answered from AirPlus documentation — always with sources.
  </p>
</div>
<hr style="border:none;border-top:1px solid #E5E7EB;margin:12px 0 20px 0;">
""", unsafe_allow_html=True)

# ── API reachability check ────────────────────────────────────────────────────

api_ok = True
try:
    call_health()
except Exception:
    api_ok = False

if not api_ok:
    st.warning("""
⚠️ AirPlus Assist is starting up.
Please wait a moment and refresh the page.
""")

# ── Replay chat history ───────────────────────────────────────────────────────

for msg in st.session_state.messages:
    if msg["role"] == "user":
        if msg.get("content"):
            with st.chat_message("user"):
                st.markdown(msg["content"])
    elif msg["role"] == "assistant" and msg.get("answer") is not None:
        with st.chat_message("assistant", avatar="✈️"):
            render_assistant_message(msg)

# ── Chat input ────────────────────────────────────────────────────────────────

if question := st.chat_input("Ask a question about AirPlus products…"):
    # Show user message immediately
    with st.chat_message("user"):
        st.markdown(question)
    st.session_state.messages.append({"role": "user", "content": question})

    # Call API — spinner wraps the blocking request, render after it exits
    with st.chat_message("assistant", avatar="✈️"):
        response = None
        error_text = None
        with st.spinner("Searching AirPlus knowledge base..."):
            try:
                response = call_ask(question, selected_lang, selected_product)
            except requests.Timeout:
                error_text = "The response is taking longer than expected. Please try again."
            except Exception:
                error_text = "Something went wrong. Please try again."

        if response is not None:
            render_assistant_message(response)
            st.session_state.messages.append({
                "role":       "assistant",
                "confidence": response.get("confidence", "none"),
                "answer":     response.get("answer", ""),
                "sources":    response.get("sources", []),
            })
        else:
            st.markdown(error_text)
            st.session_state.messages.append({
                "role": "assistant", "confidence": "none",
                "answer": error_text, "sources": [],
            })
