"""VPC network topology discovery — docs/11-network-topology-visualization.md §1-§6.

Given a starting VPC, assembles a graph of its subnets/route tables/gateways/instances
plus one hop into anything directly connected (VPC peering, Site-to-Site VPN, Transit
Gateway attachments) — same account/region only for the one-hop expansion (docs/11 §1's
"cross-account out of scope for v1" decision). This module only ever calls
`describe_*`/`list_*` boto3 methods — read-only by construction, same guardrail
principle as every other tool in app/agents/live_ops_agents.py: no mutating call exists
here for anything to invoke.

Deliberately a boto3-direct fixed tool, not a NL-to-CLI generated command (docs/11 §2):
this needs ~10 coordinated calls cross-referenced by id (which subnet's route table
points at which NAT gateway, which peering connection's accepter VPC is which), not
something to re-derive per question via the single-command generator in
app/agents/cli_agent.py. It does, however, reuse that pipeline's per-user access model
(`app/services/user_aws_accounts.py`) rather than the group-scoped `IntegrationScope`
the rest of app/agents/live_ops_agents.py's fixed tools use — same reasoning docs/10 §9
gave for the CLI pipeline: this is interactive/personal/self-service, not admin-curated.

Only builds the structured result (§5's `TopologyResult`) — Mermaid rendering and the
LLM synthesis pass are a separate, not-yet-built step (docs/11 §7).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import UserAwsAccount
from app.services import aws_session
from app.services.user_aws_accounts import account_config, accounts_for, resolve_account

# docs/11 §5 — beyond this many instances in one subnet, the rest collapse into a single
# "+N more" count rather than being enumerated, so one busy subnet can't blow up the
# diagram this feeds into.
INSTANCE_CAP = 25

NOT_CONFIGURED_MSG = "You don't have any AWS accounts registered yet — add one under Settings → AWS Accounts."


@dataclass
class InstanceLeaf:
    instance_id: str
    name: str | None
    state: str


@dataclass
class NatGatewayNode:
    nat_gateway_id: str
    state: str


@dataclass
class IgwNode:
    igw_id: str
    state: str | None


@dataclass
class VpcEndpointNode:
    endpoint_id: str
    service_name: str
    endpoint_type: str


@dataclass
class OpaqueNode:
    """A peer VPC this tool declined to describe further — either its account isn't one
    of the requesting user's own registered accounts, or it's in a different region.
    docs/11 §1/§4: cross-account/cross-region expansion is out of scope for v1 even when
    the *same user* happens to have separately registered that other account."""

    account_id: str
    resource_id: str


@dataclass
class CustomerGatewayNode:
    customer_gateway_id: str
    ip_address: str | None
    bgp_asn: int | None


@dataclass
class SubnetNode:
    subnet_id: str
    cidr: str
    az: str
    public: bool
    route_table_id: str | None
    nat_gateways: list[NatGatewayNode] = field(default_factory=list)
    instances: list[InstanceLeaf] = field(default_factory=list)
    extra_instance_count: int = 0  # instances beyond INSTANCE_CAP, not enumerated


@dataclass
class PeeringEdge:
    connection_id: str
    status: str | None
    peer: VpcNode | OpaqueNode


@dataclass
class VpnEdge:
    vpn_connection_id: str
    state: str | None
    customer_gateway: CustomerGatewayNode | None


@dataclass
class TgwEdge:
    attachment_id: str
    transit_gateway_id: str
    peer: VpcNode | OpaqueNode


@dataclass
class VpcNode:
    vpc_id: str
    cidr: str
    name: str | None
    subnets: list[SubnetNode] = field(default_factory=list)
    internet_gateway: IgwNode | None = None
    vpc_endpoints: list[VpcEndpointNode] = field(default_factory=list)
    peering_connections: list[PeeringEdge] = field(default_factory=list)
    vpn_connections: list[VpnEdge] = field(default_factory=list)
    tgw_attachments: list[TgwEdge] = field(default_factory=list)


@dataclass
class TopologyResult:
    account_label: str
    region: str
    root: VpcNode
    # docs/11 §6 — per-call failures degrade just that branch, collected here rather
    # than failing the whole answer; the synthesis step (not yet built) surfaces these
    # plainly instead of silently omitting what couldn't be determined.
    warnings: list[str] = field(default_factory=list)


def _filter(name: str, value: str) -> dict:
    return {"Name": name, "Values": [value]}


def _tag(tags: list[dict] | None, key: str) -> str | None:
    return next((t["Value"] for t in (tags or []) if t.get("Key") == key), None)


def _safe_list(fn, response_key: str, description: str, warnings: list[str], **kwargs) -> list[dict] | None:
    """Run one describe/list call, returning its list field or None (distinct from an
    empty list, which means "no such resource") on failure — appending a human-readable
    warning instead of raising, per docs/11 §6's per-call degradation."""
    try:
        return fn(**kwargs).get(response_key, [])
    except Exception as exc:  # pragma: no cover - depends on real AWS/network behavior
        warnings.append(f"{description}: could not be determined — {exc}")
        return None


