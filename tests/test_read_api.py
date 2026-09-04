"""Tests for the read-only HTTP side.

The one property worth guarding above the others: caddy proxies everything on this
port through the public funnel, so an unauthenticated route here is a public vault
reader. Every test below exists because of that.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from brain_mcp import read_api

TOKEN = "s3cret-read-token"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(read_api.settings, "read_token", TOKEN)
    app = Starlette(
        routes=[
            Route("/api/vault/health", read_api.health),
            Route("/api/vault/open", read_api.open_notes),
            Route("/api/vault/diff", read_api.note_diff),
            Route("/api/vault/accept", read_api.accept_note, methods=["POST"]),
        ]
    )
    return TestClient(app)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


# --- the gate -------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/vault/open", "/api/vault/diff?path=x.md"])
def test_no_token_no_vault(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401


@pytest.mark.parametrize(
    "header",
    [{"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}, {"Authorization": "Basic x"}],
)
def test_a_wrong_token_is_not_close_enough(client: TestClient, header: dict[str, str]) -> None:
    assert client.get("/api/vault/open", headers=header).status_code == 401


def test_health_needs_no_token(client: TestClient) -> None:
    """A caller has to be able to ask 'are you there' before it has a token."""
    resp = client.get("/api/vault/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "read_api": True}


def test_routes_are_not_registered_without_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed: an unauthenticated vault reader must not be one typo away."""
    monkeypatch.setattr(read_api.settings, "read_token", "")
    registered: list[str] = []

    class FakeMCP:
        def custom_route(self, path: str, methods: list[str]) -> object:
            registered.append(path)
            return lambda fn: fn

    assert read_api.register(FakeMCP()) is False
    assert registered == []


def test_routes_are_registered_with_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(read_api.settings, "read_token", TOKEN)
    registered: list[str] = []

    class FakeMCP:
        def custom_route(self, path: str, methods: list[str]) -> object:
            registered.append(path)
            return lambda fn: fn

    assert read_api.register(FakeMCP()) is True
    assert registered == [
        "/api/vault/health",
        "/api/vault/open",
        "/api/vault/diff",
        "/api/vault/accept",
    ]


# --- the data -------------------------------------------------------------


