"""Mermaid diagram serialization for VPC topology — docs/11-network-topology-visualization.md
§5, §7.

Turns the structured `vpc_topology.TopologyResult` produced by `describe_vpc_topology`
into a Mermaid `graph LR` diagram string. This module only turns already-assembled data
into diagram text — it never calls AWS itself, and it's the only place that knows
Mermaid syntax (the rest of the pipeline works with plain dataclasses).

Not yet wired into an actual chat answer: that needs the orchestrator routing step and
the LLM synthesis pass (docs/11 §7, not built yet), and the diagram won't actually
render in the UI until frontend/src/components/MarkdownContent.tsx gains a
`language-mermaid` case (docs/11 §7/§8, also not built yet) — until then a
` ```mermaid ` fence just displays as a plain code block.

Graph, not tree, on purpose (docs/11 §1): peering/VPN/Transit-Gateway edges are
cross-links, not parent-child, so this renders `graph LR` rather than a strict tree
layout, with each VPC as one Mermaid subgraph and cross-links drawn between subgraphs.
A VPC reachable via more than one edge (e.g. both a direct peering connection and a
shared Transit Gateway attachment — see vpc_topology.py's `visited` cache, which
guarantees the *same* VpcNode object in both places) is rendered as a single subgraph,
referenced by every edge that reaches it, never duplicated — `_Renderer` dedupes on
`vpc_id` for exactly this reason, mirroring the dedup vpc_topology.py already did one
layer down.

Link styles are chosen to be visually distinct, not arbitrary: solid line for peering,
dotted for VPN (matching how these are usually drawn by hand/in AWS's own console),
plain undirected line for Transit Gateway hub-and-spoke. Anything the topology tool
couldn't fully describe (`OpaqueNode` — cross-account/cross-region, docs/11 §1) renders
with a dashed border via a Mermaid `classDef`, so an incomplete branch of the diagram
looks visibly different from one that was actually resolved.
"""

from __future__ import annotations

from app.services.vpc_topology import (
    OpaqueNode,
    SubnetNode,
    TopologyResult,
    VpcNode,
    VpnEdge,
)


def _sanitize(raw: str) -> str:
    """A Mermaid node/subgraph id must be alphanumeric/underscore — AWS resource ids are
    already safe once their conventional dashes are swapped out, and since every AWS id
    is already unique *and* type-prefixed (vpc-.../subnet-.../i-...), the sanitized id
    alone is a safe, collision-free Mermaid token with no extra prefixing needed."""
    return raw.replace("-", "_").replace(".", "_").replace(" ", "_")


def _escape(text: str) -> str:
    """Mermaid node labels here are always double-quoted strings — escape the one
    character that would end the string early, and turn a newline into Mermaid's own
    line-break markup rather than a raw newline that would break the diagram's
    line-based syntax."""
    return text.replace('"', "#quot;").replace("\n", "<br/>")


