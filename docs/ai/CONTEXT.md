# Projektkontext — brain-mcp

> Zuerst lesen. Unter 200 Zeilen halten. Mit der Weiterentwicklung des Projekts aktualisieren.

## Was dieses Projekt macht

brain-mcp ist ein MCP-Server und Vault-Watcher für Claude. Es macht den persönlichen
Obsidian-Vault durchsuchbar, indem es Markdown-Notizen an den Titan-RAG-Service
delegiert (der als systemd-User-Daemon läuft) und Claude über MCP eine Reihe von Tools
bereitstellt.

## Architektur

```
Obsidian (Windows) → Vault (F:\vault\) → brain-watcher (watchdog)
                                            │ HTTP POST /ingest/file
                                            ▼
                                     titan-service :8765  (separates Repo)
                                            ▲
Claude ──(stdio | HTTP/Funnel-Connector)──► brain-mcp    │ HTTP /search usw.
```

- **brain-watcher**: systemd-User-Daemon, überwacht den Vault rekursiv, debounct
  30s, indexiert geänderte `.md`-Dateien über den Titan-Service neu. Reconnect-Logik mit
  exponentiellem Backoff.
- **brain-mcp**: der MCP-Server. Transport ist `stdio` (der Default — z. B. von
  Claude Desktop als Subprozess gestartet) oder Streamable-HTTP (der deployte Modus: ein
  systemd-User-Service `brain-mcp` auf Port 9100, über die Tailscale-Funnel
  als Claude-Custom-Connector exponiert und durch GitHub-OAuth abgesichert). Sechs MCP-Tools:
  `query_knowledge`, `ingest_note`, `list_domains`, `find_related`, `list_notes`,
  `delete_note`.

## Stack

- **Sprache:** Python 3.12+
- **Paketmanager:** uv
- **MCP:** FastMCP (stdio- + Streamable-HTTP-Transport)
- **HTTP:** httpx + tenacity (Retry 3×, exp. Backoff)
- **Settings:** pydantic-settings (Env-Präfix: BRAIN_)
- **Watcher:** watchdog
- **Test-Runner:** pytest
- **Lint/Format:** ruff (Zeilenlänge 100, doppelte Anführungszeichen)
- **Typprüfer:** mypy (strict, mit Overrides für watchdog/mcp/tenacity)
- **CI:** GitHub Actions

## Aufbau

```
src/brain_mcp/
├── config.py        # Settings: BRAIN_TITAN_URL, BRAIN_VAULT_ROOT, BRAIN_DEBOUNCE_SECONDS, BRAIN_MCP_*
├── schemas.py       # Pydantic-Schemas (lokale Kopie der Titan-API-Schemas)
├── titan_client.py  # TitanClient (httpx, Retry via tenacity)
├── mcp_server.py    # FastMCP-Server + die sechs Tools
└── watcher.py       # VaultWatcher (watchdog, Debounce, Reconnect)
deploy/
├── brain-watcher.service  # systemd-User-Service (Vault-Watcher)
├── brain-mcp.service      # systemd-User-Service (HTTP-MCP-Server)
└── README.md              # Aktivierungsanleitung + Connector-Setup
tests/
├── test_titan_client.py   # httpx.MockTransport
├── test_mcp_tools.py       # patch(_client.method)
├── test_watcher.py         # mock TitanClient, Unit + Integration
└── integration/
    └── test_e2e_pipeline.py  # Polling (kein sleep), benötigt einen laufenden Titan-Service
```

## Umgebungsvariablen (BRAIN_-Präfix)

