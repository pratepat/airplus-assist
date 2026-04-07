"""
AirPlus Assist — Regression Test Suite
=======================================
Run before every demo to verify the full stack is working correctly.
Requires: docker compose up (all services running)

Usage:
    python tests/regression_tests.py

Exit code 0 = all passed, 1 = one or more failures.
"""

import json
import sys
import time

import requests

# ── Configuration ─────────────────────────────────────────────────────────────

API_BASE = "http://localhost:8001"
UI_BASE  = "http://localhost:8501"
TIMEOUT  = 300  # seconds — mistral:7b can be slow under sustained load


# ── Helpers ───────────────────────────────────────────────────────────────────

_RETRY_WAIT   = 5   # seconds between recovery polls
_RECOVERY_MAX = 60  # seconds to wait for API to come back after a crash


def _wait_for_api():
    """Block until /health returns 200, or raise after _RECOVERY_MAX seconds."""
    deadline = time.time() + _RECOVERY_MAX
    while time.time() < deadline:
        try:
            r = requests.get(f"{API_BASE}/health", timeout=5)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(_RETRY_WAIT)
    raise RuntimeError(f"API did not recover within {_RECOVERY_MAX}s")


def _get(path: str, **kwargs):
    try:
        return requests.get(f"{API_BASE}{path}", timeout=TIMEOUT, **kwargs)
    except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError):
        _wait_for_api()
        return requests.get(f"{API_BASE}{path}", timeout=TIMEOUT, **kwargs)


def _post(path: str, body: dict, **kwargs):
    try:
        return requests.post(
            f"{API_BASE}{path}",
            json=body,
            timeout=TIMEOUT,
            **kwargs,
        )
    except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError):
        _wait_for_api()
        return requests.post(
            f"{API_BASE}{path}",
            json=body,
            timeout=TIMEOUT,
            **kwargs,
        )


def _ask(body: dict):
    """POST /ask and return parsed JSON dict."""
    r = _post("/ask", body)
    r.raise_for_status()
    return r.json()


# ── Section 1 — API Health ────────────────────────────────────────────────────

def api_health():
    t0 = time.time()
    r = _get("/health")
    elapsed = time.time() - t0
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    data = r.json()
    if data.get("status") != "ok":
        return False, f"status != 'ok': {data.get('status')}"
    if "model" not in data:
        return False, "missing 'model' key"
    if "collection" not in data:
        return False, "missing 'collection' key"
    if elapsed >= 5:
        return False, f"response took {elapsed:.1f}s (> 5s)"
    return True, ""


def api_products():
    r = _get("/products")
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    data = r.json()
    if "products" not in data:
        return False, "missing 'products' key"
    products = data["products"]
    if "airplus_intelligence" not in products:
        return False, "'airplus_intelligence' not in products"
    if "portal" not in products:
        return False, "'portal' not in products"
    if len(products) < 2:
        return False, f"expected >= 2 products, got {len(products)}"
    return True, ""


def api_languages():
    r = _get("/languages")
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    data = r.json()
    if "languages" not in data:
        return False, "missing 'languages' key"
    langs = data["languages"]
    for code in ("EN", "DE", "FR"):
        if code not in langs:
            return False, f"'{code}' not in languages"
    return True, ""


# ── Section 2 — Hallucination Guard (must BLOCK) ──────────────────────────────

def gate_blocks_capital_of_france():
    data = _ask({"question": "What is the capital of France?", "language": "EN"})
    if data.get("confidence") != "none":
        return False, "Hallucination guard failed — out-of-domain question was answered"
    if data.get("sources") != []:
        return False, "Hallucination guard failed — out-of-domain question was answered"
    answer = data.get("answer", "")
    if "don't have enough information" not in answer.lower():
        return False, "Hallucination guard failed — out-of-domain question was answered"
    return True, ""


def gate_blocks_ceo_of_apple():
    data = _ask({"question": "Who is the CEO of Apple?", "language": "EN"})
    if data.get("confidence") != "none":
        return False, "Hallucination guard failed — out-of-domain question was answered"
    if data.get("sources") != []:
        return False, "Hallucination guard failed — out-of-domain question was answered"
    return True, ""


