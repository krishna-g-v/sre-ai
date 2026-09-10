"""Run at Docker build time only — see docs/06-deployment-and-environments.md §2a.
Downloads the embedding model weights into the image so the runtime container never
needs to reach Hugging Face (blocked on the corporate network)."""

import os

from sentence_transformers import SentenceTransformer

model_id = os.environ["EMBEDDING_MODEL_ID"]
cache_folder = os.environ["EMBEDDING_LOCAL_MODEL_PATH"]

SentenceTransformer(model_id, cache_folder=cache_folder)
print(f"Downloaded {model_id} into {cache_folder}")
