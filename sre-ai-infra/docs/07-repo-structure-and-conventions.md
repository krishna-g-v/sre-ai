# Repo Structure & Conventions for Claude Code Sessions

This doc exists specifically so that a **future Claude Code session working inside `sre-ai-frontend` or `sre-ai-backend`** (which won't have this conversation's context) can quickly find and trust the requirements.

## 1. The three repos

```
sre-ai/                      # parent workspace directory (not itself a repo)
├── sre-ai-infra/            # git repo — source of truth for requirements + deployment
│   ├── docs/                # <-- ALL requirement/architecture docs live here
│   │   ├── 00-overview.md
│   │   ├── 01-architecture.md
│   │   ├── 02-access-control-and-rag.md
│   │   ├── 03-agent-and-integrations.md
│   │   ├── 04-frontend-ui.md
│   │   ├── 05-auth-and-users.md
│   │   ├── 06-deployment-and-environments.md
│   │   ├── 07-repo-structure-and-conventions.md   # this file
│   │   └── 08-chat-sessions-and-orchestration.md
│   ├── docker-compose/      # local dev orchestration
│   ├── eks/                 # k8s manifests / Helm chart for prod
│   └── terraform/           # RDS, IAM, networking for prod
├── sre-ai-frontend/         # git repo — React app only
└── sre-ai-backend/          # git repo — FastAPI + LangGraph app only
```

## 2. Rule: requirements live in one place

**`sre-ai-infra/docs/` is the single source of truth.** Do not duplicate requirements into `sre-ai-frontend` or `sre-ai-backend` READMEs beyond a short pointer. If a requirement changes, update it in `sre-ai-infra/docs/` first.

## 3. How to reference these docs from another repo/session

If you (a Claude Code session, or a human) are working inside `sre-ai-frontend` or `sre-ai-backend` and need requirements context:

1. Check whether `sre-ai-infra` is checked out as a sibling directory (i.e. `../sre-ai-infra/docs/`) — it usually will be, since all three repos are meant to be cloned side-by-side under one parent workspace folder, as in this environment (`/pdata/claude/sre-ai/`).
2. Start at `../sre-ai-infra/docs/00-overview.md` — it links to every other doc and lists the settled decisions.
3. If `sre-ai-infra` is not available locally, ask the user for its location/remote URL rather than guessing or re-deriving requirements from scratch.

Each of `sre-ai-frontend/README.md` and `sre-ai-backend/README.md` contains this same pointer.

## 4. Conventions

- Keep doc filenames numbered (`00-`, `01-`, ...) so ordering is obvious in a file listing.
- Use `[[doc-name-without-extension]]` wiki-link style cross-references between docs (as used throughout this doc set) — human-readable even where the renderer doesn't turn them into real links.
- When a decision changes, update the **decision log table in `00-overview.md`** as well as the doc that goes into detail on it — don't let them drift.
- New integrations, new groups semantics, or new autonomy tiers should be added as new sections/docs, not by silently reinterpreting existing ones.
