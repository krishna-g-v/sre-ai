# frontend

React (Material Design / MUI) frontend for the SRE Agent. Part of the `sre-ai` monorepo — see [`../docs/00-overview.md`](../docs/00-overview.md) for full requirements before making changes here.

- Frontend-specific requirements: [`../docs/04-frontend-ui.md`](../docs/04-frontend-ui.md).
- Env var contract (which vars this app reads): [`../docs/06-deployment-and-environments.md`](../docs/06-deployment-and-environments.md).
- Repo layout & conventions: [`../docs/07-repo-structure-and-conventions.md`](../docs/07-repo-structure-and-conventions.md).

## Local development

```bash
npm install
npm run dev
```

Runs against the backend API at `VITE_API_BASE_URL` (see `.env.example`). For the full stack (backend + Postgres), use `infra/docker-compose/` instead.