def gate_blocks_unrelated_personal_question():
    data = _ask({"question": "What is the weather like today?", "language": "EN"})
    if data.get("confidence") != "none":
        return False, "Hallucination guard failed — personal/weather question was answered"
    return True, ""


# ── Section 3 — Domain Questions (must PASS with answer) ──────────────────────

def domain_merchant_city_en():
    data = _ask({"question": "What does MERCHANT_CITY mean?", "language": "EN"})
    if data.get("confidence") not in ("high", "medium"):
        return False, "Core domain question not answered"
    sources = data.get("sources", [])
    if len(sources) < 1:
        return False, "Core domain question not answered"
    if "don't have enough information" in data.get("answer", "").lower():
        return False, "Core domain question not answered"
    if not any(s.get("source_type") == "xlsx" for s in sources):
        return False, "Core domain question not answered"
    return True, ""


def domain_eur_amount_en():
    data = _ask({"question": "What is EUR Amount?", "language": "EN"})
    if data.get("confidence") not in ("high", "medium"):
        return False, "EUR Amount question not answered"
    sources = data.get("sources", [])
    if len(sources) < 1:
        return False, "EUR Amount question not answered"
    if "don't have enough information" in data.get("answer", "").lower():
        return False, "EUR Amount question not answered"
    return True, ""


def domain_ebilling_download():
    data = _ask({"question": "How do I download my eBilling file?", "language": "EN"})
    if data.get("confidence") not in ("high", "medium"):
        return False, "eBilling download question not answered or no PDF source cited"
    sources = data.get("sources", [])
    if len(sources) < 1:
        return False, "eBilling download question not answered or no PDF source cited"
    if not any(s.get("source_type") == "pdf" for s in sources):
        return False, "eBilling download question not answered or no PDF source cited"
    return True, ""


def domain_fare_basis():
    data = _ask({"question": "What is fare basis?", "language": "EN"})
    if data.get("confidence") not in ("high", "medium"):
        return False, "Fare basis question not answered or wrong source cited"
    sources = data.get("sources", [])
    if len(sources) < 1:
        return False, "Fare basis question not answered or wrong source cited"
    if not any("FLIGHT_COUPON_FARE_BASIS" in s.get("label", "") for s in sources):
        return False, "Fare basis question not answered or wrong source cited"
    return True, ""


def domain_where_fare_basis():
    data = _ask({"question": "Where can I find fare basis?", "language": "EN"})
    if data.get("confidence") not in ("high", "medium"):
        return False, "Navigational fare basis question not answered or attribute_information not cited"
    sources = data.get("sources", [])
    if len(sources) < 1:
        return False, "Navigational fare basis question not answered or attribute_information not cited"
    if not any("attribute_information" in s.get("label", "").lower() for s in sources):
        return False, "Navigational fare basis question not answered or attribute_information not cited"
    return True, ""


def domain_user_management():
    data = _ask({"question": "How do I manage user access?", "language": "EN"})
    if data.get("confidence") not in ("high", "medium"):
        return False, "User management question not answered"
    sources = data.get("sources", [])
    if len(sources) < 1:
        return False, "User management question not answered"
    return True, ""


# ── Section 4 — Product Scoping ───────────────────────────────────────────────

def product_scope_portal_enforced():
    data = _ask({"question": "What is EUR Amount?", "language": "EN", "product": "portal"})
    if data.get("product_scope") != "portal":
        return False, "Product scope not enforced — non-portal sources returned for portal query"
    sources = data.get("sources", [])
    if data.get("confidence") != "none":
        if not all(s.get("product") == "portal" for s in sources):
            return False, "Product scope not enforced — non-portal sources returned for portal query"
    return True, ""


