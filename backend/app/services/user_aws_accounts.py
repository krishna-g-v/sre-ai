"""Per-user AWS account lookup — docs/10-nl-to-cli-execution.md §9.

Parallel to app/services/integration_scopes.py's group-scoped lookup, but personal to
the requesting user: used only by the NL-to-CLI pipeline (app/services/cli_executor.py,
app/agents/cli_agent.py), not by the hand-written tools in app/agents/live_ops_agents.py
which stay on the group-scoped IntegrationScope model.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import UserAwsAccount


def accounts_for(db: Session, user_id: uuid.UUID) -> list[UserAwsAccount]:
    stmt = (
        select(UserAwsAccount)
        .where(UserAwsAccount.user_id == user_id)
        .order_by(UserAwsAccount.label)
    )
    return list(db.execute(stmt).scalars().all())
