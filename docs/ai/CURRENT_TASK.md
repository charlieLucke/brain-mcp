# Current Task

> Keep this short. One screen max. Update as you progress.

## Goal

System produktiv und an Claude angebunden.

## Status

- [x] Phase 2 (B0–B11): brain-mcp implementiert + auditiert
- [x] `brain-watcher.service` läuft (systemd User-Service)
- [x] HTTP-Transport (`BRAIN_MCP_TRANSPORT=http`); `brain-mcp.service` auf
      `127.0.0.1:9100`
- [x] OAuth-Auth: GitHub-Proxy mit Allowlist (`src/brain_mcp/auth.py`)
- [x] `tailscale funnel` aktiv → `https://charliespc.taild04050.ts.net/`
- [x] Custom Connector in Claude eingetragen, OAuth-Login erfolgreich
- [x] End-to-End verifiziert: `query_knowledge` liefert Vault-Treffer
- [x] 2026-05-17: Etappe 2 — Tools `list_notes` + `delete_note` (brain hat 6 Tools)

## Offen

- [ ] optional: Docker Desktop auf Windows-Autostart setzen

## Notes

- Connector-URL: `https://charliespc.taild04050.ts.net/mcp`
- 6 Tools: `query_knowledge`, `ingest_note`, `list_domains`, `find_related`,
  `list_notes`, `delete_note`.
- Auth-Konfig (Secrets) in `brain-mcp/.env` (gitignored).
- Funnel braucht intakte WSL2-Mirrored-Networking-Brücke — sonst 502 (Fix:
  `wsl --shutdown`). Details: `docs/ai/DECISIONS.md` + `HANDOFF.md` (2026-05-16).
- Start/Stopp über das Desktop-Skript `RAG-System.bat` oder das `brain-dashboard`
  (Web-UI, Port 9200); die systemd-Units sind `linked` (kein Autostart).
