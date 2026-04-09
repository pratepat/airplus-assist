/**
 * AirPlus Assist — neo-app frontend
 * Vanilla JS, no frameworks.
 */

// ── State ──────────────────────────────────────────────────────────────────────
const state = {
  mode: "chat",          // "chat" | "reply"
  language: "EN",
  product: null,         // null = all, or "airplus_intelligence" | "portal" etc.
  messages: [],          // {role, content, data?}
  isLoading: false,
  summaries: {},         // msg index → null | "loading" | {summary, sources, sources_count}
  analyseResults: null,
  generatedReply: null,
};

// ── Constants ──────────────────────────────────────────────────────────────────
const LANGUAGE_OPTIONS = {
  "🇬🇧 English":    "EN",
  "🇩🇪 Deutsch":    "DE",
  "🇫🇷 Français":   "FR",
  "🇪🇸 Español":    "ES",
  "🇮🇹 Italiano":   "IT",
  "🇳🇱 Nederlands": "NL",
};

const PRODUCT_DISPLAY = {
  airplus_intelligence: "AirPlus Intelligence",
  portal: "Portal",
};

const SCOPE_DISPLAY = {
  all: "All Products",
  airplus_intelligence: "AirPlus Intelligence",
  portal: "Portal",
};

const SOURCE_ICONS = {
  xlsx: "📊", pdf: "📄", url: "🌐", docx: "📝", txt: "📃",
};

const RANK_SYMBOLS = ["", "①", "②", "③", "④", "⑤"];

const META_ANSWERS = {
  how_to_use: {
    triggers: ["how can i use", "how do i use", "how to use", "what is this tool",
               "how does this work", "how does it answer", "what can you do",
               "how do you work", "getting started"],
    answer: `**AirPlus Assist** is an AI-powered FAQ assistant that answers your questions directly from official AirPlus product documentation. Here's how it works:

- Type your question in plain language — no special commands needed
- The assistant searches the knowledge base and finds the most relevant content
- You receive a concise answer with the exact sources it was drawn from
- Click the **📚 Sources** panel below any answer to see which documents were used

**Try asking:**
- *"What is EUR Amount?"*
- *"How do I download my eBilling file?"*
- *"What does MERCHANT_CITY mean?"*
- *"How do I manage user access?"*

Use the **Knowledge Base** filter in the sidebar to focus on a specific product, or leave it on **All Products** for a broader search. Select your **language** from the sidebar — answers will be provided in your chosen language where available.`,
  },
  not_satisfied: {
    triggers: ["not satisfied", "wrong answer", "incorrect", "bad answer",
               "improve", "not happy", "dissatisfied", "answer is wrong",
               "what if i don't", "what to do if"],
    answer: `If an answer doesn't fully address your question, here's what to do:

1. **Check the sources** — Click the 📚 Sources panel below the answer. Each source shows the exact document and page the answer came from. Read the full section for more detail.
2. **Rephrase your question** — Try asking differently. For example, instead of *"Where is fare basis?"* try *"How do I find the fare basis field?"*
3. **Change the knowledge base filter** — If you're searching All Products, try filtering to a specific product using the sidebar.
4. **Go to the source documents** — The source citations show you exactly which document to open. The answer may be part of a larger section that gives more context.

Remember: AirPlus Assist only answers from official documentation. If the information isn't in the knowledge base yet, it will say so honestly rather than guessing.`,
  },
  help_channels: {
    triggers: ["help channel", "support", "contact", "who do i contact", "reach out",
               "raise an incident", "get help", "need help", "help desk", "helpdesk"],
    answer: `If AirPlus Assist cannot answer your question or you need further support:

- **Product questions** — Reach out through the usual channels in your Product Management team
- **Technical issues with this tool** — Raise an incident through the standard IT support process
- **Missing information** — If you believe a document or topic should be in the knowledge base, contact the Product Management team to have it added
- **Urgent queries** — Use your standard escalation path for time-sensitive matters

AirPlus Assist is designed to reduce routine questions, but your teams are always available for complex or escalated issues.`,
  },
  tech_architecture: {
    triggers: ["tech", "technical", "architecture", "how is this built", "technology",
               "under the hood", "how does the ai", "machine learning", "rag", "vector",
               "language model", "llm"],
    answer: `AirPlus Assist is built on a fully local, privacy-first RAG (Retrieval-Augmented Generation) architecture. No data leaves your machine at any point.

**📥 Ingestion pipeline**
Documents (PDF, Word, Excel, URLs) are parsed, chunked into ~512-token segments, and embedded as vectors using \`paraphrase-multilingual-MiniLM-L12-v2\` — a multilingual sentence transformer supporting EN, DE, FR, ES, IT and NL.

**🗄️ Vector store**
Chunks are stored in-memory with full metadata — source file, page number, product, language, and ingestion timestamp.

**🔍 Retrieval**
Top 15 candidates retrieved by cosine similarity → re-ranked by \`cross-encoder/ms-marco-MiniLM-L-6-v2\`. Only the top 3 re-ranked chunks reach the language model.

**🛡️ Hallucination guard**
Two-layer gate: cosine pre-filter + re-ranker score threshold (−0.50). If no chunk scores above the threshold, the LLM is never called.

**🤖 Language model**
Runs locally via **Ollama**. Temperature 0.1 for maximum factual consistency.

**🏗️ Infrastructure**
Single Python process — no Docker, no separate services. Just \`uvicorn app.main:app\`.`,
    showDiagram: true,
  },
};

