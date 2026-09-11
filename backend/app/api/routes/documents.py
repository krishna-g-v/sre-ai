import json
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.db.models import ChatSession, Document
from app.db.session import get_db
from app.schemas.documents import DocumentOut
from app.services.ingestion import ingest_document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[Document]:
    stmt = select(Document)
    if not user.is_superuser:
        # Superusers see every document regardless of their own group membership —
        # docs/02-access-control-and-rag.md §7. Everyone else only sees documents
        # scoped to a group they belong to, or their own personal KB.
        stmt = stmt.where(
            (Document.owner_scope == "group") & (Document.group_ids.overlap(user.group_ids))
            | (Document.owner_scope == "personal") & (Document.personal_owner_id == user.user_id)
        )
    return list(db.execute(stmt).scalars().all())


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),  # user-facing document name, shown in chat citations instead of the filename
    owner_scope: str = Form(...),  # "group" | "personal"
    group_ids: str = Form("[]"),  # JSON array of UUID strings, required if owner_scope == group
    tags: str = Form("[]"),  # JSON array of strings
    chunk_strategy: str = Form("whole_document"),  # "whole_document" | "best_effort"
    best_effort_target_size: str | None = Form(None),  # "small" | "medium" | "large"
    convert_to_markdown: bool = Form(
        False
    ),  # LLM-rewrite non-md files to Markdown before ingesting
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> Document:
    if owner_scope not in ("group", "personal"):
        raise HTTPException(status_code=400, detail="owner_scope must be 'group' or 'personal'")

    parsed_group_ids: list[UUID] = []
    if owner_scope == "group":
        parsed_group_ids = [UUID(g) for g in json.loads(group_ids)]
        if not parsed_group_ids:
            raise HTTPException(status_code=400, detail="group_ids required for owner_scope='group'")
        if not user.is_superuser and not set(parsed_group_ids).issubset(set(user.group_ids)):
            raise HTTPException(
                status_code=403, detail="Cannot upload into a group you don't belong to"
            )

    content = await file.read()

    document = ingest_document(
        db,
        filename=file.filename,
        content=content,
        title=title.strip() or file.filename,
        uploaded_by=user.user_id,
        owner_scope=owner_scope,
        group_ids=parsed_group_ids,
        personal_owner_id=user.user_id if owner_scope == "personal" else None,
        tags=json.loads(tags),
        chunk_strategy=chunk_strategy,
        best_effort_target_size=best_effort_target_size,
        convert_markdown=convert_to_markdown,
    )
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> None:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    is_owner = document.owner_scope == "personal" and document.personal_owner_id == user.user_id
    is_group_member = document.owner_scope == "group" and set(document.group_ids) & set(user.group_ids)
    if not (user.is_superuser or is_owner or is_group_member):
        raise HTTPException(status_code=403, detail="Not allowed to delete this document")

    # A session pinned to this document degrades gracefully back to "general" rather than
    # pointing at a document that no longer exists — the FK's ON DELETE SET NULL alone
    # would only null the column, leaving status stuck saying "pinned".
    pinned_sessions = db.execute(
        select(ChatSession).where(ChatSession.pinned_document_id == document_id)
    ).scalars().all()
    for session in pinned_sessions:
        session.status = "general"
        session.pinned_document_id = None
        session.pinned_at = None

    db.delete(document)
    db.commit()
