"""
Embedder for AirPlus Assist.

Loads a SentenceTransformer model once and caches it.
Provides embed_texts() to encode a list of strings into
dense float vectors for ChromaDB storage.
"""

from sentence_transformers import SentenceTransformer

_model_cache: dict[str, SentenceTransformer] = {}


def get_embedder(model_name: str) -> SentenceTransformer:
    """Load and cache a SentenceTransformer model by name."""
    if model_name not in _model_cache:
        print(f"[embedder] Loading model: {model_name}")
        _model_cache[model_name] = SentenceTransformer(model_name)
    return _model_cache[model_name]


def embed_texts(texts: list[str], model: SentenceTransformer) -> list[list[float]]:
    """Return a list of float embeddings for each input string."""
    embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    return embeddings.tolist()
