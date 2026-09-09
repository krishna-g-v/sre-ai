# Deployment & Environments

See [[00-overview]], [[01-architecture]].

## 1. Environments

| | Local / Dev | Production |
|---|---|---|
| Compute | Docker + Docker Compose on an Ubuntu VM | AWS EKS |
| Database | PostgreSQL+pgvector container (Docker Compose) | AWS RDS for PostgreSQL, with `pgvector` extension enabled |
| LLM provider | Any OpenAI-compatible chat completions API (currently nscale — `inference.api.nscale.com`) | AWS Bedrock |
| LLM model | Llama 4 Scout | Llama 4 Scout (same model, different provider — see [[00-overview]] open questions on Bedrock availability) |
| Embedding model | `BAAI/bge-large-en-v1.5`, local, baked into the backend image | Same — identical image/model in both environments (see §2a) |
| Secrets | `.env` file (git-ignored), loaded by Docker Compose | AWS Secrets Manager / EKS External Secrets → k8s Secrets |
| Frontend hosting | Vite/Next dev server or served via the backend container | Static build behind CloudFront/S3, or an EKS deployment — decide in `sre-ai-infra` when building |

## 2. LLM provider abstraction — generic env vars

The backend must never hardcode a specific vendor's name (e.g. "nscale", "OpenRouter") into its logic — only two adapter *kinds* exist: a generic **OpenAI-compatible REST client** (works against nscale, OpenRouter, or any other vendor exposing a `/v1/chat/completions`-style API — swapping vendors within this kind is just changing `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`, no code change) and a **Bedrock adapter** (AWS SDK-based, since Bedrock isn't a plain REST endpoint). Env var names are **generic** so the same code path works in both environments, only the values (and which adapter is selected) change:

```bash
# --- LLM (chat/completions) ---
LLM_PROVIDER=openai_compatible   # openai_compatible | bedrock
LLM_BASE_URL=https://inference.api.nscale.com/v1   # dev's current value (nscale); unused for bedrock (AWS SDK handles routing)
LLM_API_KEY=                     # required for openai_compatible; empty/unused for bedrock when using IAM (IRSA) auth
LLM_MODEL=meta-llama/Llama-4-Scout-17B-16E-Instruct   # dev's current value; prod: the equivalent Bedrock model ID for Llama 4 Scout — confirm the exact string/region availability at build time (see 00-overview.md open questions)
LLM_REGION=                      # used by the bedrock adapter only, e.g. us-east-1

# --- Embeddings (for RAG ingestion + query-time embedding) ---
# Local model only — Hugging Face is not reachable from the corporate network at runtime.
# No API key / base URL needed: the model runs in-process inside the backend, loaded from
# weights baked into the Docker image at build time. See §2a.
EMBEDDING_PROVIDER=local                              # local is the only supported value in v1 (no hosted-API option for embeddings)
EMBEDDING_MODEL_ID=BAAI/bge-large-en-v1.5             # fixes the 1024-dim vector column in pgvector — see 02-access-control-and-rag.md §5
EMBEDDING_LOCAL_MODEL_PATH=/opt/models/bge-large-en-v1.5   # path inside the container image where weights are baked in

# --- Database ---
DATABASE_URL=postgresql://user:pass@host:5432/sreagent

# --- Auth ---
JWT_SECRET=
JWT_EXPIRY_MINUTES=1440
BOOTSTRAP_ADMIN_USERNAME=
BOOTSTRAP_ADMIN_PASSWORD=

# --- Integrations (per-cluster/account config lives in DB `integration_scope`,
#     but base credentials/paths are env-driven) ---
AWS_REGION=
KUBECONFIG_PATH=                 # or per-cluster kubeconfig secrets mounted in EKS
GRAFANA_BASE_URL=
GRAFANA_API_KEY=
PROMETHEUS_BASE_URL=
ALERTMANAGER_BASE_URL=
```

Rules:
- In **prod on EKS**, prefer IAM roles for service accounts (IRSA) over static `LLM_API_KEY`/AWS keys wherever the Bedrock/CloudWatch SDK supports it — leave the key vars empty and rely on the pod's IAM role.
- In **dev**, `LLM_API_KEY` (currently an nscale key) is required and comes from a git-ignored `.env` — see §3a.
- The adapter layer (`LLM_PROVIDER` switch) lives entirely in `sre-ai-backend`; this doc just fixes the **contract** (var names + meaning) so it's consistent across both environments and doesn't get reinvented per-feature.
- The `LLM_*` vars above are for chat/completions only (Llama 4 Scout via the OpenAI-compatible adapter in dev / Bedrock in prod) and are unrelated to the embedding model, which is local — see §2a.

## 2a. Baking the local embedding model into the backend Docker image

Why: the corporate network (both the Ubuntu dev VM and the EKS prod environment) blocks outbound *unauthenticated* access to Hugging Face at container runtime, so the embedding model (`BAAI/bge-large-en-v1.5`, see [[02-access-control-and-rag]] §5) cannot be downloaded on first use. It must already be present in the image. The dev Ubuntu VM does have authenticated Hugging Face access available (via `HUGGING_FACE_TOKEN`, see §3a) — this resolves the open question in [[00-overview]] about whether the build environment can reach Hugging Face, at least for dev. **Confirm separately whether the actual prod/CI build pipeline has the same authenticated access**, or needs an internal model mirror instead.

