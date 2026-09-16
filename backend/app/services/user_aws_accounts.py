"""Per-user AWS account lookup — docs/10-nl-to-cli-execution.md §9.

Parallel to app/services/integration_scopes.py's group-scoped lookup, but personal to
the requesting user: used by the NL-to-CLI pipeline (app/services/cli_executor.py,
app/agents/cli_agent.py) and, per docs/11-network-topology-visualization.md, the VPC
topology tool (app/services/vpc_topology.py) — not by the hand-written tools in
app/agents/live_ops_agents.py, which stay on the group-scoped IntegrationScope model.

`resolve_account`/`account_config` originated in cli_executor.py and were lifted here
once vpc_topology.py needed the exact same "ask, don't guess" account-disambiguation
logic — a second copy of that logic would be a real correctness risk (the two pipelines
disagreeing on how ambiguity is handled), not just duplication.
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


def resolve_account(
    accounts: list[UserAwsAccount], account_label: str | None
) -> UserAwsAccount | str:
    """The single account to run against, or an error string to return to the caller
    directly. Ambiguity is never silently guessed at — with more than one account and
    no label, this asks rather than picking one or fanning out across all of them."""
    if account_label:
        matched = [a for a in accounts if a.label == account_label]
        if not matched:
            configured = ", ".join(a.label for a in accounts)
            return f"Rejected: no AWS account named '{account_label}' is registered. Configured: {configured}"
        return matched[0]
    if len(accounts) == 1:
        return accounts[0]
    configured = ", ".join(a.label for a in accounts)
    return f"Multiple AWS accounts are registered: {configured}. Please specify which account."


def describe_known_accounts(db: Session, user_id: uuid.UUID) -> str:
    """Human-readable "Known AWS accounts" listing for an LLM prompt — shared by the
    NL-to-CLI generator (app/agents/cli_agent.py) and, per
    docs/11-network-topology-visualization.md §3, the VPC topology intent classifier
    (app/agents/orchestrator.py), both of which need the same account labels/ids/
    regions to resolve an "account_label" field from a question. Originated in
    cli_agent.py as `_describe_known_resources`; lifted here once a second caller
    needed the exact same listing, same reasoning as `resolve_account`/`account_config`
    above."""
    accounts = accounts_for(db, user_id)
    if not accounts:
        return "(no AWS accounts registered — tell the user to add one under Settings → AWS Accounts)"
    return "\n".join(f"- {a.label} (account {a.account_id or '?'}, region {a.region or '?'})" for a in accounts)


def account_config(account: UserAwsAccount) -> dict:
    return {
        "role_arn": account.role_arn,
        "external_id": account.external_id or None,
        "region": account.region,
        # optional — falls back to the shared ambient base identity when unset,
        # per aws_session.py's _base_session_kwargs (docs/10 §9)
        "access_key_id": account.access_key_id or None,
        "secret_access_key": account.secret_access_key or None,
    }