def _route_tables_by_subnet(route_tables: list[dict]) -> tuple[dict[str, dict], dict | None]:
    by_subnet: dict[str, dict] = {}
    main: dict | None = None
    for rt in route_tables:
        for assoc in rt.get("Associations", []):
            if assoc.get("SubnetId"):
                by_subnet[assoc["SubnetId"]] = rt
            if assoc.get("Main"):
                main = rt
    return by_subnet, main


def _has_igw_route(route_table: dict) -> bool:
    return any(r.get("GatewayId", "").startswith("igw-") for r in route_table.get("Routes", []))


def _instances_by_subnet(
    ec2, vpc_id: str, warnings: list[str]
) -> tuple[dict[str, list[InstanceLeaf]], dict[str, int]]:
    try:
        reservations = ec2.describe_instances(Filters=[_filter("vpc-id", vpc_id)]).get("Reservations", [])
    except Exception as exc:  # pragma: no cover - depends on real AWS/network behavior
        warnings.append(f"instances: could not be determined — {exc}")
        return {}, {}

    raw_by_subnet: dict[str, list[dict]] = {}
    for reservation in reservations:
        for instance in reservation.get("Instances", []):
            raw_by_subnet.setdefault(instance.get("SubnetId", ""), []).append(instance)

    leaves_by_subnet: dict[str, list[InstanceLeaf]] = {}
    extra_by_subnet: dict[str, int] = {}
    for subnet_id, instances in raw_by_subnet.items():
        leaves_by_subnet[subnet_id] = [
            InstanceLeaf(
                instance_id=i["InstanceId"],
                name=_tag(i.get("Tags"), "Name"),
                state=i.get("State", {}).get("Name", ""),
            )
            for i in instances[:INSTANCE_CAP]
        ]
        if len(instances) > INSTANCE_CAP:
            extra_by_subnet[subnet_id] = len(instances) - INSTANCE_CAP
    return leaves_by_subnet, extra_by_subnet


def _build_vpc_basic(ec2, vpc: dict, warnings: list[str]) -> VpcNode:
    """Subnets/route-tables/gateways/endpoints/instances only — never follows peering/
    VPN/TGW edges itself. Used both for the root VPC and for a one-hop peer/sibling
    (docs/11 §1: "no recursion past that one hop" — enforced structurally here, since
    this function has no code path that calls the edge-finding functions below)."""
    vpc_id = vpc["VpcId"]
    node = VpcNode(vpc_id=vpc_id, cidr=vpc.get("CidrBlock", ""), name=_tag(vpc.get("Tags"), "Name"))

    subnets = _safe_list(ec2.describe_subnets, "Subnets", "subnets", warnings, Filters=[_filter("vpc-id", vpc_id)]) or []
    route_tables = (
        _safe_list(ec2.describe_route_tables, "RouteTables", "route tables", warnings, Filters=[_filter("vpc-id", vpc_id)])
        or []
    )
    # DescribeNatGateways uses `Filter` (singular), unlike almost every other EC2 describe
    # call — an easy, silent mistake if copy-pasted from the others.
    nat_gateways = (
        _safe_list(ec2.describe_nat_gateways, "NatGateways", "NAT gateways", warnings, Filter=[_filter("vpc-id", vpc_id)])
        or []
    )
    igws = (
        _safe_list(
            ec2.describe_internet_gateways,
            "InternetGateways",
            "internet gateway",
            warnings,
            Filters=[_filter("attachment.vpc-id", vpc_id)],
        )
        or []
    )
    endpoints = (
        _safe_list(
            ec2.describe_vpc_endpoints, "VpcEndpoints", "VPC endpoints", warnings, Filters=[_filter("vpc-id", vpc_id)]
        )
        or []
    )
    instances_by_subnet, extra_by_subnet = _instances_by_subnet(ec2, vpc_id, warnings)

    if igws:
        attachments = igws[0].get("Attachments", [{}])
        node.internet_gateway = IgwNode(
            igw_id=igws[0]["InternetGatewayId"], state=attachments[0].get("State") if attachments else None
        )

    node.vpc_endpoints = [
        VpcEndpointNode(
            endpoint_id=e["VpcEndpointId"], service_name=e.get("ServiceName", ""), endpoint_type=e.get("VpcEndpointType", "")
        )
        for e in endpoints
    ]

    nat_by_subnet: dict[str, list[NatGatewayNode]] = {}
    for nat in nat_gateways:
        nat_by_subnet.setdefault(nat.get("SubnetId", ""), []).append(
            NatGatewayNode(nat_gateway_id=nat["NatGatewayId"], state=nat.get("State", ""))
        )

    rt_by_subnet, main_rt = _route_tables_by_subnet(route_tables)

    for subnet in subnets:
        subnet_id = subnet["SubnetId"]
        route_table = rt_by_subnet.get(subnet_id, main_rt)
        node.subnets.append(
            SubnetNode(
                subnet_id=subnet_id,
                cidr=subnet.get("CidrBlock", ""),
                az=subnet.get("AvailabilityZone", ""),
                public=_has_igw_route(route_table) if route_table else False,
                route_table_id=route_table.get("RouteTableId") if route_table else None,
                nat_gateways=nat_by_subnet.get(subnet_id, []),
                instances=instances_by_subnet.get(subnet_id, []),
                extra_instance_count=extra_by_subnet.get(subnet_id, 0),
            )
        )
    return node


