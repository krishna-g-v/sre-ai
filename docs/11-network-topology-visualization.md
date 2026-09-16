# VPC Network Topology Visualization

See [[00-overview]], [[09-ops-runbook-and-proactive-monitoring]] (fixed read-only tool catalog this extends, §2's AssumeRole model), [[10-nl-to-cli-execution]] (per-user AWS account registration this reuses, and the architecture boundary this doc's §2 explains why it *doesn't* reuse).

This covers a third way `live_ops_node` can answer a live-ops question, alongside the hand-written tool catalog (docs/09 §3) and the NL-to-CLI generator (docs/10): given a starting VPC, discover and render its network topology — subnets, route tables, gateways, VPC peering, Site-to-Site VPN, Transit Gateway attachments, VPC endpoints, and the instances living in each subnet — as a Mermaid diagram plus a text summary.

## 1. Decisions (confirmed with the user, 2026-09-15)

| Topic | Decision |
|---|---|
| Implementation shape | A new **fixed tool** (boto3, like `k8s_get_pods`/`cloudwatch_query_logs` in docs/09 §3), not a NL-to-CLI generated command. One question here needs ~10 coordinated `describe-*`/`list-*` calls stitched into one structure — the CLI generator (docs/10) is built for one command → one answer per turn, not multi-call aggregation with cross-referencing. See §2. |
| Access model | Per-user `user_aws_accounts` (docs/10 §9), not the group-scoped `integration_scope` model the rest of docs/09 §3's fixed tools use. Reasoning: this is interactive/personal/self-service the same way the CLI pipeline is (an engineer investigating their own registered accounts), not admin-curated/shared-across-a-group the way Grafana/Prometheus/the poller are. |
| Data model | A **graph**, not a strict tree — VPC peering and Transit Gateway attachments can form cycles (A peered to B peered back to A). Rendered as a tree rooted at the starting VPC, with visited-node tracking so a cycle renders once, not infinitely. |
| Traversal scope (v1) | Full detail on the starting VPC (subnets w/ AZ+CIDR+public/private, route tables, IGW, NAT gateways, VPC endpoints, instances) **plus one hop** into anything directly connected: peered VPCs, VPCs reachable via a shared Transit Gateway attachment, and the Customer Gateway/VPN Gateway side of any Site-to-Site VPN connection — same account/region only. No recursion past that one hop (a peered VPC's own peering connections are not expanded). |
| Cross-account | Out of scope for v1. If a peering connection or TGW attachment points at an AWS account the user hasn't personally registered, it renders as an opaque edge (peer account id + connection id), not described further. |
| Leaf detail | EC2 instances render as leaves under their subnet (id, name tag, state), not just a count — capped per subnet (§5) so a large subnet doesn't blow up the diagram. |
| Routing (how `live_ops_node` decides to call this) | A small, cheap LLM classification call, not a keyword match — mirrors the existing `_classify`/`_check_drift` pattern in `orchestrator.py` rather than checking `"topology" in lowered`. See §3. |
| VPC selection | The user must name a VPC (by `vpc-id` or `Name` tag), resolved from the current message or conversation history. If none is named and the account/region has more than one VPC, the tool asks the user to disambiguate rather than rendering all VPCs at once — same "ask, don't guess" principle docs/10 §9/§7a established for account/cluster resolution. |
| Output format | A Mermaid `graph` block (not `flowchart TB`/a strict tree layout — cross-links from peering/VPN don't fit one) plus a short Markdown counts summary, in one synthesized chat answer — same second-LLM-pass pattern `cli_agent.py` uses to turn raw tool output into prose. |

## 2. Why this isn't a NL-to-CLI use case

Docs/10 §1 already drew this line for a different reason ("EKS, EC2/VPC, ECR, CloudWatch, RDS — all metadata/describe-level"): that pipeline generates and validates **one** `aws`/`kubectl` command per turn. A topology view needs `describe-vpcs`, `describe-subnets`, `describe-route-tables`, `describe-internet-gateways`, `describe-nat-gateways`, `describe-vpc-peering-connections`, `describe-vpn-connections`, `describe-vpn-gateways`, `describe-customer-gateways`, `describe-transit-gateway-vpc-attachments`, `describe-vpc-endpoints`, `describe-network-interfaces`/`describe-instances` — a fixed, known sequence of calls whose results must be cross-referenced by id (which subnet's route table points at which NAT gateway, which peering connection's accepter VPC is which), not something an LLM should re-derive per question via retry/self-correction. That's exactly the shape of the existing fixed-tool catalog (docs/09 §3): a hand-written function using `aws_session.py`'s `get_client`, not a generated shell command.

This also sidesteps `cli_validator.py` entirely — `describe_vpc_topology` never constructs or executes a shell command, so there's nothing for that module's allowlist to gate. The read-only guardrail here is the same one docs/09's module docstring states for the rest of `live_ops_agents.py`: *no mutating call exists in this function for anything to invoke* — every boto3 call it makes is `describe_*`/`list_*`/`get_*`, by construction, not by a runtime check.

## 3. Routing

`live_ops_node` ([orchestrator.py](../backend/app/agents/orchestrator.py):192) currently tries `answer_with_generated_cli` unconditionally first (docs/10 §9d — a keyword gate in front of it was found live to be actively harmful and removed). This adds one more classification step ahead of that call:

```
live_ops_node reached (classifier already said "live_ops")
  -> _classify_topology_intent(llm, message, history):
       one LLM call, JSON contract:
       {"is_topology": true, "vpc": "<id or Name tag>", "account_label": "<only if >1 account known>"}
       or {"is_topology": false}
  -> if is_topology and a vpc was resolved: call describe_vpc_topology(...) directly,
     skip answer_with_generated_cli entirely for this turn
  -> if is_topology but no vpc resolved (and >1 VPC exists in the account/region):
     ask the user to name one, skip both the CLI generator and fixed tools
  -> otherwise: existing flow unchanged (answer_with_generated_cli -> fixed tools -> decline)
```

This is deliberately a **separate** LLM call from CLI generation, not a field folded into `GENERATE_SYSTEM_PROMPT` (docs/10 §9's prompt) — the CLI generator shouldn't need to know about a capability it never invokes itself, and keeping tool-selection separate from command-generation avoids the two concerns fighting over the same JSON contract. Same reasoning as why `_classify` (top-level category) and `_check_drift` (pinned-session drift) are two separate calls in `orchestrator.py` rather than one combined prompt.

History matters here the same way it does throughout this module (see `orchestrator.py`'s docstring): "show me its peering connections" after a prior turn already named a VPC only resolves correctly because the classification call sees prior turns, not just the latest message.

## 4. AWS calls

| Call | Purpose |
|---|---|
| `ec2:DescribeVpcs` | Resolve the named VPC (by id or `Name` tag), get its CIDR |
| `ec2:DescribeSubnets` | Subnets in the VPC — CIDR, AZ, `MapPublicIpOnLaunch` |
| `ec2:DescribeRouteTables` | Determine public vs. private per subnet (route to an IGW vs. not) |
| `ec2:DescribeInternetGateways` | IGW attached to the VPC |
| `ec2:DescribeNatGateways` | NAT gateways and which subnet each lives in |
| `ec2:DescribeVpcEndpoints` | Interface/gateway endpoints in the VPC |
| `ec2:DescribeNetworkInterfaces`, `ec2:DescribeInstances` | Leaf-level instances per subnet (§5 cap) |
| `ec2:DescribeVpcPeeringConnections` | Peering connections where this VPC is requester or accepter |
| `ec2:DescribeVpnConnections`, `ec2:DescribeVpnGateways`, `ec2:DescribeCustomerGateways` | Site-to-Site VPN topology (VGW attached to this VPC, its VPN connections, each connection's Customer Gateway) |
| `ec2:DescribeTransitGatewayVpcAttachments`, `ec2:DescribeTransitGatewayAttachments` | TGW attachment for this VPC and sibling VPC attachments on the same TGW (the "one hop" per §1) |

Which of these actually succeed depends entirely on the permissions the user granted the role/access key they registered under Settings → AWS Accounts — this project doesn't prescribe or track a required policy for it. A call the registered credentials aren't permitted to make simply fails and degrades that one branch of the diagram (§6), the same as any other AWS API error.

## 5. Rendering

**Structure**, built server-side before either LLM call touches it (the LLM only turns already-assembled structured data into prose/diagram — it doesn't re-derive cross-references from raw API output):

```
VpcNode
  id, cidr, name_tag
  subnets: [SubnetNode]
    id, cidr, az, public: bool, route_table_id
    nat_gateway: NatGatewayNode | None
    instances: [InstanceLeaf]  # capped, see below
  internet_gateway: IgwNode | None
  vpc_endpoints: [VpcEndpointNode]
  peering_connections: [PeeringEdge]      # -> PeerVpcNode (one hop) or OpaqueNode (cross-account)
  vpn_connections: [VpnEdge]              # -> CustomerGatewayNode
  tgw_attachments: [TgwEdge]              # -> sibling VpcNode (one hop, same TGW) or OpaqueNode
```

- **Instance cap**: 25 instances rendered per subnet; beyond that, a single `"+N more"` leaf. Keeps a diagram for a subnet with hundreds of instances readable; a subnet with a handful shows everything.
- **Cycle handling**: a `visited: set[vpc_id]` threaded through peering/TGW expansion — the root VPC is added before recursing, so a peering connection back to the root (or to a sibling already rendered via another edge) renders as a reference edge to the existing node, not a re-expanded subtree.
- **Cross-account edges**: if a peering connection's or TGW attachment's peer account id isn't in the requesting user's registered `user_aws_accounts`, render an `OpaqueNode` (account id + connection id only) — no attempt to assume into it.

**Diagram**: a Mermaid `graph LR` (left-to-right graph, not `flowchart TB`) — chosen over a tree-only layout specifically because peering/VPN/TGW edges are cross-links, not parent-child, and `graph` renders those without contorting the layout. Subnets/gateways/instances nest under their VPC via Mermaid subgraphs; peering/VPN/TGW render as labeled edges between VPC subgraphs.

**Text summary** accompanies the diagram in the same answer: counts (subnets, public vs. private, peering connections, VPN connections, TGW attachments, instances) plus anything that failed to resolve (a `describe-*` call that came back `AccessDenied`, a cross-account edge left opaque) — same "state plainly what didn't resolve, never fabricate" principle as every other tool in this codebase (docs/00 §3's advisory-only guardrail).

## 6. Failure handling

Per-call, not whole-tool: a single `describe-*` call failing (permission denied, resource not found, region mismatch) degrades that one branch of the topology (e.g. "VPN topology: could not be determined — Access Denied on `DescribeVpnConnections`") rather than failing the entire answer — same degrade-one-section pattern `cli_agent.py`'s `_describe_relevant_docs` already uses for an empty/unreachable KB (docs/10 §10).

## 7. Pipeline implementation

Built as designed above, in `app/services/vpc_topology.py` (a new module, not folded into `app/agents/live_ops_agents.py` — the multi-call assembly logic and its dataclasses were substantial enough to warrant their own file, resolved the "TBD at implementation time" question this section originally left open):

- `describe_vpc_topology(db, user_id, vpc_identifier="", account_label=None) -> TopologyResult | str`, using `app/services/aws_session.py::get_client` exactly as the existing fixed tools do. Account resolution reuses the exact same "ask, don't guess" logic `run_readonly_aws` uses — lifted out of `cli_executor.py` into `app/services/user_aws_accounts.py::resolve_account`/`account_config` (public functions now) once this module needed the identical behavior, rather than a second copy.
- `app/services/topology_mermaid.py::to_mermaid(result) -> str` — the Mermaid `graph LR` serializer (§5), a separate module since it's the only place that needs to know Mermaid syntax.
- `vpc_topology.py::summarize_counts(result) -> str` — the mechanical half of the "text summary" from §5, computed in Python rather than left for an LLM to tally.
- `orchestrator.py`'s `live_ops_node` gained `_classify_topology_intent` (§3) ahead of `answer_with_generated_cli`, and `_synthesize_topology_answer`, which feeds the LLM only `summarize_counts`'s text as ground truth and appends the Mermaid diagram **verbatim** afterward — the model is explicitly told not to draw or describe the diagram itself, so a hallucinated or malformed diagram can't reach the user. (§9 below: the prompt instruction alone wasn't sufficient live, so a deterministic strip of any LLM-authored mermaid fence backs it up.) `describe_known_accounts` (the "Known AWS accounts" listing) was similarly lifted out of `cli_agent.py` into `user_aws_accounts.py` once the classifier needed the same listing.
- `frontend/src/components/MermaidDiagram.tsx` (new component) + a `language-mermaid` case in `MarkdownContent.tsx`'s `code` renderer. `mermaid` (`^11.17.2`) added to `package.json`, dynamically imported so it's not in the main bundle for users who never see a diagram; theme picked from MUI's `useTheme().palette.mode`, `securityLevel: "strict"` since diagram content traces back to AWS resource tags a user could control.

**Tests**: `tests/test_vpc_topology.py` (13 cases — disambiguation, AssumeRole failure, public/private subnet detection, instance capping, same-account vs. cross-account peering/TGW, the memoization-across-two-edges case, VPN+Customer-Gateway assembly, per-call degradation), `tests/test_topology_mermaid.py` (11 cases), `tests/test_orchestrator.py` (9 cases, the two new pure(ish) orchestrator functions plus the §9 regression test — this repo's convention is to exercise the full LangGraph/DB wiring only via `tests/e2e/`, not a mocked unit test, per docs/10 §9's note on `user_settings.py`). 142 backend unit tests passing total, no regressions.

**Verified without a real AWS account**: the exact Mermaid text `to_mermaid()` produces was rendered through the real installed `mermaid` package in headless Chromium (dark and light theme), confirming valid SVG output with zero console errors and correct subgraph nesting/opaque-node dashed styling/edge-type distinction. `tsc -b` and `npm run build` both pass.

## 8. Status

All of §7 is built, unit-tested, and — per §9 — verified live end to end against a real account. No known gaps remain; the codebase's usual caveat still applies (a future live session may surface something a mocked test can't).

## 9. Live verification (2026-09-15, real account 907986008762)

Run against the same account docs/10's own live testing used, already registered under Settings → AWS Accounts with its own AssumeRole credentials (`role/sre-agent-readonly`, `ap-southeast-2`) — no code changes needed to reach it, confirming §7's account-resolution reuse works as designed. Backend and frontend images were rebuilt from current source first (the running dev containers don't bind-mount source, so a stale image would have silently tested old code).

Two real questions run through the actual chat API end to end:

1. **"list the VPCs in the sreacc account"** — routed through the NL-to-CLI pipeline (not topology, correctly — this is a narrower question), returned two real VPCs including `vpc-0efa68055b98ba4a4` (`medreport_incoming`, `10.0.0.0/16`). Confirms the topology classifier isn't over-firing on adjacent questions the existing pipeline already handles.
2. **"show me the full network topology of vpc-0efa68055b98ba4a4 — subnets, gateways, peering, VPN, everything"** — correctly classified as a topology request, `describe_vpc_topology` ran for real: 1 subnet (public, `10.0.1.0/24`), 1 running instance (`i-091487317b438bc65`, tagged `Prod`), 1 Internet Gateway, and 1 VPC peering connection to a different, unregistered AWS account (`036222729236`) — correctly rendered as an opaque, dashed node per §1's cross-account rule rather than erroring or guessing. The synthesized answer and the resulting diagram were both accurate against this real data.

**One real bug found, not visible from unit tests or code review**: on the first run, the synthesized answer contained **two** mermaid blocks — the real, deterministically-generated one, and a second, fabricated one the LLM drew on its own (`subnet-1`, `instance-1`, `vpc-peering-1` — none of these are real ids) despite `TOPOLOGY_SYNTHESIZE_SYSTEM_PROMPT` explicitly instructing it not to. A prompt instruction alone wasn't a reliable guardrail — same lesson docs/03 §3 and docs/10 §2 already drew for the read-only boundary, now confirmed for this boundary too. Fixed with defense in depth, not just a stronger prompt: `_synthesize_topology_answer` now strips any ` ```mermaid ` fence out of the narrative (`_MERMAID_FENCE_RE`) before appending the real one, so a non-compliant response degrades to "missing narrative content," never "two diagrams, one fabricated." The prompt was also strengthened (explicit "Do NOT include a ```mermaid code block... not even a small or partial one") as the first line of defense, but the strip is what actually guarantees it. Covered by `test_synthesize_topology_answer_strips_a_hallucinated_mermaid_block_from_the_narrative`. Re-ran question 2 after the fix (rebuilt backend image, same account, same VPC) — exactly one, correct diagram.

The real diagram's exact Mermaid text (from the fixed run) was also rendered through the real `mermaid` package in headless Chromium, same as §7's synthetic example — valid SVG, correct dashed styling on the cross-account node, zero console errors.

Not covered by this pass: Site-to-Site VPN and Transit Gateway attachments (this account/VPC has neither), and the actual browser UI (`MermaidDiagram.tsx` in the running chat page) — verified instead via the real diagram text rendered standalone through the same `mermaid` package, since no browser session was available in this environment. Both are reasonable follow-ups whenever a VPC with VPN/TGW is available to test against, or a browser session is available to click through the chat UI directly — not blockers, since the underlying pieces (real AWS calls, real serialization, real rendering) are now each independently confirmed working.
