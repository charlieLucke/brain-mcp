"""A narrow read-only HTTP side for the review view.

`tools/geprueft.py` answers two questions no other interface can: which notes an
agent wrote and nobody has read yet, and — for one of them — what changed since
the last time a *human* touched it. Both are git operations on the vault, so they
live here and not in whatever wants to display them.

Until now they were reachable only as MCP tools, which means only from a client
that speaks MCP and holds an OAuth token. That is the right shape for Claude and
the wrong shape for a dashboard on the same machine, so these three routes expose
the same data as JSON.

Accepting a note is the one write here, added on 2026-09-05 so the review view can
be finished in a browser rather than requiring a remembered command. It goes
through the same `abnehmen()` the command line uses — including its refusal of an
invented `quelle`, which is the point of the field.

**The token is not optional.** caddy's default route proxies everything on this
port through the public funnel, so a route here is publicly reachable whether or
not that was intended. Without `BRAIN_READ_TOKEN` the routes are not registered
at all — an unauthenticated vault reader is not something to leave to a
misconfiguration.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from brain_mcp.config import settings
from brain_mcp.tools.geprueft import (
    abnehmen,
    agenten_diff,
    letzte_menschliche_fassung,
    offene_notizen,
)
from brain_mcp.vault_writer import QUELLE_AGENT, QUELLEN, VaultWriteError, resolve_note_path

log = logging.getLogger(__name__)


def _authorized(request: Request) -> bool:
    """Check the bearer token in constant time."""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[len("Bearer ") :], settings.read_token)


def _unauthorized() -> Response:
    return JSONResponse({"detail": "Unauthorized"}, status_code=401)


def _relative(path: Any) -> str:
    """Return a vault-relative path.

    Absolute paths are not handed out: the client does not need the layout of the
    filesystem, and the diff endpoint resolves what it is given through the vault
    sandbox anyway.
    """
    return str(path.relative_to(settings.vault_root.resolve()))


async def open_notes(request: Request) -> Response:
    """Notes waiting for review.

    Query:
        nur_agent: "false" widens the list from agent drafts to everything without
            a `geprueft` date. Default true — see `offene_notizen` for why those
            two are different kinds of work.
    """
    if not _authorized(request):
        return _unauthorized()
    nur_agent = request.query_params.get("nur_agent", "true").lower() != "false"
    notes = [
        {"path": _relative(path), "quelle": quelle, "geprueft": geprueft}
        for path, quelle, geprueft in offene_notizen(nur_agent=nur_agent)
    ]
    # The allowed provenance values ride along: accepting requires one, and a
    # client that had to hard-code the list would drift from vault_writer.
    return JSONResponse({"notes": notes, "quellen": sorted(QUELLEN - {QUELLE_AGENT})})


async def note_diff(request: Request) -> Response:
    """What an agent changed in one note since the last human version.

    Query:
        path: The note, vault-relative or a bare file name.

    Returns:
        The diff against the last commit not authored by the agent — not against
        HEAD. That distinction is the whole point: HEAD may itself be agent work.
    """
    if not _authorized(request):
        return _unauthorized()
    raw = request.query_params.get("path", "")
    if not raw:
        return JSONResponse({"detail": "path is required"}, status_code=400)
    try:
        path = resolve_note_path(raw, must_exist=True)
    except VaultWriteError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return JSONResponse(
        {
            "path": _relative(path),
            "base": letzte_menschliche_fassung(path),
            "diff": agenten_diff(path),
        }
    )


async def accept_note(request: Request) -> Response:
    """Record that a note's claims were checked, and commit it.

    Body:
        path: The note, vault-relative or a bare file name.
        quelle: How the content is evidenced — one of the values `/api/vault/open`
            returns. Required, and `agent-entwurf` is refused: a note cannot be
            accepted as still being an agent draft.

    Returns:
        The new `geprueft` date and the commit.

    The only write on this side, and it goes through the same `abnehmen()` as the
    command line — including that it commits as the agent author, exactly as
    `mark_verified` and `geprueft --ok` do. An invented date would take the note
    out of `list_stale` forever, which is why the caller has to say *how* it is
    evidenced rather than merely that it is.
    """
    if not _authorized(request):
        return _unauthorized()
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"detail": "body must be JSON"}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"detail": "body must be a JSON object"}, status_code=400)

    raw = str(payload.get("path", ""))
    quelle = str(payload.get("quelle", ""))
    if not raw:
        return JSONResponse({"detail": "path is required"}, status_code=400)
    if not quelle:
        erlaubt = ", ".join(sorted(QUELLEN - {QUELLE_AGENT}))
        return JSONResponse({"detail": f"quelle is required, one of {erlaubt}"}, status_code=400)

    try:
        path = resolve_note_path(raw, must_exist=True)
        commit = abnehmen(path, quelle)
    except VaultWriteError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    log.info("note accepted over HTTP: %s (quelle=%s)", _relative(path), quelle)
    return JSONResponse({"path": _relative(path), "quelle": quelle, "commit": commit})


async def health(request: Request) -> Response:
    """Say the read side is up and how many notes are waiting.

    Unauthenticated on purpose and deliberately thin: it answers "is this reachable
    and configured", which a caller needs *before* it has a token to try.
    """
    return JSONResponse({"status": "ok", "read_api": True})


def register(mcp: Any) -> bool:
    """Attach the read routes to the MCP server's HTTP app.

    Args:
        mcp: The FastMCP server.

    Returns:
        Whether the routes were registered. False when `BRAIN_READ_TOKEN` is
        unset, which is the fail-closed default.
    """
    if not settings.read_token:
        log.info("read API not registered: BRAIN_READ_TOKEN is unset")
        return False
    mcp.custom_route("/api/vault/health", methods=["GET"])(health)
    mcp.custom_route("/api/vault/open", methods=["GET"])(open_notes)
    mcp.custom_route("/api/vault/diff", methods=["GET"])(note_diff)
    mcp.custom_route("/api/vault/accept", methods=["POST"])(accept_note)
    log.info("read API registered at /api/vault/*")
    return True
