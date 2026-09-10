# Live chat e2e tests

Integration tests against the **real running stack** — real backend, real Postgres, real
Llama 4 Scout inference, real embedding model. They exist to catch query-orchestration and
conversational-context regressions in the chat agent (misclassification, false-positive
topic drift, hallucinated answers) that a mocked/unit test can't catch, since the actual
failure mode lives in how the LLM interprets a real conversation.

## Why these are never run by default

They're slow (each test is one or more real LLM round-trips), cost real inference calls,
and are inherently a little non-deterministic (you're testing an LLM's judgment, not a
pure function) — not something to run on every save or commit. `pyproject.toml` marks
them (`pytest.mark.e2e`) and excludes that marker by default, so a bare `pytest` run in
`backend/` skips this directory entirely.

## Running them

1. The full stack must actually be up:
   ```bash
   cd infra/docker-compose
   docker compose up -d
   ```
2. Install test dependencies (once): `pip install -r requirements-dev.txt`
3. Run on demand:
   ```bash
   cd backend
   pytest -m e2e -v
   ```

Defaults assume `http://localhost:8000`, the bootstrap `admin`/`admin123` account, and
`user_data/engg_onboarding.pdf` at the repo root. Override with `E2E_BASE_URL`,
`E2E_USERNAME`/`E2E_PASSWORD`, `E2E_ONBOARDING_PDF` if your setup differs.

Each test gets its own fresh chat session (deleted afterward); the onboarding PDF is
uploaded once per test run as a personal-scope document and deleted at the end — nothing
here depends on or pollutes whatever's already in anyone's knowledge base.

## If a test fails

Read the assertion message first — they're written to say *what* was expected/forbidden
and show the actual answer text, not just "assert False". A failure here means the chat
agent's actual behavior changed, not necessarily that the test is wrong — check whether a
recent prompt/orchestrator change (`app/agents/orchestrator.py`, `app/agents/rag_agent.py`)
explains it before assuming LLM flakiness.
