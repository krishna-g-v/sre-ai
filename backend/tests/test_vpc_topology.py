"""Unit tests for app/services/vpc_topology.py — docs/11-network-topology-visualization.md
§1, §5, §6.

No real AWS calls: the ec2 client is a MagicMock with per-test `describe_*.return_value`s,
and `accounts_for`/`aws_session.get_client` are patched, so these run offline and fast.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.vpc_topology import (
    INSTANCE_CAP,
    NOT_CONFIGURED_MSG,
    OpaqueNode,
    VpcNode,
    describe_vpc_topology,
)


def _account(label="nonprod", account_id="111111111111", region="us-east-1", **extra):
    defaults = {
        "label": label,
        "account_id": account_id,
        "role_arn": f"arn:aws:iam::{account_id}:role/ro",
        "external_id": "",
        "region": region,
        "access_key_id": "",
        "secret_access_key": "",
    }
    defaults.update(extra)
    return SimpleNamespace(**defaults)


def _empty_ec2(**overrides) -> MagicMock:
    """An ec2 client mock where every describe_* call this module might make returns an
    empty list for its response key, unless overridden — keeps each test's setup to just
    the calls it actually cares about."""
    ec2 = MagicMock()
    ec2.describe_vpcs.return_value = {"Vpcs": [{"VpcId": "vpc-root", "CidrBlock": "10.0.0.0/16", "Tags": []}]}
    ec2.describe_subnets.return_value = {"Subnets": []}
    ec2.describe_route_tables.return_value = {"RouteTables": []}
    ec2.describe_nat_gateways.return_value = {"NatGateways": []}
    ec2.describe_internet_gateways.return_value = {"InternetGateways": []}
    ec2.describe_vpc_endpoints.return_value = {"VpcEndpoints": []}
    ec2.describe_instances.return_value = {"Reservations": []}
    ec2.describe_vpc_peering_connections.return_value = {"VpcPeeringConnections": []}
    ec2.describe_vpn_gateways.return_value = {"VpnGateways": []}
    ec2.describe_vpn_connections.return_value = {"VpnConnections": []}
    ec2.describe_customer_gateways.return_value = {"CustomerGateways": []}
    ec2.describe_transit_gateway_vpc_attachments.return_value = {"TransitGatewayVpcAttachments": []}
    for name, value in overrides.items():
        getattr(ec2, name).return_value = value
    return ec2


def _run(ec2, accounts, **kwargs):
    with patch("app.services.vpc_topology.accounts_for", return_value=accounts), patch(
        "app.services.vpc_topology.aws_session.get_client", return_value=ec2
    ):
        return describe_vpc_topology(MagicMock(), MagicMock(), **kwargs)


def test_reports_not_configured_when_no_accounts_registered():
    result = _run(_empty_ec2(), [])
    assert result == NOT_CONFIGURED_MSG


def test_asks_to_disambiguate_with_multiple_accounts_and_no_label():
    result = _run(_empty_ec2(), [_account("prod"), _account("nonprod")])
    assert "prod" in result and "nonprod" in result
    assert "specify" in result.lower()


def test_reports_no_vpc_found():
    ec2 = _empty_ec2(describe_vpcs={"Vpcs": []})
    result = _run(ec2, [_account()], vpc_identifier="vpc-missing")
    assert "No VPC found" in result


def test_asks_to_disambiguate_multiple_matching_vpcs():
    ec2 = _empty_ec2(
        describe_vpcs={
            "Vpcs": [
                {"VpcId": "vpc-a", "CidrBlock": "10.0.0.0/16", "Tags": [{"Key": "Name", "Value": "shared"}]},
                {"VpcId": "vpc-b", "CidrBlock": "10.1.0.0/16", "Tags": [{"Key": "Name", "Value": "shared"}]},
            ]
        }
    )
    result = _run(ec2, [_account()], vpc_identifier="shared")
    assert "vpc-a" in result and "vpc-b" in result and "Multiple VPCs" in result


def test_assume_role_failure_becomes_error_string_not_exception():
    with patch("app.services.vpc_topology.accounts_for", return_value=[_account()]), patch(
        "app.services.vpc_topology.aws_session.get_client", side_effect=Exception("AccessDenied on sts:AssumeRole")
    ):
        result = describe_vpc_topology(MagicMock(), MagicMock())
    assert result.startswith("[nonprod] ERROR:")


def test_builds_subnets_with_public_private_and_nat_gateway():
    ec2 = _empty_ec2(
        describe_subnets={
            "Subnets": [
                {"SubnetId": "subnet-pub", "CidrBlock": "10.0.1.0/24", "AvailabilityZone": "us-east-1a"},
                {"SubnetId": "subnet-priv", "CidrBlock": "10.0.2.0/24", "AvailabilityZone": "us-east-1b"},
            ]
        },
        describe_route_tables={
            "RouteTables": [
                {
                    "RouteTableId": "rtb-pub",
                    "Associations": [{"SubnetId": "subnet-pub"}],
                    "Routes": [{"GatewayId": "igw-123"}],
                },
                {
                    "RouteTableId": "rtb-priv",
                    "Associations": [{"SubnetId": "subnet-priv"}],
                    "Routes": [{"GatewayId": "local"}],
                },
            ]
        },
        describe_nat_gateways={"NatGateways": [{"NatGatewayId": "nat-1", "SubnetId": "subnet-priv", "State": "available"}]},
        describe_internet_gateways={
            "InternetGateways": [{"InternetGatewayId": "igw-123", "Attachments": [{"State": "available"}]}]
        },
    )
    result = _run(ec2, [_account()])
    root = result.root
    assert root.internet_gateway.igw_id == "igw-123"
    by_id = {s.subnet_id: s for s in root.subnets}
    assert by_id["subnet-pub"].public is True
    assert by_id["subnet-priv"].public is False
    assert by_id["subnet-priv"].nat_gateways[0].nat_gateway_id == "nat-1"
    assert by_id["subnet-pub"].nat_gateways == []


def test_instances_grouped_by_subnet_and_capped():
    instances = [
        {"InstanceId": f"i-{n}", "SubnetId": "subnet-a", "State": {"Name": "running"}, "Tags": []}
        for n in range(INSTANCE_CAP + 5)
    ]
    ec2 = _empty_ec2(
        describe_subnets={"Subnets": [{"SubnetId": "subnet-a", "CidrBlock": "10.0.1.0/24", "AvailabilityZone": "us-east-1a"}]},
        describe_instances={"Reservations": [{"Instances": instances}]},
    )
    result = _run(ec2, [_account()])
    subnet = result.root.subnets[0]
    assert len(subnet.instances) == INSTANCE_CAP
    assert subnet.extra_instance_count == 5


def test_peering_to_same_account_same_region_expands_to_full_vpc_node():
    ec2 = _empty_ec2(
        describe_vpc_peering_connections={
            "VpcPeeringConnections": [
                {
                    "VpcPeeringConnectionId": "pcx-1",
                    "Status": {"Code": "active"},
                    "RequesterVpcInfo": {"VpcId": "vpc-root", "OwnerId": "111111111111", "Region": "us-east-1"},
                    "AccepterVpcInfo": {"VpcId": "vpc-peer", "OwnerId": "111111111111", "Region": "us-east-1"},
                }
            ]
        },
    )
    ec2.describe_vpcs.side_effect = [
        {"Vpcs": [{"VpcId": "vpc-root", "CidrBlock": "10.0.0.0/16", "Tags": [], "OwnerId": "111111111111"}]},
        {"Vpcs": [{"VpcId": "vpc-peer", "CidrBlock": "10.1.0.0/16", "Tags": []}]},
    ]
    result = _run(ec2, [_account()])
    edge = result.root.peering_connections[0]
    assert edge.connection_id == "pcx-1"
    assert isinstance(edge.peer, VpcNode)
    assert edge.peer.vpc_id == "vpc-peer"


def test_peering_to_different_account_stays_opaque():
    ec2 = _empty_ec2(
        describe_vpc_peering_connections={
            "VpcPeeringConnections": [
                {
                    "VpcPeeringConnectionId": "pcx-2",
                    "Status": {"Code": "active"},
                    "RequesterVpcInfo": {"VpcId": "vpc-root", "OwnerId": "111111111111", "Region": "us-east-1"},
                    "AccepterVpcInfo": {"VpcId": "vpc-other", "OwnerId": "999999999999", "Region": "us-east-1"},
                }
            ]
        },
    )
    ec2.describe_vpcs.return_value = {
        "Vpcs": [{"VpcId": "vpc-root", "CidrBlock": "10.0.0.0/16", "Tags": [], "OwnerId": "111111111111"}]
    }
    result = _run(ec2, [_account()])
    edge = result.root.peering_connections[0]
    assert isinstance(edge.peer, OpaqueNode)
    assert edge.peer.account_id == "999999999999"
    # Never even attempted to describe the other account's VPC.
    assert ec2.describe_vpcs.call_count == 1


def test_peer_reachable_via_two_edges_is_only_built_once():
    """docs/11 §5's cycle handling: the same peer VPC reachable via both a peering
    connection and a TGW attachment must be memoized, not rebuilt (which would also
    render as a duplicate node once the Mermaid serializer exists)."""
    ec2 = _empty_ec2(
        describe_vpc_peering_connections={
            "VpcPeeringConnections": [
                {
                    "VpcPeeringConnectionId": "pcx-3",
                    "Status": {"Code": "active"},
                    "RequesterVpcInfo": {"VpcId": "vpc-root", "OwnerId": "111111111111", "Region": "us-east-1"},
                    "AccepterVpcInfo": {"VpcId": "vpc-shared", "OwnerId": "111111111111", "Region": "us-east-1"},
                }
            ]
        },
        describe_transit_gateway_vpc_attachments={
            "TransitGatewayVpcAttachments": [
                {
                    "TransitGatewayAttachmentId": "tgw-attach-1",
                    "TransitGatewayId": "tgw-1",
                    "VpcId": "vpc-root",
                    "State": "available",
                }
            ]
        },
    )
    ec2.describe_vpcs.side_effect = [
        {"Vpcs": [{"VpcId": "vpc-root", "CidrBlock": "10.0.0.0/16", "Tags": [], "OwnerId": "111111111111"}]},
        {"Vpcs": [{"VpcId": "vpc-shared", "CidrBlock": "10.2.0.0/16", "Tags": []}]},
    ]
    ec2.describe_transit_gateway_vpc_attachments.side_effect = [
        {
            "TransitGatewayVpcAttachments": [
                {
                    "TransitGatewayAttachmentId": "tgw-attach-1",
                    "TransitGatewayId": "tgw-1",
                    "VpcId": "vpc-root",
                    "State": "available",
                }
            ]
        },
        {
            "TransitGatewayVpcAttachments": [
                {
                    "TransitGatewayAttachmentId": "tgw-attach-2",
                    "TransitGatewayId": "tgw-1",
                    "VpcId": "vpc-shared",
                    "ResourceOwnerId": "111111111111",
                    "State": "available",
                }
            ]
        },
    ]
    result = _run(ec2, [_account()])
    peering_peer = result.root.peering_connections[0].peer
    tgw_peer = result.root.tgw_attachments[0].peer
    assert peering_peer is tgw_peer  # same object, built once
    # describe_vpcs called exactly twice: once for the root, once for vpc-shared.
    assert ec2.describe_vpcs.call_count == 2


def test_vpn_connection_includes_customer_gateway():
    ec2 = _empty_ec2(
        describe_vpn_gateways={"VpnGateways": [{"VpnGatewayId": "vgw-1"}]},
        describe_vpn_connections={
            "VpnConnections": [{"VpnConnectionId": "vpn-1", "State": "available", "CustomerGatewayId": "cgw-1"}]
        },
        describe_customer_gateways={"CustomerGateways": [{"IpAddress": "203.0.113.5", "BgpAsn": "65000"}]},
    )
    result = _run(ec2, [_account()])
    vpn = result.root.vpn_connections[0]
    assert vpn.vpn_connection_id == "vpn-1"
    assert vpn.customer_gateway.ip_address == "203.0.113.5"
    assert vpn.customer_gateway.bgp_asn == 65000


def test_tgw_sibling_in_different_account_is_opaque():
    ec2 = _empty_ec2(
        describe_transit_gateway_vpc_attachments={
            "TransitGatewayVpcAttachments": [
                {
                    "TransitGatewayAttachmentId": "tgw-attach-1",
                    "TransitGatewayId": "tgw-1",
                    "VpcId": "vpc-root",
                    "State": "available",
                }
            ]
        }
    )
    ec2.describe_transit_gateway_vpc_attachments.side_effect = [
        {
            "TransitGatewayVpcAttachments": [
                {
                    "TransitGatewayAttachmentId": "tgw-attach-1",
                    "TransitGatewayId": "tgw-1",
                    "VpcId": "vpc-root",
                    "State": "available",
                }
            ]
        },
        {
            "TransitGatewayVpcAttachments": [
                {
                    "TransitGatewayAttachmentId": "tgw-attach-2",
                    "TransitGatewayId": "tgw-1",
                    "VpcId": "vpc-other",
                    "ResourceOwnerId": "999999999999",
                    "State": "available",
                }
            ]
        },
    ]
    ec2.describe_vpcs.return_value = {
        "Vpcs": [{"VpcId": "vpc-root", "CidrBlock": "10.0.0.0/16", "Tags": [], "OwnerId": "111111111111"}]
    }
    result = _run(ec2, [_account()])
    edge = result.root.tgw_attachments[0]
    assert isinstance(edge.peer, OpaqueNode)
    assert edge.peer.account_id == "999999999999"


def test_failed_call_is_degraded_to_a_warning_not_an_exception():
    ec2 = _empty_ec2()
    ec2.describe_vpc_peering_connections.side_effect = Exception("AccessDenied")
    result = _run(ec2, [_account()])
    assert result.root.peering_connections == []
    assert any("peering" in w.lower() and "AccessDenied" in w for w in result.warnings)
