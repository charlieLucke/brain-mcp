# Aktuelle Aufgabe

> Kurz halten. Maximal ein Bildschirm. Mit dem Fortschritt aktualisieren.

## Ziel

System in Produktion und mit Claude verbunden.

## Status

- [x] Phase 2 (B0–B11): brain-mcp implementiert + auditiert
- [x] `brain-watcher.service` läuft (systemd-User-Service)
- [x] HTTP-Transport (`BRAIN_MCP_TRANSPORT=http`); `brain-mcp.service` auf
      `127.0.0.1:9100`
- [x] OAuth-Auth: GitHub-Proxy mit Allowlist (`src/brain_mcp/auth.py`)
- [x] `tailscale funnel` aktiv → `https://charliespc.taild04050.ts.net/`
- [x] Custom Connector in Claude hinzugefügt, OAuth-Login erfolgreich
- [x] End-to-end verifiziert: `query_knowledge` liefert Vault-Treffer
- [x] 2026-05-17: Stage 2 — Tools `list_notes` + `delete_note` (brain hat 6 Tools)
- [x] 2026-06-02: Stage 2 — brain-mcp content_hash-Schema und Startup-Reconcile-Pass
      Workspace-Plan: `docs/ai/plans/2026-06-02_vault-index-startup-reconcile.md`
      Committet: `784cf75` (brain-mcp feat)
      Quality-Gate: 57/57 Tests grün (inkl. 5 neue Reconcile-Tests); mypy-strict grün; `./workspace.sh check` grün.

## Offen

- [ ] optional: Docker Desktop unter Windows auf Autostart setzen

## Notizen

- Connector-URL: `https://charliespc.taild04050.ts.net/mcp`
- 6 Tools: `query_knowledge`, `ingest_note`, `list_domains`, `find_related`,
  `list_notes`, `delete_note`.
- Auth-Konfiguration (Secrets) in `brain-mcp/.env` (gitignored).
- Die Funnel braucht eine intakte WSL2-Mirrored-Networking-Bridge — sonst 502 (Fix:
  `wsl --shutdown`). Details: `docs/ai/DECISIONS.md` + `HANDOFF.md` (2026-05-16).
- Start/Stopp über das Desktop-Skript `RAG-System.bat` oder `brain-dashboard`
  (Web-UI, Port 9200); die systemd-Units sind `linked` (kein Autostart).