def test_open_notes_are_vault_relative(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Absolute paths would hand out the filesystem layout for no gain."""
    monkeypatch.setattr(read_api.settings, "vault_root", tmp_path)
    note = tmp_path / "notes" / "betrieb" / "x.md"
    note.parent.mkdir(parents=True)
    note.write_text("x")
    monkeypatch.setattr(
        read_api, "offene_notizen", lambda nur_agent: [(note, "agent-entwurf", None)]
    )

    body = client.get("/api/vault/open", headers=_auth()).json()

    assert body["notes"] == [
        {"path": "notes/betrieb/x.md", "quelle": "agent-entwurf", "geprueft": None}
    ]


def test_nur_agent_defaults_to_true(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent drafts and never-checked notes are different work; the default is
    the urgent one."""
    seen: list[bool] = []
    monkeypatch.setattr(read_api, "offene_notizen", lambda nur_agent: seen.append(nur_agent) or [])

    client.get("/api/vault/open", headers=_auth())
    client.get("/api/vault/open?nur_agent=false", headers=_auth())

    assert seen == [True, False]


def test_diff_requires_a_path(client: TestClient) -> None:
    assert client.get("/api/vault/diff", headers=_auth()).status_code == 400


def test_diff_outside_the_vault_is_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The path arrives over HTTP; the vault sandbox is what stops it."""
    from brain_mcp.vault_writer import VaultWriteError

    def boom(file_path: str, *, must_exist: bool, domain: str | None = None) -> Path:
        raise VaultWriteError("outside the vault")

    monkeypatch.setattr(read_api, "resolve_note_path", boom)

    resp = client.get("/api/vault/diff?path=../../etc/passwd", headers=_auth())

    assert resp.status_code == 400
    assert "outside" in resp.json()["detail"]


def test_diff_is_against_the_last_human_version(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Not against HEAD — HEAD may itself be agent work, which is the whole point."""
    monkeypatch.setattr(read_api.settings, "vault_root", tmp_path)
    note = tmp_path / "notes" / "x.md"
    note.parent.mkdir(parents=True)
    note.write_text("x")
    monkeypatch.setattr(
        read_api, "resolve_note_path", lambda file_path, must_exist, domain=None: note
    )
    monkeypatch.setattr(read_api, "letzte_menschliche_fassung", lambda p: "abc123")
    monkeypatch.setattr(read_api, "agenten_diff", lambda p: "@@ -1 +1 @@\n-a\n+b\n")

    body = client.get("/api/vault/diff?path=x.md", headers=_auth()).json()

    assert body == {"path": "notes/x.md", "base": "abc123", "diff": "@@ -1 +1 @@\n-a\n+b\n"}


# --- accepting a note: the one write ---------------------------------------


def test_accept_needs_a_token(client: TestClient) -> None:
    """The only write here must not be the one route that forgot the gate."""
    resp = client.post("/api/vault/accept", json={"path": "x.md", "quelle": "gemessen"})
    assert resp.status_code == 401


def test_accept_requires_a_quelle(client: TestClient) -> None:
    """An invented date takes a note out of list_stale forever, so the caller has
    to say how the content is evidenced rather than merely that it is."""
    resp = client.post("/api/vault/accept", json={"path": "x.md"}, headers=_auth())
    assert resp.status_code == 400
    assert "quelle is required" in resp.json()["detail"]


def test_accept_requires_a_path(client: TestClient) -> None:
    resp = client.post("/api/vault/accept", json={"quelle": "gemessen"}, headers=_auth())
    assert resp.status_code == 400


def test_accept_refuses_agent_entwurf(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A note cannot be accepted as still being an agent draft — abnehmen() says so
    and this must not route around it."""
    from brain_mcp.vault_writer import VaultWriteError

    note = tmp_path / "notes" / "x.md"
    note.parent.mkdir(parents=True)
    note.write_text("x")
    monkeypatch.setattr(read_api.settings, "vault_root", tmp_path)
    monkeypatch.setattr(
        read_api, "resolve_note_path", lambda file_path, must_exist, domain=None: note
    )

    def refuse(pfad: Path, quelle: str) -> str:
        raise VaultWriteError("--quelle muss eins von gemessen, recherchiert sein")

    monkeypatch.setattr(read_api, "abnehmen", refuse)

    resp = client.post(
        "/api/vault/accept", json={"path": "x.md", "quelle": "agent-entwurf"}, headers=_auth()
    )

    assert resp.status_code == 400
    assert "quelle" in resp.json()["detail"]


def test_accept_returns_the_commit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    note = tmp_path / "notes" / "x.md"
    note.parent.mkdir(parents=True)
    note.write_text("x")
    monkeypatch.setattr(read_api.settings, "vault_root", tmp_path)
    monkeypatch.setattr(
        read_api, "resolve_note_path", lambda file_path, must_exist, domain=None: note
    )
    monkeypatch.setattr(read_api, "abnehmen", lambda pfad, quelle: "abc1234")

    resp = client.post(
        "/api/vault/accept", json={"path": "x.md", "quelle": "gemessen"}, headers=_auth()
    )

    assert resp.status_code == 200
    assert resp.json() == {"path": "notes/x.md", "quelle": "gemessen", "commit": "abc1234"}


def test_open_hands_out_the_allowed_quellen(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A client that hard-coded the list would drift from vault_writer."""
    monkeypatch.setattr(read_api, "offene_notizen", lambda nur_agent: [])

    body = client.get("/api/vault/open", headers=_auth()).json()

    assert "agent-entwurf" not in body["quellen"]
    assert "gemessen" in body["quellen"]
