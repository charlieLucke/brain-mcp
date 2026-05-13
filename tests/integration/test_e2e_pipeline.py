"""End-to-end integration test: Note write → Watcher → Titan ingest → Search finds it.

Uses a local mock server (pytest-httpserver) to simulate the Titan RAG service.
This ensures the tests run completely offline and don't modify any productive
collections or rely on hardcoded paths.
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Any

import frontmatter
import httpx
import pytest
from werkzeug.wrappers import Request, Response

from brain_mcp.titan_client import TitanClient
from brain_mcp.watcher import VaultWatcher

UNIQUE_PHRASE = "BRAIN_MCP_E2E_TEST_XYZ987654321"


def _wait_until(condition: object, timeout: float = 5.0, poll: float = 0.1) -> bool:
    """Poll until condition() returns truthy or timeout is reached."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():  # type: ignore[operator]
            return True
        time.sleep(poll)
    return False


@pytest.fixture
def mock_titan(httpserver: Any) -> Any:
    """Simulates the Titan service with a simple in-memory chunk store."""
    state = {"chunks": []}

    def health(request: Request) -> Response:
        return Response(
            json.dumps(
                {
                    "status": "ok",
                    "bge_loaded": True,
                    "qdrant_reachable": True,
                    "vram_used_mb": 0,
                    "collection_name": "test",
                    "colbert_dim": 128,
                }
            ),
            mimetype="application/json",
        )

    def ingest(request: Request) -> Response:
        data = json.loads(request.data)
        path = data["file_path"]
        post = frontmatter.load(path)
        indexed = str(post.get("indexed", "true")).lower()

        if indexed == "false":
            state["chunks"] = [c for c in state["chunks"] if c["source_path"] != path]
            return Response(
                json.dumps(
                    {
                        "file_path": path,
                        "domain": None,
                        "chunks_deleted": 1,
                        "chunks_created": 0,
                        "skipped_reason": "indexed:false",
                        "latency_ms": 10,
                    }
                ),
                mimetype="application/json",
            )

        # Mock successful ingest
        state["chunks"].append(
            {
                "text": post.content,
                "source_path": path,
                "domain": "test",
                "chunk_offset": 0,
                "score": 0.99,
                "metadata": {},
            }
        )
        return Response(
            json.dumps(
                {
                    "file_path": path,
                    "domain": "test",
                    "chunks_deleted": 0,
                    "chunks_created": 1,
                    "skipped_reason": None,
                    "latency_ms": 10,
                }
            ),
            mimetype="application/json",
        )

    def search(request: Request) -> Response:
        data = json.loads(request.data)
        query = data.get("query", "")
        # Filter chunks that contain the query
        res = [c for c in state["chunks"] if query in c["text"]]
        return Response(
            json.dumps(
                {
                    "query": query,
                    "chunks": res,
                    "sub_queries": [query],
                    "cache_hit": False,
                    "latency_ms": 10,
                }
            ),
            mimetype="application/json",
        )

    def delete_chunks(request: Request) -> Response:
        path = request.args.get("source_path", "")
        state["chunks"] = [c for c in state["chunks"] if c["source_path"] != path]
        return Response(
            json.dumps({"source_path": str(path), "chunks_deleted": 1}), mimetype="application/json"
        )

    httpserver.expect_request("/health", method="GET").respond_with_handler(health)
    httpserver.expect_request("/ingest/file", method="POST").respond_with_handler(ingest)
    httpserver.expect_request("/search", method="POST").respond_with_handler(search)
    httpserver.expect_request("/chunks", method="DELETE").respond_with_handler(delete_chunks)

    return httpserver


@pytest.fixture
def titan_client(mock_titan: Any) -> TitanClient:
    return TitanClient(base_url=mock_titan.url_for("/"), timeout=2)