def _resolve_peer_vpc(
    ec2, peer_vpc_id: str, peer_owner_id: str, root_account_id: str, same_region: bool, warnings: list[str], visited: dict[str, VpcNode]
) -> VpcNode | OpaqueNode:
    """One hop only: same account + same region resolves to a full VpcNode (memoized in
    `visited` so a peer reachable via two different edges is only ever built once —
    docs/11 §5's cycle handling); anything else stays an OpaqueNode, deliberately, even
    if the requesting user separately has that other account registered (docs/11 §1)."""
    if peer_owner_id != root_account_id or not same_region:
        return OpaqueNode(account_id=peer_owner_id or "unknown", resource_id=peer_vpc_id)
    if peer_vpc_id in visited:
        return visited[peer_vpc_id]
    peer_vpcs = _safe_list(ec2.describe_vpcs, "Vpcs", f"peer VPC {peer_vpc_id}", warnings, VpcIds=[peer_vpc_id])
    if not peer_vpcs:
        return OpaqueNode(account_id=peer_owner_id or "unknown", resource_id=peer_vpc_id)
    peer_node = _build_vpc_basic(ec2, peer_vpcs[0], warnings)
    visited[peer_vpc_id] = peer_node
    return peer_node


def _find_peering_edges(
    ec2, vpc_id: str, root_account_id: str, region: str, warnings: list[str], visited: dict[str, VpcNode]
) -> list[PeeringEdge]:
    connections: dict[str, dict] = {}
    for role_filter in ("requester-vpc-info.vpc-id", "accepter-vpc-info.vpc-id"):
        raw = _safe_list(
            ec2.describe_vpc_peering_connections,
            "VpcPeeringConnections",
            "VPC peering connections",
            warnings,
            Filters=[_filter(role_filter, vpc_id)],
        )
        for conn in raw or []:
            connections[conn["VpcPeeringConnectionId"]] = conn

    edges = []
    for conn_id, conn in connections.items():
        requester = conn.get("RequesterVpcInfo", {})
        accepter = conn.get("AccepterVpcInfo", {})
        peer_info = accepter if requester.get("VpcId") == vpc_id else requester
        peer_vpc_id = peer_info.get("VpcId", conn_id)
        peer_owner_id = peer_info.get("OwnerId", "unknown")
        peer = _resolve_peer_vpc(
            ec2, peer_vpc_id, peer_owner_id, root_account_id, peer_info.get("Region") == region, warnings, visited
        )
        edges.append(PeeringEdge(connection_id=conn_id, status=conn.get("Status", {}).get("Code"), peer=peer))
    return edges


