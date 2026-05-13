"""End-to-end integration test: Note write → Watcher → Titan ingest → Search finds it.

Requires:
- Titan service running on BRAIN_TITAN_URL (default http://127.0.0.1:8765)
- Qdrant + BGE-M3 loaded (titan-service.service active)

Run with:
    uv run pytest tests/integration/ -m integration -v

The test uses a temporary vault root and short debounce (0.1s) so it runs in <5s.
No time.sleep() for synchronisation — uses polling with a deadline.
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import httpx
import pytest

from brain_mcp.titan_client import TitanClient
from brain_mcp.watcher import VaultWatcher

TITAN_URL = "http://127.0.0.1:8765"
# Unique phrase unlikely to appear in the real index
UNIQUE_PHRASE = "BRAIN_MCP_E2E_TEST_XYZ987654321"


def _wait_until(condition: object, timeout: float = 5.0, poll: float = 0.1) -> bool:
    """Poll until condition() returns truthy or timeout is reached."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():  # type: ignore[operator]
            return True
        time.sleep(poll)
    return False


@pytest.fixture(scope="module")
def titan_client() -> TitanClient:
    return TitanClient(base_url=TITAN_URL, timeout=60)


@pytest.fixture(scope="module")
def titan_available(titan_client: TitanClient) -> bool:
    try:
        health = titan_client.health()
        return health.status in ("ok", "degraded")
    except httpx.ConnectError:
        return False


@pytest.mark.integration
def test_full_pipeline(tmp_path: Path, titan_client: TitanClient, titan_available: bool) -> None:
    """Write note → watcher ingests → search finds it."""
    if not titan_available:
        pytest.skip("Titan service not reachable — skipping E2E test")

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
            f"Unique phrase for E2E verification: {UNIQUE_PHRASE}."
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
        # Cleanup: delete test chunks (best-effort)
        with contextlib.suppress(httpx.HTTPError):
            titan_client.delete_chunks(vault_root / "notes" / "e2e_test.md")


@pytest.mark.integration
def test_indexed_false_clears_chunks(
    tmp_path: Path, titan_client: TitanClient, titan_available: bool
) -> None:
    """Note marked indexed:false → chunks removed from index."""
    if not titan_available:
        pytest.skip("Titan service not reachable — skipping E2E test")

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
        note.write_text(f"---\ndomain: test\nindexed: true\n---\nPrivate content: {phrase_2}.")

        def _found() -> bool:
            try:
                r = titan_client.search(phrase_2, domain="test", top_k=3)
                return any(phrase_2 in c.text for c in r.chunks)
            except httpx.HTTPError:
                return False

        assert _wait_until(_found, timeout=10.0), "Note not indexed initially"

        # Then: mark indexed:false — watcher should clear chunks
        note.write_text(f"---\ndomain: test\nindexed: false\n---\nPrivate content: {phrase_2}.")

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
def test_watcher_survives_titan_restart(tmp_path: Path, titan_available: bool) -> None:
    """Watcher must not crash when Titan is temporarily unreachable."""
    if not titan_available:
        pytest.skip("Titan service not reachable — skipping E2E test")

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
    note.write_text("---\ndomain: test\n---\nContent")
    # Give the watcher time to attempt (and fail) the ingest
    time.sleep(1.0)

    # Worker must still be alive
    assert watcher._worker_thread.is_alive(), "Worker thread crashed!"
    watcher.stop()
    dead_client.close()
