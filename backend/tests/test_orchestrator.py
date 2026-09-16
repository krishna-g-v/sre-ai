"""Unit tests for the new VPC-topology routing/synthesis helpers in
app/agents/orchestrator.py — docs/11-network-topology-visualization.md §3, §7.

Only the two new pure(ish) functions are covered here (LLM mocked, no DB) — the rest of
orchestrator.py's node functions close over a real `db` via `build_orchestrator_graph(db)`
and this repo's convention is to exercise that wiring through tests/e2e/ against a real
running stack, not a mocked one (see docs/10-nl-to-cli-execution.md §9's note on
user_settings.py for the same reasoning).
"""

import json
from unittest.mock import MagicMock

from app.agents.orchestrator import (
    _classify_topology_intent,
    _synthesize_topology_answer,
)
from app.services.topology_mermaid import to_mermaid
from app.services.vpc_topology import TopologyResult, VpcNode


def _llm(*responses):
    mock = MagicMock()
    mock.chat.side_effect = list(responses)
    return mock


def test_classify_topology_intent_parses_vpc_and_account_label():
    llm = _llm(json.dumps({"is_topology": True, "vpc": "vpc-0abc123", "account_label": "prod"}))
    result = _classify_topology_intent(llm, "map out the peering for vpc-0abc123 in prod", [], "- prod (account 1, region us-east-1)")
    assert result == {"is_topology": True, "vpc": "vpc-0abc123", "account_label": "prod"}


def test_classify_topology_intent_defaults_missing_vpc_to_empty_string():
    llm = _llm(json.dumps({"is_topology": True}))
    result = _classify_topology_intent(llm, "show me the network topology", [], "(no AWS accounts registered)")
    assert result == {"is_topology": True, "vpc": "", "account_label": None}


def test_classify_topology_intent_false_when_llm_says_false():
    llm = _llm(json.dumps({"is_topology": False}))
    result = _classify_topology_intent(llm, "how many EBS volumes are there", [], "")
    assert result == {"is_topology": False}


def test_classify_topology_intent_fails_closed_on_unparseable_response():
    llm = _llm("not json at all")
    result = _classify_topology_intent(llm, "anything", [], "")
    assert result == {"is_topology": False}


def test_classify_topology_intent_fails_closed_on_non_dict_json():
    llm = _llm(json.dumps(["is_topology", True]))
    result = _classify_topology_intent(llm, "anything", [], "")
    assert result == {"is_topology": False}


def _topology_result() -> TopologyResult:
    root = VpcNode(vpc_id="vpc-root", cidr="10.0.0.0/16", name="app-prod")
    return TopologyResult(account_label="nonprod", region="us-east-1", root=root, warnings=[])


def test_synthesize_topology_answer_appends_the_exact_mermaid_diagram():
    result = _topology_result()
    llm = _llm("Here's what I found about vpc-root.")
    answer = _synthesize_topology_answer(llm, "what does vpc-root look like?", [], result)

    assert answer.startswith("Here's what I found about vpc-root.")
    assert f"```mermaid\n{to_mermaid(result)}\n```" in answer


def test_synthesize_topology_answer_strips_a_hallucinated_mermaid_block_from_the_narrative():
    """Regression test: found live (2026-09-15, real AWS account) that the model drew its
    own fabricated mermaid diagram despite the prompt telling it not to — a prompt
    instruction alone wasn't a reliable guardrail. Exactly one mermaid block (the real,
    deterministically-generated one) must survive."""
    result = _topology_result()
    llm = _llm(
        "Here's the topology.\n\n```mermaid\ngraph LR\n  fake[Fabricated Node]\n```\n\nHope that helps!"
    )
    answer = _synthesize_topology_answer(llm, "question", [], result)

    assert answer.count("```mermaid") == 1
    assert "fake" not in answer
    assert "Fabricated Node" not in answer
    assert "Here's the topology." in answer
    assert "Hope that helps!" in answer
    assert f"```mermaid\n{to_mermaid(result)}\n```" in answer


def test_synthesize_topology_answer_sends_counts_summary_not_raw_result_object():
    result = _topology_result()
    llm = _llm("narrative")
    _synthesize_topology_answer(llm, "question", [], result)

    sent_messages = llm.chat.call_args[0][0]
    user_content = sent_messages[-1]["content"]
    assert "VPC vpc-root" in user_content
    assert "Subnets: 0" in user_content


def test_synthesize_topology_answer_includes_history():
    result = _topology_result()
    llm = _llm("narrative")
    history = [{"role": "user", "content": "earlier turn"}, {"role": "assistant", "content": "earlier answer"}]
    _synthesize_topology_answer(llm, "question", history, result)

    sent_messages = llm.chat.call_args[0][0]
    assert {"role": "user", "content": "earlier turn"} in sent_messages
    assert {"role": "assistant", "content": "earlier answer"} in sent_messages
