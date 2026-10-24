"""Embeddings. BGE-M3 by default: one vector space for Hebrew and English.

That single property is why this model is the choice. Her training material is
Hebrew, the method literature is English, and a session must be able to pull the
relevant passage from either without a translation step in between.

Loading is lazy so that importing this module never triggers a model download.
"""

from __future__ import annotations

import os
from functools import lru_cache

DEFAULT_MODEL = os.environ.get("RAG_EMBED_MODEL", "BAAI/bge-m3")
DIMENSIONS = {"BAAI/bge-m3": 1024, "intfloat/multilingual-e5-large": 1024}


@lru_cache(maxsize=2)
def _load(model_name: str):
    from sentence_transformers import SentenceTransformer  # heavy import

    return SentenceTransformer(model_name, device="cpu")


def dimension(model_name: str = DEFAULT_MODEL) -> int:
    if model_name in DIMENSIONS:
        return DIMENSIONS[model_name]
    return _load(model_name).get_sentence_embedding_dimension()


def embed_passages(
    texts: list[str], model_name: str = DEFAULT_MODEL, batch_size: int = 8
) -> list[list[float]]:
    if not texts:
        return []
    model = _load(model_name)
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=len(texts) > 64,
        convert_to_numpy=True,
    )
    return [v.tolist() for v in vectors]


def embed_query(text: str, model_name: str = DEFAULT_MODEL) -> list[float]:
    model = _load(model_name)
    vec = model.encode([text], normalize_embeddings=True, convert_to_numpy=True)[0]
    return vec.tolist()