| Variable | Default | Bedeutung |
|---|---|---|
| BRAIN_TITAN_URL | http://127.0.0.1:8765 | Titan-Service-URL |
| BRAIN_VAULT_ROOT | /mnt/f/vault | Obsidian-Vault-Root (Beispielpfad; an dein Setup anpassen) |
| BRAIN_DEBOUNCE_SECONDS | 30.0 | Debounce-Fenster für den Watcher |
| BRAIN_MCP_TRANSPORT | stdio | `stdio` oder `http` (für Claude-Custom-Connectors) |
| BRAIN_MCP_HOST | 127.0.0.1 | HTTP-Bind-Host (im Deployment `0.0.0.0` setzen) |
| BRAIN_MCP_PORT | 9100 | HTTP-Bind-Port |
| BRAIN_MCP_AUTH | none | `none` oder `github` (erforderlich, sobald öffentlich erreichbar) |
| BRAIN_MCP_BASE_URL | (leer) | öffentliche Basis-URL, z. B. `https://host.ts.net` |
| BRAIN_GITHUB_CLIENT_ID / _SECRET | (leer) | GitHub-OAuth-App-Credentials |
| BRAIN_GITHUB_ALLOWED_LOGINS | (leer) | kommagetrennte GitHub-Logins mit Zugriff |

## Konventionen

- Alle Konventionen aus CLAUDE.md (ruff, mypy strict, snake_case, Google-Docstrings usw.)
- MCP-Tool-Rückgabewerte sind immer Markdown-Strings, niemals JSON
- Pfadvalidierung gegen VAULT_ROOT erfolgt sowohl clientseitig (MCP) ALS AUCH serverseitig (Titan)

## Befehle

```bash
make install          # Abhängigkeiten + pre-commit-Hooks
make check            # Lint + Typen + Tests
make test             # pytest mit Coverage
make test-fast        # ohne langsame + Integration
uv run pytest tests/integration/ -m integration -v  # E2E (benötigt Titan)
```

## Bekannte Fallstricke
- **caddys Default-Route proxyt alles auf Port 9100 durch den öffentlichen
  Funnel.** Jeder Pfad, der zum HTTP-Transport dazukommt, ist öffentlich
  erreichbar, nicht nur `/mcp`. Deshalb prüft `/api/vault/*` selbst ein
  Bearer-Token, statt einen Loopback-Bind anzunehmen — und wird ohne Token gar
  nicht registriert.
- **Der Checkout ist der laufende Code.** `WorkingDirectory` und `ExecStart` der Unit
  zeigen auf `~/projects/brain-mcp`. Ein Push nach GitHub ändert den laufenden Server
  nicht, ein bloßer Neustart bringt den alten Stand wieder hoch: erst `git pull`, dann
  `systemctl --user restart brain-watcher brain-mcp` (`deploy/README.md` §6).
- **„Registrierung beim Anmeldedienst fehlgeschlagen" in Claude** = FastMCP bewirbt
  CIMD. `enable_cimd=False` in `auth.py` muss stehen bleiben (DECISIONS 2026-09-23).


- VS Code zeigt „Package not installed"-Hinweise — das ist das falsche venv (mein-projekt).
  Das `.venv` im Projektverzeichnis hat alle Pakete korrekt.
- Der pre-commit mypy-Hook braucht `additional_dependencies` in `.pre-commit-config.yaml`.
- `@mcp.tool()` und tenacity `@_RETRY` sind untypisierte Dekoratoren → pyproject.toml-Override
  `disable_error_code = ["untyped-decorator", "no-any-return"]` für die betroffenen Module.
- `watchdog` hat keine Type-Stubs → `ignore_missing_imports = true` in pyproject.toml.
- Im `stdio`-Transport wird brain-mcp von Claude Desktop als Subprozess gestartet; im
  deployten `http`-Transport läuft es als systemd-User-Service `brain-mcp`.
- systemd-Unit: `Wants=` verwenden (NICHT `Requires=`), damit der Watcher einen Titan-Neustart überlebt.
- Den HTTP-Server an `0.0.0.0` binden, nicht `127.0.0.1`: unter WSL2 Mirrored Networking ist ein
  reiner Loopback-Bind von der Windows-seitigen Tailscale-Funnel aus unerreichbar (→ 502).
```