// ── DOM refs (populated after DOMContentLoaded) ────────────────────────────────
let $messages, $chatInput, $sendBtn, $chatView, $replyView, $welcome;

// ── Simple Markdown renderer ───────────────────────────────────────────────────
function renderMarkdown(text) {
  if (!text) return "";
  let html = escHtml(text);

  // Code blocks
  html = html.replace(/```[\w]*\n?([\s\S]*?)```/g, (_, c) =>
    `<pre><code>${c.trim()}</code></pre>`);

  // Inline code
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  // Italic
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");

  // Headers
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm,  "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm,   "<h1>$1</h1>");

  // Ordered list items
  html = html.replace(/^\d+\. (.+)$/gm, "<li>$1</li>");
  html = html.replace(/((<li>.*<\/li>\n?)+)/g, "<ol>$1</ol>");

  // Unordered list items (after ordered, so - isn't caught twice)
  html = html.replace(/^[-•] (.+)$/gm, "<li>$1</li>");
  html = html.replace(/((?:<li>(?!.*<\/ol>).*<\/li>\n?)+)(?!<\/ol>)/g, (match) => {
    if (match.includes("<ol>")) return match;
    return `<ul>${match}</ul>`;
  });

  // Paragraphs: double newlines
  html = html.replace(/\n\n+/g, "</p><p>");
  html = "<p>" + html + "</p>";

  // Single newlines inside paragraphs
  html = html.replace(/(?<!>)\n(?!<)/g, "<br>");

  // Clean up empty paragraphs
  html = html.replace(/<p><\/p>/g, "");
  html = html.replace(/<p>(<(?:h[1-3]|ul|ol|pre)[^>]*>)/g, "$1");
  html = html.replace(/(<\/(?:h[1-3]|ul|ol|pre)>)<\/p>/g, "$1");

  return html;
}

function escHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// ── Badge helpers ──────────────────────────────────────────────────────────────
function productBadge(product) {
  if (product === "airplus_intelligence")
    return `<span class="badge badge-product-ai">AirPlus Intelligence</span>`;
  if (product === "portal")
    return `<span class="badge badge-product-portal">Portal</span>`;
  const label = product ? (PRODUCT_DISPLAY[product] || product) : "";
  return label ? `<span class="badge badge-product-other">${escHtml(label)}</span>` : "";
}

function confidenceBadge(conf) {
  const map = {
    high:   ["badge-high",   "● High"],
    medium: ["badge-medium", "◐ Medium"],
    low:    ["badge-low",    "○ Low"],
  };
  const [cls, text] = map[conf] || map.medium;
  return `<span class="badge ${cls}">${text}</span>`;
}

// ── Source card HTML ───────────────────────────────────────────────────────────
function primaryCardHTML(source, hasContradiction) {
  const icon     = SOURCE_ICONS[source.source_type] || "📄";
  const rankSym  = RANK_SYMBOLS[source.rank] || source.rank;
  const rankCls  = hasContradiction ? "rank-warn" : "rank-ok";
  const cardCls  = hasContradiction ? "primary-warn" : "primary-ok";
  const excerpt  = escHtml((source.excerpt || "").slice(0, 200));
  const link     = source.url
    ? `<a class="card-link" href="${escHtml(source.url)}" target="_blank" rel="noopener">🔗 Open source →</a>`
    : "";

  return `
<div class="source-card ${cardCls}">
  <div class="card-top">
    <div class="card-title">
      <span class="card-rank ${rankCls}">${rankSym}</span>
      <span class="card-label">${icon} ${escHtml(source.label || "")}</span>
    </div>
    <div class="card-badges">
      ${productBadge(source.product)}
      ${confidenceBadge(source.confidence)}
    </div>
  </div>
  <div class="card-excerpt">${excerpt}</div>
  ${link}
</div>`;
}

