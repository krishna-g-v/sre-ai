"""NL-to-CLI generation pipeline — docs/10-nl-to-cli-execution.md §2, §9.

Reached from app/agents/orchestrator.py's live_ops_node as the fallback for a live-ops
question that doesn't match one of the fixed tools in app/agents/live_ops_agents.py
(docs/09-ops-runbook-and-proactive-monitoring.md §3 stays the primary, tested path for
common questions — see docs/10 §1's "complement, not replace" decision).

Pipeline: RAG-style few-shot retrieval (cli_examples.py) -> LLM generates a command ->
the read-only validator+executor (cli_validator.py/cli_executor.py) -> bounded self-
correction on error -> a final LLM pass turns the raw output into the answer. This
module only ever calls `run_readonly_aws`/`run_readonly_kubectl` — it has no path to
anything mutating, by construction (docs/03-agent-and-integrations.md §3).

AWS access is resolved from the requesting user's own registered accounts
(`user_aws_accounts`, docs/10 §9's Settings page), not the group-scoped
`IntegrationScope` model the fixed tools use — specific resource names (cluster/repo/
log-group) aren't pre-registered anywhere either, only accounts are, so the LLM is
expected to discover them via read commands (`aws eks list-clusters`, ...) or resolve
them from conversation history, not read them off a pre-built list.
"""

import json
import uuid

from sqlalchemy.orm import Session

from app.agents.rag_agent import contextualized_search_query
from app.services.cli_examples import get_similar_examples
from app.services.cli_executor import (
    TRUNCATION_MARKER,
    run_readonly_aws,
    run_readonly_kubectl,
)
from app.services.llm import LLMAdapter
from app.services.retrieval import retrieve
from app.services.user_aws_accounts import accounts_for

_DOC_CONTEXT_LIMIT = 3

MAX_RETRIES = 2

GENERATE_SYSTEM_PROMPT = """You are an SRE assistant that answers live-infrastructure \
questions by generating a single read-only aws CLI or kubectl command, the same way an \
engineer would investigate by hand.

Rules:
- Only ever generate a read/describe/list/get command. Never delete/apply/patch/exec/\
scale/create/update/terminate/drain/cordon/label/annotate/rollout-restart, or any other \
command that changes state — you will be rejected and asked to correct it if you do.
- "Known AWS accounts" below lists which accounts you can run commands against — it is \
NOT a list of specific resources (clusters, repos, log groups, VPCs, ...). Those aren't \
pre-registered; discover them yourself with a read command (e.g. `aws eks list-clusters`, \
`aws ecr describe-repositories`), or resolve them from something already named earlier \
in this conversation.
- Use the conversation history to resolve anything the user didn't spell out again — \
e.g. if a prior turn's command output already named a specific cluster/repo/log-group \
and the new question says "that cluster", "the one above", or otherwise clearly \
continues the same thread, resolve it from history rather than treating it as missing.
- If more than one AWS account is listed under "Known AWS accounts", you MUST include a \
top-level "account_label" field naming exactly one of them (resolved from this question \
or from history). Omit it if only one account is listed.
- kubectl has no flag to select which cluster it talks to, and cluster names are never \
pre-registered — for every kubectl command you MUST include a top-level "cluster_name" \
field with the exact cluster name (from this question, or from an earlier turn's `aws \
eks list-clusters`/similar output in history). If you don't actually know the cluster \
name yet, generate `aws eks list-clusters` first instead of guessing one.
- If the question cannot be answered with a single read-only aws/kubectl command, or \
needs a resource name you have no way to know, respond with \
{"cannot_answer": true, "reason": "<short reason>"} instead of a command.
- aws CLI JSON output is verbose by default (every field of every object) and gets \
truncated past a size limit — a handful of EC2 instances' full describe-instances output \
alone can exceed it. Ask for only what the question needs, using --query (JMESPath) and \
--output: a count ("how many") is `--query 'length(Reservations[].Instances[])'`, a list \
of names/ids is `--query 'Reservations[].Instances[].InstanceId'` (or the equivalent \
projection for the resource in question), not the bare, unfiltered command. Reserve the \
unfiltered form only for when the user actually wants full detail on one specific, \
already-identified resource.
- JMESPath does not support SQL-style `as` aliasing or comma-separated top-level \
expressions — `length(X) as count` is invalid and will be rejected. To return more than \
one computed value in one query (e.g. a count *and* the largest item), use multi-select \
hash syntax: `--query '{count: length(X), largest: sort_by(X, &Size)[-1]}'`.
- "Relevant internal documentation" below (if any) is real content from this user's \
knowledge base — runbooks, naming conventions, prior incident notes. Use it to pick a \
better command when it's actually relevant (e.g. a documented resource-naming pattern, or \
a runbook naming the specific log group/cluster to check) — it never expands what you're \
allowed to run, only informs which read-only command answers the question well. If it \
isn't relevant to this question, ignore it.

Respond with ONLY a JSON object, no markdown fences, no commentary:
{"command": "<the exact aws or kubectl command>", "account_label": "<only if >1 account is known>", "cluster_name": "<only for kubectl>"}
or
{"cannot_answer": true, "reason": "<short reason>"}

Known AWS accounts for this user:
{resources}

Relevant internal documentation:
{doc_context}

Similar past examples (account/resource names are placeholders — substitute real ones \
from "Known AWS accounts" or conversation history):
{examples}"""