def _vpn_edges_from_connections(ec2, connections: list[dict], warnings: list[str]) -> list[VpnEdge]:
    edges = []
    for conn in connections:
        cgw_node = None
        cgw_id = conn.get("CustomerGatewayId")
        if cgw_id:
            cgws = _safe_list(
                ec2.describe_customer_gateways, "CustomerGateways", "customer gateway", warnings, CustomerGatewayIds=[cgw_id]
            )
            if cgws:
                cgw = cgws[0]
                bgp_asn = cgw.get("BgpAsn")
                cgw_node = CustomerGatewayNode(
                    customer_gateway_id=cgw_id,
                    ip_address=cgw.get("IpAddress"),
                    bgp_asn=int(bgp_asn) if bgp_asn else None,
                )
        edges.append(
            VpnEdge(vpn_connection_id=conn["VpnConnectionId"], state=conn.get("State"), customer_gateway=cgw_node)
        )
    return edges


def _find_vpn_edges(ec2, vpc_id: str, warnings: list[str]) -> list[VpnEdge]:
    """Site-to-Site VPN attached directly via a Virtual Private Gateway. VPN attached via
    a Transit Gateway instead is found in `_find_tgw_edges` (it needs the TGW id, which
    this function has no reason to look up on its own)."""
    vgws = (
        _safe_list(
            ec2.describe_vpn_gateways,
            "VpnGateways",
            "VPN gateway",
            warnings,
            Filters=[_filter("attachment.vpc-id", vpc_id), _filter("attachment.state", "attached")],
        )
        or []
    )
    edges: list[VpnEdge] = []
    for vgw in vgws:
        connections = (
            _safe_list(
                ec2.describe_vpn_connections,
                "VpnConnections",
                "VPN connections",
                warnings,
                Filters=[_filter("vpn-gateway-id", vgw["VpnGatewayId"])],
            )
            or []
        )
        edges.extend(_vpn_edges_from_connections(ec2, connections, warnings))
    return edges


def _find_tgw_edges(
    ec2, vpc_id: str, root_account_id: str, warnings: list[str], visited: dict[str, VpcNode]
) -> tuple[list[TgwEdge], list[VpnEdge]]:
    attachments = (
        _safe_list(
            ec2.describe_transit_gateway_vpc_attachments,
            "TransitGatewayVpcAttachments",
            "Transit Gateway attachments",
            warnings,
            Filters=[_filter("vpc-id", vpc_id)],
        )
        or []
    )

    tgw_edges: list[TgwEdge] = []
    vpn_edges: list[VpnEdge] = []
    for attachment in attachments:
        if attachment.get("State") not in ("available", "pending", "modifying"):
            continue
        tgw_id = attachment["TransitGatewayId"]

        siblings = (
            _safe_list(
                ec2.describe_transit_gateway_vpc_attachments,
                "TransitGatewayVpcAttachments",
                f"Transit Gateway {tgw_id} attachments",
                warnings,
                Filters=[_filter("transit-gateway-id", tgw_id)],
            )
            or []
        )
        for sibling in siblings:
            sibling_vpc_id = sibling.get("VpcId")
            if not sibling_vpc_id or sibling_vpc_id == vpc_id:
                continue
            # Region isn't part of a TGW-attachment record the way it is for a peering
            # connection (a TGW attachment is inherently regional) — same-account is the
            # only check that applies here.
            peer = _resolve_peer_vpc(
                ec2, sibling_vpc_id, sibling.get("ResourceOwnerId", "unknown"), root_account_id, True, warnings, visited
            )
            tgw_edges.append(
                TgwEdge(attachment_id=attachment["TransitGatewayAttachmentId"], transit_gateway_id=tgw_id, peer=peer)
            )

        tgw_vpn_connections = (
            _safe_list(
                ec2.describe_vpn_connections,
                "VpnConnections",
                f"Transit Gateway {tgw_id} VPN connections",
                warnings,
                Filters=[_filter("transit-gateway-id", tgw_id)],
            )
            or []
        )
        vpn_edges.extend(_vpn_edges_from_connections(ec2, tgw_vpn_connections, warnings))

    return tgw_edges, vpn_edges