function furtherCardHTML(source) {
  const icon    = SOURCE_ICONS[source.source_type] || "📄";
  const rankSym = RANK_SYMBOLS[source.rank] || source.rank;
  const snippet = escHtml((source.excerpt || "").slice(0, 150)) + (source.excerpt && source.excerpt.length > 150 ? "…" : "");
  const link    = source.url
    ? `<a class="card-link" href="${escHtml(source.url)}" target="_blank" rel="noopener">🔗 Open source →</a>`
    : "";

  return `
<div class="source-card further">
  <div class="card-top">
    <div class="card-title">
      <span class="card-rank rank-gray">${rankSym}</span>
      <span class="card-label">${icon} ${escHtml(source.label || "")}</span>
    </div>
    <div class="card-badges">
      ${productBadge(source.product)}
      ${confidenceBadge(source.confidence)}
    </div>
  </div>
  <div class="card-excerpt">${snippet}</div>
  ${link}
</div>`;
}

// ── Render a single assistant message ─────────────────────────────────────────
function renderAssistantMessage(data, msgIndex, container) {
  const {
    answer = "", confidence = "none", sources = [], has_contradiction = false,
    product_scope = "all", response_time,
  } = data;

  let html = "";

  // Confidence pill
  if (confidence === "high")
    html += `<div class="confidence-pill high">● High confidence</div>`;
  else if (confidence === "medium")
    html += `<div class="confidence-pill medium">● Sources found</div>`;
  else if (confidence === "low")
    html += `<div class="confidence-pill low">● Low confidence</div>`;

  // Contradiction banner
  if (has_contradiction) {
    html += `<div class="contradiction-banner">
      ⚠️ <strong>Multiple sources found with differing information.</strong>
      Review all citations below for the complete picture.
    </div>`;
  }

  // Scope
  const scopeLabel = SCOPE_DISPLAY[product_scope] || "All Products";
  html += `<div class="scope-indicator">🔍 Searched: ${escHtml(scopeLabel)}</div>`;

  // Answer text (rendered as markdown)
  html += `<div class="answer-text md-render">${renderMarkdown(answer)}</div>`;

  // No-answer hint
  if (confidence === "none") {
    html += `<div class="no-answer-hint">💡 Try rephrasing your question or selecting a different knowledge base filter.</div>`;
    if (response_time != null)
      html += `<div class="response-time">Answered in ${Math.round(response_time)}s</div>`;
    container.innerHTML = html;
    return;
  }

  // Summary button placeholder (injected after render)
  html += `<div class="summary-area" id="summary-area-${msgIndex}"></div>`;

  // Sources
  if (sources && sources.length > 0) {
    const hasHighConf = sources.some(s => s.confidence === "high");
    const primary = hasHighConf ? sources.slice(0, 2) : sources;
    const further = hasHighConf ? sources.slice(2) : [];

    html += `<div class="sources-header">PRIMARY SOURCES</div>`;
    for (const src of primary) {
      html += primaryCardHTML(src, has_contradiction);
    }

    if (!hasHighConf) {
      html += `<div style="font-size:12px;color:#9CA3AF;margin-top:4px;">
        No high-confidence sources found — verify answers against original documents.
      </div>`;
    }

    if (further.length > 0) {
      html += `<details class="further-toggle">
        <summary>📖 Further reading — ${further.length} additional source(s)</summary>
        <div class="further-toggle-body">
          <p style="margin-bottom:10px;">These sources contain related information that may help if the answer above doesn't fully address your question.</p>
          ${further.map(s => furtherCardHTML(s)).join("")}
        </div>
      </details>`;
    }
  }

  // Response time
  if (response_time != null)
    html += `<div class="response-time">Answered in ${Math.round(response_time)}s</div>`;

  container.innerHTML = html;

  // Wire up summary button after DOM insert
  wireUpSummaryButton(msgIndex, data);

  // Fallback banner for product filter miss
  if ((confidence === "none" || confidence === "low") && state.product) {
    const productLabel = PRODUCT_DISPLAY[state.product] || state.product;
    const banner = document.createElement("div");
    banner.className = "fallback-banner";
    banner.innerHTML = `
      <span>🔍 Not finding what you need in ${escHtml(productLabel)}?</span>
      <button class="btn btn-sm btn-secondary" onclick="retryAllProducts()">Search in All Products →</button>
    `;
    container.appendChild(banner);
  }
}

