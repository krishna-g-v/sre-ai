"""RAG subgraph — docs/03-agent-and-integrations.md §2.

Retrieves chunks (mixing chunk types/documents per docs/02-access-control-and-rag.md §4 —
never a blanket "summarize the whole document") and synthesizes an answer grounded in them.
"""

import uuid

from sqlalchemy.orm import Session

from app.services.llm import get_llm
from app.services.retrieval import RetrievedChunk, retrieve

SYSTEM_PROMPT = """You are an SRE Agent answering questions using the organization's internal
documentation. This assistant does not hold open-ended conversations and does not answer from
general/outside knowledge, even if you personally know the answer — if the provided context
doesn't contain it, say so plainly and stop there. Never fill a gap in the context with your
own general knowledge; that's a fabrication as far as this assistant is concerned, not a
helpful save. If the question is too vague to know what it's really asking, ask a brief
clarifying question instead of guessing.

Do not blanket-summarize a whole document unless the user actually asked for a summary;
extract the specific answer to the question asked.

The user's message may be a short follow-up ("what next?", a one- or two-word answer to something
you just asked) — use the conversation history to understand what it actually refers to, the same
way a human reading the whole thread would, rather than treating it as a standalone question.

Never name or describe the specific source document (no title, filename, or phrases like "the
onboarding guide"/"the runbook"/"the X manual") — the UI shows the source separately, and your
job is only the answer. Write it directly, as your own knowledge, by default. A generic,
non-specific framing like "Based on the knowledge I have..." or "From what I know..." is fine
if it reads more naturally, as long as it never identifies which document.

Format the answer in Markdown where it helps readability (headings, bullet/numbered lists, bold,
code blocks for commands) — do not just write one long paragraph for anything with multiple steps."""


def contextualized_search_query(query: str, history: list[dict], turns: int = 2) -> str:
    """A short follow-up ("ad uid it is", "what next?") embeds poorly on its own — there's
    barely any semantic content to match against. Folding in the last couple of turns gives
    the embedding something to actually latch onto, without diluting it with the full
    (potentially long) history."""
    if not history:
        return query
    recent = history[-(turns * 2):]
    recent_text = " ".join(m["content"] for m in recent)
    return f"{recent_text} {query}"


def run_rag(
    db: Session,
    *,
    query: str,
    user_id: uuid.UUID,
    group_ids: list[uuid.UUID],
    pinned_document_id: uuid.UUID | None,
    is_superuser: bool = False,
    history: list[dict] | None = None,
) -> tuple[str, list[RetrievedChunk]]:
    history = history or []
    search_query = contextualized_search_query(query, history)

    results = retrieve(
        db,
        query=search_query,
        user_id=user_id,
        group_ids=group_ids,
        pinned_document_id=pinned_document_id,
        is_superuser=is_superuser,
    )

    if not results:
        scope = "the pinned document" if pinned_document_id else "your accessible knowledge base"
        return (
            f"I couldn't find anything relevant to that in {scope}. "
            "Try rephrasing, or upload the relevant document if it isn't in the knowledge base yet.",
            [],
        )

    context = "\n\n---\n\n".join(
        f"[Document: {r.document.title}]\n{r.chunk.content}" for r in results
    )

    llm = get_llm()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *({"role": m["role"], "content": m["content"]} for m in history),
        {"role": "user", "content": f"Context:\n\n{context}\n\nQuestion: {query}"},
    ]
    answer = llm.chat(messages)
    return answer, results
