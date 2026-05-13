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


_VAULT = Path("/vault")


def test_should_ignore_obsidian_dir() -> None:
    assert _should_ignore(Path("/vault/.obsidian/config.json"), _VAULT) is True


def test_should_ignore_trash() -> None:
    assert _should_ignore(Path("/vault/.trash/note.md"), _VAULT) is True


def test_should_ignore_git() -> None:
    assert _should_ignore(Path("/vault/.git/COMMIT_EDITMSG"), _VAULT) is True


def test_should_ignore_hidden_file() -> None:
    assert _should_ignore(Path("/vault/.DS_Store"), _VAULT) is True


def test_should_not_ignore_normal_note() -> None:
    assert _should_ignore(Path("/vault/notes/learning/rrf.md"), _VAULT) is False


def test_should_not_ignore_note_under_dotfile_root() -> None:
    """B-MED-2: vault placed under ~/.config/vault/ must not be ignored."""
    dotroot = Path("/home/user/.config/vault")
    assert _should_ignore(dotroot / "notes" / "rrf.md", dotroot) is False


def test_should_ignore_path_outside_vault() -> None:
    """Paths outside vault_root are always ignored."""
    assert _should_ignore(Path("/tmp/other/note.md"), _VAULT) is True


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


# ---------------------------------------------------------------------------
# B-CRIT-2: Cool-down-based _ensure_titan_available
# ---------------------------------------------------------------------------


def test_cooldown_prevents_repeated_health_calls(
    watcher: VaultWatcher, mock_client: MagicMock
) -> None:
    """After ConnectError, health() is not called again during cool-down window."""
    import httpx

    mock_client.health.side_effect = httpx.ConnectError("refused")

    result1 = watcher._ensure_titan_available()
    assert result1 is False
    assert mock_client.health.call_count == 1

    # Cool-down is active — second call must NOT hit health() again.
    result2 = watcher._ensure_titan_available()
    assert result2 is False
    assert mock_client.health.call_count == 1  # unchanged


def test_cooldown_resets_after_success(watcher: VaultWatcher, mock_client: MagicMock) -> None:
    """After cool-down expires, a successful probe resets _titan_dead_until."""
    import httpx

    mock_client.health.side_effect = [httpx.ConnectError("refused"), None]

    watcher._ensure_titan_available()  # sets cool-down
    watcher._titan_dead_until = 0.0  # simulate expiry

    result = watcher._ensure_titan_available()
    assert result is True
    assert mock_client.health.call_count == 2
    assert watcher._titan_dead_until == 0.0


def test_unexpected_exception_triggers_cooldown(
    watcher: VaultWatcher, mock_client: MagicMock
) -> None:
    """B-CRIT-1 bridge: any exception from health() (e.g. ValidationError) sets cool-down."""
    mock_client.health.side_effect = ValueError("unexpected schema error")

    result = watcher._ensure_titan_available()
    assert result is False
    assert watcher._titan_dead_until > 0.0


# ---------------------------------------------------------------------------
# B-MED-3: Failed-Delete-Queue
# ---------------------------------------------------------------------------


def test_failed_delete_is_queued(watcher: VaultWatcher, mock_client: MagicMock) -> None:
    """When Titan is unreachable during delete, the path goes to _pending_deletes."""
    from unittest.mock import patch

    path = Path("/vault/gone.md")
    mock_client.delete_chunks.return_value = 1

    with patch.object(watcher, "_ensure_titan_available", return_value=False):
        watcher._handle_delete(path)

    assert path in watcher._pending_deletes
    mock_client.delete_chunks.assert_not_called()


def test_queued_delete_retried_when_titan_recovers(
    watcher: VaultWatcher, vault_root: Path, mock_client: MagicMock
) -> None:
    """Pending deletes are executed by the worker once Titan becomes available."""
    path = vault_root / "gone.md"
    mock_client.delete_chunks.return_value = 1

    # Seed the queue directly (as if a previous failed delete queued it).
    with watcher._lock:
        watcher._pending_deletes.add(path)

    watcher.start()
    time.sleep(0.3)  # give worker time to process
    watcher.stop()

    mock_client.delete_chunks.assert_called_once_with(path)


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