class _Renderer:
    def __init__(self) -> None:
        self._lines: list[str] = ["graph LR"]
        self._indent = 0
        self._rendered_vpcs: set[str] = set()
        self._rendered_leaf_nodes: set[str] = set()  # customer gateways + opaque nodes
        self._opaque_tokens: list[str] = []  # for the dashed classDef, applied once at the end

    def _add(self, line: str) -> None:
        self._lines.append(("    " * self._indent) + line)

    def render(self, result: TopologyResult) -> str:
        for vpc in self._collect_vpcs(result.root):
            self._render_vpc_subgraph(vpc)

        tgw_ids = sorted({edge.transit_gateway_id for edge in result.root.tgw_attachments})
        for tgw_id in tgw_ids:
            self._add(f'{_sanitize(tgw_id)}(["Transit Gateway<br/>{_escape(tgw_id)}"])')

        self._render_peering_edges(result.root)
        self._render_vpn_edges(result.root)
        self._render_tgw_edges(result.root)

        if self._opaque_tokens:
            self._add("classDef opaque stroke-dasharray: 5 5;")
            self._add(f"class {','.join(self._opaque_tokens)} opaque;")

        return "\n".join(self._lines)

    def _collect_vpcs(self, root: VpcNode) -> list[VpcNode]:
        """Every VPC that needs its own subgraph: the root, plus any one-hop peer that
        was actually resolved (as opposed to left as an OpaqueNode) — deduped by
        vpc_id, since the same peer can be reachable via two different edges."""
        seen: dict[str, VpcNode] = {root.vpc_id: root}
        for edge in root.peering_connections:
            if isinstance(edge.peer, VpcNode):
                seen.setdefault(edge.peer.vpc_id, edge.peer)
        for edge in root.tgw_attachments:
            if isinstance(edge.peer, VpcNode):
                seen.setdefault(edge.peer.vpc_id, edge.peer)
        return list(seen.values())

    def _render_vpc_subgraph(self, vpc: VpcNode) -> None:
        if vpc.vpc_id in self._rendered_vpcs:
            return
        self._rendered_vpcs.add(vpc.vpc_id)

        token = _sanitize(vpc.vpc_id)
        title = f"{vpc.vpc_id} ({vpc.cidr})" + (f" — {vpc.name}" if vpc.name else "")
        self._add(f'subgraph {token}["{_escape(title)}"]')
        self._indent += 1
        self._add("direction TB")

        if vpc.internet_gateway:
            igw = vpc.internet_gateway
            label = f"Internet Gateway<br/>{igw.igw_id}"
            self._add(f'{_sanitize(igw.igw_id)}(["{_escape(label)}"])')

        for endpoint in vpc.vpc_endpoints:
            label = f"Endpoint<br/>{endpoint.endpoint_id}<br/>{endpoint.service_name} ({endpoint.endpoint_type})"
            self._add(f'{_sanitize(endpoint.endpoint_id)}["{_escape(label)}"]')

        for subnet in vpc.subnets:
            self._render_subnet(subnet)

        self._indent -= 1
        self._add("end")

    def _render_subnet(self, subnet: SubnetNode) -> None:
        token = _sanitize(subnet.subnet_id)
        visibility = "public" if subnet.public else "private"
        title = f"{subnet.subnet_id} ({subnet.cidr}, {subnet.az}) — {visibility}"
        self._add(f'subgraph {token}["{_escape(title)}"]')
        self._indent += 1

        for nat in subnet.nat_gateways:
            label = f"NAT Gateway<br/>{nat.nat_gateway_id}<br/>{nat.state}"
            self._add(f'{_sanitize(nat.nat_gateway_id)}(["{_escape(label)}"])')

        for instance in subnet.instances:
            label = instance.instance_id + (f" ({instance.name})" if instance.name else "") + f"<br/>{instance.state}"
            self._add(f'{_sanitize(instance.instance_id)}["{_escape(label)}"]')

        if subnet.extra_instance_count:
            self._add(f'more_{token}["+{subnet.extra_instance_count} more instance(s)"]')

        self._indent -= 1
        self._add("end")

    def _opaque_token(self, node: OpaqueNode) -> str:
        token = f"opaque_{_sanitize(node.account_id)}_{_sanitize(node.resource_id)}"
        if token not in self._rendered_leaf_nodes:
            self._rendered_leaf_nodes.add(token)
            label = f"Other account<br/>{node.account_id}<br/>{node.resource_id}"
            self._add(f'{token}["{_escape(label)}"]')
            self._opaque_tokens.append(token)
        return token

    def _peer_token(self, peer: VpcNode | OpaqueNode) -> str:
        return _sanitize(peer.vpc_id) if isinstance(peer, VpcNode) else self._opaque_token(peer)

    def _render_peering_edges(self, root: VpcNode) -> None:
        root_token = _sanitize(root.vpc_id)
        for edge in root.peering_connections:
            peer_token = self._peer_token(edge.peer)
            label = f"Peering {edge.connection_id}" + (f" ({edge.status})" if edge.status else "")
            self._add(f'{root_token} -- "{_escape(label)}" --- {peer_token}')

    def _vpn_target_token(self, edge: VpnEdge) -> str:
        """The Customer Gateway node this VPN connection points at, or a placeholder
        when the customer gateway itself couldn't be resolved (e.g. a degraded call,
        docs/11 §6) — either way, dedupe on the node's own id so two VPN connections to
        the same customer gateway don't render it twice."""
        if edge.customer_gateway:
            cgw = edge.customer_gateway
            token = _sanitize(cgw.customer_gateway_id)
            if token not in self._rendered_leaf_nodes:
                self._rendered_leaf_nodes.add(token)
                details = cgw.ip_address or "unknown IP"
                if cgw.bgp_asn:
                    details += f", ASN {cgw.bgp_asn}"
                label = f"Customer Gateway<br/>{cgw.customer_gateway_id}<br/>{details}"
                self._add(f'{token}["{_escape(label)}"]')
            return token

        token = f"cgw_unknown_{_sanitize(edge.vpn_connection_id)}"
        if token not in self._rendered_leaf_nodes:
            self._rendered_leaf_nodes.add(token)
            self._add(f'{token}["Customer Gateway<br/>(unknown)"]')
        return token

    def _render_vpn_edges(self, root: VpcNode) -> None:
        root_token = _sanitize(root.vpc_id)
        for edge in root.vpn_connections:
            target_token = self._vpn_target_token(edge)
            label = f"VPN {edge.vpn_connection_id}" + (f" ({edge.state})" if edge.state else "")
            self._add(f'{root_token} -. "{_escape(label)}" .-> {target_token}')

    def _render_tgw_edges(self, root: VpcNode) -> None:
        root_token = _sanitize(root.vpc_id)
        rendered_hub_edges: set[str] = set()
        for edge in root.tgw_attachments:
            hub_token = _sanitize(edge.transit_gateway_id)
            if hub_token not in rendered_hub_edges:
                self._add(f"{root_token} --- {hub_token}")
                rendered_hub_edges.add(hub_token)
            self._add(f"{hub_token} --- {self._peer_token(edge.peer)}")


def to_mermaid(result: TopologyResult) -> str:
    """The full ` ```mermaid ` block body (without the fence itself — the caller wraps
    it, since whether/how to wrap it depends on the surrounding chat answer)."""
    return _Renderer().render(result)
