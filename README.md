# SRE Agent

An internal AI agent for day-to-day SRE work and engineer onboarding: a RAG chatbot over access-controlled documentation, plus read-only investigation tools (AWS CloudWatch, EKS/kubectl, Grafana, Prometheus).

**Start here:** [`docs/00-overview.md`](docs/00-overview.md) — requirements, architecture, and every settled decision live in `docs/`.

## Layout

```
sre-ai/
├── docs/         # requirements & architecture (source of truth)
├── frontend/     # React + MUI app
├── backend/      # FastAPI + LangGraph app
└── infra/        # docker-compose (dev), eks/ + terraform/ (prod)
```

## Local development

```bash
cp infra/docker-compose/.env.example infra/docker-compose/.env   # then fill in real values
cd infra/docker-compose
docker compose up --build
```

Frontend: http://localhost:5173 · Backend API: http://localhost:8000/docs
