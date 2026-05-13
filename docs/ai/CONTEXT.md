# Project Context — brain-mcp

> Read this first. Keep under 200 lines. Update as the project evolves.

## What this project does

brain-mcp ist ein MCP-Server und Vault-Watcher für Claude Desktop. Es macht den persönlichen
Obsidian-Vault durchsuchbar, indem es Markdown-Notizen automatisch an den Titan-RAG-Service
(läuft als systemd-User-Daemon) delegiert und Claude vier Tools als MCP-Interface bereitstellt.

## Architektur

```
Obsidian (Windows) → Vault (F:\vault\) → brain-watcher (watchdog)
                                            │ HTTP POST /ingest/file
                                            ▼
                                     titan-service :8765  (separates Repo)
                                            ▲
Claude Desktop ──MCP stdio──► brain-mcp    │ HTTP /search etc.
```

- **brain-watcher**: Systemd-User-Daemon, beobachtet Vault rekursiv, debounced 30s,
  re-indexiert geänderte .md-Dateien via Titan-Service. Reconnect-Logik mit exp. Backoff.
- **brain-mcp**: Per-Session-Prozess, gestartet von Claude Desktop via stdio transport.
  4 MCP-Tools: query_knowledge, ingest_note, list_domains, find_related.

## Stack

- **Language:** Python 3.12+
- **Package manager:** uv
- **MCP:** FastMCP (stdio transport)
- **HTTP:** httpx + tenacity (retry 3x, exp backoff)
- **Settings:** pydantic-settings (env prefix: BRAIN_)
- **Watcher:** watchdog
- **Test runner:** pytest
- **Lint/format:** ruff (line length 100, double quotes)
- **Type checker:** mypy (strict, mit Overrides für watchdog/mcp/tenacity)
- **CI:** GitHub Actions

## Layout

```
src/brain_mcp/
├── config.py        # Settings: BRAIN_TITAN_URL, BRAIN_VAULT_ROOT, BRAIN_DEBOUNCE_SECONDS
├── schemas.py       # Pydantic-Schemas (lokale Kopie der Titan-API-Schemas)
├── titan_client.py  # TitanClient (httpx, retry via tenacity)
├── mcp_server.py    # FastMCP server + 4 Tools
└── watcher.py       # VaultWatcher (watchdog, debounce, reconnect)
deploy/
├── brain-watcher.service  # systemd User-Service
└── README.md              # Aktivierungs-Anleitung + Claude Desktop JSON Config
tests/
├── test_titan_client.py   # httpx.MockTransport
├── test_mcp_tools.py      # patch(_client.method)
├── test_watcher.py        # Mock TitanClient, unit + integration
└── integration/
    └── test_e2e_pipeline.py  # Polling (kein sleep), braucht live Titan-Service
```

## Environment Variables (BRAIN_ Prefix)

| Variable | Default | Bedeutung |
|---|---|---|
| BRAIN_TITAN_URL | http://127.0.0.1:8765 | Titan-Service URL |
| BRAIN_VAULT_ROOT | /mnt/f/vault | Obsidian-Vault root |
| BRAIN_DEBOUNCE_SECONDS | 30.0 | Debounce-Fenster für Watcher |

## Conventions

- Alle Konventionen aus CLAUDE.md (ruff, mypy strict, snake_case, Google docstrings, etc.)
- MCP-Tool-Return-Werte sind immer Markdown-Strings, nie JSON
- Pfad-Validierung gegen VAULT_ROOT erfolgt Client-seitig (MCP) UND Server-seitig (Titan)

## Commands

```bash
make install          # deps + pre-commit hooks
make check            # lint + types + tests
make test             # pytest mit coverage
make test-fast        # ohne slow + integration
uv run pytest tests/integration/ -m integration -v  # E2E (braucht Titan)
```

## Known pitfalls

- VS Code zeigt "Package not installed" Hints — ist die falsche venv (mein-projekt).
  Das `.venv` im Projektverzeichnis hat alle Packages korrekt.
- pre-commit mypy-Hook braucht `additional_dependencies` in `.pre-commit-config.yaml`.
- `@mcp.tool()` und tenacity `@_RETRY` sind untyped decorators → pyproject.toml Override
  `disable_error_code = ["untyped-decorator", "no-any-return"]` für betroffene Module.
- `watchdog` hat keine Typstubs → `ignore_missing_imports = true` in pyproject.toml.
- brain-mcp läuft NICHT als systemd-Daemon — wird von Claude Desktop per subprocess gestartet.
- systemd-Unit: `Wants=` (NICHT `Requires=`) damit Watcher bei Titan-Restart überlebt.
