#!/usr/bin/env bash
set -euo pipefail

PASS=0
FAIL=0

header() { echo ""; echo "======================================"; echo " $1"; echo "======================================"; }
ok()     { echo "  [PASS] $1"; PASS=$((PASS+1)); }
fail()   { echo "  [FAIL] $1"; echo "         -> $2"; FAIL=$((FAIL+1)); }

header "AirPlus Assist — Demo Readiness Check"

# Check 1: docs/ has at least one non-.gitkeep file
DOCS_DIR="$(cd "$(dirname "$0")/.." && pwd)/docs"
NON_GITKEEP=$(find "$DOCS_DIR" -type f ! -name ".gitkeep" ! -name "*.txt" 2>/dev/null | wc -l | tr -d ' ')
# Also allow urls.txt if it has non-comment lines
URL_LINES=$(grep -cv '^\s*#' "$DOCS_DIR/urls.txt" 2>/dev/null || echo 0)

if [ "$NON_GITKEEP" -gt 0 ] || [ "$URL_LINES" -gt 0 ]; then
  ok "docs/ contains source documents or URLs"
else
  fail "docs/ has no source documents" \
       "Drop PDF/DOCX/XLSX/TXT files into docs/, or add URLs to docs/urls.txt"
fi

# Check 2: chroma Docker volume exists
if docker volume ls --format '{{.Name}}' 2>/dev/null | grep -q 'chroma_data\|airplus.*chroma'; then
  ok "ChromaDB Docker volume exists"
else
  fail "ChromaDB Docker volume not found" \
       "Run 'docker compose up' at least once to create the volume"
fi

# Check 3: Ollama container is running
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'ollama'; then
  ok "Ollama container is running"
else
  fail "Ollama container is not running" \
       "Run 'docker compose up -d ollama' and wait for the health check to pass"
fi

# Summary
echo ""
echo "--------------------------------------"
echo " Results: ${PASS} passed, ${FAIL} failed"
echo "--------------------------------------"

if [ "$FAIL" -gt 0 ]; then
  echo " STATUS: NOT READY FOR DEMO"
  echo ""
  exit 1
else
  echo " STATUS: READY FOR DEMO"
  echo ""
  exit 0
fi
