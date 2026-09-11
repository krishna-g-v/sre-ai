"""Unit tests for app/agents/cli_agent.py — docs/10-nl-to-cli-execution.md §2, §9.

The LLM and the underlying executor/example-retrieval/account-lookup calls are all
mocked — this tests the generate -> validate/execute -> retry -> synthesize control
flow itself, not any real model or AWS/k8s behavior (already covered by
test_cli_executor.py and test_cli_validator.py).
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.cli_agent import MAX_RETRIES, answer_with_generated_cli


@pytest.fixture(autouse=True)
def _no_doc_retrieval_by_default():
    # Every test gets this by default (real retrieve() would try loading the actual
    # embedding model, which is slow and pointless for tests that aren't specifically
    # about doc-context integration) — the one test that needs real doc content
    # overrides it locally with a nested patch of the same target.
    with patch(
        "app.agents.cli_agent._describe_relevant_docs", return_value="(none found)"
    ):
        yield


def _llm(*responses):
    mock = MagicMock()
    mock.chat.side_effect = list(responses)
    return mock


def _patches(run_readonly_aws_result="ok output"):
    return (
        patch("app.agents.cli_agent.get_similar_examples", return_value=[]),
        patch("app.agents.cli_agent.accounts_for", return_value=[]),
        patch(
            "app.agents.cli_agent.run_readonly_aws",
            return_value=run_readonly_aws_result,
        ),
    )


def test_returns_none_when_llm_declines():
    llm = _llm(json.dumps({"cannot_answer": True, "reason": "no matching resource"}))
    p1, p2, p3 = _patches()
    with p1, p2, p3:
        result = answer_with_generated_cli(
            MagicMock(), MagicMock(), "what's the weather", llm
        )

    assert result is None
    assert llm.chat.call_count == 1


def test_returns_none_on_unparseable_llm_response():
    llm = _llm("not json at all")
    p1, p2, p3 = _patches()
    with p1, p2, p3:
        result = answer_with_generated_cli(
            MagicMock(), MagicMock(), "describe the cluster", llm
        )

    assert result is None


def test_happy_path_generates_executes_and_synthesizes():
    llm = _llm(
        json.dumps({"command": "aws eks describe-cluster --name prod"}),
        "The cluster prod is running Kubernetes 1.29.",
    )
    p1, p2, p3 = _patches(run_readonly_aws_result="[nonprod]\n{...cluster json...}")
    with p1, p2, p3:
        result = answer_with_generated_cli(
            MagicMock(), MagicMock(), "what version is the cluster on", llm
        )

    assert result == "The cluster prod is running Kubernetes 1.29."
    assert llm.chat.call_count == 2  # one generate call, one synthesize call


def test_retries_once_on_rejected_command_then_succeeds():
    llm = _llm(
        json.dumps({"command": "aws eks delete-cluster --name prod"}),  # rejected
        json.dumps({"command": "aws eks describe-cluster --name prod"}),  # corrected
        "Here's the cluster info.",
    )
    p1, p2, _ = _patches()
    with (
        p1,
        p2,
        patch(
            "app.agents.cli_agent.run_readonly_aws",
            side_effect=["Rejected: kubectl verb...", "cluster info here"],
        ) as mock_run,
    ):
        result = answer_with_generated_cli(
            MagicMock(), MagicMock(), "delete the cluster", llm
        )

    assert result == "Here's the cluster info."
    assert mock_run.call_count == 2
    assert llm.chat.call_count == 3  # generate, retry-generate, synthesize
    retry_call_messages = llm.chat.call_args_list[1].args[0]
    assert any("Rejected" in m["content"] for m in retry_call_messages)


def test_gives_up_after_max_retries_but_still_synthesizes_the_failure():
    responses = [json.dumps({"command": "aws eks describe-cluster --name prod"})] * (
        MAX_RETRIES + 1
    )
    responses.append("The command kept failing — here's why.")
    llm = _llm(*responses)
    p1, p2, _ = _patches()
    with (
        p1,
        p2,
        patch(
            "app.agents.cli_agent.run_readonly_aws", return_value="ERROR: AccessDenied"
        ) as mock_run,
    ):
        result = answer_with_generated_cli(
            MagicMock(), MagicMock(), "describe the cluster", llm
        )

    assert result == "The command kept failing — here's why."
    assert mock_run.call_count == MAX_RETRIES + 1


def test_dispatches_kubectl_commands_to_run_readonly_kubectl():
    llm = _llm(
        json.dumps(
            {"command": "kubectl get pods -n payments", "cluster_name": "nonprod-a"}
        ),
        "Pods look healthy.",
    )
    p1, p2, _ = _patches()
    with (
        p1,
        p2,
        patch(
            "app.agents.cli_agent.run_readonly_kubectl", return_value="pod list"
        ) as mock_kubectl,
        patch("app.agents.cli_agent.run_readonly_aws") as mock_aws,
    ):
        result = answer_with_generated_cli(
            MagicMock(), MagicMock(), "list pods in payments", llm
        )

    assert result == "Pods look healthy."
    mock_kubectl.assert_called_once()
    mock_aws.assert_not_called()


def test_passes_conversation_history_to_the_generation_call():
    llm = _llm(
        json.dumps({"command": "aws eks describe-cluster --name prod"}), "answer"
    )
    p1, p2, p3 = _patches()
    history = [
        {"role": "user", "content": "list all the eks clusters in nonprod"},
        {"role": "assistant", "content": "Clusters: nonprod-a, nonprod-b"},
    ]
    with p1, p2, p3:
        answer_with_generated_cli(
            MagicMock(), MagicMock(), "describe nonprod-a", llm, history=history
        )

    generate_call_messages = llm.chat.call_args_list[0].args[0]
    contents = [m["content"] for m in generate_call_messages]
    assert "list all the eks clusters in nonprod" in contents
    assert "Clusters: nonprod-a, nonprod-b" in contents


def test_resolves_cluster_from_history_and_passes_it_to_kubectl_executor():
    # Mirrors the exact sample conversation: turn 1 lists clusters, turn 2 says "list
    # the pods in <name from turn 1>" — the LLM is expected to emit cluster_name
    # explicitly (per GENERATE_SYSTEM_PROMPT), and that must reach run_readonly_kubectl.
    llm = _llm(
        json.dumps(
            {"command": "kubectl get pods -n payments", "cluster_name": "nonprod-a"}
        ),
        "Here are the pods in nonprod-a.",
    )
    p1, p2, _ = _patches()
    history = [
        {"role": "user", "content": "list all the eks clusters in nonprod account"},
        {"role": "assistant", "content": "Clusters: nonprod-a, nonprod-b"},
    ]
    with (
        p1,
        p2,
        patch(
            "app.agents.cli_agent.run_readonly_kubectl", return_value="pod list"
        ) as mock_kubectl,
    ):
        result = answer_with_generated_cli(
            MagicMock(), MagicMock(), "list the pods in nonprod-a", llm, history=history
        )

    assert result == "Here are the pods in nonprod-a."
    mock_kubectl.assert_called_once()
    _, kwargs = mock_kubectl.call_args
    assert kwargs["cluster_name"] == "nonprod-a"


def test_passes_account_label_from_llm_response_to_executors():
    llm = _llm(
        json.dumps({"command": "aws eks list-clusters", "account_label": "nonprod"}),
        "Clusters in nonprod: a, b.",
    )
    p1, p2, _ = _patches()
    with (
        p1,
        p2,
        patch(
            "app.agents.cli_agent.run_readonly_aws", return_value="[nonprod]\n[]"
        ) as mock_aws,
    ):
        answer_with_generated_cli(
            MagicMock(), MagicMock(), "list clusters in nonprod", llm
        )

    _, kwargs = mock_aws.call_args
    assert kwargs["account_label"] == "nonprod"


def test_works_without_history_argument():
    llm = _llm(json.dumps({"command": "aws eks list-clusters"}), "answer")
    p1, p2, p3 = _patches()
    with p1, p2, p3:
        result = answer_with_generated_cli(
            MagicMock(), MagicMock(), "list clusters", llm
        )

    assert result == "answer"


def test_known_resources_lists_registered_accounts():
    from app.agents.cli_agent import _describe_known_resources

    account = MagicMock(label="nonprod", account_id="111111111111", region="us-east-1")
    with patch("app.agents.cli_agent.accounts_for", return_value=[account]):
        description = _describe_known_resources(MagicMock(), MagicMock())

    assert "nonprod" in description
    assert "111111111111" in description


def test_known_resources_empty_when_no_accounts_registered():
    from app.agents.cli_agent import _describe_known_resources

    with patch("app.agents.cli_agent.accounts_for", return_value=[]):
        description = _describe_known_resources(MagicMock(), MagicMock())

    assert "Settings" in description


def test_retries_on_truncated_output_and_uses_a_narrower_command():
    """Regression test for a real case hit in live testing: an unfiltered
    `aws ec2 describe-instances` truncated mid-JSON before revealing the full instance
    count, and the model correctly hedged rather than guess — the fix is generating a
    narrower --query command instead, which this exercises via the retry loop."""
    llm = _llm(
        json.dumps({"command": "aws ec2 describe-instances"}),
        json.dumps(
            {
                "command": "aws ec2 describe-instances --query 'length(Reservations[].Instances[])'"
            }
        ),
        "There are 3 EC2 instances running.",
    )
    p1, p2, _ = _patches()
    truncated_output = "[sreacc]\n{...\n... [truncated, 4000 more characters]"
    with (
        p1,
        p2,
        patch(
            "app.agents.cli_agent.run_readonly_aws",
            side_effect=[truncated_output, "[sreacc]\n3"],
        ) as mock_run,
    ):
        result = answer_with_generated_cli(
            MagicMock(), MagicMock(), "how many VMs are there", llm
        )

    assert result == "There are 3 EC2 instances running."
    assert mock_run.call_count == 2
    # the second, narrower command actually reached the executor
    second_call_command = mock_run.call_args_list[1].args[2]
    assert "--query" in second_call_command


def test_preserves_first_attempt_when_retry_response_is_unparseable():
    """Regression test for a real case hit in live testing: attempt 1 generated a
    command that failed (bad JMESPath), attempt 2's LLM response wasn't clean JSON —
    the old behavior discarded attempt 1's real progress entirely and returned None,
    which sent the caller down an unrelated fallback path. It should synthesize from
    the last real attempt instead of giving up."""
    llm = _llm(
        json.dumps({"command": "aws ec2 describe-volumes --query 'bad syntax,'"}),
        "Sorry, let me reconsider — I think the right approach here is...",  # not JSON
        "The describe-volumes query failed due to invalid syntax; here's what I tried.",
    )
    p1, p2, _ = _patches()
    with (
        p1,
        p2,
        patch(
            "app.agents.cli_agent.run_readonly_aws",
            return_value="ERROR: ParamValidation: Bad value for --query",
        ) as mock_run,
    ):
        result = answer_with_generated_cli(
            MagicMock(), MagicMock(), "how many volumes", llm
        )

    assert (
        result
        == "The describe-volumes query failed due to invalid syntax; here's what I tried."
    )
    assert mock_run.call_count == 1  # never got a second valid command to try
    assert (
        llm.chat.call_count == 3
    )  # generate, unparseable retry attempt, synthesize anyway


def test_returns_none_on_first_attempt_unparseable_response_with_nothing_to_fall_back_on():
    llm = _llm("not json, and no prior attempt exists to fall back on")
    p1, p2, p3 = _patches()
    with p1, p2, p3:
        result = answer_with_generated_cli(
            MagicMock(), MagicMock(), "how many volumes", llm
        )

    assert result is None


def test_relevant_docs_reach_both_the_generation_and_synthesis_prompts():
    """The user's explicit request (2026-09-11): a live-ops question should also check
    the knowledge base, not just run commands in isolation."""
    llm = _llm(
        json.dumps({"command": "aws ec2 describe-volumes"}),
        "3 volumes, per the runbook.",
    )
    p1, p2, _ = _patches(run_readonly_aws_result="[sreacc]\n3 volumes")
    with (
        p1,
        p2,
        patch(
            "app.agents.cli_agent._describe_relevant_docs",
            return_value="[EBS Runbook]\nCheck volume count before any resize.",
        ) as mock_docs,
    ):
        result = answer_with_generated_cli(
            MagicMock(),
            MagicMock(),
            "how many volumes",
            llm,
            group_ids=[],
            is_superuser=False,
        )

    assert result == "3 volumes, per the runbook."
    mock_docs.assert_called_once()

    generate_messages = llm.chat.call_args_list[0].args[0]
    assert any("EBS Runbook" in m["content"] for m in generate_messages)

    synthesize_messages = llm.chat.call_args_list[1].args[0]
    assert any("EBS Runbook" in m["content"] for m in synthesize_messages)


def test_works_when_no_relevant_docs_are_found():
    llm = _llm(json.dumps({"command": "aws ec2 describe-volumes"}), "3 volumes.")
    p1, p2, p3 = _patches(run_readonly_aws_result="[sreacc]\n3 volumes")
    with p1, p2, p3:  # autouse fixture already returns "(none found)"
        result = answer_with_generated_cli(
            MagicMock(), MagicMock(), "how many volumes", llm
        )

    assert result == "3 volumes."