// ── Meta answer rendering ──────────────────────────────────────────────────────
function renderMetaMessage(meta, container) {
  let html = `<div class="confidence-pill meta">● AirPlus Assist</div>`;
  html += `<div class="answer-text md-render">${renderMarkdown(meta.answer)}</div>`;

  if (meta.showDiagram) {
    html += `<div class="arch-diagram">
      <div class="arch-label">SYSTEM ARCHITECTURE</div>
      <div>
        <span style="color:#6B7280;">📁 docs/</span>
        <span style="color:#9CA3AF;"> ──────────────────────────────────────┐</span><br>
        <span style="color:#6B7280;">&nbsp;&nbsp; PDF · Excel · Word · URLs</span>
        <span style="color:#9CA3AF;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│</span><br>
        <span style="color:#9CA3AF;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;▼</span><br>
        <span class="tag-green">Ingest Pipeline</span>
        <span style="color:#9CA3AF;"> → chunk → embed → </span>
        <span class="tag-blue">In-Memory Store</span><br>
        <br>
        <span style="color:#9CA3AF;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│</span><br>
        <span style="color:#9CA3AF;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;┌──────────────────────────┘</span><br>
        <span style="color:#9CA3AF;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│ top 15 by cosine similarity</span><br>
        <span style="color:#9CA3AF;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;▼</span><br>
        <span style="color:#6B7280;">🧑 Question</span>
        <span style="color:#9CA3AF;"> ──► </span>
        <span class="tag-green">FastAPI</span>
        <span style="color:#9CA3AF;"> ──► </span>
        <span class="tag-amber">Re-ranker</span>
        <span style="color:#9CA3AF;"> ──► </span>
        <span class="tag-pink">Ollama</span>
        <span style="color:#9CA3AF;"> ──► </span>
        <span class="tag-answer">Answer + Sources</span>
      </div>
      <div class="arch-footer">🔒 Fully local · No external APIs · No data leaves your machine</div>
    </div>`;
  }

  container.innerHTML = html;
}

// ── Summary feature ────────────────────────────────────────────────────────────
function wireUpSummaryButton(msgIndex, data) {
  const area = document.getElementById(`summary-area-${msgIndex}`);
  if (!area) return;

  const cached = state.summaries[msgIndex];
  if (cached === undefined || cached === null) {
    // Show button
    const btn = document.createElement("button");
    btn.className = "btn btn-secondary btn-sm";
    btn.style.marginBottom = "8px";
    btn.textContent = "📋 Generate Complete Summary";
    btn.onclick = () => {
      state.summaries[msgIndex] = "loading";
      loadSummary(msgIndex, data);
    };
    area.appendChild(btn);
  } else if (cached === "loading") {
    area.innerHTML = `<div class="progress-box">
      <div class="progress-stage current"><span class="spinner">⟳</span> 🔍 Building comprehensive summary…</div>
    </div>`;
  } else {
    renderSummary(area, cached, msgIndex, data);
  }
}

function renderSummary(area, summaryData, msgIndex, data) {
  const { summary, sources = [], sources_count = 0 } = summaryData;
  const primary = sources.slice(0, 2);
  const further = sources.slice(2);

  let html = `<details open class="further-toggle" style="margin-top:8px;">
    <summary>📋 Complete Summary (${sources_count} sources)</summary>
    <div class="further-toggle-body">
      <div class="summary-box">
        <div class="summary-note">📖 <strong>Complete Summary</strong> — synthesised from ${sources_count} sources · wider retrieval than answer</div>
        <div class="summary-text md-render">${renderMarkdown(summary)}</div>
      </div>`;

  if (sources.length > 0) {
    html += `<div class="sources-header">SUMMARY SOURCES</div>`;
    for (const src of primary) html += primaryCardHTML(src, false);
    if (further.length > 0) {
      html += `<details class="further-toggle">
        <summary>📖 ${further.length} more source(s)</summary>
        <div class="further-toggle-body">${further.map(s => furtherCardHTML(s)).join("")}</div>
      </details>`;
    }
  }

  html += `<div style="text-align:right;margin-top:8px;">
    <button class="btn btn-secondary btn-sm" onclick="regenSummary(${msgIndex})">🔄 Regenerate</button>
  </div>
  </div></details>`;

  area.innerHTML = html;
}

