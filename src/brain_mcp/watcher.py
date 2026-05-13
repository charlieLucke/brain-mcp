"""Vault watcher daemon — monitors the Obsidian vault and triggers Titan ingests.

Architecture:
- watchdog.Observer watches VAULT_ROOT recursively for filesystem events.
- A background worker thread processes a dict of {Path: last_event_timestamp}.
- Only .md files are processed; PDFs are ingested via CLI.
- Delete events fire immediately (no debouncing).
- Modify/Create events are debounced: the file is ingested only after
  `debounce_seconds` have elapsed since the last event for that path.
- If Titan is unreachable, the watcher retries with exponential backoff
  (B7) rather than crashing or losing events.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from brain_mcp.config import settings
from brain_mcp.titan_client import TitanClient

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

# Directories / prefixes to ignore inside the vault.
_IGNORE_DIRS: frozenset[str] = frozenset({".obsidian", ".trash", ".git"})


def _should_ignore(path: Path) -> bool:
    """Return True if this path should not trigger an ingest."""
    return any(part in _IGNORE_DIRS or part.startswith(".") for part in path.parts)


class _VaultEventHandler(FileSystemEventHandler):
    """Translates watchdog filesystem events into watcher actions."""

    def __init__(self, watcher: VaultWatcher) -> None:
        super().__init__()
        self._watcher = watcher

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(str(event.src_path))
        if path.suffix.lower() != ".md" or _should_ignore(path):
            return
        self._watcher._schedule(path)

    def on_created(self, event: FileSystemEvent) -> None:
        self.on_modified(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(str(event.src_path))
        if path.suffix.lower() != ".md" or _should_ignore(path):
            return
        # Delete fires immediately — no debouncing needed.
        self._watcher._handle_delete(path)

    def on_moved(self, event: FileSystemEvent) -> None:
        """Treat as delete of old path + create of new path."""
        if event.is_directory:
            return
        old = Path(str(event.src_path))
        new = Path(str(getattr(event, "dest_path", event.src_path)))
        if old.suffix.lower() == ".md" and not _should_ignore(old):
            self._watcher._handle_delete(old)
        if new.suffix.lower() == ".md" and not _should_ignore(new):
            self._watcher._schedule(new)


class VaultWatcher:
    """Watches an Obsidian vault and ingests changed Markdown notes into Titan.

    Args:
        vault_root: Directory to watch recursively.
        titan_client: Pre-configured TitanClient.
        debounce_seconds: Seconds to wait after the last event before ingesting.
            Inject a small value (e.g. 0.1) in tests for fast execution.
        poll_interval: How often the worker checks for ready paths. Defaults to 1.0s.
    """

    def __init__(
        self,
        vault_root: Path,
        titan_client: TitanClient,
        debounce_seconds: float = 30.0,
        poll_interval: float = 1.0,
    ) -> None:
        self.vault_root = vault_root
        self.titan_client = titan_client
        self.debounce_seconds = debounce_seconds
        self.poll_interval = poll_interval

        # {path: monotonic timestamp of the last event}
        self._pending: dict[Path, float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()

        self._observer = Observer()
        self._observer.schedule(
            _VaultEventHandler(self),
            str(vault_root),
            recursive=True,
        )
        self._worker_thread = threading.Thread(
            target=self._worker, daemon=True, name="watcher-worker"
        )

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the observer and the debounce worker."""
        self._observer.start()
        self._worker_thread.start()
        log.info(
            "VaultWatcher started, watching %s (debounce=%.1fs)",
            self.vault_root,
            self.debounce_seconds,
        )

    def stop(self) -> None:
        """Gracefully stop the watcher."""
        self._stop.set()
        self._observer.stop()
        self._observer.join()
        self._worker_thread.join(timeout=5.0)
        log.info("VaultWatcher stopped")

    # ------------------------------------------------------------------
    # Internal scheduling (called from event handler thread)
    # ------------------------------------------------------------------

    def _schedule(self, path: Path) -> None:
        """Record a modify/create event for debouncing."""
        with self._lock:
            self._pending[path] = time.monotonic()
        log.debug("Scheduled %s (debounce reset)", path)

    def _handle_delete(self, path: Path) -> None:
        """Delete chunks for a removed note immediately."""
        # Remove from pending if present (cancels any scheduled ingest).
        with self._lock:
            self._pending.pop(path, None)
        log.info("Delete event: %s", path)
        if not self._ensure_titan_available():
            log.error("Titan unreachable — could not delete chunks for %s", path)
            return
        try:
            n = self.titan_client.delete_chunks(path)
            log.info("Deleted %d chunk(s) for %s", n, path)
        except httpx.HTTPError as exc:
            log.error("Failed to delete chunks for %s: %s", path, exc)

    # ------------------------------------------------------------------
    # Worker loop (runs in background thread)
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        """Process debounced ingest events."""
        while not self._stop.is_set():
            now = time.monotonic()
            with self._lock:
                ready = [p for p, t in self._pending.items() if now - t >= self.debounce_seconds]
                for p in ready:
                    del self._pending[p]

            for path in ready:
                self._ingest(path)

            self._stop.wait(self.poll_interval)

    def _ingest(self, path: Path) -> None:
        """Ingest a single file; re-schedule on transient error."""
        log.info("Ingesting %s", path)
        if not self._ensure_titan_available():
            log.warning("Titan unreachable — re-scheduling %s", path)
            self._schedule(path)
            return
        try:
            result = self.titan_client.ingest_file(path)
            if result.skipped_reason:
                log.info(
                    "Skipped %s (%s) — %d old chunk(s) removed",
                    path,
                    result.skipped_reason,
                    result.chunks_deleted,
                )
            else:
                log.info(
                    "Indexed %s: %d chunk(s) created, %d replaced, domain=%s",
                    path,
                    result.chunks_created,
                    result.chunks_deleted,
                    result.domain,
                )
        except httpx.ConnectError:
            log.warning("ConnectError ingesting %s — re-scheduling", path)
            self._schedule(path)
        except httpx.HTTPStatusError as exc:
            log.error("HTTP %s ingesting %s: %s", exc.response.status_code, path, exc.response.text)
        except Exception as exc:
            log.exception("Unexpected error ingesting %s: %s", path, exc)

    # ------------------------------------------------------------------
    # B7 — Reconnect logic with exponential backoff
    # ------------------------------------------------------------------

    def _ensure_titan_available(self) -> bool:
        """Return True if Titan is reachable; probe with exponential backoff if not.

        Tries 5 times with delays 1s, 2s, 4s, 8s, 16s before giving up.
        Giving up does NOT set a permanent dead state — the next call will retry.
        """
        for delay in (1, 2, 4, 8, 16):
            try:
                self.titan_client.health()
                return True
            except httpx.ConnectError:
                log.warning("Titan unreachable, retrying in %ds…", delay)
                if self._stop.wait(delay):
                    # Stop was requested while waiting — abort gracefully.
                    return False
        log.error("Titan still unreachable after backoff sequence")
        return False


# ---------------------------------------------------------------------------
# Entry point (brain-watcher CLI)
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the vault watcher daemon."""
    import signal

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    client = TitanClient(base_url=settings.titan_url)
    watcher = VaultWatcher(
        vault_root=settings.vault_root,
        titan_client=client,
        debounce_seconds=settings.debounce_seconds,
    )

    stop_event = threading.Event()

    def _handle_signal(signum: int, frame: object) -> None:
        log.info("Received signal %d, shutting down…", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    watcher.start()
    stop_event.wait()
    watcher.stop()
    client.close()


if __name__ == "__main__":
    main()
