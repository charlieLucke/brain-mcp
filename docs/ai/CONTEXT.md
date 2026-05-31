# Project Context — brain-mcp

> Read this first. Keep under 200 lines. Update as the project evolves.

## What this project does

brain-mcp is an MCP server and vault watcher for Claude. It makes the personal
Obsidian vault searchable by delegating Markdown notes to the Titan RAG service
(running as a systemd user daemon) and exposing a set of tools to Claude over MCP.

## Architecture

```
Obsidian (Windows) → Vault (F:\vault\) → brain-watcher (watchdog)
                                            │ HTTP POST /ingest/file
                                            ▼
                                     titan-service :8765  (separate repo)
                                            ▲
Claude ──(stdio | HTTP/Funnel connector)──► brain-mcp    │ HTTP /search etc.
```

- **brain-watcher**: systemd user daemon, watches the vault recursively, debounces
  30s, re-indexes changed `.md` files via the Titan service. Reconnect logic with
  exponential backoff.
- **brain-mcp**: the MCP server. Transport is `stdio` (the default — e.g. launched
  by Claude Desktop as a subprocess) or Streamable-HTTP (the deployed mode: a
  systemd user service `brain-mcp` on port 9100, exposed via the Tailscale Funnel
  as a Claude custom connector and gated by GitHub OAuth). Six MCP tools:
  `query_knowledge`, `ingest_note`, `list_domains`, `find_related`, `list_notes`,
  `delete_note`.

## Stack

- **Language:** Python 3.12+
- **Package manager:** uv
- **MCP:** FastMCP (stdio + Streamable-HTTP transport)
- **HTTP:** httpx + tenacity (retry 3x, exp backoff)
- **Settings:** pydantic-settings (env prefix: BRAIN_)
- **Watcher:** watchdog
- **Test runner:** pytest
- **Lint/format:** ruff (line length 100, double quotes)
- **Type checker:** mypy (strict, with overrides for watchdog/mcp/tenacity)
- **CI:** GitHub Actions

## Layout

```
src/brain_mcp/
├── config.py        # Settings: BRAIN_TITAN_URL, BRAIN_VAULT_ROOT, BRAIN_DEBOUNCE_SECONDS, BRAIN_MCP_*
├── schemas.py       # Pydantic schemas (local copy of the Titan API schemas)
├── titan_client.py  # TitanClient (httpx, retry via tenacity)
├── mcp_server.py    # FastMCP server + the six tools
└── watcher.py       # VaultWatcher (watchdog, debounce, reconnect)
deploy/
├── brain-watcher.service  # systemd user service (vault watcher)
├── brain-mcp.service      # systemd user service (HTTP MCP server)
└── README.md              # activation guide + connector setup
tests/
├── test_titan_client.py   # httpx.MockTransport
├── test_mcp_tools.py       # patch(_client.method)
├── test_watcher.py         # mock TitanClient, unit + integration
└── integration/
    └── test_e2e_pipeline.py  # polling (no sleep), needs a live Titan service
```

## Environment Variables (BRAIN_ prefix)

| Variable | Default | Meaning |
|---|---|---|
| BRAIN_TITAN_URL | http://127.0.0.1:8765 | Titan service URL |
| BRAIN_VAULT_ROOT | /mnt/f/vault | Obsidian vault root |
| BRAIN_DEBOUNCE_SECONDS | 30.0 | Debounce window for the watcher |
| BRAIN_MCP_TRANSPORT | stdio | `stdio` or `http` (for Claude custom connectors) |
| BRAIN_MCP_HOST | 127.0.0.1 | HTTP bind host (set `0.0.0.0` in deployment) |
| BRAIN_MCP_PORT | 9100 | HTTP bind port |
| BRAIN_MCP_AUTH | none | `none` or `github` (required once publicly reachable) |
| BRAIN_MCP_BASE_URL | (empty) | public base URL, e.g. `https://host.ts.net` |
| BRAIN_GITHUB_CLIENT_ID / _SECRET | (empty) | GitHub OAuth app credentials |
| BRAIN_GITHUB_ALLOWED_LOGINS | (empty) | comma-separated GitHub logins with access |

## Conventions

- All conventions from CLAUDE.md (ruff, mypy strict, snake_case, Google docstrings, etc.)
- MCP tool return values are always Markdown strings, never JSON
- Path validation against VAULT_ROOT happens both client-side (MCP) AND server-side (Titan)

## Commands

```bash
make install          # deps + pre-commit hooks
make check            # lint + types + tests
make test             # pytest with coverage
make test-fast        # without slow + integration
uv run pytest tests/integration/ -m integration -v  # E2E (needs Titan)
```

## Known pitfalls

- VS Code shows "Package not installed" hints — that's the wrong venv (mein-projekt).
  The `.venv` in the project directory has all packages correct.
- The pre-commit mypy hook needs `additional_dependencies` in `.pre-commit-config.yaml`.
- `@mcp.tool()` and tenacity `@_RETRY` are untyped decorators → pyproject.toml override
  `disable_error_code = ["untyped-decorator", "no-any-return"]` for the affected modules.
- `watchdog` has no type stubs → `ignore_missing_imports = true` in pyproject.toml.
- In `stdio` transport brain-mcp is launched by Claude Desktop as a subprocess; in the
  deployed `http` transport it runs as the systemd user service `brain-mcp`.
- systemd unit: use `Wants=` (NOT `Requires=`) so the watcher survives a Titan restart.
- Bind the HTTP server to `0.0.0.0`, not `127.0.0.1`: under WSL2 mirrored networking a
  loopback-only bind is unreachable from the Windows-side Tailscale Funnel (→ 502).