async function loadSummary(msgIndex, data) {
  const area = document.getElementById(`summary-area-${msgIndex}`);
  if (!area) return;

  area.innerHTML = `<div class="progress-box">
    <div class="progress-stage current"><span class="spinner">⟳</span> 🔍 Building comprehensive summary…</div>
  </div>`;

  const question = data.original_question || data.last_question || "";
  const language = data.language || "EN";
  const product  = data.product_scope === "all" ? null : data.product_scope;

  try {
    const resp = await fetch("/api/summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, product, language }),
    });
    const result = await resp.json();
    state.summaries[msgIndex] = result;
    renderSummary(area, result, msgIndex, data);
  } catch (e) {
    area.innerHTML = `<div class="no-answer-hint">⚠️ Summary generation failed. Please try again.</div>`;
    state.summaries[msgIndex] = null;
  }
}

window.regenSummary = function(msgIndex) {
  state.summaries[msgIndex] = "loading";
  // Reload from stored message data
  const msgData = state.messages.filter(m => m.role === "assistant")[msgIndex];
  if (msgData) loadSummary(msgIndex, msgData.data);
};

// ── Render all messages ────────────────────────────────────────────────────────
function renderMessages() {
  const assistantIdx = { count: 0 };

  // Show/hide welcome
  const $w = document.getElementById("welcome");
  if ($w) $w.style.display = state.messages.length === 0 ? "flex" : "none";

  // Remove all rendered messages (keep #welcome)
  const existing = $messages.querySelectorAll(".msg");
  existing.forEach(el => el.remove());

  for (const msg of state.messages) {
    const wrap = document.createElement("div");
    wrap.className = `msg ${msg.role}`;

    const avatar = document.createElement("div");
    avatar.className = `avatar ${msg.role}`;
    avatar.textContent = msg.role === "user" ? "👤" : "🤖";

    const body = document.createElement("div");
    body.className = "msg-body";

    if (msg.role === "user") {
      body.innerHTML = `<div class="user-bubble">${escHtml(msg.content)}</div>`;
    } else if (msg.role === "assistant") {
      const idx = assistantIdx.count++;
      body.className = "msg-body assistant-content";
      if (msg.meta) {
        renderMetaMessage(msg.data, body);
      } else {
        renderAssistantMessage(msg.data, idx, body);
      }
    }

    wrap.appendChild(avatar);
    wrap.appendChild(body);
    $messages.appendChild(wrap);
  }

  // Scroll to bottom
  $messages.scrollTop = $messages.scrollHeight;
}

// ── Progress indicator for streaming ──────────────────────────────────────────
function renderProgressBox(stages, elapsed, model) {
  const rows = stages.map(([icon, text], i) => {
    const isCurrent = i === stages.length - 1;
    const cls   = isCurrent ? "current" : "done";
    const sym   = isCurrent ? `<span class="spinner">⟳</span> ` : "✓ ";
    return `<div class="progress-stage ${cls}">${sym}${icon} ${escHtml(text)}</div>`;
  }).join("");

  return `<div class="progress-box">
    ${rows}
    <div class="progress-footer">⏱ ${elapsed}s · ${escHtml(model)}</div>
  </div>`;
}

