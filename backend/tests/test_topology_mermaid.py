"""Unit tests for app/services/topology_mermaid.py — docs/11-network-topology-visualization.md
§5, §7.

Builds `TopologyResult`/dataclass graphs directly (no AWS, no vpc_topology.py calls) and
asserts on the generated Mermaid text — structure, dedup, and escaping, not exact
byte-for-byte output, so the renderer's formatting can evolve without breaking every test.
"""

from app.services.topology_mermaid import to_mermaid
from app.services.vpc_topology import (
    CustomerGatewayNode,
    IgwNode,
    InstanceLeaf,
    NatGatewayNode,
    OpaqueNode,
    PeeringEdge,
    SubnetNode,
    TgwEdge,
    TopologyResult,
    VpcEndpointNode,
    VpcNode,
    VpnEdge,
)


def _result(root: VpcNode, warnings: list[str] | None = None) -> TopologyResult:
    return TopologyResult(account_label="nonprod", region="us-east-1", root=root, warnings=warnings or [])


def _subgraph_count(text: str, token: str) -> int:
    return text.count(f'subgraph {token}[')


def _assert_balanced_blocks(text: str) -> None:
    """Every `subgraph` line must have a matching `end` — a basic syntactic sanity check
    that doesn't require a real Mermaid parser."""
    lines = [line.strip() for line in text.splitlines()]
    opens = sum(1 for line in lines if line.startswith("subgraph "))
    closes = sum(1 for line in lines if line == "end")
    assert opens == closes


def test_minimal_vpc_renders_without_crashing():
    root = VpcNode(vpc_id="vpc-root", cidr="10.0.0.0/16", name=None)
    text = to_mermaid(_result(root))
    assert text.startswith("graph LR")
    assert 'subgraph vpc_root["vpc-root (10.0.0.0/16)"]' in text
    _assert_balanced_blocks(text)


def test_vpc_name_tag_included_in_title():
    root = VpcNode(vpc_id="vpc-root", cidr="10.0.0.0/16", name="shared-services")
    text = to_mermaid(_result(root))
    assert "vpc-root (10.0.0.0/16) — shared-services" in text


def test_subnet_public_private_igw_and_nat_render():
    root = VpcNode(
        vpc_id="vpc-root",
        cidr="10.0.0.0/16",
        name=None,
        internet_gateway=IgwNode(igw_id="igw-1", state="available"),
        subnets=[
            SubnetNode(
                subnet_id="subnet-pub",
                cidr="10.0.1.0/24",
                az="us-east-1a",
                public=True,
                route_table_id="rtb-1",
            ),
            SubnetNode(
                subnet_id="subnet-priv",
                cidr="10.0.2.0/24",
                az="us-east-1b",
                public=False,
                route_table_id="rtb-2",
                nat_gateways=[NatGatewayNode(nat_gateway_id="nat-1", state="available")],
            ),
        ],
    )
    text = to_mermaid(_result(root))
    assert "subnet-pub (10.0.1.0/24, us-east-1a) — public" in text
    assert "subnet-priv (10.0.2.0/24, us-east-1b) — private" in text
    assert 'igw_1(["Internet Gateway<br/>igw-1"])' in text
    assert 'nat_1(["NAT Gateway<br/>nat-1<br/>available"])' in text
    _assert_balanced_blocks(text)


def test_instances_and_overflow_count_render():
    subnet = SubnetNode(
        subnet_id="subnet-a",
        cidr="10.0.1.0/24",
        az="us-east-1a",
        public=False,
        route_table_id=None,
        instances=[InstanceLeaf(instance_id="i-1", name="web-1", state="running")],
        extra_instance_count=7,
    )
    root = VpcNode(vpc_id="vpc-root", cidr="10.0.0.0/16", name=None, subnets=[subnet])
    text = to_mermaid(_result(root))
    assert "i-1 (web-1)<br/>running" in text
    assert 'more_subnet_a["+7 more instance(s)"]' in text


