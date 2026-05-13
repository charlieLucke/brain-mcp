"""Unit tests for VaultWatcher (debouncing, ignores, delete-on-event).

These tests do NOT require Titan, Qdrant, or BGE-M3. They use a mock
TitanClient so the suite runs offline and fast.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from brain_mcp.schemas import IngestResponse
from brain_mcp.watcher import VaultWatcher, _should_ignore

# ---------------------------------------------------------------------------
# _should_ignore unit tests
# ---------------------------------------------------------------------------


def test_should_ignore_obsidian_dir() -> None:
    assert _should_ignore(Path("/vault/.obsidian/config.json")) is True


def test_should_ignore_trash() -> None:
    assert _should_ignore(Path("/vault/.trash/note.md")) is True


def test_should_ignore_git() -> None:
    assert _should_ignore(Path("/vault/.git/COMMIT_EDITMSG")) is True


def test_should_ignore_hidden_file() -> None:
    assert _should_ignore(Path("/vault/.DS_Store")) is True


def test_should_not_ignore_normal_note() -> None:
    assert _should_ignore(Path("/vault/notes/learning/rrf.md")) is False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_ingest_response(path: Path, chunks_created: int = 3) -> IngestResponse:
    return IngestResponse(
        file_path=str(path),
        domain="test",
        chunks_deleted=0,
        chunks_created=chunks_created,
        skipped_reason=None,
        latency_ms=42,
    )


@pytest.fixture()
def vault_root(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    return root


@pytest.fixture()
def mock_client() -> MagicMock:
    client = MagicMock()
    client.health.return_value = MagicMock()
    return client


@pytest.fixture()
def watcher(vault_root: Path, mock_client: MagicMock) -> VaultWatcher:
    return VaultWatcher(
        vault_root=vault_root,
        titan_client=mock_client,
        debounce_seconds=0.05,  # fast for tests
        poll_interval=0.02,
    )


# ---------------------------------------------------------------------------
# VaultWatcher unit tests (no filesystem events — call internals directly)
# ---------------------------------------------------------------------------


def test_schedule_adds_to_pending(watcher: VaultWatcher, vault_root: Path) -> None:
    path = vault_root / "note.md"
    watcher._schedule(path)
    assert path in watcher._pending


def test_schedule_resets_timer(watcher: VaultWatcher, vault_root: Path) -> None:
    path = vault_root / "note.md"
    watcher._schedule(path)
    t1 = watcher._pending[path]
    time.sleep(0.01)
    watcher._schedule(path)
    t2 = watcher._pending[path]
    assert t2 > t1


def test_ingest_called_after_debounce(
    watcher: VaultWatcher, vault_root: Path, mock_client: MagicMock
) -> None:
    path = vault_root / "note.md"
    path.write_text("---\ndomain: test\n---\nHello")
    mock_client.ingest_file.return_value = _make_ingest_response(path)

    watcher.start()
    watcher._schedule(path)
    # Wait longer than debounce_seconds (0.05s) + a couple poll_intervals (0.02s)
    time.sleep(0.2)
    watcher.stop()

    mock_client.ingest_file.assert_called_once_with(path)


def test_delete_removes_from_pending(
    watcher: VaultWatcher, vault_root: Path, mock_client: MagicMock
) -> None:
    path = vault_root / "note.md"
    watcher._schedule(path)
    assert path in watcher._pending

    mock_client.delete_chunks.return_value = 2
    # _ensure_titan_available calls health()
    watcher._handle_delete(path)

    assert path not in watcher._pending
    mock_client.delete_chunks.assert_called_once_with(path)


def test_rapid_saves_only_trigger_one_ingest(
    watcher: VaultWatcher, vault_root: Path, mock_client: MagicMock
) -> None:
    """10 rapid saves within debounce window → exactly one ingest."""
    path = vault_root / "note.md"
    path.write_text("---\ndomain: test\n---\nContent")
    mock_client.ingest_file.return_value = _make_ingest_response(path)

    watcher.start()
    for _ in range(10):
        watcher._schedule(path)
        time.sleep(0.005)  # 5ms between saves, debounce is 50ms
    time.sleep(0.3)  # wait for debounce to expire and worker to process
    watcher.stop()

    assert mock_client.ingest_file.call_count == 1


def test_ingest_reschedules_on_connect_error(
    watcher: VaultWatcher, vault_root: Path, mock_client: MagicMock
) -> None:
    """If health() raises ConnectError, the path is re-scheduled."""
    import httpx

    path = vault_root / "note.md"
    # Make health() always fail so _ensure_titan_available returns False
    mock_client.health.side_effect = httpx.ConnectError("refused")

    with patch.object(watcher, "_schedule") as mock_schedule:
        watcher._ingest(path)
        mock_schedule.assert_called_once_with(path)


def test_skipped_reason_logged(
    watcher: VaultWatcher, vault_root: Path, mock_client: MagicMock
) -> None:
    path = vault_root / "private.md"
    mock_client.ingest_file.return_value = IngestResponse(
        file_path=str(path),
        domain=None,
        chunks_deleted=1,
        chunks_created=0,
        skipped_reason="indexed:false",
        latency_ms=5,
    )
    # health() succeeds
    watcher._ingest(path)
    mock_client.ingest_file.assert_called_once()


# ---------------------------------------------------------------------------
# Integration: filesystem events trigger ingest (requires real watchdog)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_filesystem_modify_triggers_ingest(vault_root: Path, mock_client: MagicMock) -> None:
    """Writing a .md file should trigger an ingest after the debounce window."""
    path = vault_root / "notes" / "test.md"
    path.parent.mkdir(parents=True)
    mock_client.health.return_value = MagicMock()
    mock_client.ingest_file.return_value = _make_ingest_response(path)

    watcher = VaultWatcher(
        vault_root=vault_root,
        titan_client=mock_client,
        debounce_seconds=0.1,
        poll_interval=0.05,
    )
    watcher.start()
    path.write_text("---\ndomain: test\n---\nHello world")

    # Poll until ingest is called or timeout
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if mock_client.ingest_file.called:
            break
        time.sleep(0.05)

    watcher.stop()
    assert mock_client.ingest_file.called, "ingest_file was not called within timeout"


@pytest.mark.integration
def test_filesystem_delete_triggers_chunk_delete(vault_root: Path, mock_client: MagicMock) -> None:
    """Deleting a .md file should immediately delete its chunks."""
    path = vault_root / "notes" / "gone.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\ndomain: test\n---\nContent")
    mock_client.health.return_value = MagicMock()
    mock_client.delete_chunks.return_value = 2

    watcher = VaultWatcher(
        vault_root=vault_root,
        titan_client=mock_client,
        debounce_seconds=0.1,
        poll_interval=0.05,
    )
    watcher.start()
    path.unlink()

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if mock_client.delete_chunks.called:
            break
        time.sleep(0.05)

    watcher.stop()
    assert mock_client.delete_chunks.called


@pytest.mark.integration
def test_non_md_file_not_ingested(vault_root: Path, mock_client: MagicMock) -> None:
    """Writing a .pdf file must NOT trigger an ingest."""
    path = vault_root / "document.pdf"
    mock_client.health.return_value = MagicMock()

    watcher = VaultWatcher(
        vault_root=vault_root,
        titan_client=mock_client,
        debounce_seconds=0.1,
        poll_interval=0.05,
    )
    watcher.start()
    path.write_bytes(b"%PDF-1.4 fake")
    time.sleep(0.5)
    watcher.stop()

    mock_client.ingest_file.assert_not_called()