RETRY_PROMPT_TEMPLATE = """That command was rejected or failed:

Command: {command}
Error: {error}

Generate a corrected command for the same original question. Respond with ONLY a JSON \
object, exactly the same format as your first response — no prose, no explanation, no \
markdown fences, nothing outside the JSON object itself: \
{"command": "<the corrected command>", "account_label": "<only if >1 account is known>", "cluster_name": "<only for kubectl>"} \
or, if it genuinely can't be fixed, {"cannot_answer": true, "reason": "..."}."""

SYNTHESIZE_SYSTEM_PROMPT = """You are an SRE Agent. Turn the raw CLI output below into a \
clear answer to the engineer's question. Be advisory only — never claim to have taken any \
remediation action. If the output shows an error or an empty result, say so plainly rather \
than guessing at an explanation. Format with Markdown (lists, bold, code blocks) where it \
helps readability. State the exact command that was run, so the engineer can verify or \
rerun it themselves. If relevant internal documentation was provided alongside the command \
output, weave it in where it genuinely helps (e.g. a runbook's next steps, a known cause for \
this exact symptom) — but never state anything from it that the retrieved excerpt doesn't \
actually say, and never blend it with your own outside knowledge."""


def _describe_relevant_docs(
    db: Session,
    question: str,
    history: list[dict],
    *,
    user_id: uuid.UUID,
    group_ids: list[uuid.UUID],
    is_superuser: bool,
) -> str:
    """Same KB `retrieve()` the document_topic path uses (docs/02 §7's access-control
    filter applies identically — group + personal KB), so a live-ops question can be
    grounded in an uploaded runbook/naming-convention doc/incident note the same way an
    Ops Runbook assistant would (docs/09-ops-runbook-and-proactive-monitoring.md §4),
    not just live command output in isolation. Degrades to "none found" rather than
    failing the whole answer — an embedding hiccup or empty KB shouldn't block a
    question retrieval was never required to answer."""
    try:
        search_query = contextualized_search_query(question, history)
        results = retrieve(
            db,
            query=search_query,
            user_id=user_id,
            group_ids=group_ids,
            is_superuser=is_superuser,
            limit=_DOC_CONTEXT_LIMIT,
        )
    except Exception:
        return "(none found)"
    if not results:
        return "(none found)"
    return "\n---\n".join(
        f"[{r.document.title}]\n{r.chunk.content[:800]}" for r in results
    )


def _describe_known_resources(db: Session, user_id: uuid.UUID) -> str:
    accounts = accounts_for(db, user_id)
    if not accounts:
        return "(no AWS accounts registered — tell the user to add one under Settings → AWS Accounts)"
    return "\n".join(
        f"- {a.label} (account {a.account_id or '?'}, region {a.region or '?'})"
        for a in accounts
    )


def _extract_json(raw: str) -> dict:
    cleaned = raw.strip().strip("`")
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    return json.loads(cleaned)


def _run_command(
    db: Session,
    user_id: uuid.UUID,
    command: str,
    *,
    account_label: str | None = None,
    cluster_name: str | None = None,
) -> str:
    binary = command.strip().split(" ", 1)[0] if command.strip() else ""
    if binary == "aws":
        return run_readonly_aws(db, user_id, command, account_label=account_label)
    if binary == "kubectl":
        return run_readonly_kubectl(
            db, user_id, command, account_label=account_label, cluster_name=cluster_name
        )
    return f"Rejected: '{binary}' is not an allowed binary."