def product_scope_airplus_intelligence():
    data = _ask({
        "question": "What does MERCHANT_CITY mean?",
        "language": "EN",
        "product": "airplus_intelligence",
    })
    if data.get("product_scope") != "airplus_intelligence":
        return False, "AirPlus Intelligence scope not enforced"
    if data.get("confidence") not in ("high", "medium"):
        return False, "AirPlus Intelligence scope not enforced"
    sources = data.get("sources", [])
    if not all(s.get("product") == "airplus_intelligence" for s in sources):
        return False, "AirPlus Intelligence scope not enforced"
    return True, ""


def product_scope_all_products():
    data = _ask({"question": "What does MERCHANT_CITY mean?", "language": "EN"})
    if data.get("product_scope") != "all":
        return False, "All Products scope not working"
    if data.get("confidence") not in ("high", "medium"):
        return False, "All Products scope not working"
    return True, ""


# ── Section 5 — Multilingual Pipeline ────────────────────────────────────────

def multilingual_german_excel():
    data = _ask({"question": "Was bedeutet MERCHANT_CITY?", "language": "DE"})
    if data.get("confidence") not in ("high", "medium"):
        return False, "German multilingual query failed"
    if data.get("retrieved_with") == data.get("original_question"):
        return False, "German multilingual query failed"
    if data.get("language") != "DE":
        return False, "German multilingual query failed"
    sources = data.get("sources", [])
    if len(sources) < 1:
        return False, "German multilingual query failed"
    german_words = ["händler", "stadt", "ort", "betrag", "de:"]
    answer = data.get("answer", "").lower()
    if not any(w in answer for w in german_words):
        return False, "German multilingual query failed"
    return True, ""


def multilingual_french_excel():
    data = _ask({"question": "Que signifie MERCHANT_CITY?", "language": "FR"})
    if data.get("confidence") not in ("high", "medium"):
        return False, "French multilingual query failed"
    if data.get("language") != "FR":
        return False, "French multilingual query failed"
    if data.get("retrieved_with") == data.get("original_question"):
        return False, "French multilingual query failed"
    return True, ""


def multilingual_english_default():
    data = _ask({"question": "What is EUR Amount?"})
    if data.get("language") != "EN":
        return False, "English default language not working"
    if data.get("retrieved_with") != data.get("original_question"):
        return False, "English default language not working"
    return True, ""


# ── Section 6 — Source Citations ──────────────────────────────────────────────

def citations_have_required_fields():
    data = _ask({"question": "What does MERCHANT_CITY mean?", "language": "EN"})
    sources = data.get("sources", [])
    required = ("rank", "label", "excerpt", "confidence", "source_type", "product")
    for i, src in enumerate(sources):
        for field in required:
            if field not in src:
                return False, f"Source citation missing required fields (source {i+1} missing '{field}')"
        if not src.get("excerpt"):
            return False, f"Source citation missing required fields (source {i+1} has empty excerpt)"
        if src.get("rank", 0) < 1:
            return False, f"Source citation missing required fields (source {i+1} rank < 1)"
    return True, ""


def citations_ranked_correctly():
    data = _ask({"question": "What does MERCHANT_CITY mean?", "language": "EN"})
    sources = data.get("sources", [])
    if len(sources) < 2:
        return False, "Sources not ranked in order (fewer than 2 sources returned)"
    ranks = [s.get("rank") for s in sources]
    if ranks != sorted(ranks):
        return False, f"Sources not ranked in order: {ranks}"
    if ranks[0] != 1:
        return False, f"Sources not ranked in order (first rank is {ranks[0]}, expected 1)"
    return True, ""


def citations_max_five_sources():
    data = _ask({"question": "How do I manage user access?", "language": "EN"})
    sources = data.get("sources", [])
    if len(sources) > 5:
        return False, f"More than 5 sources returned — TOP_K_RERANK exceeded ({len(sources)} sources)"
    return True, ""


# ── Section 7 — Response Schema ───────────────────────────────────────────────

