# backend

FastAPI + LangGraph backend for the SRE Agent (RAG, multi-agent investigation tools, auth, ingestion). Part of the `sre-ai` monorepo — see [`../docs/00-overview.md`](../docs/00-overview.md) for full requirements before making changes here.

- Access control & RAG design: [`../docs/02-access-control-and-rag.md`](../docs/02-access-control-and-rag.md).
- Agent design & integrations: [`../docs/03-agent-and-integrations.md`](../docs/03-agent-and-integrations.md).
- Chat sessions & orchestration: [`../docs/08-chat-sessions-and-orchestration.md`](../docs/08-chat-sessions-and-orchestration.md).
- Auth & user model: [`../docs/05-auth-and-users.md`](../docs/05-auth-and-users.md).
- Env var contract: [`../docs/06-deployment-and-environments.md`](../docs/06-deployment-and-environments.md).

## Local development

```bash
python -m venv .venv && source .venv/bin/activate

# CPU-only torch first — the default PyPI wheel pulls ~2GB of unused CUDA libraries.
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

cp .env.example .env   # then fill in real values (or point DATABASE_URL etc. at your own Postgres)
alembic upgrade head
uvicorn app.main:app --reload
```

Needs a running Postgres+pgvector instance (`docker run -p 5432:5432 -e POSTGRES_USER=sreagent -e POSTGRES_PASSWORD=sreagent -e POSTGRES_DB=sreagent pgvector/pgvector:pg16` works for local dev) and the env vars in `.env.example`. For the full stack, use `infra/docker-compose/` instead — its Dockerfile handles the CPU-only torch install and bakes in the embedding model at build time (see [`../docs/06-deployment-and-environments.md`](../docs/06-deployment-and-environments.md) §2a).

The bootstrap admin user (`BOOTSTRAP_ADMIN_USERNAME`/`BOOTSTRAP_ADMIN_PASSWORD`) is created automatically on first startup if no superuser exists yet — see [`../docs/05-auth-and-users.md`](../docs/05-auth-and-users.md) §3.

## Testing the chat agent's actual behavior

`tests/e2e/` has live conversation tests against a real running stack (real LLM, real embeddings, real Postgres) — the only way to actually catch chat-agent regressions like misclassification, false topic-drift, or hallucinated answers, since those are LLM judgment calls, not something a mocked unit test can see. They're slow and cost real inference calls, so they're never run automatically — see [`tests/e2e/README.md`](tests/e2e/README.md) for how to run them on demand (`pytest -m e2e -v`) before/after touching anything in `app/agents/`.