def test_vpc_endpoint_renders():
    root = VpcNode(
        vpc_id="vpc-root",
        cidr="10.0.0.0/16",
        name=None,
        vpc_endpoints=[VpcEndpointNode(endpoint_id="vpce-1", service_name="com.amazonaws.us-east-1.s3", endpoint_type="Gateway")],
    )
    text = to_mermaid(_result(root))
    assert "com.amazonaws.us-east-1.s3 (Gateway)" in text


def test_peering_to_resolved_vpc_renders_one_subgraph_and_one_edge():
    peer = VpcNode(vpc_id="vpc-peer", cidr="10.1.0.0/16", name=None)
    root = VpcNode(
        vpc_id="vpc-root",
        cidr="10.0.0.0/16",
        name=None,
        peering_connections=[PeeringEdge(connection_id="pcx-1", status="active", peer=peer)],
    )
    text = to_mermaid(_result(root))
    assert _subgraph_count(text, "vpc_peer") == 1
    assert 'vpc_root -- "Peering pcx-1 (active)" --- vpc_peer' in text
    _assert_balanced_blocks(text)


def test_peer_reachable_via_peering_and_tgw_renders_only_once():
    peer = VpcNode(vpc_id="vpc-shared", cidr="10.2.0.0/16", name=None)
    root = VpcNode(
        vpc_id="vpc-root",
        cidr="10.0.0.0/16",
        name=None,
        peering_connections=[PeeringEdge(connection_id="pcx-1", status="active", peer=peer)],
        tgw_attachments=[TgwEdge(attachment_id="tgw-attach-1", transit_gateway_id="tgw-1", peer=peer)],
    )
    text = to_mermaid(_result(root))
    assert _subgraph_count(text, "vpc_shared") == 1
    assert "vpc_root -- " in text  # peering edge present
    assert "vpc_root --- tgw_1" in text  # tgw hub edge present
    assert "tgw_1 --- vpc_shared" in text
    _assert_balanced_blocks(text)


def test_cross_account_peer_renders_as_dashed_opaque_node():
    opaque = OpaqueNode(account_id="999999999999", resource_id="vpc-other")
    root = VpcNode(
        vpc_id="vpc-root",
        cidr="10.0.0.0/16",
        name=None,
        peering_connections=[PeeringEdge(connection_id="pcx-2", status="active", peer=opaque)],
    )
    text = to_mermaid(_result(root))
    assert "Other account<br/>999999999999<br/>vpc-other" in text
    assert "classDef opaque stroke-dasharray: 5 5;" in text
    assert "class opaque_999999999999_vpc_other opaque;" in text


def test_vpn_edge_with_customer_gateway_renders_dotted_link():
    cgw = CustomerGatewayNode(customer_gateway_id="cgw-1", ip_address="203.0.113.5", bgp_asn=65000)
    root = VpcNode(
        vpc_id="vpc-root",
        cidr="10.0.0.0/16",
        name=None,
        vpn_connections=[VpnEdge(vpn_connection_id="vpn-1", state="available", customer_gateway=cgw)],
    )
    text = to_mermaid(_result(root))
    assert "Customer Gateway<br/>cgw-1<br/>203.0.113.5, ASN 65000" in text
    assert 'vpc_root -. "VPN vpn-1 (available)" .-> cgw_1' in text


def test_vpn_edge_without_customer_gateway_renders_placeholder():
    root = VpcNode(
        vpc_id="vpc-root",
        cidr="10.0.0.0/16",
        name=None,
        vpn_connections=[VpnEdge(vpn_connection_id="vpn-2", state="pending", customer_gateway=None)],
    )
    text = to_mermaid(_result(root))
    assert "Customer Gateway<br/>(unknown)" in text
    assert "cgw_unknown_vpn_2" in text


def test_quote_in_name_tag_is_escaped():
    root = VpcNode(vpc_id="vpc-root", cidr="10.0.0.0/16", name='prod "core"')
    text = to_mermaid(_result(root))
    assert "#quot;core#quot;" in text
    assert '"core"' not in text
