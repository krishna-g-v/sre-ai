from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.db.models import Agent, Alert
from app.db.session import get_db

router = APIRouter(tags=["stats"])


@router.get("/stats")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    alert_stmt = select(Alert)
    agent_stmt = select(Agent)
    if not user.is_superuser:
        alert_stmt = alert_stmt.where((Alert.group_ids == []) | (Alert.group_ids.overlap(user.group_ids)))
        agent_stmt = agent_stmt.where((Agent.group_ids == []) | (Agent.group_ids.overlap(user.group_ids)))

    alerts = list(db.execute(alert_stmt).scalars().all())
    agents = list(db.execute(agent_stmt).scalars().all())

    total_alerts = len(alerts)
    real_incidents = sum(1 for a in alerts if a.verdict == "Real Incident")
    filtered_noise = sum(1 for a in alerts if a.verdict == "Filtered Noise")
    active_agents = sum(1 for a in agents if a.enabled)
    triaged_count = sum(1 for a in alerts if a.triage_report)

    return {
        "total_alerts_ingested": total_alerts,
        "real_incidents_count": real_incidents,
        "filtered_noise_count": filtered_noise,
        "active_agents_count": active_agents,
        "auto_triaged_percentage": int((triaged_count / total_alerts) * 100) if total_alerts else 100,
        "noise_reduction_rate": int((filtered_noise / total_alerts) * 100) if total_alerts else 0,
    }
