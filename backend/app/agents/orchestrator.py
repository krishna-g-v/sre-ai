"""Orchestrator + Supervisor graph — docs/08-chat-sessions-and-orchestration.md,
docs/03-agent-and-integrations.md §1.

A LangGraph StateGraph: classify -> route to (general | document_topic -> RAG | live_ops
-> domain tools) -> respond. Session pin/drift state (docs/08 §5-6) is decided here and
applied by the caller (app/api/routes/chat.py), which owns the DB write for the session row.

Every LLM call in this module — classification, drift-check, and the actual answers — is
given the recent conversation history, not just the latest message in isolation. Short
follow-ups ("what next?", "ad uid it is") are only interpretable in light of what was just
discussed; classifying/answering them one message at a time is what causes both
misclassification (an on-topic follow-up read as unrelated) and ungrounded answers (a
context-free guess instead of using the pinned document or prior turns).
"""

import json
import re
import uuid
from typing import Literal, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from app.agents.cli_agent import answer_with_generated_cli
from app.agents.live_ops_agents import (
    cloudwatch_query_logs,
    grafana_get_active_alerts,
    k8s_get_pods,
    prometheus_instant_query,
)
from app.agents.rag_agent import contextualized_search_query, run_rag
from app.core.config import get_settings
from app.services.llm import get_llm
from app.services.retrieval import find_dominant_document, retrieve
from app.services.topology_mermaid import to_mermaid
from app.services.user_aws_accounts import describe_known_accounts
from app.services.vpc_topology import (
    TopologyResult,
    describe_vpc_topology,
    summarize_counts,
)

Category = Literal["general", "document_topic", "live_ops"]

CLASSIFY_PROMPT = """Classify the user's NEWEST message into exactly one category. Respond
with ONLY a JSON object: {"category": "general" | "document_topic" | "live_ops"}

This assistant does not hold open-ended conversations and does not answer from its own
general/outside knowledge — it only answers using internal documentation. So classify
aggressively toward "document_topic": the instant a message contains ANY content beyond a
bare greeting/thanks/goodbye — a statement about the user ("I'm a new joinee", "I just
started"), a request for help, a vague question, anything — it is "document_topic", even if
it isn't phrased as a formal question and even if you doubt the documentation covers it.
Whether it's actually covered gets decided later, by retrieval — your job here is only to
decide it isn't a bare social nicety.

Use the conversation so far for context before deciding — a short message like "what next?"
or a one-word answer to a question the assistant just asked only makes sense in light of what
was just discussed. If the newest message reads as a continuation of the topic already being
discussed (answering the assistant's last question, naming something the assistant just asked
about, a natural follow-up), classify it the same way as that ongoing topic — including when
that means "live_ops", not just "document_topic". Concretely: if the assistant's last turn ran
a live investigation (listed clusters, pods, deployments, logs, metrics, alerts — anything
about AWS/EKS/Grafana/Prometheus), a follow-up continuing that same investigation ("list the
pods in <cluster the assistant just named>", "what about that namespace", "show me its logs")
is "live_ops" too, even if the follow-up message itself doesn't repeat words like "pod" or
"cluster". The "classify aggressively toward document_topic" instruction below is about
default-when-genuinely-unclear, not about overriding an obvious live-ops continuation.

- "general": ONLY a bare greeting, thanks, or goodbye and NOTHING else — "hi", "hello",
  "good morning", "thanks!", "bye". If the message does anything more than that, it is not
  "general".
- "document_topic": the default for everything else — statements, questions, vague requests,
  anything that could plausibly relate to internal documentation, including short follow-ups
  continuing such a conversation. If you are unsure, choose this one.
- "live_ops": a question specifically about live/current production state — pods, deployments,
  logs, metrics, dashboards, active alerts (AWS/EKS/Grafana/Prometheus) — not general how-to
  questions about those systems.

Conversation so far:
{history}

Newest message: {message}"""

