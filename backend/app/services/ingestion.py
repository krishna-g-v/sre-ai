import uuid

from sqlalchemy.orm import Session

from app.db.models import Chunk, Document
from app.services.chunking import chunk_text
from app.services.embeddings import embed_documents
from app.services.parsing import extract_text, infer_content_type


def ingest_document(
    db: Session,
    *,
    filename: str,
    content: bytes,
    title: str,
    uploaded_by: uuid.UUID,
    owner_scope: str,
    group_ids: list[uuid.UUID],
    personal_owner_id: uuid.UUID | None,
    tags: list[str],
    chunk_strategy: str,
    best_effort_target_size: str | None,
) -> Document:
    content_type = infer_content_type(filename)

    document = Document(
        title=title,
        source_filename=filename,
        uploaded_by=uploaded_by,
        owner_scope=owner_scope,
        group_ids=group_ids,
        personal_owner_id=personal_owner_id,
        content_type=content_type,
        status="processing",
        tags=tags,
        chunk_strategy=chunk_strategy,
        best_effort_target_size=best_effort_target_size,
    )
    db.add(document)
    db.flush()

    try:
        text = extract_text(content, content_type)
        pieces = chunk_text(text, chunk_strategy, best_effort_target_size)
        chunk_type = "whole_document" if chunk_strategy == "whole_document" else "best_effort"
        vectors = embed_documents(pieces)

        for idx, (piece, vector) in enumerate(zip(pieces, vectors)):
            db.add(
                Chunk(
                    document_id=document.id,
                    chunk_index=idx,
                    chunk_type=chunk_type,
                    content=piece,
                    embedding=vector,
                    token_count=len(piece) // 4,  # rough estimate, not load-bearing
                )
            )
        document.status = "ready"
    except Exception:
        document.status = "failed"
        raise
    finally:
        db.commit()

    db.refresh(document)
    return document
