from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.routes import admin, agents, alerts, auth, chat, documents, groups, health, stats
from app.core.config import get_settings
from app.db.models import User
from app.db.session import SessionLocal


def _ensure_bootstrap_admin() -> None:
    """docs/05-auth-and-users.md §3 — the first superuser must exist without manual SQL."""
    settings = get_settings()
    db = SessionLocal()
    try:
        existing_superuser = db.execute(select(User).where(User.is_superuser.is_(True))).first()
        if existing_superuser is not None:
            return

        existing_username = db.execute(
            select(User).where(User.username == settings.bootstrap_admin_username)
        ).scalar_one_or_none()
        if existing_username is not None:
            existing_username.is_superuser = True
            db.commit()
            return

        db.add(
            User(
                username=settings.bootstrap_admin_username,
                password=settings.bootstrap_admin_password,
                display_name="Bootstrap Admin",
                is_superuser=True,
            )
        )
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_bootstrap_admin()
    yield


app = FastAPI(title="SRE Agent API", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bare /health for local docker-compose / convenience curl checks.
app.include_router(health.router)

# Everything (including /api/health) also mounted under /api — the AWS/EKS deployment's
# liveness/readiness probes hit /api/health, and the frontend's production server proxies
# same-origin /api/* requests to this backend (see frontend/server.ts), so the whole API
# needs to live under one consistent prefix rather than special-casing just health.
api_router = APIRouter(prefix="/api")
for router in (health.router, auth.router, documents.router, chat.router, admin.router, groups.router, agents.router, alerts.router, stats.router):
    api_router.include_router(router)
app.include_router(api_router)