@pytest.mark.integration
def test_full_pipeline(tmp_path: Path, titan_client: TitanClient) -> None:
    """Write note → watcher ingests → search finds it."""
    vault_root = tmp_path / "vault"
    (vault_root / "notes").mkdir(parents=True)

    watcher = VaultWatcher(
        vault_root=vault_root,
        titan_client=titan_client,
        debounce_seconds=0.1,
        poll_interval=0.05,
    )
    watcher.start()

    try:
        note = vault_root / "notes" / "e2e_test.md"
        note.write_text(
            f"---\ndomain: test\nindexed: true\n---\n"
            f"# E2E Test Note\n\n"
            f"Unique phrase for E2E verification: {UNIQUE_PHRASE}.",
            encoding="utf-8",
        )

        # Wait until indexed (watcher fires after debounce)
        def _indexed() -> bool:
            try:
                result = titan_client.search(UNIQUE_PHRASE, domain="test", top_k=3)
                return any(UNIQUE_PHRASE in c.text for c in result.chunks)
            except httpx.HTTPError:
                return False

        indexed = _wait_until(_indexed, timeout=10.0)
        assert indexed, f"Note not found in index within timeout (phrase: {UNIQUE_PHRASE})"

        # Verify chunk content
        result = titan_client.search(UNIQUE_PHRASE, domain="test", top_k=3)
        texts = [c.text for c in result.chunks]
        assert any(UNIQUE_PHRASE in t for t in texts), f"Phrase not in chunks: {texts}"

    finally:
        watcher.stop()
        with contextlib.suppress(httpx.HTTPError):
            titan_client.delete_chunks(vault_root / "notes" / "e2e_test.md")


@pytest.mark.integration
def test_indexed_false_clears_chunks(tmp_path: Path, titan_client: TitanClient) -> None:
    """Note marked indexed:false → chunks removed from index."""
    vault_root = tmp_path / "vault2"
    (vault_root / "notes").mkdir(parents=True)

    watcher = VaultWatcher(
        vault_root=vault_root,
        titan_client=titan_client,
        debounce_seconds=0.1,
        poll_interval=0.05,
    )
    watcher.start()

    phrase_2 = "BRAIN_MCP_INDEXED_FALSE_ABC123XYZ"
    note = vault_root / "notes" / "private.md"

    try:
        # First: index it
        note.write_text(
            f"---\ndomain: test\nindexed: true\n---\nPrivate content: {phrase_2}.",
            encoding="utf-8",
        )

        def _found() -> bool:
            try:
                r = titan_client.search(phrase_2, domain="test", top_k=3)
                return any(phrase_2 in c.text for c in r.chunks)
            except httpx.HTTPError:
                return False

        assert _wait_until(_found, timeout=10.0), "Note not indexed initially"

        # Then: mark indexed:false — watcher should clear chunks
        note.write_text(
            f"---\ndomain: test\nindexed: false\n---\nPrivate content: {phrase_2}.",
            encoding="utf-8",
        )

        def _gone() -> bool:
            try:
                r = titan_client.search(phrase_2, domain="test", top_k=3)
                return not any(phrase_2 in c.text for c in r.chunks)
            except httpx.HTTPError:
                return False

        assert _wait_until(_gone, timeout=10.0), "Chunks not removed after indexed:false"

    finally:
        watcher.stop()


@pytest.mark.integration
def test_watcher_survives_titan_restart(tmp_path: Path) -> None:
    """Watcher must not crash when Titan is temporarily unreachable."""
    vault_root = tmp_path / "vault3"
    vault_root.mkdir()

    # Use a client pointed at a non-existent URL to simulate Titan down
    dead_client = TitanClient(base_url="http://127.0.0.1:19999", timeout=1)
    watcher = VaultWatcher(
        vault_root=vault_root,
        titan_client=dead_client,
        debounce_seconds=0.1,
        poll_interval=0.05,
    )
    watcher.start()

    note = vault_root / "note.md"
    note.write_text("---\ndomain: test\n---\nContent", encoding="utf-8")

    # Give the watcher time to attempt (and fail) the ingest
    time.sleep(1.0)

    # Worker must still be alive
    assert watcher._worker_thread.is_alive(), "Worker thread crashed!"
    watcher.stop()
    dead_client.close()
