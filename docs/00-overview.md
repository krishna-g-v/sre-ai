# SRE Agent — Overview & Decision Log

> **Read this file first.** It is the entry point for every Claude Code session (or human) working on this project. Every other doc in `docs/` builds on the decisions recorded here. If a doc conflicts with this file, this file wins until it is explicitly updated.

## 1. What we are building

An internal AI agent ("SRE Agent") that helps engineers with:

1. **Day-to-day SRE work** — monitoring Grafana dashboards, EKS clusters, deployment/pod health and logs, AWS CloudWatch, Prometheus/Alertmanager; helping engineers spot and understand production issues before/as they escalate.
2. **Onboarding & knowledge work** — a RAG chatbot over ingested organizational/application documentation, scoped by group membership, plus a personal knowledge base per user.

It is delivered as a chat-first web application with supporting dashboards, backed by a multi-agent LangGraph backend that can call read-only investigation tools (AWS CLI, kubectl, Grafana, Prometheus) in addition to RAG retrieval.

## 2. Primary personas

- **SRE Engineer** — needs the chatbot, monitoring dashboards, and access to all application/operational documentation relevant to their groups. Primary user of the "investigate a production issue" flow.
- **AI Engineer** — works on specific projects; should only see documents tagged to the group(s)/project(s) they belong to, not the whole org's docs.
- **Superuser / Admin** — a flag on any user account (not a separate role hierarchy); manages groups, user-to-group assignments, and document tags. See [[05-auth-and-users]].

Groups are **fully dynamic** — there is no fixed enum of roles baked into the system. "SRE Engineer" and "AI Engineer" above are example groups/personas, not hardcoded types. Any org can define arbitrary groups (e.g. `project-atlas`, `platform-core`, `payments-team`) and permissions (which docs are visible, which dashboards/integrations are enabled) flow from group membership.

## 3. MVP scope

**In scope for v1:**
- RAG chatbot over uploaded documents (PDF, Word, Markdown, TXT), access-controlled by dynamic group tags.
- Personal knowledge base per user, combined automatically with group-scoped docs during retrieval.
- Multi-agent LangGraph backend: RAG agent + domain agents for AWS/CloudWatch, EKS/kubectl, Grafana, Prometheus — all **read-only / advisory** (see below).
- Simple username + password login (no password hashing/encryption yet — explicitly deferred, see [[05-auth-and-users]]), JWT-based sessions.
- React + Material Design UI, dark/light themes, chat interface, dashboards, personal knowledge base management, admin screens for group/user/doc-tag management.
- Local dev on an Ubuntu VM via Docker Compose; production on AWS EKS + RDS (Postgres/pgvector).
- LLM access abstracted behind generic env vars: a generic OpenAI-compatible adapter in dev (currently pointed at nscale), AWS Bedrock in prod.

**Explicitly out of scope for v1 (future work, tracked so nobody "accidentally" builds it early):**
- Any autonomous remediation (restarting pods, scaling deployments, etc.) — v1 is **advisory only**. The agent proposes; a human executes.
- Microsoft Entra ID / SSO login — v1 uses plain username+password. The auth layer must be designed so Entra ID can be slotted in later without a rewrite (see [[05-auth-and-users]]).
- Password hashing/encryption, rate limiting, MFA — deferred alongside Entra ID.
- Confluence/wiki sync, git-repo doc sync — only manual file upload is in scope for v1 ingestion.
- Multi-region / multi-cluster federation beyond "point the integration at N EKS clusters/AWS accounts via config."

## 4. Key decisions (from requirements clarification)

These were decided explicitly with the user and should be treated as settled unless revisited:

