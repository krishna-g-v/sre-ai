# Repo Structure & Conventions for Claude Code Sessions

This doc exists specifically so that a **future Claude Code session working in this repo** (which won't have any prior conversation's context) can quickly find and trust the requirements.

## 1. Monorepo layout

A single git repo, one GitHub remote (`sre-ai`). This was a correction from an earlier draft of these docs, which assumed three separate repos before the actual git setup existed — see [[00-overview]] decision log.

```
sre-ai/                          # repo root
├── docs/                        # <-- ALL requirement/architecture docs live here
│   ├── 00-overview.md
│   ├── 01-architecture.md
│   ├── 02-access-control-and-rag.md
│   ├── 03-agent-and-integrations.md
│   ├── 04-frontend-ui.md
│   ├── 05-auth-and-users.md
│   ├── 06-deployment-and-environments.md
│   ├── 07-repo-structure-and-conventions.md   # this file
│   └── 08-chat-sessions-and-orchestration.md
├── frontend/                    # React app
├── backend/                     # FastAPI + LangGraph app
├── infra/                       # docker-compose (dev), eks/ + terraform/ (prod)
│   ├── docker-compose/
│   ├── eks/
│   └── terraform/
├── .gitignore
└── README.md
```

## 2. Rule: requirements live in one place

**`docs/` is the single source of truth.** Do not duplicate requirements into `frontend/README.md` or `backend/README.md` beyond a short pointer. If a requirement changes, update it in `docs/` first.

## 3. How to find these docs from anywhere in the repo

Every subfolder (`frontend/`, `backend/`, `infra/`) is a direct sibling of `docs/`, so from any of them the docs are always at `../docs/`:

1. Start at `../docs/00-overview.md` — it links to every other doc and lists the settled decisions.
2. Each of `frontend/README.md` and `backend/README.md` contains this same pointer.

## 4. Conventions

- Keep doc filenames numbered (`00-`, `01-`, ...) so ordering is obvious in a file listing.
- Use `[[doc-name-without-extension]]` wiki-link style cross-references between docs (as used throughout this doc set) — human-readable even where the renderer doesn't turn them into real links.
- When a decision changes, update the **decision log table in `00-overview.md`** as well as the doc that goes into detail on it — don't let them drift.
- New integrations, new groups semantics, or new autonomy tiers should be added as new sections/docs, not by silently reinterpreting existing ones.
