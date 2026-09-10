"""Fixtures for the live e2e chat-conversation tests — see README.md in this directory
for what these are, why they're separate from any normal test run, and how to run them."""

import os
from pathlib import Path

import httpx
import pytest

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
TEST_USERNAME = os.environ.get("E2E_USERNAME", "admin")
TEST_PASSWORD = os.environ.get("E2E_PASSWORD", "admin123")

# backend/tests/e2e/conftest.py -> backend/tests/e2e -> backend/tests -> backend -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
ONBOARDING_PDF_PATH = Path(
    os.environ.get("E2E_ONBOARDING_PDF", _REPO_ROOT / "user_data" / "engg_onboarding.pdf")
)


@pytest.fixture(scope="session")
def api_client():
    with httpx.Client(base_url=f"{BASE_URL}/api", timeout=60.0) as client:
        yield client


@pytest.fixture(scope="session")
def auth_headers(api_client):
    resp = api_client.post("/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
    resp.raise_for_status()
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def onboarding_document(api_client, auth_headers):
    """Uploads the real onboarding PDF fresh for this test run (personal-scope, so it
    can't collide with anyone's group docs) and deletes it afterward — these tests must
    not depend on, or leave behind, any pre-existing knowledge-base state."""
    if not ONBOARDING_PDF_PATH.exists():
        pytest.skip(f"Onboarding PDF not found at {ONBOARDING_PDF_PATH} — set E2E_ONBOARDING_PDF to override.")

    with open(ONBOARDING_PDF_PATH, "rb") as f:
        resp = api_client.post(
            "/documents",
            headers=auth_headers,
            files={"file": ("engg_onboarding.pdf", f, "application/pdf")},
            data={
                "title": "Engineering Onboarding Guide",
                "owner_scope": "personal",
                "group_ids": "[]",
                "tags": "[]",
                "chunk_strategy": "whole_document",
            },
        )
    resp.raise_for_status()
    doc = resp.json()
    assert doc["status"] == "ready", f"document ingestion failed: {doc}"

    yield doc

    api_client.delete(f"/documents/{doc['id']}", headers=auth_headers)


class Conversation:
    """Wraps one chat session so test bodies read like the conversation they're
    reproducing, not a pile of raw HTTP calls."""

    def __init__(self, client: httpx.Client, headers: dict, session_id: str):
        self.client = client
        self.headers = headers
        self.session_id = session_id

    def say(self, content: str) -> dict:
        resp = self.client.post(
            f"/chat/sessions/{self.session_id}/messages",
            headers=self.headers,
            json={"content": content},
        )
        resp.raise_for_status()
        return resp.json()

    def session_state(self) -> dict:
        resp = self.client.get("/chat/sessions", headers=self.headers)
        resp.raise_for_status()
        return next(s for s in resp.json() if s["id"] == self.session_id)


@pytest.fixture()
def conversation(api_client, auth_headers, onboarding_document):
    """A fresh chat session per test. Depends on onboarding_document so the KB is
    guaranteed populated before any test in this session tries to talk about it."""
    resp = api_client.post("/chat/sessions", headers=auth_headers)
    resp.raise_for_status()
    session_id = resp.json()["id"]

    yield Conversation(api_client, auth_headers, session_id)

    api_client.delete(f"/chat/sessions/{session_id}", headers=auth_headers)
