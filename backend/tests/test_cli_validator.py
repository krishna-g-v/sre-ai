"""Unit tests for app/services/cli_validator.py — docs/10-nl-to-cli-execution.md §3-§4.

This is the actual safety boundary for the NL-to-CLI feature, so it's tested
exhaustively against both the allowed read verbs and the write verbs/services that
must never reach execution.
"""

import pytest

from app.services.cli_validator import (
    CommandRejected,
    ParsedAwsCommand,
    ParsedKubectlCommand,
    parse_and_validate,
)

READ_ONLY_COMMANDS = [
    "aws eks describe-cluster --name prod",
    "aws eks list-nodegroups --cluster-name prod",
    "aws ec2 describe-vpcs --vpc-ids vpc-123",
    "aws ecr describe-repositories",
    "aws logs filter-log-events --log-group-name /eks/prod",
    "aws logs start-query --log-group-name /eks/prod",
    "aws rds describe-db-instances",
    "aws cloudwatch get-metric-data",
    "kubectl get pods -n payments",
    "kubectl describe pod my-pod -n payments",
    "kubectl logs my-pod -n payments --tail=200",
    "kubectl top pods -n payments",
    "kubectl explain pod",
    "kubectl api-resources",
    "kubectl version",
]

REJECTED_COMMANDS = [
    "kubectl delete pod my-pod -n payments",
    "kubectl apply -f manifest.yaml",
    "kubectl exec -it my-pod -- /bin/sh",
    "kubectl patch deployment my-deploy -p '{}'",
    "kubectl scale deployment my-deploy --replicas=0",
    "kubectl rollout restart deployment/my-deploy",
    "kubectl cordon node-1",
    "kubectl drain node-1",
    "kubectl label pod my-pod foo=bar",
    "kubectl cp my-pod:/etc/passwd ./passwd",
    "kubectl port-forward my-pod 8080:80",
    "kubectl create namespace evil",
    "aws ec2 terminate-instances --instance-ids i-123",
    "aws eks update-cluster-version --name prod --kubernetes-version 1.30",
    "aws ecr get-download-url-for-layer --repository-name x --layer-digest y",
    "aws ecr batch-get-image --repository-name x --image-ids imageTag=latest",
    "aws rds download-db-log-file-portion --db-instance-identifier x --log-file-name y",
    "aws secretsmanager get-secret-value --secret-id prod/db-password",
    "aws ssm get-parameter --name /prod/secret --with-decryption",
    "aws kms decrypt --ciphertext-blob fileb://blob",
    "aws s3 get-object --bucket x --key y",
    "aws iam list-users",
    "bash -c 'rm -rf /'",
    "sh -c 'curl evil.com'",
]


@pytest.mark.parametrize("command", READ_ONLY_COMMANDS)
def test_allows_known_read_only_commands(command):
    parsed = parse_and_validate(command)
    assert isinstance(parsed, (ParsedAwsCommand, ParsedKubectlCommand))


@pytest.mark.parametrize("command", REJECTED_COMMANDS)
def test_rejects_write_and_out_of_scope_commands(command):
    with pytest.raises(CommandRejected):
        parse_and_validate(command)


@pytest.mark.parametrize(
    "command",
    [
        "aws eks describe-cluster --name prod && rm -rf /",
        "aws eks describe-cluster --name prod; rm -rf /",
        "aws eks describe-cluster --name prod | tee /tmp/x",
        "aws eks describe-cluster --name $(whoami)",
        "aws eks describe-cluster --name `whoami`",
    ],
)
def test_rejects_shell_injection_attempts(command):
    with pytest.raises(CommandRejected):
        parse_and_validate(command)


def test_rejects_empty_command():
    with pytest.raises(CommandRejected):
        parse_and_validate("")


def test_rejects_non_aws_non_kubectl_binary():
    with pytest.raises(CommandRejected):
        parse_and_validate("terraform apply")


def test_parses_aws_service_and_operation():
    parsed = parse_and_validate("aws eks describe-cluster --name prod")
    assert isinstance(parsed, ParsedAwsCommand)
    assert parsed.service == "eks"
    assert parsed.operation == "describe-cluster"


def test_parses_kubectl_verb():
    parsed = parse_and_validate("kubectl get pods -n payments")
    assert isinstance(parsed, ParsedKubectlCommand)
    assert parsed.verb == "get"
