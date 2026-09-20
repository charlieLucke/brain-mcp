"""Unit tests for MCP tool functions (no FastMCP / MCP protocol needed)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx

from brain_mcp.schemas import (
    DomainsResponse,
    FindRelatedResponse,
    IngestResponse,
    SearchResponse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VAULT_ROOT = Path("/mnt/f/vault")

_CHUNK = {
    "text": "BGE-M3 uses late chunking.",
    "source_path": "/mnt/f/vault/notes/rrf.md",
    "domain": "titan",
    "chunk_offset": 0,
    "score": 0.92,
    "metadata": {},
}

_SEARCH_RESP = SearchResponse(
    query="late chunking",
    chunks=[],  # populated per test
    sub_queries=[],
    cache_hit=False,
    latency_ms=100,
)


# ---------------------------------------------------------------------------
# query_knowledge
# ---------------------------------------------------------------------------


def test_query_knowledge_returns_markdown(tmp_path: Path) -> None:
    from brain_mcp import mcp_server

    resp = SearchResponse(
        query="late chunking",
        chunks=[],
        sub_queries=[],
        cache_hit=False,
        latency_ms=50,
    )
    resp.chunks = [resp.model_validate(_SEARCH_RESP.model_dump() | {"chunks": [_CHUNK]}).chunks[0]]  # type: ignore[assignment]

    # Rebuild with chunk
    from brain_mcp.schemas import Chunk

    chunk = Chunk(**_CHUNK)
    full_resp = SearchResponse(
        query="late chunking",
        chunks=[chunk],
        sub_queries=[],
        cache_hit=False,
        latency_ms=50,
    )

    with patch.object(mcp_server._client, "search", return_value=full_resp):
        result = mcp_server.query_knowledge("late chunking", domain="titan")

    assert "BGE-M3" in result
    assert "0.92" in result


def test_query_knowledge_connect_error() -> None:
    from brain_mcp import mcp_server

    with patch.object(mcp_server._client, "search", side_effect=httpx.ConnectError("refused")):
        result = mcp_server.query_knowledge("test")

    assert "not reachable" in result


def test_query_knowledge_top_k_clamped() -> None:
    """top_k > 30 should be clamped to 30."""
    from brain_mcp import mcp_server

    captured: list[int] = []

    def _capture_search(
        query: str,
        domain: object = None,
        top_k: int = 10,
        **kwargs: object,
    ) -> SearchResponse:
        captured.append(top_k)
        return SearchResponse(query=query, chunks=[], sub_queries=[], cache_hit=False, latency_ms=0)

    with patch.object(mcp_server._client, "search", side_effect=_capture_search):
        mcp_server.query_knowledge("test", top_k=100)

    assert captured[0] == 30


# ---------------------------------------------------------------------------
# ingest_note
# ---------------------------------------------------------------------------


def test_ingest_note_outside_vault_returns_error() -> None:
    from brain_mcp import mcp_server

    with patch("brain_mcp.mcp_server.settings") as mock_settings:
        mock_settings.vault_root = _VAULT_ROOT
        result = mcp_server.ingest_note("/tmp/outside.md")

    assert "outside the vault root" in result


def test_ingest_note_success() -> None:
    from brain_mcp import mcp_server

    resp = IngestResponse(
        file_path=str(_VAULT_ROOT / "note.md"),
        domain="lernen",
        chunks_deleted=2,
        chunks_created=4,
        skipped_reason=None,
        latency_ms=300,
    )

    with (
        patch("brain_mcp.mcp_server.settings") as mock_settings,
        patch.object(mcp_server._client, "ingest_file", return_value=resp),
    ):
        mock_settings.vault_root = _VAULT_ROOT
        result = mcp_server.ingest_note(str(_VAULT_ROOT / "note.md"))

    assert "4 chunk(s) created" in result
    assert "2 replaced" in result


def test_ingest_note_skipped_reason() -> None:
    from brain_mcp import mcp_server

    resp = IngestResponse(
        file_path=str(_VAULT_ROOT / "private.md"),
        domain=None,
        chunks_deleted=1,
        chunks_created=0,
        skipped_reason="indexed:false",
        latency_ms=10,
    )

    with (
        patch("brain_mcp.mcp_server.settings") as mock_settings,
        patch.object(mcp_server._client, "ingest_file", return_value=resp),
    ):
        mock_settings.vault_root = _VAULT_ROOT
        result = mcp_server.ingest_note(str(_VAULT_ROOT / "private.md"))

    assert "indexed:false" in result
    assert "1 old chunk" in result


# ---------------------------------------------------------------------------
# list_domains
# ---------------------------------------------------------------------------


def test_list_domains_returns_markdown() -> None:
    from brain_mcp import mcp_server

    resp = DomainsResponse(domains=["lernen", "titan"], counts={"lernen": 10, "titan": 5})

    with patch.object(mcp_server._client, "list_domains", return_value=resp):
        result = mcp_server.list_domains()

    assert "**lernen**" in result
    assert "10" in result


def test_list_domains_empty() -> None:
    from brain_mcp import mcp_server

    resp = DomainsResponse(domains=[], counts={})

    with patch.object(mcp_server._client, "list_domains", return_value=resp):
        result = mcp_server.list_domains()

    assert "No domains" in result


# ---------------------------------------------------------------------------
# find_related
# ---------------------------------------------------------------------------


def test_find_related_outside_vault() -> None:
    from brain_mcp import mcp_server

    with patch("brain_mcp.mcp_server.settings") as mock_settings:
        mock_settings.vault_root = _VAULT_ROOT
        result = mcp_server.find_related("/tmp/note.md")

    assert "outside the vault root" in result


def test_find_related_success() -> None:
    from brain_mcp import mcp_server
    from brain_mcp.schemas import Chunk

    chunk = Chunk(**_CHUNK)
    resp = FindRelatedResponse(
        source_path=str(_VAULT_ROOT / "notes/rrf.md"),
        related=[chunk],
        latency_ms=60,
    )

    with (
        patch("brain_mcp.mcp_server.settings") as mock_settings,
        patch.object(mcp_server._client, "find_related", return_value=resp),
    ):
        mock_settings.vault_root = _VAULT_ROOT
        result = mcp_server.find_related(str(_VAULT_ROOT / "notes/rrf.md"))

    assert "BGE-M3" in result


# ---------------------------------------------------------------------------
# list_notes
# ---------------------------------------------------------------------------


def _notes_response() -> object:
    from brain_mcp.schemas import NoteInfo, NotesResponse

    return NotesResponse(
        notes=[
            NoteInfo(source_path="/mnt/f/vault/a.md", domain="lernen", chunk_count=3),
            NoteInfo(source_path="/mnt/f/vault/b.md", domain="titan", chunk_count=5),
        ],
        total=2,
    )


def test_list_notes_returns_markdown() -> None:
    from brain_mcp import mcp_server

    with patch.object(mcp_server._client, "list_notes", return_value=_notes_response()):
        result = mcp_server.list_notes()

    assert "a.md" in result
    assert "b.md" in result
    assert "2 indexed note(s)" in result


def test_list_notes_domain_filter() -> None:
    from brain_mcp import mcp_server

    with patch.object(mcp_server._client, "list_notes", return_value=_notes_response()):
        result = mcp_server.list_notes(domain="titan")

    assert "b.md" in result
    assert "a.md" not in result


def test_list_notes_empty() -> None:
    from brain_mcp import mcp_server
    from brain_mcp.schemas import NotesResponse

    empty = NotesResponse(notes=[], total=0)
    with patch.object(mcp_server._client, "list_notes", return_value=empty):
        result = mcp_server.list_notes()

    assert "No notes indexed" in result


def test_list_notes_connect_error() -> None:
    from brain_mcp import mcp_server

    with patch.object(mcp_server._client, "list_notes", side_effect=httpx.ConnectError("refused")):
        result = mcp_server.list_notes()

    assert "not reachable" in result


def _notes_response_with_hash() -> object:
    from brain_mcp.schemas import NoteInfo, NotesResponse

    return NotesResponse(
        notes=[
            NoteInfo(
                source_path="/mnt/f/vault/a.md",
                domain="lernen",
                chunk_count=3,
                content_hash="b" * 64,
            ),
            NoteInfo(source_path="/mnt/f/vault/b.md", domain="titan", chunk_count=5),
        ],
        total=2,
    )


def test_list_notes_omits_hash_by_default() -> None:
    """The listing every session makes must not carry 64 hex characters per note."""
    from brain_mcp import mcp_server

    with patch.object(mcp_server._client, "list_notes", return_value=_notes_response_with_hash()):
        result = mcp_server.list_notes()

    assert "hash" not in result


def test_list_notes_with_hash_prints_it_whole() -> None:
    """edit_note compares the whole string, so a shortened hash could not be passed back."""
    from brain_mcp import mcp_server

    with patch.object(mcp_server._client, "list_notes", return_value=_notes_response_with_hash()):
        result = mcp_server.list_notes(with_hash=True)

    assert "b" * 64 in result


def test_list_notes_with_hash_says_when_none_is_indexed() -> None:
    """A note without an indexed hash says so instead of silently dropping the field."""
    from brain_mcp import mcp_server

    with patch.object(mcp_server._client, "list_notes", return_value=_notes_response_with_hash()):
        result = mcp_server.list_notes(with_hash=True)

    assert "_not indexed_" in result


# ---------------------------------------------------------------------------
# delete_note
# ---------------------------------------------------------------------------


def test_delete_note_outside_vault() -> None:
    from brain_mcp import mcp_server

    with patch("brain_mcp.mcp_server.settings") as mock_settings:
        mock_settings.vault_root = _VAULT_ROOT
        result = mcp_server.delete_note("/tmp/outside.md")

    assert "outside the vault root" in result


def test_delete_note_success() -> None:
    from brain_mcp import mcp_server

    with (
        patch("brain_mcp.mcp_server.settings") as mock_settings,
        patch.object(mcp_server._client, "delete_chunks", return_value=5),
    ):
        mock_settings.vault_root = _VAULT_ROOT
        result = mcp_server.delete_note(str(_VAULT_ROOT / "note.md"))

    assert "5 chunk(s) removed" in result
    assert "not touched" in result


def test_delete_note_not_in_index() -> None:
    from brain_mcp import mcp_server

    with (
        patch("brain_mcp.mcp_server.settings") as mock_settings,
        patch.object(mcp_server._client, "delete_chunks", return_value=0),
    ):
        mock_settings.vault_root = _VAULT_ROOT
        result = mcp_server.delete_note(str(_VAULT_ROOT / "ghost.md"))

    assert "not in the index" in result