def response_has_required_fields():
    data = _ask({"question": "What is EUR Amount?", "language": "EN"})
    required = (
        "answer", "confidence", "product_scope", "language",
        "original_question", "retrieved_with", "sources", "has_contradiction",
    )
    missing = [f for f in required if f not in data]
    if missing:
        return False, f"Response schema missing required fields: {missing}"
    return True, ""


def confidence_values_valid():
    data = _ask({"question": "What is EUR Amount?", "language": "EN"})
    confidence = data.get("confidence")
    if confidence not in ("high", "medium", "low", "none"):
        return False, f"Invalid confidence value returned: {confidence!r}"
    return True, ""


def no_answer_response_clean():
    data = _ask({"question": "What is the capital of France?", "language": "EN"})
    if data.get("confidence") != "none":
        return False, "No-answer response not clean"
    if data.get("sources") != []:
        return False, "No-answer response not clean"
    if data.get("has_contradiction") is not False:
        return False, "No-answer response not clean"
    if not data.get("answer"):
        return False, "No-answer response not clean"
    return True, ""


# ── Section 8 — Ingest Integrity ─────────────────────────────────────────────

def ingest_chunk_count():
    r = _get("/stats")
    if r.status_code != 200:
        return False, f"GET /stats returned HTTP {r.status_code}"
    data = r.json()
    count = data.get("total_chunks", 0)
    if count < 1400 or count > 2000:
        return False, (
            f"Unexpected chunk count: {count}. "
            "Expected 1400-2000. Re-ingest may be needed."
        )
    return True, ""


def both_products_have_chunks():
    r = _get("/products")
    if r.status_code != 200:
        return False, f"GET /products returned HTTP {r.status_code}"
    data = r.json()
    products = data.get("products", [])
    if "airplus_intelligence" not in products:
        return False, "One or more products missing from ChromaDB. Re-ingest required."
    if "portal" not in products:
        return False, "One or more products missing from ChromaDB. Re-ingest required."
    return True, ""


# ── Test runner ───────────────────────────────────────────────────────────────

def run_all_tests():
    tests = [
        # Section 1 — Health
        api_health,
        api_products,
        api_languages,
        # Section 2 — Gate
        gate_blocks_capital_of_france,
        gate_blocks_ceo_of_apple,
        gate_blocks_unrelated_personal_question,
        # Section 3 — Domain
        domain_merchant_city_en,
        domain_eur_amount_en,
        domain_ebilling_download,
        domain_fare_basis,
        domain_where_fare_basis,
        domain_user_management,
        # Section 4 — Product scope
        product_scope_portal_enforced,
        product_scope_airplus_intelligence,
        product_scope_all_products,
        # Section 5 — Multilingual
        multilingual_german_excel,
        multilingual_french_excel,
        multilingual_english_default,
        # Section 6 — Citations
        citations_have_required_fields,
        citations_ranked_correctly,
        citations_max_five_sources,
        # Section 7 — Schema
        response_has_required_fields,
        confidence_values_valid,
        no_answer_response_clean,
        # Section 8 — Ingest
        ingest_chunk_count,
        both_products_have_chunks,
    ]

    passed = 0
    failed = 0
    failures = []

    print("\n" + "=" * 60)
    print("  AirPlus Assist — Regression Test Suite")
    print("=" * 60 + "\n")

    for test_fn in tests:
        try:
            ok, msg = test_fn()
            if ok:
                print(f"  ✅ PASS  {test_fn.__name__}")
                passed += 1
            else:
                print(f"  ❌ FAIL  {test_fn.__name__}: {msg}")
                failed += 1
                failures.append((test_fn.__name__, msg))
        except Exception as e:
            print(f"  💥 ERROR {test_fn.__name__}: {str(e)}")
            failed += 1
            failures.append((test_fn.__name__, str(e)))

    print("\n" + "=" * 60)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if failures:
        print("\n  Failed tests:")
        for name, reason in failures:
            print(f"    • {name}: {reason}")
        print()

    if failed == 0:
        print("\n  🟢 All tests passed — demo ready!\n")
    else:
        print(f"\n  🔴 {failed} test(s) failed — fix before demo!\n")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