| Topic | Decision |
|---|---|
| Roles/groups | Fully dynamic groups, no fixed role enum. Every user has an `is_superuser` boolean. |
| Admin capability | Superusers get an admin UI to create groups, assign users to groups, and tag documents. |
| Agent autonomy (v1) | Advisory only — investigate & recommend, never execute changes. |
| v1 integrations | Grafana, AWS CloudWatch, EKS/kubectl, Prometheus/Alertmanager. |
| Repo structure | **Single monorepo** (`sre-ai`, one GitHub remote), not separate repos as originally drafted — corrected once the actual git setup was in place. Subfolders: `docs/`, `frontend/`, `backend/`, `infra/` (docker-compose + EKS/Terraform). See [[07-repo-structure-and-conventions]]. |
| Doc ingestion (v1) | Manual file upload only: PDF, Word, Markdown, TXT. |
| Logs/ops vector store | Same PostgreSQL+pgvector instance as the document KB, but separate schema/tables with their own retention policy. |
| Personal KB scope | Combined automatically with the user's group-scoped docs on every chat query — no manual toggling. |
| Session mechanism | Simple JWT issued on login (plaintext password compare against DB for v1); frontend sends it as a Bearer token. |
| Agent architecture | Multi-agent: a supervisor graph routes to domain subgraphs (RAG, AWS/CloudWatch, EKS/kubectl, Grafana, Prometheus). |
| UI design system | Material Design (MUI), dark + light themes, elegant/professional palette (see [[04-frontend-ui]]). |
| LLM model | **Llama 4 Scout** (large context window) — via a generic OpenAI-compatible adapter in dev (currently nscale, model `meta-llama/Llama-4-Scout-17B-16E-Instruct`), AWS Bedrock in prod. Large context window is why whole-document-as-one-chunk is viable (see [[02-access-control-and-rag]]). |
| Chunking strategy | Configurable, not hardcoded to exact token counts: `whole_document` (single chunk) or `best_effort` (qualitative small/medium/large, natural-boundary splitting). System-wide default with a per-document override at upload time. See [[02-access-control-and-rag]]. |
| Retrieval behavior | Must not default to "always summarize the whole document" — retrieval mixes chunks (whole-doc and best-effort, across documents) based on relevance to the actual question asked. See [[02-access-control-and-rag]]. |
| Chat session scoping | Sessions auto-pin to a single document once a categorized, dominant-match topic is detected; renamed to that topic. Drift is judged by an LLM check each turn; on drift, the assistant tells the user to start a new session rather than answering. Live-ops questions (AWS/EKS/Grafana/Prometheus) are always allowed regardless of pin state. See [[08-chat-sessions-and-orchestration]]. |
| Embedding model | **Local model, baked into the backend Docker image at build time** — `BAAI/bge-large-en-v1.5` (1024-dim, MIT license, CPU-friendly). Corporate network blocks Hugging Face at runtime, so weights are downloaded once during image build (where internet access is available) and never fetched at runtime. Same model used for ingestion and query-time embedding, in both dev and prod (no per-environment split). See [[06-deployment-and-environments]] and [[02-access-control-and-rag]]. |
| AWS/EKS deployment | Real AWS resources (EKS `misthios-eks-sharedsvcs`, RDS, ECR, Bedrock inference profile, IRSA role) are provisioned and the Helm charts already applied outside this repo — this repo only builds images to match that existing config, not Terraform/charts. Backend auto-derives `DATABASE_URL` from discrete `DB_*` env vars and auto-selects the Bedrock LLM adapter when `BEDROCK_*` vars are present. Whole API moved under an `/api` prefix to match the charts' health-probe path and to give the frontend one consistent path to proxy. Frontend ships a small Express server (`frontend/Dockerfile.prod`) that proxies `/api/*` to `BACKEND_URL` at runtime, since the backend Service is `ClusterIP`-only (no Ingress) and unreachable from the browser directly. See [[06-deployment-and-environments]] §4 for the full env var table and flagged gaps (`JWT_SECRET`/bootstrap admin creds not yet in the chart values). |
| General-chat scope (no open-ended talk) | `general` classification narrowed to *only* a bare greeting/thanks/goodbye; everything else (including plain statements like "I am a new joinee") defaults to `document_topic` and goes through real retrieval instead of an LLM-improvised reply. The assistant never answers from its own outside knowledge and never names the source document (only "based on the knowledge I have..."). Prompted by a reported case where a non-question statement produced a fabricated "Welcome to the team — here's what I can help with" menu. See [[08-chat-sessions-and-orchestration]] §4 and §9. |

## 5. Doc map

