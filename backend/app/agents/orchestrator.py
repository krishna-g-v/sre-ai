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
import uuid
from typing import Literal, TypedDict

from sqlalchemy.orm import Session
from langgraph.graph import StateGraph, END

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
about, a natural follow-up), classify it the same way as that ongoing topic.

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
        group_ids = [uuid.UUID(g) for g in state["group_ids"]]
        message = state["query"]
        results = []
        lowered = message.lower()
        if any(k in lowered for k in ("pod", "deployment", "namespace", "cluster", "kubectl", "eks")):
            results.append(("EKS/kubectl", k8s_get_pods(db, group_ids, "default")))
        if any(k in lowered for k in ("log", "cloudwatch")):
            results.append(("CloudWatch", cloudwatch_query_logs(db, group_ids, message)))
        if "alert" in lowered or "grafana" in lowered:
            results.append(("Grafana", grafana_get_active_alerts(db, group_ids)))
        if "metric" in lowered or "prometheus" in lowered:
            results.append(("Prometheus", prometheus_instant_query(db, group_ids, message)))

        if not results:
            results.append(("EKS/kubectl", k8s_get_pods(db, group_ids, "default")))

        tool_output = "\n\n".join(f"[{name}]\n{output}" for name, output in results)
        messages = [
            {
                "role": "system",
                "content": "You are an SRE Agent. Summarize the live investigation tool output "
                "below for the engineer. Be advisory only: never claim to have taken any action. "
                "If tools report 'not configured', tell the user plainly. Format with Markdown "
                "(lists, bold, code blocks) where it helps readability.",
            },
            *_history_messages(state.get("history", [])),
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
