# Architecture

> System-level design. Update when modules, contracts, or data models change.

## Overview

brain-mcp is the bridge between an Obsidian vault, the
[titan](https://github.com/charlieLucke/titan) RAG service, and Claude. It
consists of two cooperating but independent services: a **vault watcher** that
auto-indexes changed notes into titan, and an **MCP server** that exposes six
search/admin tools to Claude. Both talk to titan exclusively over its HTTP API —
there is no direct coupling to titan's code or to Qdrant.

```
Obsidian (Windows) → Vault (F:\vault\) → brain-watcher (watchdog)
                                            │ HTTP POST /ingest/file
                                            ▼
                                     titan-service :8765  (separate repo)
                                            ▲
Claude ──(stdio | HTTP/Funnel connector)──► brain-mcp    │ HTTP /search etc.
```

## Module map

```
src/brain_mcp/
├── config.py        # Settings (env prefix BRAIN_): titan URL, vault root, debounce, transport, OAuth
├── schemas.py       # Pydantic request/response schemas (local copy of the titan API schemas)
├── titan_client.py  # TitanClient: async httpx + retry via tenacity
├── mcp_server.py    # FastMCP server + the six MCP tools + transport selection (stdio | http)
├── auth.py          # GitHub OAuth proxy + GitHubAllowlistVerifier (login allowlist)
└── watcher.py       # VaultWatcher: watchdog observer, debounce, reconnect, reconcile
deploy/
├── brain-watcher.service  # systemd user service (vault watcher)
├── brain-mcp.service      # systemd user service (HTTP MCP server)
└── README.md              # activation + connector guide
```

## The two services

### brain-watcher
A systemd user daemon that watches the vault recursively. Changed `.md` files are
batched with a **30 s debounce** (several quick saves coalesce into one ingest) and
handed to titan via `POST /ingest/file`. **Reconnect logic** with exponential
backoff and a **cool-down** ensure a Titan outage neither blocks nor crashes the
watcher; delete events land in a pending queue when needed and are worked off after
recovery. On startup a **reconcile pass** diffs the vault against titan's index and
catches up any changes made during a downtime.

### brain-mcp (the MCP server)
Built on **FastMCP**. The transport is switchable:
- **stdio** — the MCP client (e.g. Claude Desktop) launches brain-mcp as a
  subprocess; no network exposure, no auth.
- **Streamable-HTTP** — a long-lived server (systemd service on port 9100) made
  publicly reachable via a Tailscale Funnel and secured with GitHub OAuth, wired
  into Claude as a custom connector.

## External services

| Service | Connection | Purpose |
|---|---|---|
| titan | HTTP `127.0.0.1:8765` | RAG backend: search, ingest, notes/domains |
| GitHub OAuth | HTTPS (api.github.com) | authentication + login allowlist in HTTP mode |
| Tailscale Funnel | public HTTPS | makes the local MCP server reachable from the Anthropic cloud |
| Obsidian vault | filesystem (watchdog) | source of the notes to index |

## Data flow

### Indexing (vault → titan)
```
.md changed → watchdog event → debounce (30 s) → TitanClient.ingest_file()
           → POST titan /ingest/file → (titan: Late Chunking + BGE-M3 + Qdrant upsert)
```

### Query (Claude → vault)
```
Claude calls MCP tool query_knowledge → brain-mcp → POST titan /search
      → ranked chunks → formatted as Markdown back to Claude
```

MCP tool return values are always Markdown strings (never raw JSON), so Claude can
render them directly.

## Security & boundaries

- **Auth only in HTTP mode:** stdio stays local/unauthenticated; the public HTTP
  mode enforces OAuth + allowlist.
- **Path validation against `VAULT_ROOT`** happens both client-side (brain-mcp) and
  server-side (titan).
- **Decoupling:** brain-mcp imports no titan code; it keeps a local copy of the API
  schemas — the repos stay independently deployable.

## Deployment

Two systemd user services. In always-on mode `brain-mcp` binds `0.0.0.0:9100` (not
`127.0.0.1`) so the Windows-side Tailscale Funnel can reach it under WSL2 mirrored
networking. Linger keeps the services alive without an open login session. Details:
[`deploy/README.md`](../../deploy/README.md).