// ── Send a question ────────────────────────────────────────────────────────────
async function sendQuestion(question) {
  if (!question.trim() || state.isLoading) return;
  question = question.trim();

  // Push user message
  state.messages.push({ role: "user", content: question });
  renderMessages();
  state.isLoading = true;
  updateInputState();

  // Check meta answers first
  const qLower = question.toLowerCase();
  let metaKey = null;
  for (const [key, meta] of Object.entries(META_ANSWERS)) {
    if (meta.triggers.some(t => qLower.includes(t))) { metaKey = key; break; }
  }

  if (metaKey) {
    // Instant meta answer — no API call
    const meta = META_ANSWERS[metaKey];
    state.messages.push({ role: "assistant", content: "", meta: true, data: meta });
    state.isLoading = false;
    updateInputState();
    renderMessages();
    return;
  }

  // Show streaming progress in a temp element
  const tempWrap = document.createElement("div");
  tempWrap.className = "msg assistant";
  const tempAvatar = document.createElement("div");
  tempAvatar.className = "avatar assistant";
  tempAvatar.textContent = "🤖";
  const tempBody = document.createElement("div");
  tempBody.className = "msg-body assistant-content";
  tempWrap.appendChild(tempAvatar);
  tempWrap.appendChild(tempBody);
  $messages.appendChild(tempWrap);
  $messages.scrollTop = $messages.scrollHeight;

  const startTime = Date.now();
  const stages = [];
  let finalResult = null;

  try {
    const resp = await fetch("/api/ask/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        product:  state.product,
        language: state.language,
      }),
    });

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer    = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        try {
          const evt = JSON.parse(line.slice(6));
          if (evt.stage === "complete") {
            finalResult = evt.result;
          } else if (evt.stage === "error") {
            throw new Error(evt.message || "Stream error");
          } else {
            stages.push([evt.icon || "⏳", evt.message || evt.stage]);
            const elapsed = ((Date.now() - startTime) / 1000).toFixed(0);
            // Get model from window (injected by template)
            const model = window.OLLAMA_MODEL || "";
            tempBody.innerHTML = renderProgressBox(stages, elapsed, model);
            $messages.scrollTop = $messages.scrollHeight;
          }
        } catch (parseErr) {
          if (parseErr.message !== "Stream error") continue;
          throw parseErr;
        }
      }
    }
  } catch (err) {
    console.error("Stream error:", err);
    finalResult = {
      answer: "⚠️ Could not reach the AirPlus Assist API. " + (err.message || ""),
      confidence: "none",
      product_scope: state.product || "all",
      language: state.language,
      original_question: question,
      retrieved_with: question,
      sources: [],
      has_contradiction: false,
    };
  }

  // Remove temp element
  tempWrap.remove();

  if (finalResult) {
    const elapsed = (Date.now() - startTime) / 1000;
    finalResult.response_time = elapsed;
    finalResult.last_question  = question;
    state.messages.push({ role: "assistant", content: "", data: finalResult });
    state.summaries[state.messages.filter(m => m.role === "assistant").length - 1] = null;
  }

  state.isLoading = false;
  updateInputState();
  renderMessages();
}

window.retryAllProducts = function() {
  const lastUser = [...state.messages].reverse().find(m => m.role === "user");
  if (!lastUser) return;
  // Temporarily clear product filter
  const prevProduct = state.product;
  state.product = null;
  document.getElementById("product-select").value = "";
  sendQuestion(lastUser.content).then(() => {
    // restore if needed — user can re-select
  });
};

// ── Draft Reply mode ───────────────────────────────────────────────────────────
async function analyseText() {
  const text = document.getElementById("email-input").value.trim();
  if (!text || text.length > 5000) return;

  const btn = document.getElementById("analyse-btn");
  btn.disabled = true;
  btn.textContent = "⏳ Analysing…";

  const resultsDiv = document.getElementById("analysis-results");
  resultsDiv.innerHTML = `<div class="progress-box">
    <div class="progress-stage current"><span class="spinner">⟳</span> 🔍 Extracting and answering questions…</div>
  </div>`;

  try {
    const resp = await fetch("/api/analyse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        product:       state.product,
        language:      state.language,
        max_questions: 5,
      }),
    });
    const data = await resp.json();
    state.analyseResults = data;
    state.generatedReply = null;
    renderAnalysisResults(data, text);
  } catch (e) {
    resultsDiv.innerHTML = `<div class="no-answer-hint">⚠️ Analysis failed: ${escHtml(e.message)}</div>`;
  }

  btn.disabled = false;
  btn.textContent = "🔍 Find Answers";
}

