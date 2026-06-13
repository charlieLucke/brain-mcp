# Current Task

> Keep this short. One screen max. Update as you progress.

## Goal

System in production and connected to Claude.

## Status

- [x] Phase 2 (B0–B11): brain-mcp implemented + audited
- [x] `brain-watcher.service` running (systemd user service)
- [x] HTTP transport (`BRAIN_MCP_TRANSPORT=http`); `brain-mcp.service` on
      `127.0.0.1:9100`
- [x] OAuth auth: GitHub proxy with allowlist (`src/brain_mcp/auth.py`)
- [x] `tailscale funnel` active → `https://<your-tailnet-host>.ts.net/`
- [x] Custom connector added in Claude, OAuth login successful
- [x] End-to-end verified: `query_knowledge` returns vault hits
- [x] 2026-05-17: Stage 2 — tools `list_notes` + `delete_note` (brain has 6 tools)
- [x] 2026-06-02: Stage 2 — brain-mcp content_hash schema and startup reconcile pass
      Workspace plan: `docs/ai/plans/2026-06-02_vault-index-startup-reconcile.md`
      Committed: `784cf75` (brain-mcp feat)
      Quality gate: 57/57 tests green (incl. 5 new reconcile tests); mypy-strict green; `./workspace.sh check` green.

## Open

- [ ] optional: set Docker Desktop to autostart on Windows

## Notes

- Connector URL: `https://<your-tailnet-host>.ts.net/mcp`
- 6 tools: `query_knowledge`, `ingest_note`, `list_domains`, `find_related`,
  `list_notes`, `delete_note`.
- Auth config (secrets) in `brain-mcp/.env` (gitignored).
- The Funnel needs an intact WSL2 mirrored-networking bridge — otherwise 502 (fix:
  `wsl --shutdown`). Details: `docs/ai/DECISIONS.md` + `HANDOFF.md` (2026-05-16).
- Start/stop via the desktop script `RAG-System.bat` or `brain-dashboard`
  (web UI, port 9200); the systemd units are `linked` (no autostart).
