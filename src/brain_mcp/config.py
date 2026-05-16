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

    # MCP-Server-Transport: "stdio" (Default) oder "http" für Claude-Desktop-Connectors
    mcp_transport: str = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 9100

    # OAuth-Authentifizierung für den HTTP-Transport: "none" (Default) oder "github".
    # Pflicht, sobald der Server öffentlich erreichbar ist (Tailscale Funnel).
    mcp_auth: str = "none"
    mcp_base_url: str = ""  # öffentliche Basis-URL, z. B. https://host.ts.net
    github_client_id: str = ""
    github_client_secret: str = ""
    github_allowed_logins: str = ""  # kommagetrennte GitHub-Logins mit Zugriff

    model_config = SettingsConfigDict(env_prefix="BRAIN_", env_file=".env", extra="ignore")


settings = Settings()