DRIFT_PROMPT = """This chat session is pinned to one document, titled "{title}". The assistant
must only answer questions about that document; anything genuinely unrelated should be
redirected to a new session.

Use the conversation so far to judge this, not the newest message alone — a short reply like
"ad uid it is" or "what next?" is ON topic if it's answering or following up on what the
assistant itself just said, even if it doesn't repeat the document's title or obvious keywords.
Only mark it as drifted if the newest message is a genuinely different subject from the thread
of conversation that's been happening, not merely because it's short or terse.

Respond with ONLY a JSON object:
{"on_topic": true | false, "drifted_topic_label": "<short label if drifted, else empty>"}

Conversation so far:
{history}

Newest message: {message}"""

# docs/11-network-topology-visualization.md §3 — a small, dedicated classification call
# ahead of the CLI generator in live_ops_node, not a keyword match (docs/11 §1's
# "Routing" decision) and not a field folded into the CLI generator's own prompt (the
# generator shouldn't need to know about a capability it never invokes itself — same
# reasoning CLASSIFY_PROMPT/DRIFT_PROMPT above are two separate calls, not one).
TOPOLOGY_CLASSIFY_PROMPT = """The user's message is already known to be about live AWS \
infrastructure. Decide specifically whether it is a request to visualize/describe a VPC's \
network topology as a whole — its subnets, gateways, VPC peering, Site-to-Site VPN, or \
Transit Gateway attachments — as opposed to a narrower question about one specific resource \
(e.g. "how many EBS volumes", "list EKS clusters", "show logs for X") that the existing AWS \
CLI pipeline already handles well and should keep handling.

Respond with ONLY a JSON object:
{"is_topology": true, "vpc": "<vpc-id or Name tag, or empty string if not named>", "account_label": "<only if more than one AWS account is known, else omit>"}
or
{"is_topology": false}

Use the conversation history to resolve "that VPC"/"it" to something named earlier, the same \
way you would for any other follow-up. If no VPC is named anywhere in the conversation, leave \
"vpc" as an empty string rather than guessing — the tool itself will ask the user to pick one \
if the account has more than one VPC.

Known AWS accounts for this user:
{accounts}

Conversation so far:
{history}

Newest message: {message}"""

TOPOLOGY_SYNTHESIZE_SYSTEM_PROMPT = """You are an SRE Agent. Answer the engineer's question \
about a VPC's network topology using the structured summary below.

Do NOT include a ```mermaid code block, or any other diagram, anywhere in your response — \
not even a small or partial one. A real diagram of the actual topology, generated separately \
from the exact same data, is appended after your reply automatically. Your job is ONLY the \
prose/Markdown answer (lists, bold) using the counts and facts given below — never attempt to \
draw, sketch, or describe the diagram's shape yourself, and never invent node/resource names \
that aren't in the summary.

Be advisory only — never claim to have taken any action. If the summary notes anything that \
could not be fully determined, say so plainly rather than guessing what it would have shown. \
Directly address what the engineer actually asked (e.g. if they asked specifically about VPN \
or peering, lead with that) rather than just restating every count generically."""

# Defense in depth for the "don't draw a diagram yourself" instruction above: found live
# (2026-09-15, real account 907986008762) that the model drew its own fabricated mermaid
# block anyway despite the prompt — a prompt instruction alone wasn't enough, so this
# strips any mermaid fence out of the narrative before the real, deterministically-
# generated diagram is appended. Same principle as cli_validator.py being a hard gate
# rather than a prompt instruction: nothing here trusts the LLM to have complied.
_MERMAID_FENCE_RE = re.compile(r"```mermaid.*?```", re.DOTALL | re.IGNORECASE)

# How many recent messages (user+assistant turns combined) to feed into every LLM call in
# this module. Applied once where history enters the graph (app/api/routes/chat.py) — every
# node here just uses whatever list it's given.
HISTORY_WINDOW = 20


def _format_history(history: list[dict]) -> str:
    if not history:
        return "(this is the first message in the session)"
    speaker = {"user": "User", "assistant": "Assistant"}
    return "\n".join(f"{speaker.get(m['role'], m['role'])}: {m['content']}" for m in history)


def _history_messages(history: list[dict]) -> list[dict]:
    """As chat-completion messages, for LLM calls that should see the actual conversation
    turns (answering), as opposed to ones that just need it as read-only context (classify/
    drift, which embed it as text inside a single instruction prompt instead)."""
    return [{"role": m["role"], "content": m["content"]} for m in history]


