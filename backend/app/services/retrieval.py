"""RAG retrieval — docs/02-access-control-and-rag.md §4, §7.

The access-control filter (group membership OR personal ownership) is applied
unconditionally here, at the query layer — never left to the LLM to self-police.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document
from app.services.embeddings import embed_query


class RetrievedChunk:
    def __init__(self, chunk: Chunk, document: Document, score: float):
        self.chunk = chunk
        self.document = document
        self.score = score


def retrieve(
    db: Session,
    *,
    query: str,
    user_id: uuid.UUID,
    group_ids: list[uuid.UUID],
    pinned_document_id: uuid.UUID | None = None,
    is_superuser: bool = False,
    limit: int = 6,
) -> list[RetrievedChunk]:
    query_vector = embed_query(query)

    stmt = (
        select(Chunk, Document, Chunk.embedding.cosine_distance(query_vector).label("distance"))
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.status == "ready")
    )

    if pinned_document_id is not None:
        stmt = stmt.where(Document.id == pinned_document_id)
    elif not is_superuser:
        # Superusers search every document regardless of their own group membership —
        # docs/02-access-control-and-rag.md §7 — same rule as the /documents list endpoint.
        stmt = stmt.where(
            (Document.owner_scope == "group") & (Document.group_ids.overlap(group_ids))
            | (Document.owner_scope == "personal") & (Document.personal_owner_id == user_id)
        )

    stmt = stmt.order_by("distance").limit(limit)

    results = db.execute(stmt).all()
    return [RetrievedChunk(chunk=row[0], document=row[1], score=1 - row[2]) for row in results]


def find_dominant_document(results: list[RetrievedChunk], margin: float) -> uuid.UUID | None:
    """docs/08-chat-sessions-and-orchestration.md §5 — a document is 'dominant' if its
    best score clearly exceeds the best score from any other distinct document."""
    if not results:
        return None

    best_by_doc: dict[uuid.UUID, float] = {}
    for r in results:
        doc_id = r.document.id
        if doc_id not in best_by_doc or r.score > best_by_doc[doc_id]:
            best_by_doc[doc_id] = r.score

    if len(best_by_doc) == 1:
        return next(iter(best_by_doc))

    ranked = sorted(best_by_doc.items(), key=lambda kv: kv[1], reverse=True)
    top_doc, top_score = ranked[0]
    _, runner_up_score = ranked[1]

    if top_score - runner_up_score >= margin:
        return top_doc
    return None
