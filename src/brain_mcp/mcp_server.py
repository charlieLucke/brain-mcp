"""FastMCP server — exposes knowledge vault as MCP tools for Claude."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth.oauth_proxy import OAuthProxy

from brain_mcp.auth import build_github_auth
from brain_mcp.config import settings
from brain_mcp.schemas import Chunk
from brain_mcp.titan_client import TitanClient

log = logging.getLogger(__name__)


def _build_auth() -> OAuthProxy | None:
    """Build the OAuth provider when HTTP auth is enabled, else None.

    Auth applies only to the HTTP transport; stdio is local and unauthenticated.
    Raises if BRAIN_MCP_AUTH=github but required settings are missing.
    """
    if settings.mcp_transport != "http" or settings.mcp_auth != "github":
        return None
    allowed_logins = {
        login.strip().lower()
        for login in settings.github_allowed_logins.split(",")
        if login.strip()
    }
    missing = [
        name
        for name, value in (
            ("BRAIN_MCP_BASE_URL", settings.mcp_base_url),
            ("BRAIN_GITHUB_CLIENT_ID", settings.github_client_id),
            ("BRAIN_GITHUB_CLIENT_SECRET", settings.github_client_secret),
            ("BRAIN_GITHUB_ALLOWED_LOGINS", settings.github_allowed_logins),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("BRAIN_MCP_AUTH=github requires these settings: " + ", ".join(missing))
    log.info("OAuth enabled (GitHub), allowlist: %s", sorted(allowed_logins))
    return build_github_auth(
        client_id=settings.github_client_id,
        client_secret=settings.github_client_secret,
        base_url=settings.mcp_base_url,
        allowed_logins=allowed_logins,
    )


mcp: FastMCP = FastMCP("brain", auth=_build_auth())
_client = TitanClient(base_url=settings.titan_url)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _format_chunks(chunks: list[Chunk], cache_hit: bool, latency_ms: int) -> str:
    """Format a list of Chunk objects as a Markdown string for Claude."""
    if not chunks:
        return "_No relevant chunks found._"
    lines: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        lines.append(f"## Result {i} (score: {chunk.score:.2f}, source: {chunk.source_path})")
        lines.append(chunk.text.strip())
        lines.append("")
    lines.append(f"*Cache hit: {str(cache_hit).lower()}, latency: {latency_ms}ms*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# B3 — query_knowledge
# ---------------------------------------------------------------------------


@mcp.tool()
def query_knowledge(
    query: str,
    domain: str | None = None,
    top_k: int = 10,
) -> str:
    """Search my personal knowledge vault.

    Args:
        query: Natural-language question or keywords to search for.
        domain: Optional domain filter. Use list_domains() first to see available
            domains (e.g. "lernen", "titan", "trading"). Leave empty to search all.
        top_k: Number of chunks to return (1-30). Default 10.

    Returns:
        Markdown-formatted list of relevant chunks with source paths and scores.
        Returns an error message if the Titan service is unreachable.
    """
    top_k = min(max(1, top_k), 30)
    try:
        result = _client.search(query, domain=domain, top_k=top_k)
    except httpx.ConnectError:
        return (
            "Error: Titan service is not reachable. Check `systemctl --user status titan-service`."
        )
    except httpx.HTTPStatusError as e:
        return f"Error: Titan service returned {e.response.status_code}: {e.response.text}"
    return _format_chunks(result.chunks, result.cache_hit, result.latency_ms)


# ---------------------------------------------------------------------------
# B4 — ingest_note
# ---------------------------------------------------------------------------


@mcp.tool()
def ingest_note(file_path: str, force: bool = False) -> str:
    """Trigger immediate re-indexing of a note (bypasses the watcher's 30-second delay).

    Use when:
    - You just edited a note and want it searchable immediately.
    - You suspect the index is stale for a specific note.

    Args:
        file_path: Absolute path to the Markdown note inside the vault.
        force: Currently without effect — Titan always re-ingests on every call. Default False.

    Returns:
        A short status message describing what happened (chunks created/replaced,
        or why the note was skipped).
    """
    path = Path(file_path).resolve()
    if not path.is_relative_to(settings.vault_root):
        return f"Error: {file_path!r} is outside the vault root ({settings.vault_root})."

    try:
        result = _client.ingest_file(path, force=force)
    except httpx.ConnectError:
        return (
            "Error: Titan service is not reachable. Check `systemctl --user status titan-service`."
        )
    except httpx.HTTPStatusError as e:
        return f"Error: Titan service returned {e.response.status_code}: {e.response.text}"

    if result.skipped_reason:
        return f"Skipped ({result.skipped_reason}). {result.chunks_deleted} old chunk(s) removed."
    return (
        f"Indexed: {result.chunks_created} chunk(s) created, "
        f"{result.chunks_deleted} replaced. "
        f"Domain: {result.domain}."
    )


# ---------------------------------------------------------------------------
# B5 — list_domains
# ---------------------------------------------------------------------------


@mcp.tool()
def list_domains() -> str:
    """List all domains in the knowledge vault with chunk counts.

    Use this before calling query_knowledge() with a domain filter to see
    which domains are available.

    Returns:
        Markdown-formatted list of domains and their chunk counts.
    """
    try:
        result = _client.list_domains()
    except httpx.ConnectError:
        return (
            "Error: Titan service is not reachable. Check `systemctl --user status titan-service`."
        )
    except httpx.HTTPStatusError as e:
        return f"Error: Titan service returned {e.response.status_code}: {e.response.text}"

    if not result.domains:
        return "_No domains indexed yet._"
    lines = [f"- **{d}**: {result.counts.get(d, 0)} chunk(s)" for d in result.domains]
    return "Available domains:\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# B5 — find_related
# ---------------------------------------------------------------------------


@mcp.tool()
def find_related(file_path: str, top_k: int = 5) -> str:
    """Find notes semantically related to a given note.

    Uses the embedding of the note's first chunk to search for similar content
    in the vault, excluding the note itself.

    Args:
        file_path: Absolute path to the source Markdown note inside the vault.
        top_k: Number of related notes to return (1-20). Default 5.

    Returns:
        Markdown-formatted list of related chunks with source paths and scores.
    """
    path = Path(file_path).resolve()
    if not path.is_relative_to(settings.vault_root):
        return f"Error: {file_path!r} is outside the vault root ({settings.vault_root})."

    try:
        result = _client.find_related(path, top_k=top_k)
    except httpx.ConnectError:
        return (
            "Error: Titan service is not reachable. Check `systemctl --user status titan-service`."
        )
    except httpx.HTTPStatusError as e:
        return f"Error: Titan service returned {e.response.status_code}: {e.response.text}"

    return _format_chunks(result.related, cache_hit=False, latency_ms=result.latency_ms)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server.

    Transport is selected via BRAIN_MCP_TRANSPORT:
    - "stdio" (default): classic subprocess transport.
    - "http": Streamable-HTTP server on BRAIN_MCP_HOST:BRAIN_MCP_PORT, so it can
      be registered as a custom connector in Claude Desktop.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if settings.mcp_transport == "http":
        log.info("Starting MCP server (http) on %s:%s", settings.mcp_host, settings.mcp_port)
        mcp.run(transport="http", host=settings.mcp_host, port=settings.mcp_port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
