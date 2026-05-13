"""Smoke test for the package."""

from __future__ import annotations

from brain_mcp.main import main


def test_main_runs() -> None:
    """Confirm main() executes without raising."""
    main()