def _resolve_vpc(ec2, vpc_identifier: str, warnings: list[str]) -> dict | str:
    """The single VPC to root the topology at, or an error string. Handles both an
    explicit `vpc-...` id and a `Name` tag; with nothing named and more than one VPC in
    the account/region, asks rather than guessing (docs/11 §1's "VPC selection" decision)
    — this is a second line of defense alongside the orchestrator-level disambiguation
    (docs/11 §3), not a replacement for it, since this function is also callable
    directly (e.g. from tests, or a future non-chat caller)."""
    filters = []
    if vpc_identifier:
        filters = (
            [_filter("vpc-id", vpc_identifier)]
            if vpc_identifier.startswith("vpc-")
            else [_filter("tag:Name", vpc_identifier)]
        )
    try:
        kwargs = {"Filters": filters} if filters else {}
        vpcs = ec2.describe_vpcs(**kwargs).get("Vpcs", [])
    except Exception as exc:  # pragma: no cover - depends on real AWS/network behavior
        return f"ERROR: could not describe VPCs: {exc}"

    if not vpcs:
        return f"No VPC found matching '{vpc_identifier}'." if vpc_identifier else "No VPCs found in this account/region."
    if len(vpcs) > 1:
        labels = ", ".join(
            f"{v['VpcId']} ({_tag(v.get('Tags'), 'Name')})" if _tag(v.get("Tags"), "Name") else v["VpcId"] for v in vpcs
        )
        return f"Multiple VPCs match: {labels}. Please specify one by vpc-id or Name tag."
    return vpcs[0]


def describe_vpc_topology(
    db: Session, user_id, vpc_identifier: str = "", account_label: str | None = None
) -> TopologyResult | str:
    """Entry point (docs/11 §7). Returns a `TopologyResult`, or a plain string — a
    disambiguation/not-configured/not-found message, or an "ERROR: ..." for an
    AssumeRole failure — for the caller (`orchestrator.py`'s `live_ops_node`) to
    surface directly, same convention `cli_executor.py` uses."""
    accounts = accounts_for(db, user_id)
    if not accounts:
        return NOT_CONFIGURED_MSG

    resolved = resolve_account(accounts, account_label)
    if isinstance(resolved, str):
        return resolved
    account: UserAwsAccount = resolved

    default_region = get_settings().aws_region
    region = account.region or default_region
    try:
        ec2 = aws_session.get_client(account_config(account), "ec2", default_region=region)
    except Exception as exc:  # pragma: no cover - depends on real AWS/network behavior
        return f"[{account.label}] ERROR: could not assume {account.role_arn}: {exc}"

    warnings: list[str] = []
    vpc = _resolve_vpc(ec2, vpc_identifier, warnings)
    if isinstance(vpc, str):
        return vpc

    root_account_id = vpc.get("OwnerId") or account.account_id or ""
    root = _build_vpc_basic(ec2, vpc, warnings)
    visited: dict[str, VpcNode] = {root.vpc_id: root}

    root.peering_connections = _find_peering_edges(ec2, root.vpc_id, root_account_id, region, warnings, visited)
    root.vpn_connections = _find_vpn_edges(ec2, root.vpc_id, warnings)
    tgw_edges, tgw_vpn_edges = _find_tgw_edges(ec2, root.vpc_id, root_account_id, warnings, visited)
    root.tgw_attachments = tgw_edges
    root.vpn_connections.extend(tgw_vpn_edges)

    return TopologyResult(account_label=account.label, region=region, root=root, warnings=warnings)


def summarize_counts(result: TopologyResult) -> str:
    """The mechanical half of docs/11 §5's "Text summary" — counts, computed directly
    from the structured result rather than left for an LLM to tally (a count is exactly
    the kind of fact that shouldn't depend on a model reading a diagram correctly).
    `orchestrator.py`'s synthesis step feeds this to the LLM as ground truth for the
    prose answer, and appends the Mermaid diagram itself afterward, verbatim — never
    asking the model to reproduce or describe the diagram's syntax."""
    root = result.root
    public = sum(1 for s in root.subnets if s.public)
    instance_count = sum(len(s.instances) + s.extra_instance_count for s in root.subnets)
    nat_count = sum(len(s.nat_gateways) for s in root.subnets)

    lines = [
        f"VPC {root.vpc_id} ({root.cidr})" + (f" — {root.name}" if root.name else ""),
        f"- Account: {result.account_label} (region {result.region})",
        f"- Subnets: {len(root.subnets)} ({public} public, {len(root.subnets) - public} private)",
        f"- Instances: {instance_count}",
        f"- NAT gateways: {nat_count}",
        f"- Internet gateway: {root.internet_gateway.igw_id if root.internet_gateway else 'none'}",
        f"- VPC endpoints: {len(root.vpc_endpoints)}",
        f"- VPC peering connections: {len(root.peering_connections)}",
        f"- Site-to-Site VPN connections: {len(root.vpn_connections)}",
        f"- Transit Gateway attachments: {len(root.tgw_attachments)}",
    ]
    if result.warnings:
        lines.append("- Could not be fully determined:")
        lines.extend(f"  - {w}" for w in result.warnings)
    return "\n".join(lines)
