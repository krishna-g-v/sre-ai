"""Optional LLM-based Markdown conversion at ingestion time — docs/02-access-control-and-rag.md
(chunking/retrieval this feeds into) plus the 2026-09-11 decision log in docs/00-overview.md.

Requested per upload (`convert_to_markdown`, docs/04-frontend-ui.md's Knowledge Base upload
dialog): rewrite the raw extracted text as clean, structured Markdown *before* chunking and
embedding, instead of ingesting raw PDF/DOCX extraction output as-is. The reasoning (from the
user): cleaner structure improves retrieval relevance, and Markdown is more token-dense than
raw extraction noise (repeated page headers/footers, broken mid-sentence line wraps), so
answering from it costs fewer tokens per turn too.

This is a single whole-document LLM call, same assumption already recorded in docs/02 §3 for
whole-document chunking — the chosen LLM's context window is large enough for this scope's
document sizes (short internal docs, not book-length manuals).
"""

from app.services.llm import LLMAdapter

MARKDOWN_CONVERSION_SYSTEM_PROMPT = """You convert raw extracted document text into clean, \
well-structured Markdown.

Rules:
- Preserve ALL information and meaning from the source — do not summarize, shorten, omit, or \
paraphrase away any content, facts, numbers, names, or details. This is a reformatting task, \
not a summarization task.
- Reconstruct obvious structure the raw text implies: headings (#, ##, ...), bullet/numbered \
lists, tables (Markdown table syntax) where the source clearly has one, code blocks for \
anything that reads as code/commands/config/file paths.
- Fix extraction artifacts — broken line wraps mid-sentence, repeated page headers/footers, \
stray page numbers, stray form-feed characters — without changing the actual content.
- Do not add any commentary, preamble, title you invented, or explanation of what you did. \
Output ONLY the converted Markdown, nothing else."""


def convert_to_markdown(text: str, llm: LLMAdapter) -> tuple[str, bool]:
    """Returns (markdown_text, succeeded). On any failure (LLM error, empty response),
    returns the original text unchanged with succeeded=False — a conversion problem
    must never fail the whole upload, it should just ingest the original extraction
    instead, same as if the checkbox had been left unchecked."""
    if not text.strip():
        return text, False
    try:
        result = llm.chat(
            [
                {"role": "system", "content": MARKDOWN_CONVERSION_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.0,
        )
    except Exception:
        return text, False
    result = (result or "").strip()
    if not result:
        return text, False
    return result, True
