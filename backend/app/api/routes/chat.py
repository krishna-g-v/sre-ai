from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.orchestrator import HISTORY_WINDOW, build_orchestrator_graph
from app.api.deps import CurrentUser, get_current_user
from app.db.models import ChatMessage, ChatSession, Document
from app.db.session import get_db
from app.schemas.chat import ChatMessageOut, ChatSessionOut, SendMessageResponse, ChatMessageIn

router = APIRouter(prefix="/chat", tags=["chat"])

TITLE_MAX_LEN = 60


def _title_from_message(content: str) -> str:
    """First-message-as-title, like ChatGPT/Claude — a single line, truncated."""
    single_line = " ".join(content.split())
    if len(single_line) <= TITLE_MAX_LEN:
        return single_line
    return single_line[: TITLE_MAX_LEN - 1].rstrip() + "…"


@router.get("/sessions", response_model=list[ChatSessionOut])
def list_sessions(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[ChatSession]:
    stmt = (
        select(ChatSession)
        .where(ChatSession.user_id == user.user_id)
        .order_by(ChatSession.updated_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


@router.post("/sessions", response_model=ChatSessionOut, status_code=201)
def create_session(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> ChatSession:
    session = ChatSession(user_id=user.user_id, title="New Chat", status="general")
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def list_messages(
    session_id: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[ChatMessage]:
    session = _get_owned_session(db, session_id, user)
    stmt = select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at)
    return list(db.execute(stmt).scalars().all())


@router.post("/sessions/{session_id}/messages", response_model=SendMessageResponse)
def send_message(
    session_id: UUID,
    payload: ChatMessageIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> SendMessageResponse:
    session = _get_owned_session(db, session_id, user)

    # Prior turns only — the new user message is added after this, so it isn't double
    # counted. Every node in the orchestrator graph uses this for context; see its
    # module docstring for why (short follow-ups are unreadable in isolation).
    prior_messages = (
        db.execute(
            select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at)
        )
        .scalars()
        .all()
    )
    history = [{"role": m.role, "content": m.content} for m in prior_messages][-HISTORY_WINDOW:]

    if not prior_messages:
        session.title = _title_from_message(payload.content)

    user_message = ChatMessage(session_id=session.id, role="user", content=payload.content)
    db.add(user_message)
    db.flush()

    pinned_title = None
    if session.pinned_document_id:
        doc = db.get(Document, session.pinned_document_id)
        pinned_title = doc.title if doc else None

    graph = build_orchestrator_graph(db)
    result = graph.invoke(
        {
            "query": payload.content,
            "history": history,
            "user_id": str(user.user_id),
            "group_ids": [str(g) for g in user.group_ids],
            "is_superuser": user.is_superuser,
            "session_status": session.status,
            "pinned_document_id": str(session.pinned_document_id) if session.pinned_document_id else None,
            "pinned_document_title": pinned_title,
        }
    )

    user_message.message_category = result.get("category")

    assistant_message = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=result["answer"],
        message_category=result.get("category"),
    )
    db.add(assistant_message)

    if result.get("new_pinned_document_id"):
        session.status = "pinned"
        session.pinned_document_id = UUID(result["new_pinned_document_id"])
        session.pinned_at = datetime.now(timezone.utc)

    session.updated_at = datetime.now(timezone.utc)

    db.add(session)
    db.commit()
    db.refresh(session)
    db.refresh(assistant_message)

    return SendMessageResponse(
        session=session,
        message=assistant_message,
        retrieved_titles=result.get("retrieved_titles", []),
        drifted=result.get("drifted", False),
    )


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> None:
    session = _get_owned_session(db, session_id, user)
    db.delete(session)  # cascades to chat_messages via FK ondelete="CASCADE"
    db.commit()


def _get_owned_session(db: Session, session_id: UUID, user: CurrentUser) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if session is None or session.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session