| Doc | Covers |
|---|---|
| [01-architecture.md](01-architecture.md) | System components, data flow, tech stack, repo topology |
| [02-access-control-and-rag.md](02-access-control-and-rag.md) | Dynamic groups, document tagging/metadata, pgvector schema, retrieval scoping |
| [03-agent-and-integrations.md](03-agent-and-integrations.md) | LangGraph multi-agent design, tool contracts, autonomy/guardrails |
| [04-frontend-ui.md](04-frontend-ui.md) | React/Material Design UI, theming, screens, color system |
| [05-auth-and-users.md](05-auth-and-users.md) | Login flow, user/group data model, JWT, future Entra ID path |
| [06-deployment-and-environments.md](06-deployment-and-environments.md) | Docker Compose (dev), EKS+RDS (prod), env var conventions, LLM provider abstraction |
| [07-repo-structure-and-conventions.md](07-repo-structure-and-conventions.md) | How the 3 repos relate, cross-repo referencing, conventions for future Claude Code sessions |
| [08-chat-sessions-and-orchestration.md](08-chat-sessions-and-orchestration.md) | Query orchestration/categorization, document-pinned chat sessions, topic drift handling, session naming |

## 6. Open questions / assumptions to confirm

These were reasonable defaults chosen to keep moving, not explicitly confirmed line-by-line with the user — flag if wrong:

- **Alert/warning color palette**: the user specified primary colors `#1474d4` (blue) and `#06b6ed` (cyan) plus a soft semantic color `#78b75e` (soft green) as an *example* of the "soft color" style for alerts/warnings. Since `#78b75e` reads as a success/positive green rather than a warning color, [04-frontend-ui.md](04-frontend-ui.md) proposes a full soft semantic palette (success/warning/critical/info) in that same visual language and treats `#78b75e` as the **success** token. Confirm or adjust.
- Document formats for v1 ingestion assume standard parsing (PDF text extraction, DOCX, Markdown, plain text) with no OCR for scanned PDFs — OCR is future work.
- "EKS cluster monitoring" assumes the backend is given kubeconfig/IAM access to one or more specific EKS clusters via config, not auto-discovery of arbitrary clusters in an AWS account.
- **Llama 4 Scout on AWS Bedrock**: assumed available as a Bedrock-hosted model. Confirm the exact Bedrock model ID and regional availability at build time in [[06-deployment-and-environments]] — Bedrock's supported model catalog changes over time and this doc does not hardcode a specific model ID string for that reason.
- **Dev LLM provider is nscale, not OpenRouter**: earlier drafts of this doc set said "OpenRouter" as the placeholder dev provider; the actual dev environment (this Ubuntu VM) uses nscale's OpenAI-compatible inference API instead. Docs have been updated to describe the dev adapter generically ("OpenAI-compatible endpoint, currently nscale") rather than naming a specific vendor, consistent with the original "keep env vars generic" instruction — see [[06-deployment-and-environments]] §2.
- **Hugging Face access at build time — resolved for dev, open for prod**: the dev Ubuntu VM has authenticated Hugging Face access via a `HUGGING_FACE_TOKEN`, used only as a Docker build-time secret to download the embedding model (see [[06-deployment-and-environments]] §2a). Whether the actual prod/CI build pipeline has equivalent access (vs. needing an internal model mirror) is still unconfirmed.
- The "dominant match" threshold/margin that triggers auto-pinning a session to a document (see [[08-chat-sessions-and-orchestration]]) is a tunable config value, not a fixed number specified by the user — pick a sensible default during implementation and make it configurable.
- **Embedding model choice is a hard-to-reverse decision**: `bge-large-en-v1.5`'s 1024-dim output is baked into the `kb.chunks`/`ops.events` vector column types. Swapping embedding models later requires re-embedding the entire corpus (documents and ops data), not just a config change — flag any future request to "just switch the embedding model" as a migration, not a tweak.
- Assumed the CI/build environment (wherever `docker build` runs for `backend`) has outbound internet access to Hugging Face (or an internal model mirror/artifact registry) even though the deployed runtime environment does not — confirm this at build-pipeline setup time; if even the build environment is fully air-gapped, the model weights need to be vendored into the repo or an internal artifact store some other way.