class OrchestratorState(TypedDict, total=False):
    query: str
    history: list[dict]
    user_id: str
    group_ids: list[str]
    is_superuser: bool
    session_status: str
    pinned_document_id: str | None
    pinned_document_title: str | None
    category: Category
    answer: str
    retrieved_titles: list[str]
    new_pinned_document_id: str | None
    drifted: bool
    drifted_topic_label: str


def _classify(llm, message: str, history: list[dict]) -> Category:
    prompt = CLASSIFY_PROMPT.replace("{history}", _format_history(history)).replace("{message}", message)
    raw = llm.chat([{"role": "user", "content": prompt}], temperature=0.0)
    try:
        parsed = json.loads(raw.strip().strip("`").removeprefix("json").strip())
        category = parsed.get("category")
        if category in ("general", "document_topic", "live_ops"):
            return category
    except (json.JSONDecodeError, AttributeError):
        pass
    return "general"


def _classify_topology_intent(llm, message: str, history: list[dict], accounts_description: str) -> dict:
    """{"is_topology": False} on any parse failure or an explicit "false" — same
    fail-closed default as `_classify` above, so a malformed LLM response falls through
    to the existing CLI-generator/fixed-tool flow rather than blocking it."""
    prompt = (
        TOPOLOGY_CLASSIFY_PROMPT.replace("{accounts}", accounts_description)
        .replace("{history}", _format_history(history))
        .replace("{message}", message)
    )
    raw = llm.chat([{"role": "user", "content": prompt}], temperature=0.0)
    try:
        parsed = json.loads(raw.strip().strip("`").removeprefix("json").strip())
    except (json.JSONDecodeError, AttributeError):
        return {"is_topology": False}
    if not isinstance(parsed, dict) or not parsed.get("is_topology"):
        return {"is_topology": False}
    return {
        "is_topology": True,
        "vpc": parsed.get("vpc") or "",
        "account_label": parsed.get("account_label") or None,
    }


def _synthesize_topology_answer(llm, message: str, history: list[dict], result: TopologyResult) -> str:
    """The LLM only ever sees the mechanically-computed counts summary (`summarize_counts`)
    as ground truth, never the raw AWS API responses — and the Mermaid diagram itself is
    appended verbatim afterward, never generated or paraphrased by the model, so a diagram
    syntax error or a hallucinated resource can't reach the user's screen.

    The prompt tells the model not to draw a diagram itself, but that alone proved
    insufficient live (see `_MERMAID_FENCE_RE`'s comment) — any mermaid fence the
    narrative contains anyway is stripped here before the real one is appended, so a
    non-compliant response degrades to "missing narrative content," never "two diagrams,
    one of them fabricated."
    """
    messages = [
        {"role": "system", "content": TOPOLOGY_SYNTHESIZE_SYSTEM_PROMPT},
        *_history_messages(history),
        {"role": "user", "content": f"Question: {message}\n\nTopology summary:\n{summarize_counts(result)}"},
    ]
    narrative = llm.chat(messages)
    narrative = _MERMAID_FENCE_RE.sub("", narrative).strip()
    return f"{narrative}\n\n```mermaid\n{to_mermaid(result)}\n```"


def _check_drift(llm, pinned_title: str, message: str, history: list[dict]) -> tuple[bool, str]:
    prompt = (
        DRIFT_PROMPT.replace("{title}", pinned_title)
        .replace("{history}", _format_history(history))
        .replace("{message}", message)
    )
    raw = llm.chat([{"role": "user", "content": prompt}], temperature=0.0)
    try:
        parsed = json.loads(raw.strip().strip("`").removeprefix("json").strip())
        return (not parsed.get("on_topic", True), parsed.get("drifted_topic_label", ""))
    except (json.JSONDecodeError, AttributeError):
        return (False, "")


