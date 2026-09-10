from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.db.models import Agent, Alert
from app.db.session import get_db
from app.schemas.alerts import AlertOut, SampleTriggerRequest, WebhookPayload
from app.services.triage import generate_ai_triage

router = APIRouter(prefix="/alerts", tags=["alerts"])

# Synthetic demo payloads for the dashboard's 1-click ingestion simulator — no real
# customer/production data, just representative shapes for each source type.
SAMPLE_PAYLOADS: dict[str, tuple[str, dict]] = {
    "grafana_cpu": (
        "grafana",
        {
            "labels": {
                "alertname": "DatasourceNoData",
                "rule_uid": "14MqUgb4k",
                "rulename": "CPU Cores Reservations vs Actual alert 14MqUgb4k",
            },
            "annotations": {
                "message": "CPU reservations are reaching the limit of allocatable cores. "
                "This might result in failed deployments and pod evictions."
            },
        },
    ),
    "grafana_memory": (
        "grafana",
        {
            "labels": {
                "alertname": "DatasourceNoData",
                "rule_uid": "8qW3UgxVz",
                "rulename": "Memory Reservations vs Actual alert 8qW3UgxVz",
            },
            "annotations": {
                "message": "Memory reservations are reaching the limit of allocatable memory. "
                "This might result in failed deployments and pod evictions."
            },
        },
    ),
    "synthetics_login": (
        "synthetics",
        {
            "canary": "analytics_login_prod",
            "status": "failed",
            "duration": "43179ms",
            "start_url": "https://analytics.example.com",
            "end_url": "https://analytics.example.com/hub/my/work",
            "failed_step": "Verify logged out",
            "error": "Waiting for selector `#loginbtn` failed: Waiting failed: 30000ms exceeded",
            "steps": [
                {"name": "Load Site", "duration": "276ms", "result": "success"},
                {"name": "Submit username and password", "duration": "1627ms", "result": "success"},
                {"name": "Verify Logged in", "duration": "3401ms", "result": "success"},
                {"name": "Log out", "duration": "254ms", "result": "success"},
                {"name": "Verify logged out", "duration": "37621ms", "result": "failed"},
            ],
        },
    ),
    "prometheus_slow": (
        "prometheus",
        {
            "status": "Firing",
            "labels": {
                "alertname": "PrometheusTargetScrapingSlow",
                "instance": "localhost:9090",
                "severity": "warning",
            },
            "annotations": {
                "summary": "Prometheus target scraping slow (instance localhost:9090)",
                "description": "Prometheus is scraping exporters slowly.",
            },
        },
    ),
}


def _parse_canary_steps(payload: dict) -> list[dict] | None:
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return None
    parsed = []
    for s in steps:
        duration = s.get("duration", "100ms")
        duration_ms = int(str(duration).replace("ms", "")) if duration else 100
        parsed.append(
            {
                "name": s.get("name", "Step"),
                "durationMs": duration_ms,
                "status": "success" if s.get("result") == "success" else "failed",
                "errorDetails": s.get("error"),
            }
        )
    return parsed


def _ingest(db: Session, *, category: str, payload: dict) -> Alert:
    stmt = select(Agent).where(Agent.category.ilike(category), Agent.enabled.is_(True))
    target_agent = db.execute(stmt).scalars().first()
    if target_agent is None:
        target_agent = db.execute(select(Agent).where(Agent.enabled.is_(True))).scalars().first()

    agent_id = target_agent.id if target_agent else None
    agent_name = target_agent.name if target_agent else "Unassigned Agent"
    agent_category = target_agent.category if target_agent else category.capitalize()
    triage_prompt = target_agent.triage_prompt if target_agent else "Triage this alert."
    severity_rule = target_agent.severity_rule if target_agent else "Default severity rules."
    group_ids = target_agent.group_ids if target_agent else []

    title = (
        payload.get("title")
        or (payload.get("labels") or {}).get("rulename")
        or payload.get("canary")
        or (payload.get("labels") or {}).get("alertname")
        or f"Ingested Alert ({agent_category})"
    )

    triage = generate_ai_triage(
        db,
        agent_name=agent_name,
        triage_prompt=triage_prompt,
        severity_rule=severity_rule,
        raw_payload=payload,
        group_ids=group_ids,
    )

    alert = Alert(
        agent_id=agent_id,
        agent_name=agent_name,
        source=agent_category,
        title=title,
        status="Firing",
        severity=triage["impact_level"],
        verdict="Real Incident" if triage["is_real_issue"] else "Filtered Noise",
        raw_payload=payload,
        labels=payload.get("labels", {}),
        annotations=payload.get("annotations", {}),
        canary_name=payload.get("canary"),
        canary_start_url=payload.get("start_url"),
        canary_end_url=payload.get("end_url"),
        canary_error_step=payload.get("failed_step"),
        canary_error_msg=payload.get("error"),
        canary_steps=_parse_canary_steps(payload),
        runbook_link=payload.get("instructions_url") or triage.get("runbook_url"),
        triage_report=triage,
        group_ids=group_ids,
    )
    db.add(alert)

    if target_agent is not None:
        target_agent.last_run_at = datetime.now(timezone.utc)
        target_agent.total_triaged += 1
        if triage["is_real_issue"]:
            target_agent.real_issues_detected += 1
        else:
            target_agent.noise_filtered_count += 1

    db.commit()
    db.refresh(alert)
    return alert


@router.get("", response_model=list[AlertOut])
def list_alerts(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[Alert]:
    stmt = select(Alert)
    if not user.is_superuser:
        stmt = stmt.where((Alert.group_ids == []) | (Alert.group_ids.overlap(user.group_ids)))
    stmt = stmt.order_by(Alert.occurred_at.desc())
    return list(db.execute(stmt).scalars().all())


@router.get("/{alert_id}", response_model=AlertOut)
def get_alert(
    alert_id: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.post("/{alert_id}/re-triage", response_model=AlertOut)
def re_triage_alert(
    alert_id: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    agent = db.get(Agent, alert.agent_id) if alert.agent_id else None
    triage = generate_ai_triage(
        db,
        agent_name=agent.name if agent else alert.agent_name,
        triage_prompt=agent.triage_prompt if agent else "Triage this alert.",
        severity_rule=agent.severity_rule if agent else "Default severity rules.",
        raw_payload=alert.raw_payload,
        group_ids=alert.group_ids,
    )
    alert.triage_report = triage
    alert.verdict = "Real Incident" if triage["is_real_issue"] else "Filtered Noise"
    alert.severity = triage["impact_level"]
    db.commit()
    db.refresh(alert)
    return alert


@router.post("/sample-trigger", response_model=AlertOut)
def sample_trigger(
    req: SampleTriggerRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> Alert:
    if req.sample_type == "custom":
        category = req.category or "custom"
        payload = req.custom_payload or {"alert": "Custom SRE event", "severity": "warning"}
    else:
        category, payload = SAMPLE_PAYLOADS[req.sample_type]
    return _ingest(db, category=category, payload=payload)


@router.post("/webhook/{category}", response_model=AlertOut, status_code=201)
def webhook_ingest(
    category: str,
    payload: WebhookPayload,
    db: Session = Depends(get_db),
) -> Alert:
    """Real ingestion endpoint for Grafana Alertmanager / Synthetics / Prometheus Alertmanager
    webhooks. Unauthenticated by design (matches how these external systems POST), same as
    the reference implementation — securing this (shared secret header, IP allowlist, etc.)
    is flagged as follow-up work, not solved here."""
    return _ingest(db, category=category, payload=payload.model_dump())