Build-time steps (in `sre-ai-backend`'s `Dockerfile`):
1. A build stage downloads the model weights (e.g. via `huggingface_hub`'s `snapshot_download`, or `sentence-transformers`' own download-and-cache mechanism) to a fixed path, e.g. `/opt/models/bge-large-en-v1.5`, authenticating with `HUGGING_FACE_TOKEN` if the model or network path requires it.
2. `HUGGING_FACE_TOKEN` is a **build-time secret only** — pass it via Docker BuildKit's `--secret` mount (or an equivalent CI secret-injection mechanism), never as a plain `ARG`/`ENV`, so it is not cached into any image layer or left readable in the final image or its history.
3. The final image `COPY`s the downloaded weights from the build stage — no download step, and no `HUGGING_FACE_TOKEN`, is present at container start or at request time.
4. At runtime, the embedding client is configured to load from `EMBEDDING_LOCAL_MODEL_PATH` and should set the relevant "offline mode" flag for whatever library is used (e.g. `HF_HUB_OFFLINE=1` for `sentence-transformers`/`transformers`) so a missing-model bug fails fast instead of silently trying (and hanging on) a network call.
5. Rebuilding the image is the only way to change the embedding model — there is no runtime env var that swaps it, since the weights are physically baked in. Changing it is a migration (re-embed the whole corpus), not a config change — see [[00-overview]] open questions.

This applies only to `sre-ai-backend`'s image — the frontend image is unaffected, and the LLM (Llama 4 Scout) is still called over the network via the OpenAI-compatible/Bedrock adapters per §2, not bundled into any image.

## 3. Local dev topology (Docker Compose)

Services in `sre-ai-infra/docker-compose/`:
- `postgres` — Postgres + pgvector image, volumes for persistence, exposes `kb` and `ops` schemas (migrations run by the backend on startup or via a separate migration step).
- `backend` — FastAPI + LangGraph app, built from `sre-ai-backend`, reads `.env`.
- `frontend` — React dev server (or built static files served via nginx), built from `sre-ai-frontend`.

A single `docker-compose up` should bring up a fully working local stack against the dev LLM endpoint (currently nscale), assuming the developer supplies their own `LLM_API_KEY`.

## 3a. Dev environment variables (this Ubuntu VM)

The actual dev-time values (LLM endpoint, model, API key, HF token) live **only** in a git-ignored `sre-ai-infra/docker-compose/.env` — never in a committed doc or `.env.example`. `docker-compose/.env.example` (committed) documents the variable *names* with placeholders; see it for the full list. Two dev-specific notes:

- `LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY` currently point at nscale's OpenAI-compatible endpoint (`https://inference.api.nscale.com/v1`, model `meta-llama/Llama-4-Scout-17B-16E-Instruct`) — this is a dev-environment value, not a hardcoded requirement; prod points at Bedrock instead (§1).
- `HUGGING_FACE_TOKEN` is present in the dev `.env` for convenience (e.g. manually testing the embedding-model download step outside of a full Docker build) but, per §2a, is only ever consumed as a **build-time** secret — it must not be read by the running application containers.
- Any credential pasted into a chat/ticket/Slack message to hand off to a teammate or an AI assistant should be treated as exposed and rotated afterward, independent of where it ends up — this is a general credential-hygiene practice, not specific to this project.

## 4. Production topology (EKS + RDS)

- RDS PostgreSQL instance with `pgvector` enabled, in a private subnet, reachable from the EKS cluster's node/pod network.
- Backend deployed as an EKS `Deployment` + `Service` (+ `HorizontalPodAutoscaler` if needed later), with an IRSA-bound service account granting the read-only AWS permissions described in [[03-agent-and-integrations]].
- Frontend served as static assets (S3+CloudFront) or as its own lightweight EKS deployment behind an ingress — final call to be made in `sre-ai-infra` alongside actual Terraform/manifests.
- Secrets (`JWT_SECRET`, DB creds, any required API keys) sourced from AWS Secrets Manager, synced into k8s Secrets (e.g. via External Secrets Operator) — never committed, never baked into images.
- kubeconfig access for the EKS/kubectl agent tool: since the backend itself may run *inside* one EKS cluster while needing to query pods across *multiple* clusters (including its own), use in-cluster service account auth for the local cluster and mounted kubeconfig/IAM-auth for any additional target clusters, scoped per `integration_scope` config.

## 5. What belongs in `sre-ai-infra` vs. the app repos

- `sre-ai-infra`: `docs/` (all specs), `docker-compose/`, `eks/` (k8s manifests or Helm chart), `terraform/` (RDS, IAM roles/policies, networking) — i.e., everything about *how* the app runs, not the app's own code.
- `sre-ai-backend` / `sre-ai-frontend`: application code, their own `Dockerfile`, and app-level config (e.g. a `.env.example` documenting the vars from §2 relevant to that repo) — but not the orchestration manifests themselves.
