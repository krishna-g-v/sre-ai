"""AI alert triage — analyzes an incoming alert payload against the knowledge base and
produces a structured report. Advisory only: this never executes anything, it only
proposes a summary, root cause, and remediation steps for a human to act on — same
guardrail as the rest of the system (docs/00-overview.md, docs/03-agent-and-integrations.md).
"""

import json
import uuid

from sqlalchemy.orm import Session

from app.services.llm import get_llm
from app.services.retrieval import retrieve

TRIAGE_SYSTEM_PROMPT = "You are an AI SRE assistant. Output raw JSON only, no markdown code fences."

TRIAGE_PROMPT_TEMPLATE = """You are an expert technical AI agent named "{agent_name}".
Triage this incoming alert payload: decide if it is a Real Incident or Filtered Noise,
identify a likely root cause, and provide step-by-step remediation guidance. You are
advisory only — never claim to have taken any remediation action yourself.

Agent triage instructions: {triage_prompt}
Severity rule: {severity_rule}

Relevant internal knowledge base context:
{docs_context}

Incoming alert payload:
{payload_str}

Respond ONLY with a JSON object matching this schema, no markdown fences:
{{
  "summary": "1-2 sentence executive summary",
  "is_real_issue": true,
  "noise_reason": "why classified as real vs noise",
  "impact_level": "Critical",
  "root_cause_hypothesis": "likely root cause",
  "step_by_step_remediation": ["step 1", "step 2"],
  "runbook_url": "",
  "recommended_action": "short 3-5 word action summary",
  "estimated_resolution_minutes": 15
}}"""


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    return cleaned.strip()


def generate_ai_triage(
    db: Session,
    *,
    agent_name: str,
    triage_prompt: str,
    severity_rule: str,
    raw_payload: dict,
    group_ids: list[uuid.UUID],
) -> dict:
    payload_str = json.dumps(raw_payload)

    docs_context = "No relevant internal documentation matched this payload."
    try:
        # Not tied to a specific user's personal KB — triage runs org/group-wide, so we
        # search group-scoped docs only (a synthetic "no personal KB" retrieval). An agent
        # with no group restriction (group_ids empty, i.e. "org-wide" per the Agent model)
        # searches every group's docs, same as a superuser would — an empty group_ids list
        # would otherwise match nothing, since array-overlap with an empty array is never true.
        results = retrieve(
            db,
            query=payload_str[:2000],
            user_id=uuid.uuid4(),
            group_ids=group_ids,
            is_superuser=not group_ids,
            limit=3,
        )
        if results:
            docs_context = "\n---\n".join(f"[{r.document.title}]\n{r.chunk.content[:800]}" for r in results)
    except Exception:
        pass  # embedding/DB hiccup shouldn't block triage — fall back to the default context string

    prompt = TRIAGE_PROMPT_TEMPLATE.format(
        agent_name=agent_name,
        triage_prompt=triage_prompt,
        severity_rule=severity_rule,
        docs_context=docs_context,
        payload_str=payload_str,
    )

    llm = get_llm()
    raw = llm.chat(
        [
            {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    try:
        parsed = json.loads(_strip_code_fences(raw))
    except json.JSONDecodeError:
        parsed = {}

    return {
        "summary": parsed.get("summary", "Alert triaged by SRE Agent."),
        "is_real_issue": parsed.get("is_real_issue", True),
        "noise_reason": parsed.get("noise_reason", "Validated against alert criteria."),
        "impact_level": parsed.get("impact_level", "Critical"),
        "root_cause_hypothesis": parsed.get("root_cause_hypothesis", "Resource limit or target timeout."),
        "step_by_step_remediation": parsed.get("step_by_step_remediation", ["Inspect logs", "Check metrics"]),
        "runbook_url": parsed.get("runbook_url", ""),
        "recommended_action": parsed.get("recommended_action", "Investigate service health"),
        "estimated_resolution_minutes": parsed.get("estimated_resolution_minutes", 15),
    }