def _is_retryable_failure(output: str) -> bool:
    # A truncated-but-successful output (found via live testing: an unfiltered
    # `aws ec2 describe-instances` blew past the char cap for even a handful of
    # instances) is retryable too — the fix is the same shape as a rejected/failed
    # command: regenerate with a narrower --query, per GENERATE_SYSTEM_PROMPT's rule.
    return (
        output.startswith("Rejected:")
        or "ERROR:" in output
        or TRUNCATION_MARKER in output
    )


def answer_with_generated_cli(
    db: Session,
    user_id: uuid.UUID,
    question: str,
    llm: LLMAdapter,
    history: list[dict] | None = None,
    group_ids: list[uuid.UUID] | None = None,
    is_superuser: bool = False,
) -> str | None:
    """Returns the synthesized answer, or None if the LLM determined the question can't
    be answered this way, or its response couldn't be parsed as the expected JSON — in
    either case the caller (orchestrator.py's live_ops_node) falls back to its own
    existing default behavior rather than surfacing a confusing partial result.

    `history` matters concretely: e.g. "list the pods in it" after an earlier turn
    named a specific cluster only resolves to that cluster because the generation call
    actually sees the prior turns, not just this message in isolation — same reasoning
    as every other LLM call in app/agents/orchestrator.py (see its module docstring).

    `group_ids`/`is_superuser` are for document-KB retrieval only (docs/02 §7's access
    control), unrelated to the per-user AWS account resolution `user_id` alone already
    covers — a live-ops question also checks the knowledge base (runbooks, naming
    conventions, incident notes) alongside running commands, not just live output in
    isolation, per the user's explicit request (2026-09-11) that live-ops answers
    shouldn't skip documentation the way they previously did.
    """
    resources = _describe_known_resources(db, user_id)
    doc_context = _describe_relevant_docs(
        db,
        question,
        history or [],
        user_id=user_id,
        group_ids=group_ids or [],
        is_superuser=is_superuser,
    )
    examples = "\n".join(
        f"Q: {e['question']}\nA: {e['command']}" for e in get_similar_examples(question)
    )

    system_prompt = (
        GENERATE_SYSTEM_PROMPT.replace("{resources}", resources)
        .replace("{doc_context}", doc_context)
        .replace("{examples}", examples)
    )
    history_messages = [
        {"role": m["role"], "content": m["content"]} for m in (history or [])
    ]
    messages = [
        {"role": "system", "content": system_prompt},
        *history_messages,
        {"role": "user", "content": question},
    ]

    command: str | None = None
    output: str | None = None

    for attempt in range(MAX_RETRIES + 1):
        raw = llm.chat(messages, temperature=0.0)
        try:
            parsed = _extract_json(raw)
        except (json.JSONDecodeError, AttributeError):
            # Found via live testing: on a *retry*, the model occasionally answers
            # with something that isn't clean JSON (extra prose, a different format)
            # even though an earlier attempt in this same call already produced a
            # real command and output. Discarding that and returning None here used
            # to throw away real progress and send the caller down an unrelated
            # fallback path — if there's something usable from an earlier attempt,
            # synthesize an honest answer from it instead of giving up entirely.
            if command is None:
                return None
            break

        if parsed.get("cannot_answer"):
            if command is None:
                return None
            break

        new_command = parsed.get("command", "")
        if not new_command:
            if command is None:
                return None
            break

        command = new_command
        output = _run_command(
            db,
            user_id,
            command,
            account_label=parsed.get("account_label"),
            cluster_name=parsed.get("cluster_name"),
        )

        if not _is_retryable_failure(output):
            break
        if attempt < MAX_RETRIES:
            retry_prompt = RETRY_PROMPT_TEMPLATE.replace("{command}", command).replace(
                "{error}", output
            )
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": retry_prompt})

    if command is None or output is None:
        return None

    synthesize_messages = [
        {"role": "system", "content": SYNTHESIZE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Question: {question}\n\nCommand run: {command}\n\nOutput:\n{output}"
                f"\n\nRelevant internal documentation:\n{doc_context}"
            ),
        },
    ]
    return llm.chat(synthesize_messages)
