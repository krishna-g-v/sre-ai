"""
Local embedding model — see docs/02-access-control-and-rag.md §5 and
docs/06-deployment-and-environments.md §2a.

In the built Docker image, weights are baked in at EMBEDDING_LOCAL_MODEL_PATH and this
loads fully offline. In this dev sandbox (full internet access), sentence-transformers
will transparently download+cache the model into that same path on first use.
"""

import os
from functools import lru_cache

from app.core.config import get_settings

# Must be set before importing sentence_transformers/transformers/huggingface_hub —
# they resolve their default cache location (~/.cache/huggingface) at import time.
# Pointing HF_HOME at our own model path keeps everything (including the "check for
# updates" metadata lookups the libraries do internally) inside one place that's
# actually writable and, in the built image, pre-populated at build time — see
# docs/06-deployment-and-environments.md §2a.
os.environ.setdefault("HF_HOME", get_settings().embedding_local_model_path)

from sentence_transformers import SentenceTransformer  # noqa: E402

# bge models expect this instruction prefix on the *query* side only (not on documents)
# for retrieval tasks — see the model card. Skipping it would still work but retrieval
# quality is measurably worse.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


@lru_cache
def get_embedding_model() -> SentenceTransformer:
    settings = get_settings()
    return SentenceTransformer(
        settings.embedding_model_id,
        cache_folder=settings.embedding_local_model_path,
    )


def embed_documents(texts: list[str]) -> list[list[float]]:
    model = get_embedding_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()


def embed_query(text: str) -> list[float]:
    model = get_embedding_model()
    vector = model.encode(BGE_QUERY_INSTRUCTION + text, normalize_embeddings=True, show_progress_bar=False)
    return vector.tolist()