def build_orchestrator_graph(db: Session):
    llm = get_llm()
    settings = get_settings()

    def classify_node(state: OrchestratorState) -> OrchestratorState:
        state["category"] = _classify(llm, state["query"], state.get("history", []))
        return state

    def general_node(state: OrchestratorState) -> OrchestratorState:
        # Reached only for a bare greeting/thanks/goodbye (see CLASSIFY_PROMPT) — this
        # assistant doesn't hold open-ended conversations, so the reply stays to one short,
        # plain sentence. In particular: never invent a bullet-point menu of "things I can
        # help with" — the model doesn't actually know what topics the knowledge base
        # covers well enough to promise categories, and that fabricated-sounding menu is
        # exactly the pattern that prompted this instruction.
        messages = [
            {
                "role": "system",
                "content": "You are an SRE Agent assistant. The user just sent a bare greeting, "
                "thanks, or goodbye — reply in ONE short, plain sentence, no Markdown, no bullet "
                "lists, no headings. Do not list categories or examples of what you can help "
                "with — you don't know the knowledge base's contents well enough to promise "
                "specific topics. If it's a greeting (not thanks/goodbye), you may briefly invite "
                "them to ask a question, phrased generically (e.g. 'happy to help — what would "
                "you like to know?'), without naming specific subjects.",
            },
            *_history_messages(state.get("history", [])),
            {"role": "user", "content": state["query"]},
        ]
        state["answer"] = llm.chat(messages)
        state["retrieved_titles"] = []
        return state

    def live_ops_node(state: OrchestratorState) -> OrchestratorState:
        user_id = uuid.UUID(state["user_id"])
        group_ids = [uuid.UUID(g) for g in state["group_ids"]]
        message = state["query"]
        history = state.get("history", [])
        lowered = message.lower()

        # docs/11-network-topology-visualization.md §3 — tried first, ahead of the CLI
        # generator below: a topology question needs the multi-call boto3 tool
        # (app/services/vpc_topology.py), not a single generated aws/kubectl command.
        # LLM-classified, not a keyword match, per docs/11 §1's "Routing" decision.
        accounts_description = describe_known_accounts(db, user_id)
        topology_intent = _classify_topology_intent(llm, message, history, accounts_description)
        if topology_intent["is_topology"]:
            result = describe_vpc_topology(
                db, user_id, vpc_identifier=topology_intent["vpc"], account_label=topology_intent["account_label"]
            )
            # A string result is already a direct, final answer (not-configured,
            # ambiguous account/VPC, or an AssumeRole failure) — same convention
            # `cli_executor.py`'s functions use, surfaced as-is rather than passed
            # through an LLM that has nothing useful to add to it.
            state["answer"] = (
                result if isinstance(result, str) else _synthesize_topology_answer(llm, message, history, result)
            )
            state["retrieved_titles"] = []
            return state

        # Always try the per-user CLI pipeline (docs/10 §9) next — unconditionally,
        # not gated on keywords. This node is only ever reached once the classifier
        # has already decided the message is "live_ops" (see the conditional edges
        # below), so a second keyword filter here is both redundant and actively
        # harmful: found live that a natural follow-up like "which is the largest in
        # size of those" (no "pod"/"cluster"/"eks"/etc. in it at all) correctly
        # classified as live_ops but then got silently blocked from ever reaching the
        # CLI generator by an earlier version of this gate, even though the generator
        # itself resolves it perfectly given the conversation history. Falls through
        # to the fixed tools below only if the CLI generator itself can't produce an
        # answer, so a group that *does* have integration_scope configured (docs/09
        # §3) still benefits from them.
        generated_answer = answer_with_generated_cli(
            db,
            user_id,
            message,
            llm,
            history=history,
            group_ids=group_ids,
            is_superuser=state.get("is_superuser", False),
        )
        if generated_answer is not None:
            state["answer"] = generated_answer
            state["retrieved_titles"] = []
            return state

        results = []
        if any(k in lowered for k in ("pod", "deployment", "namespace", "cluster", "kubectl", "eks")):
            results.append(("EKS/kubectl", k8s_get_pods(db, group_ids, "default")))
        if any(k in lowered for k in ("log", "cloudwatch")):
            results.append(("CloudWatch", cloudwatch_query_logs(db, group_ids, message)))
        if "alert" in lowered or "grafana" in lowered:
            results.append(("Grafana", grafana_get_active_alerts(db, group_ids)))
        if "metric" in lowered or "prometheus" in lowered:
            results.append(("Prometheus", prometheus_instant_query(db, group_ids, message)))

        if not results:
            # Not AWS/EKS-flavored (so the CLI pipeline above never ran), or it did run
            # and declined outright — say so plainly instead of silently substituting
            # an unrelated tool's output (found via live testing to be actively
            # misleading: e.g. a question like "how many EBS volumes" has nothing to
            # do with EKS pods).
            state["answer"] = (
                "I wasn't able to work out a specific investigation command for that — "
                "try naming the exact AWS/EKS resource or account, or rephrase the question."
            )
            state["retrieved_titles"] = []
            return state

        tool_output = "\n\n".join(f"[{name}]\n{output}" for name, output in results)
        messages = [
            {
                "role": "system",
                "content": "You are an SRE Agent. Summarize the live investigation tool output "
                "below for the engineer. Be advisory only: never claim to have taken any action. "
                "If tools report 'not configured', tell the user plainly. Format with Markdown "
                "(lists, bold, code blocks) where it helps readability.",
            },
            *_history_messages(history),
            {"role": "user", "content": f"Question: {state['query']}\n\nTool output:\n{tool_output}"},
        ]
        state["answer"] = llm.chat(messages)
        state["retrieved_titles"] = []
        return state

    def document_topic_node(state: OrchestratorState) -> OrchestratorState:
        user_id = uuid.UUID(state["user_id"])
        group_ids = [uuid.UUID(g) for g in state["group_ids"]]
        is_superuser = state.get("is_superuser", False)
        history = state.get("history", [])
        pinned_document_id = uuid.UUID(state["pinned_document_id"]) if state.get("pinned_document_id") else None

        if pinned_document_id is not None:
            drifted, label = _check_drift(llm, state.get("pinned_document_title", ""), state["query"], history)
            if drifted:
                state["drifted"] = True
                state["drifted_topic_label"] = label
                state["answer"] = (
                    f"This looks like a different topic than \"{state.get('pinned_document_title')}\". "
                    "Start a new chat session to ask about that."
                )
                state["retrieved_titles"] = []
                return state

            answer, results = run_rag(
                db, query=state["query"], user_id=user_id, group_ids=group_ids,
                pinned_document_id=pinned_document_id, is_superuser=is_superuser, history=history,
            )
            state["answer"] = answer
            state["retrieved_titles"] = [r.document.title for r in results]
            state["drifted"] = False
            return state

        # Not yet pinned — try to find a dominant match to auto-pin (docs/08 §5). Same
        # context-enrichment as run_rag's own retrieval, for the same reason: a short
        # follow-up needs the recent conversation to mean anything as a search query.
        search_query = contextualized_search_query(state["query"], history)
        results = retrieve(db, query=search_query, user_id=user_id, group_ids=group_ids, is_superuser=is_superuser)
        dominant_id = find_dominant_document(results, settings.dominant_match_margin)

        answer, used = run_rag(
            db, query=state["query"], user_id=user_id, group_ids=group_ids,
            pinned_document_id=dominant_id, is_superuser=is_superuser, history=history,
        )
        state["answer"] = answer
        state["retrieved_titles"] = [r.document.title for r in used]
        if dominant_id is not None:
            state["new_pinned_document_id"] = str(dominant_id)
        state["drifted"] = False
        return state

    def route(state: OrchestratorState) -> str:
        return state["category"]

    graph = StateGraph(OrchestratorState)
    graph.add_node("classify", classify_node)
    graph.add_node("general", general_node)
    graph.add_node("document_topic", document_topic_node)
    graph.add_node("live_ops", live_ops_node)

    graph.set_entry_point("classify")
    graph.add_conditional_edges(
        "classify",
        route,
        {"general": "general", "document_topic": "document_topic", "live_ops": "live_ops"},
    )
    graph.add_edge("general", END)
    graph.add_edge("document_topic", END)
    graph.add_edge("live_ops", END)

    return graph.compile()
