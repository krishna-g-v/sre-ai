from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.db.models import Agent
from app.db.session import get_db
from app.schemas.agents import AgentCreate, AgentOut

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentOut])
def list_agents(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[Agent]:
    stmt = select(Agent)
    if not user.is_superuser:
        stmt = stmt.where((Agent.group_ids == []) | (Agent.group_ids.overlap(user.group_ids)))
    stmt = stmt.order_by(Agent.created_at.desc())
    return list(db.execute(stmt).scalars().all())


@router.post("", response_model=AgentOut, status_code=201)
def create_agent(
    payload: AgentCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> Agent:
    agent = Agent(
        name=payload.name,
        description=payload.description or "User-defined pluggable SRE agent.",
        owner=payload.owner or user.username,
        category=payload.category,
        webhook_path=f"/api/alerts/webhook/{payload.category.lower()}",
        triage_prompt=payload.triage_prompt,
        severity_rule=payload.severity_rule,
        group_ids=payload.group_ids,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.post("/{agent_id}/toggle", response_model=AgentOut)
def toggle_agent(
    agent_id: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent.enabled = not agent.enabled
    db.commit()
    db.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=204)
def delete_agent(
    agent_id: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> None:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    db.delete(agent)
    db.commit()
