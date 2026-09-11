"""Shared `integration_scope` lookup — docs/03-agent-and-integrations.md §4.

Extracted out of `app/agents/live_ops_agents.py` so `app/services/cli_executor.py`
(docs/10-nl-to-cli-execution.md) can use the exact same group-scoping logic instead of
duplicating it — there must be exactly one place that decides "which
clusters/accounts/log-groups can this user's groups reach."
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IntegrationScope


def scopes_for(
    db: Session, group_ids: list[uuid.UUID], integration_type: str
) -> list[IntegrationScope]:
    if not group_ids:
        return []
    stmt = select(IntegrationScope).where(
        IntegrationScope.group_id.in_(group_ids),
        IntegrationScope.integration_type == integration_type,
    )
    return list(db.execute(stmt).scalars().all())
