"""
Chunking strategy — docs/02-access-control-and-rag.md §3.

Two strategies, chosen at ingestion time (system default + per-document override):
  - whole_document: the entire text becomes one chunk (viable because Llama 4 Scout's
    context window comfortably fits a 10-20 page document, and it avoids losing context
    to a bad split).
  - best_effort: split on natural boundaries (blank lines / paragraphs) targeting a
    qualitative size, not an exact token count.
"""

import re

# Rough qualitative targets in characters (not an exact contract — see docs/02 §3).
# ~4 chars/token is a reasonable English-text approximation for sizing purposes only.
_TARGET_CHARS = {
    "small": 1_500,
    "medium": 4_000,
    "large": 8_000,
}


def chunk_whole_document(text: str) -> list[str]:
    return [text.strip()]


def chunk_best_effort(text: str, target_size: str = "medium") -> list[str]:
    target = _TARGET_CHARS.get(target_size, _TARGET_CHARS["medium"])
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        if current and current_len + len(para) > target:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += len(para)

    if current:
        chunks.append("\n\n".join(current))

    return chunks or [text.strip()]


def chunk_text(text: str, strategy: str, target_size: str | None) -> list[str]:
    if strategy == "whole_document":
        return chunk_whole_document(text)
    return chunk_best_effort(text, target_size or "medium")