function renderAnalysisResults(data, originalText) {
  const { questions_found, results = [], processing_time_seconds } = data;
  const resultsDiv = document.getElementById("analysis-results");

  if (questions_found === 0) {
    resultsDiv.innerHTML = `<div class="no-answer-hint">No distinct questions found in the text. Try pasting an email or message with clear questions.</div>`;
    return;
  }

  const answered = results.filter(r => r.answered);
  let html = `<div class="analysis-banner">
    ✅ Found ${questions_found} question(s) · Processed in ${processing_time_seconds}s
  </div>`;

  for (const r of results) {
    const icon = r.answered ? "✅" : "⚠️";
    html += `<div class="question-block">
      <div class="question-header">${icon} QUESTION ${r.question_number} OF ${results.length}</div>
      <input class="question-text-input" type="text" value="${escHtml(r.question)}"
             id="q-text-${r.question_number}" />
      ${r.answered
        ? `${r.confidence === "high"
            ? `<div class="confidence-pill high" style="margin-bottom:6px;">● High confidence</div>`
            : `<div class="confidence-pill medium" style="margin-bottom:6px;">● Sources found</div>`}
          <div class="question-answer md-render">${renderMarkdown(r.answer)}</div>
          ${r.sources.length > 0
            ? `<details class="further-toggle">
                <summary>📚 ${r.sources.length} source(s)</summary>
                <div class="further-toggle-body">
                  ${r.sources.slice(0,2).map(s => primaryCardHTML(s, false)).join("")}
                </div>
               </details>` : ""}
          `
        : `<div class="no-answer-box">⚠️ This question could not be answered from the knowledge base.</div>
           <button class="btn btn-secondary btn-sm" style="margin-top:8px;"
             onclick="reanswer(${r.question_number})">🔄 Re-answer question ${r.question_number}</button>`}
    </div>`;
  }

  if (answered.length > 0) {
    html += `<div style="margin-top:16px;">`;
    const unanswered = results.filter(r => !r.answered);
    if (unanswered.length > 0) {
      html += `<div class="no-answer-box" style="margin-bottom:12px;">
        ⚠️ ${unanswered.length} question(s) could not be answered and will not be included in the reply.
      </div>`;
    }
    html += `<button class="btn btn-primary" onclick="generateReply()">
      ✅ Accept ${answered.length} answered question(s) &amp; Generate Reply
    </button></div>`;
  } else {
    html += `<div class="no-answer-box" style="margin-top:12px;">No questions were answered from the knowledge base. Cannot generate a reply.</div>`;
  }

  resultsDiv.innerHTML = html;

  // Wire up reanswer
  window._originalText = originalText;
}

window.reanswer = async function(questionNumber) {
  const input = document.getElementById(`q-text-${questionNumber}`);
  const question = input ? input.value : "";
  if (!question || !state.analyseResults) return;

  const result = state.analyseResults.results.find(r => r.question_number === questionNumber);
  if (!result) return;

  try {
    const resp = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, product: state.product, language: state.language }),
    });
    const data = await resp.json();
    result.question = question;
    result.answer = data.answer;
    result.confidence = data.confidence;
    result.sources = data.sources || [];
    result.answered = data.confidence !== "none";
    renderAnalysisResults(state.analyseResults, window._originalText || "");
  } catch (e) {
    showToast("Re-answer failed: " + e.message);
  }
};

window.generateReply = async function() {
  if (!state.analyseResults) return;

  const results = state.analyseResults.results;
  // Read any edited questions
  for (const r of results) {
    const input = document.getElementById(`q-text-${r.question_number}`);
    if (input) r.question = input.value;
  }

  const answered = results.filter(r => r.answered);
  const btn = document.querySelector("#analysis-results .btn-primary");
  if (btn) { btn.disabled = true; btn.textContent = "⏳ Generating…"; }

  try {
    const resp = await fetch("/api/generate_reply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        original_text:    window._originalText || "",
        answered_results: answered,
        language:         state.language,
      }),
    });
    const data = await resp.json();
    state.generatedReply = data;
    renderGeneratedReply(data);
  } catch (e) {
    showToast("Reply generation failed: " + e.message);
    if (btn) { btn.disabled = false; btn.textContent = "✅ Generate Reply"; }
  }
};

function renderGeneratedReply(data) {
  const { reply, questions_included, questions_excluded } = data;

  const replyDiv = document.getElementById("generated-reply");
  replyDiv.innerHTML = `
    <div class="reply-box">
      <div class="reply-box-header">
        <div>
          <div class="reply-box-title">✉️ Generated Reply</div>
          <div class="reply-box-sub">Review and edit before sending</div>
        </div>
        <div style="display:flex;gap:8px;">
          <button class="btn btn-secondary btn-sm" onclick="copyReply()">📋 Copy</button>
          <button class="btn btn-secondary btn-sm" onclick="openMail()">📧 Open in Mail</button>
          <button class="btn btn-secondary btn-sm" onclick="regenReply()">🔄 Regenerate</button>
        </div>
      </div>
      <textarea id="reply-textarea" rows="12">${escHtml(reply)}</textarea>
      <div class="reply-disclaimer">
        This reply was generated from AirPlus documentation. ${questions_excluded} question(s) excluded.
        Always review before sending.
      </div>
    </div>`;

  replyDiv.scrollIntoView({ behavior: "smooth" });
}

