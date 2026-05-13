"""Entry point for brain_mcp."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the application."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Hello from brain_mcp")


if __name__ == "__main__":
    main()
