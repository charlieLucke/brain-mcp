"""Pydantic-Settings for brain-mcp."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or .env."""

    titan_url: str = "http://127.0.0.1:8765"
    vault_root: Path = Path("/mnt/f/vault")
    # Injectierbar für Tests (Tests setzen z.B. 0.1)
    debounce_seconds: float = 30.0

    model_config = SettingsConfigDict(env_prefix="BRAIN_", env_file=".env", extra="ignore")


settings = Settings()