window.copyReply = function() {
  const ta = document.getElementById("reply-textarea");
  if (!ta) return;
  navigator.clipboard.writeText(ta.value).then(() => showToast("Copied to clipboard"));
};

window.openMail = function() {
  const ta = document.getElementById("reply-textarea");
  if (!ta) return;
  window.location.href = `mailto:?body=${encodeURIComponent(ta.value)}`;
};

window.regenReply = function() {
  window.generateReply();
};

// ── Sidebar controls ───────────────────────────────────────────────────────────
function switchMode(mode) {
  state.mode = mode;
  document.querySelectorAll(".mode-btn").forEach(b => b.classList.toggle("active", b.dataset.mode === mode));
  document.getElementById("chat-view").classList.toggle("active", mode === "chat");
  document.getElementById("reply-view").classList.toggle("active", mode === "reply");
}

function updateInputState() {
  if ($sendBtn) $sendBtn.disabled = state.isLoading;
  if ($chatInput) $chatInput.disabled = state.isLoading;
}

// ── Toast ──────────────────────────────────────────────────────────────────────
function showToast(msg, dur = 3000) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), dur);
}

// ── Init ───────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  $messages  = document.getElementById("messages");
  $chatInput = document.getElementById("chat-input");
  $sendBtn   = document.getElementById("send-btn");
  $chatView  = document.getElementById("chat-view");
  $replyView = document.getElementById("reply-view");

  // Mode buttons
  document.querySelectorAll(".mode-btn").forEach(btn => {
    btn.addEventListener("click", () => switchMode(btn.dataset.mode));
  });

  // Language select
  const langSel = document.getElementById("language-select");
  if (langSel) {
    langSel.addEventListener("change", () => {
      state.language = langSel.value;
      if (state.messages.length > 0) showToast(`Language set to ${langSel.value} — applies to new questions`);
    });
  }

  // Product select
  const prodSel = document.getElementById("product-select");
  if (prodSel) {
    prodSel.addEventListener("change", () => {
      state.product = prodSel.value || null;
    });
  }

  // Clear conversation
  const clearBtn = document.getElementById("clear-btn");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      state.messages = [];
      state.summaries = {};
      renderMessages();
    });
  }

  // Chat input
  if ($chatInput) {
    $chatInput.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        const q = $chatInput.value.trim();
        if (q) { $chatInput.value = ""; sendQuestion(q); }
      }
    });
  }

  // Send button
  if ($sendBtn) {
    $sendBtn.addEventListener("click", () => {
      const q = $chatInput.value.trim();
      if (q) { $chatInput.value = ""; sendQuestion(q); }
    });
  }

  // Suggestion buttons
  document.querySelectorAll(".suggestion-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      sendQuestion(btn.dataset.question);
    });
  });

  // Analyse button
  const analyseBtn = document.getElementById("analyse-btn");
  if (analyseBtn) {
    analyseBtn.addEventListener("click", analyseText);
  }

  // Clear reply button
  const clearReplyBtn = document.getElementById("clear-reply-btn");
  if (clearReplyBtn) {
    clearReplyBtn.addEventListener("click", () => {
      document.getElementById("email-input").value = "";
      document.getElementById("analysis-results").innerHTML = "";
      document.getElementById("generated-reply").innerHTML = "";
      state.analyseResults = null;
      state.generatedReply = null;
      updateCharCounter();
    });
  }

  // Char counter
  const emailInput = document.getElementById("email-input");
  if (emailInput) {
    emailInput.addEventListener("input", updateCharCounter);
  }

  // Initial render
  renderMessages();
});

function updateCharCounter() {
  const emailInput = document.getElementById("email-input");
  const counter    = document.getElementById("char-counter");
  const analyseBtn = document.getElementById("analyse-btn");
  if (!emailInput || !counter) return;

  const len = emailInput.value.length;
  counter.textContent = `${len} / 5000`;
  counter.className = len > 5000 ? "char-counter over" : "char-counter";
  if (analyseBtn) analyseBtn.disabled = len === 0 || len > 5000;
}
